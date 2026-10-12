//! s5.rs — S5 Policy (boot-time invariants only for Tier α)
//!
//! @vsm 0.3 — V("vsf-nucleus", L=1) §S5
//! @status: Tier α Tα.2 — boot-time covenant verify with fail-closed
//!
//! Beer principle: S5 = identity. Identity drift = system death. A nucleus
//! that boots with mismatched covenant is no longer THIS system, it's
//! something else wearing the same binary.
//!
//! What we DON'T do here (yet):
//!   - S5 LLM agent (high risk, deferred)
//!   - Live policy reload (P.3 covers that path via phi_down)
//!   - Multi-witness verification (Tα.4 Scaffolding pending)
//!
//! What we DO:
//!   - At boot: load s5_policy.json, sha256 covenant.vsm, GET canonical hash,
//!     compare. If mismatch AND verify_at_boot=true → ABORT (non-zero exit
//!     via Err propagation).
//!   - Network errors do NOT block boot (flaky DNS ≠ covenant drift). Logged
//!     as warning. Covenant drift detection in production is S3*'s job.

use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::error::Error;
use std::fs;
use std::path::Path;
use std::time::Duration;

pub const DEFAULT_COVENANT_PATH: &str = "/etc/vsf/covenant.vsm";
pub const DEFAULT_S5_POLICY_PATH: &str = "/etc/vsf/s5_policy.json";

#[derive(Debug, Deserialize, Default)]
struct PolicySubset {
    #[serde(default)]
    covenant: Option<CovenantBlock>,
}

#[derive(Debug, Deserialize, Default)]
struct CovenantBlock {
    #[serde(default)]
    canonical_hash_source: Option<String>,
    #[serde(default = "default_verify_at_boot")]
    verify_at_boot: bool,
    /// Tα.4 — Witnesses configured for multi-party covenant attestation.
    /// Verify-only path for Tier α: each witness's signature over the covenant
    /// raw-bytes (sha256 input) is checked. Witnesses array empty → skip.
    #[serde(default)]
    witnesses: Vec<WitnessBlock>,
}

#[derive(Debug, Deserialize, Default, Clone)]
pub struct WitnessBlock {
    pub id: String,
    /// Ed25519 public key — base64 encoded (32 bytes raw).
    pub pubkey: String,
    /// Ed25519 signature over sha256(covenant.vsm) — base64 encoded (64 bytes raw).
    /// Optional in Tier α; absent or empty means no signature on file → skip this witness.
    #[serde(default)]
    pub signature: Option<String>,
    /// Optional URL to fetch signature (Tier β feature; not implemented yet).
    #[serde(default)]
    pub url: Option<String>,
}

fn default_verify_at_boot() -> bool {
    true
}

/// Outcome categories from the boot check (for explicit handling + logging).
#[derive(Debug)]
pub enum CovenantBootResult {
    /// Policy says skip (verify_at_boot=false). Tier α default is true; skipping
    /// is supported for dev environments but logged loudly.
    SkippedByPolicy,
    /// Hashes match. Boot proceeds.
    Match { local: String },
    /// Network or filesystem error reading canonical hash. NOT treated as drift.
    /// Logged as warning; boot proceeds. S3* will keep monitoring in steady state.
    Inconclusive { reason: String },
    /// Hashes differ. FAIL CLOSED.
    Drift { local: String, canonical: String },
}

/// Tα.4 — Outcome of witness verification.
#[derive(Debug, Clone)]
pub enum WitnessVerifyResult {
    /// No witnesses configured in policy. Nothing to verify (Tier α default).
    NoneConfigured,
    /// All configured witnesses (with signatures present) verified successfully.
    /// `verified_count` = #witnesses checked, `skipped_count` = #without signature.
    AllVerified { verified_count: usize, skipped_count: usize },
    /// One or more witnesses FAILED verification. Boot should fail-closed.
    Failed { failures: Vec<String> },
    /// Configuration error (e.g. invalid pubkey base64). Logged + treated as fail
    /// to be conservative (Tier α: scaffolding is verify-only, but malformed
    /// config is still suspicious).
    ConfigError { reason: String },
}

/// Top-level boot verifier. Returns Ok on success (Match | SkippedByPolicy |
/// Inconclusive) and Err on definitive drift. Caller is expected to propagate
/// Err to abort startup.
pub fn verify_covenant_at_boot() -> Result<CovenantBootResult, Box<dyn Error>> {
    let covenant_path = std::env::var("COVENANT_PATH")
        .unwrap_or_else(|_| DEFAULT_COVENANT_PATH.to_string());
    let policy_path = std::env::var("S5_POLICY_PATH")
        .unwrap_or_else(|_| DEFAULT_S5_POLICY_PATH.to_string());

    // Load policy
    let policy: PolicySubset = match fs::read_to_string(&policy_path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
        Err(e) => {
            eprintln!(
                "[S5] policy file unreadable ({}): {} — using defaults (verify_at_boot=true)",
                policy_path, e
            );
            PolicySubset::default()
        }
    };
    let cov = policy.covenant.unwrap_or_default();

    if !cov.verify_at_boot {
        eprintln!(
            "[S5] ⚠ covenant verify_at_boot=FALSE in policy — boot WITHOUT identity check"
        );
        return Ok(CovenantBootResult::SkippedByPolicy);
    }

    let canonical_url = match cov.canonical_hash_source {
        Some(s) if !s.is_empty() => s,
        _ => {
            eprintln!("[S5] ⚠ no canonical_hash_source in policy — boot WITHOUT remote verify");
            return Ok(CovenantBootResult::Inconclusive {
                reason: "no canonical_hash_source configured".into(),
            });
        }
    };

    // Local sha256
    let local = match local_covenant_hash(&covenant_path) {
        Ok(h) => h,
        Err(e) => {
            // covenant file missing or unreadable is a FAIL — without local
            // covenant we cannot prove identity
            return Err(format!("[S5] local covenant unreadable ({}): {}", covenant_path, e).into());
        }
    };

    // HTTPS GET canonical
    let canonical = match http_get_hash(&canonical_url) {
        Ok(h) => h,
        Err(e) => {
            eprintln!(
                "[S5] ⚠ canonical hash fetch failed ({}): {} — INCONCLUSIVE, boot proceeds (S3* will keep monitoring)",
                canonical_url, e
            );
            return Ok(CovenantBootResult::Inconclusive { reason: e });
        }
    };

    if local == canonical {
        eprintln!("[S5] ✓ covenant verified at boot — local hash matches canonical");
        Ok(CovenantBootResult::Match { local })
    } else {
        // FAIL CLOSED: explicit Err so main() can exit non-zero
        let msg = format!(
            "[S5] ✗ COVENANT DRIFT AT BOOT — local={} canonical={} — REFUSING TO BOOT",
            local, canonical
        );
        eprintln!("{}", msg);
        Err(msg.into())
    }
}

/// Tα.4 — Verify Ed25519 signatures from configured witnesses against the local
/// covenant raw bytes. Returns category. Caller decides fail-closed semantics.
///
/// Tier α policy:
///   - All-of (every witness with `signature` set must verify OK).
///   - Witnesses without `signature` (and without `url` fetch) are SKIPPED, not failed.
///   - URL fetch is NOT yet implemented (Tier β).
pub fn verify_witnesses() -> WitnessVerifyResult {
    let covenant_path = std::env::var("COVENANT_PATH")
        .unwrap_or_else(|_| DEFAULT_COVENANT_PATH.to_string());
    let policy_path = std::env::var("S5_POLICY_PATH")
        .unwrap_or_else(|_| DEFAULT_S5_POLICY_PATH.to_string());

    let policy: PolicySubset = match fs::read_to_string(&policy_path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
        Err(_) => PolicySubset::default(),
    };
    let witnesses = match policy.covenant {
        Some(c) => c.witnesses,
        None => return WitnessVerifyResult::NoneConfigured,
    };
    if witnesses.is_empty() {
        return WitnessVerifyResult::NoneConfigured;
    }

    let covenant_bytes = match fs::read(Path::new(&covenant_path)) {
        Ok(b) => b,
        Err(e) => {
            return WitnessVerifyResult::ConfigError {
                reason: format!("covenant unreadable: {}", e),
            };
        }
    };

    verify_witnesses_against_bytes(&witnesses, &covenant_bytes)
}

/// Pure-compute helper: verify a witness slice against given covenant bytes.
/// Exposed for unit tests + future Tier β multi-source.
pub fn verify_witnesses_against_bytes(
    witnesses: &[WitnessBlock],
    covenant_bytes: &[u8],
) -> WitnessVerifyResult {
    if witnesses.is_empty() {
        return WitnessVerifyResult::NoneConfigured;
    }
    let mut verified = 0usize;
    let mut skipped = 0usize;
    let mut failures: Vec<String> = Vec::new();

    for w in witnesses {
        let sig_b64 = match &w.signature {
            Some(s) if !s.trim().is_empty() => s.clone(),
            _ => {
                // No signature on file. URL fetch not implemented Tier α.
                if w.url.as_deref().map(|u| !u.is_empty()).unwrap_or(false) {
                    eprintln!(
                        "[S5/Tα.4] witness {} has url but URL fetch is Tier β — SKIPPED",
                        w.id
                    );
                } else {
                    eprintln!("[S5/Tα.4] witness {} has no signature — SKIPPED", w.id);
                }
                skipped += 1;
                continue;
            }
        };

        let pubkey_bytes = match B64.decode(w.pubkey.trim()) {
            Ok(b) if b.len() == 32 => b,
            Ok(b) => {
                return WitnessVerifyResult::ConfigError {
                    reason: format!("witness {} pubkey wrong length: {} (need 32)", w.id, b.len()),
                };
            }
            Err(e) => {
                return WitnessVerifyResult::ConfigError {
                    reason: format!("witness {} pubkey base64 decode: {}", w.id, e),
                };
            }
        };

        let sig_bytes = match B64.decode(sig_b64.trim()) {
            Ok(b) if b.len() == 64 => b,
            Ok(b) => {
                failures.push(format!(
                    "witness {} signature wrong length: {} (need 64)", w.id, b.len()
                ));
                continue;
            }
            Err(e) => {
                failures.push(format!("witness {} signature base64 decode: {}", w.id, e));
                continue;
            }
        };

        let mut pk_arr = [0u8; 32];
        pk_arr.copy_from_slice(&pubkey_bytes);
        let vk = match VerifyingKey::from_bytes(&pk_arr) {
            Ok(k) => k,
            Err(e) => {
                return WitnessVerifyResult::ConfigError {
                    reason: format!("witness {} invalid pubkey: {}", w.id, e),
                };
            }
        };
        let mut sig_arr = [0u8; 64];
        sig_arr.copy_from_slice(&sig_bytes);
        let sig = Signature::from_bytes(&sig_arr);

        match vk.verify(covenant_bytes, &sig) {
            Ok(()) => {
                eprintln!("[S5/Tα.4] witness {} ✓ verified", w.id);
                verified += 1;
            }
            Err(e) => {
                failures.push(format!("witness {} signature INVALID: {}", w.id, e));
            }
        }
    }

    if !failures.is_empty() {
        WitnessVerifyResult::Failed { failures }
    } else {
        WitnessVerifyResult::AllVerified {
            verified_count: verified,
            skipped_count: skipped,
        }
    }
}

fn local_covenant_hash(path: &str) -> Result<String, Box<dyn Error>> {
    let bytes = fs::read(Path::new(path))?;
    let mut h = Sha256::new();
    h.update(&bytes);
    Ok(hex::encode(h.finalize()))
}

fn http_get_hash(url: &str) -> Result<String, String> {
    let raw = ureq::get(url)
        .timeout(Duration::from_secs(10))
        .call()
        .map_err(|e| format!("HTTPS GET {}: {}", url, e))?
        .into_string()
        .map_err(|e| format!("read response: {}", e))?;
    let cleaned = raw.trim().to_lowercase();
    if cleaned.len() != 64 || !cleaned.chars().all(|c| c.is_ascii_hexdigit() && (c.is_ascii_digit() || c.is_ascii_lowercase())) {
        return Err(format!("canonical hash invalid format: {:?}", cleaned));
    }
    Ok(cleaned)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_hash_stable_for_same_content() {
        let tmp = std::env::temp_dir().join(format!("s5_test_{}", std::process::id()));
        fs::write(&tmp, b"test covenant content").unwrap();
        let h1 = local_covenant_hash(tmp.to_str().unwrap()).unwrap();
        let h2 = local_covenant_hash(tmp.to_str().unwrap()).unwrap();
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64);
        let _ = fs::remove_file(&tmp);
    }

    #[test]
    fn boot_result_categories_distinguishable() {
        let r = CovenantBootResult::Match { local: "x".into() };
        match r {
            CovenantBootResult::Match { .. } => (),
            _ => panic!("wrong category"),
        }
    }

    // ─── Tα.4 witness verification tests ─────────────────────────────────

    use ed25519_dalek::{Signer, SigningKey};

    fn make_signing_keypair() -> (SigningKey, String) {
        // Deterministic test keypair from a fixed 32-byte seed.
        // Production never uses this — tests only.
        let seed: [u8; 32] = [
            0x9d, 0x61, 0xb1, 0x9d, 0xef, 0xfd, 0x5a, 0x60,
            0xba, 0x84, 0x4a, 0xf4, 0x92, 0xec, 0x2c, 0xc4,
            0x44, 0x49, 0xc5, 0x69, 0x7b, 0x32, 0x69, 0x19,
            0x70, 0x3b, 0xac, 0x03, 0x1c, 0xae, 0x7f, 0x60,
        ];
        let sk = SigningKey::from_bytes(&seed);
        let pubkey_b64 = B64.encode(sk.verifying_key().to_bytes());
        (sk, pubkey_b64)
    }

    fn sign_payload(sk: &SigningKey, payload: &[u8]) -> String {
        B64.encode(sk.sign(payload).to_bytes())
    }

    #[test]
    fn witness_verify_no_witnesses_returns_none_configured() {
        let result = verify_witnesses_against_bytes(&[], b"any covenant bytes");
        assert!(matches!(result, WitnessVerifyResult::NoneConfigured));
    }

    #[test]
    fn witness_verify_valid_signature_passes() {
        let covenant = b"@vsm 0.1\nV(\"test\", L=0)\n";
        let (sk, pk_b64) = make_signing_keypair();
        let sig_b64 = sign_payload(&sk, covenant);

        let witnesses = vec![WitnessBlock {
            id: "test-witness-1".into(),
            pubkey: pk_b64,
            signature: Some(sig_b64),
            url: None,
        }];

        let result = verify_witnesses_against_bytes(&witnesses, covenant);
        match result {
            WitnessVerifyResult::AllVerified { verified_count, skipped_count } => {
                assert_eq!(verified_count, 1);
                assert_eq!(skipped_count, 0);
            }
            other => panic!("expected AllVerified, got {:?}", other),
        }
    }

    #[test]
    fn witness_verify_tampered_payload_fails() {
        let covenant = b"@vsm 0.1\nV(\"test\", L=0)\n";
        let (sk, pk_b64) = make_signing_keypair();
        let sig_b64 = sign_payload(&sk, covenant);

        let tampered = b"@vsm 0.1\nV(\"TAMPERED\", L=0)\n";
        let witnesses = vec![WitnessBlock {
            id: "tampered-test".into(),
            pubkey: pk_b64,
            signature: Some(sig_b64),
            url: None,
        }];
        let result = verify_witnesses_against_bytes(&witnesses, tampered);
        assert!(matches!(result, WitnessVerifyResult::Failed { .. }));
    }

    #[test]
    fn witness_without_signature_is_skipped_not_failed() {
        let (_, pk_b64) = make_signing_keypair();
        let witnesses = vec![WitnessBlock {
            id: "no-sig-yet".into(),
            pubkey: pk_b64,
            signature: None,
            url: None,
        }];
        let result = verify_witnesses_against_bytes(&witnesses, b"anything");
        match result {
            WitnessVerifyResult::AllVerified { verified_count, skipped_count } => {
                assert_eq!(verified_count, 0);
                assert_eq!(skipped_count, 1);
            }
            other => panic!("expected AllVerified with skipped, got {:?}", other),
        }
    }

    #[test]
    fn witness_invalid_pubkey_is_config_error() {
        let witnesses = vec![WitnessBlock {
            id: "bad-pk".into(),
            pubkey: "not-base64!!!".into(),
            signature: Some("anything".into()),
            url: None,
        }];
        let result = verify_witnesses_against_bytes(&witnesses, b"anything");
        assert!(matches!(result, WitnessVerifyResult::ConfigError { .. }));
    }
}
