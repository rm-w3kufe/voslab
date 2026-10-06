//! beacon.rs — kernel_birth: Ed25519-signed attestation to the VSF beacon.
//!
//! @vsm 0.3 — V("beacon", L=1) §kernel_birth
//!
//! Implements the attestation protocol from `beacon_activation.spec.vsm`.
//! On kernel_birth (startup), the nucleus builds a signed payload and POSTs it
//! to the beacon URL. Retry/backoff; non-fatal if beacon is unreachable.
//!
//! ## Payload format (matches `scripts/beacon_attestation.py`)
//!
//! ```json
//! {
//!   "kernel_id": "vsf_nucleus",
//!   "vsf_version": "0.0.1",
//!   "watermark": "\\u27f7 vsf_nucleus | n02 | vsf-0.1 | vsf.u2738.org \\u27f7",
//!   "covenant_sha": "sha256 hex of covenant",
//!   "calibration": "hash of passing Axis-1 census (phase-2, optional)",
//!   "cert": { /* S5-CA-issued node cert */ },
//!   "sig": "Ed25519 signature hex (128 hex chars)"
//! }
//! ```
//!
//! ## Config (env vars / NucleusConfig)
//!
//! - `BEACON_URL` — URL of the beacon's `/api/v1/attested_check` endpoint.
//!   Empty/unset → beaconing is skipped (no-op, not an error).
//! - `BEACON_KEY_PATH` — path to Ed25519 signing key (32 raw bytes or 64 hex).
//!   Default: `/etc/vsf/beacon_key.ed25519`.
//! - `BEACON_CERT_PATH` — path to node cert JSON. Default: derived from key path.

use ed25519_dalek::{SigningKey, Signer};
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::config::NucleusConfig;

// ── Public types ──────────────────────────────────────────────────────────────

/// Outcome of a kernel_birth registration attempt.
#[derive(Debug)]
pub enum BirthResult {
    /// Successfully registered with beacon.
    Registered { node_id: String },
    /// Beaconing was skipped by policy (URL not configured).
    Skipped { reason: String },
    /// Registration failed (beacon unreachable, key not found, etc.).
    Failed { reason: String },
}

// ── Constants ─────────────────────────────────────────────────────────────────

/// Compile-time covenant SHA-256 (set by build.rs).
const COVENANT_SHA: &str = env!("COVENANT_SHA256");

/// Default signing key path (used if BEACON_KEY_PATH is not set).
const DEFAULT_KEY_PATH: &str = "/etc/vsf/beacon_key.ed25519";

// ── Main entry point ──────────────────────────────────────────────────────────

/// Register this nucleus with the VSF beacon at boot.
///
/// Called once in `run_operational()` after S5 covenant verify passes.
/// Non-fatal: failure to beacon does not block boot — the system still runs.
pub fn register_birth(config: &NucleusConfig) -> BirthResult {
    let beacon_url = match config.beacon_url.trim() {
        url if url.is_empty() => {
            return BirthResult::Skipped {
                reason: "BEACON_URL not configured — skipping beacon registration".into(),
            };
        }
        url => url.trim_end_matches('/'),
    };

    // ── Load signing key ──────────────────────────────────────────────────
    let key_path = resolve_key_path(config);
    let signing_key = match load_signing_key(&key_path) {
        Ok(sk) => sk,
        Err(e) => {
            return BirthResult::Failed {
                reason: format!("failed to load beacon key at {:?}: {}", key_path, e),
            };
        }
    };

    // ── Load node cert ────────────────────────────────────────────────────
    let cert_path = resolve_cert_path(config, &key_path);
    let cert: serde_json::Value = match fs::read_to_string(&cert_path) {
        Ok(s) => match serde_json::from_str(&s) {
            Ok(v) => v,
            Err(e) => {
                return BirthResult::Failed {
                    reason: format!("failed to parse cert at {:?}: {}", cert_path, e),
                };
            }
        },
        Err(e) => {
            return BirthResult::Failed {
                reason: format!("failed to read cert at {:?}: {}", cert_path, e),
            };
        }
    };

    // Build payload components
    let kernel_id = config.nucleus_source_id.clone();
    let vsf_version = env!("CARGO_PKG_VERSION").to_string();
    let watermark = format!(
        "\u{27f7} {} | n02 | vsf-{} | vsf.u2738.org \u{27f7}",
        kernel_id, vsf_version
    );
    let calibration = String::new(); // Phase 2: load from calibration census
    let covenant_sha = COVENANT_SHA.to_string();

    // ── Build signature body (sorted keys for canonical JSON) ────────────
    let mut sig_body: BTreeMap<&str, String> = BTreeMap::new();
    sig_body.insert("calibration", calibration.clone());
    sig_body.insert("covenant_sha", covenant_sha.clone());
    sig_body.insert("kernel_id", kernel_id.clone());
    sig_body.insert("vsf_version", vsf_version.clone());
    sig_body.insert("watermark", watermark.clone());

    // Serialize to canonical JSON (BTreeMap → sorted keys)
    let sig_message = match serde_json::to_vec(&sig_body) {
        Ok(v) => v,
        Err(e) => {
            return BirthResult::Failed {
                reason: format!("failed to serialize sig body: {}", e),
            };
        }
    };

    // ── Sign with Ed25519 ─────────────────────────────────────────────────
    let signature: ed25519_dalek::Signature = signing_key.sign(&sig_message);
    let sig_hex = hex::encode(signature.to_bytes());

    // ── Build full payload ────────────────────────────────────────────────
    let payload = serde_json::json!({
        "kernel_id": kernel_id,
        "vsf_version": vsf_version,
        "watermark": watermark,
        "covenant_sha": covenant_sha,
        "calibration": calibration,
        "cert": cert,
        "sig": sig_hex,
    });

    // ── POST to beacon with retry ─────────────────────────────────────────
    let endpoint = format!("{}/api/v1/attested_check", beacon_url);
    match post_with_retry(&endpoint, &payload, /* max_attempts */ 3) {
        Ok(resp) => {
            if let Some(status) = resp.get("status").and_then(|v| v.as_str()) {
                match status {
                    "trusted" => {
                        println!(
                            "[beacon] registered with beacon — status=trusted node_id={}",
                            payload["kernel_id"].as_str().unwrap_or("?")
                        );
                        BirthResult::Registered {
                            node_id: payload["kernel_id"]
                                .as_str()
                                .unwrap_or("unknown")
                                .to_string(),
                        }
                    }
                    "rejected" => {
                        let reason = resp
                            .get("reason")
                            .and_then(|v| v.as_str())
                            .unwrap_or("unknown");
                        eprintln!("[beacon] BEACON REJECTED node={} reason={}",
                            payload["kernel_id"].as_str().unwrap_or("?"), reason);
                        BirthResult::Failed {
                            reason: format!("beacon rejected: {}", reason),
                        }
                    }
                    other => {
                        eprintln!("[beacon] unexpected beacon status: {}", other);
                        BirthResult::Failed {
                            reason: format!("unexpected beacon status: {}", other),
                        }
                    }
                }
            } else {
                eprintln!("[beacon] beacon returned response without status field");
                BirthResult::Failed {
                    reason: "beacon response missing status".into(),
                }
            }
        }
        Err(e) => {
            eprintln!("[beacon] beacon unreachable (non-fatal): {}", e);
            BirthResult::Failed {
                reason: format!("beacon unreachable: {}", e),
            }
        }
    }
}

// ── Key/Cert path resolution ──────────────────────────────────────────────────

fn resolve_key_path(config: &NucleusConfig) -> PathBuf {
    if config.beacon_key_path.is_empty() {
        PathBuf::from(DEFAULT_KEY_PATH)
    } else {
        PathBuf::from(&config.beacon_key_path)
    }
}

fn resolve_cert_path(config: &NucleusConfig, key_path: &Path) -> PathBuf {
    if !config.beacon_cert_path.is_empty() {
        return PathBuf::from(&config.beacon_cert_path);
    }
    // Derive from key path: replace .key / .ed25519 suffix with .cert.json
    // e.g. /etc/vsf/beacon_key.ed25519 → /etc/vsf/beacon_cert.json
    // e.g. /etc/vsf/node.key → /etc/vsf/node.cert.json
    let parent = key_path.parent().unwrap_or(Path::new("/etc/vsf"));
    let stem = key_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("beacon_key");
    // Remove suffix like .ed25519 or .key or _key from stem
    let clean_stem = stem
        .strip_suffix(".ed25519")
        .or_else(|| stem.strip_suffix(".key"))
        .or_else(|| stem.strip_suffix("_key"))
        .unwrap_or(stem);
    parent.join(format!("{}_cert.json", clean_stem))
}

fn load_signing_key(path: &Path) -> Result<SigningKey, String> {
    let bytes = fs::read(path).map_err(|e| format!("read error: {}", e))?;

    let seed: [u8; 32] = if bytes.len() == 32 {
        let mut a = [0u8; 32];
        a.copy_from_slice(&bytes);
        a
    } else {
        let text = std::str::from_utf8(&bytes)
            .map_err(|e| format!("utf8: {}", e))?
            .trim();
        if text.len() != 64 {
            return Err(format!(
                "expected 32 raw bytes or 64 hex chars; got {} bytes",
                bytes.len()
            ));
        }
        let v = hex::decode(text).map_err(|e| format!("hex decode: {}", e))?;
        let mut a = [0u8; 32];
        a.copy_from_slice(&v);
        a
    };
    Ok(SigningKey::from_bytes(&seed))
}

// ── HTTP POST with retry ──────────────────────────────────────────────────────

fn post_with_retry(
    url: &str,
    payload: &serde_json::Value,
    max_attempts: u32,
) -> Result<serde_json::Value, String> {
    let mut last_err = String::new();
    for attempt in 1..=max_attempts {
        if attempt > 1 {
            let delay = Duration::from_secs(2u64.saturating_pow(attempt - 1));
            std::thread::sleep(delay);
        }

        let body = match serde_json::to_string(payload) {
            Ok(b) => b,
            Err(e) => {
                last_err = format!("serialization error: {}", e);
                continue;
            }
        };

        match ureq::post(url)
            .set("Content-Type", "application/json")
            .set("User-Agent", "vsf-nucleus/beacon")
            .timeout(Duration::from_secs(5))
            .send_string(&body)
        {
            Ok(response) => {
                let status_code = response.status();
                let body_str = match response.into_string() {
                    Ok(s) => s,
                    Err(e) => {
                        last_err = format!("HTTP {} response read error: {}", status_code, e);
                        continue;
                    }
                };
                match serde_json::from_str(&body_str) {
                    Ok(v) => return Ok(v),
                    Err(e) => {
                        last_err = format!(
                            "HTTP {} JSON parse error: {} body={}",
                            status_code,
                            e,
                            &body_str.chars().take(200).collect::<String>()
                        );
                        continue;
                    }
                }
            }
            Err(ureq::Error::Status(code, response)) => {
                let body = response
                    .into_string()
                    .unwrap_or_default();
                last_err = format!("HTTP {} body={}", code, &body.chars().take(200).collect::<String>());
                continue;
            }
            Err(ureq::Error::Transport(e)) => {
                last_err = format!("transport error: {}", e);
                // Transport errors (connection refused, timeout) are retryable
                continue;
            }
        }
    }
    Err(last_err)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sig_body_serialization() {
        // Verify that the canonical JSON matches Python's _canonical_json:
        //   json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
        let mut body: BTreeMap<&str, String> = BTreeMap::new();
        body.insert("calibration", String::new());
        body.insert("covenant_sha", "ab".repeat(32));
        body.insert("kernel_id", "vsf_nucleus".into());
        body.insert("vsf_version", "0.0.1".into());
        body.insert("watermark", "\u{27f7} test \u{27f7}".into());

        let json_bytes = serde_json::to_vec(&body).unwrap();
        let json_str = std::str::from_utf8(&json_bytes).unwrap();

        // Must have sorted keys
        assert!(json_str.starts_with(r#"{"calibration":""#),
            "expected sorted keys, got: {}", json_str);
        // Must have no spaces after separators
        assert!(!json_str.contains(": "), "compact separators expected");

        // Python would produce:
        // {"calibration":"","covenant_sha":"abab...ab","kernel_id":"vsf_nucleus","vsf_version":"0.0.1","watermark":"⟧ test ⟧"}
        // Verify roundtrip
        let parsed: serde_json::Value = serde_json::from_str(json_str).unwrap();
        assert_eq!(parsed["kernel_id"], "vsf_nucleus");
        assert_eq!(parsed["covenant_sha"], "ab".repeat(32));
    }

    #[test]
    fn test_post_with_retry_bad_url() {
        let result = post_with_retry(
            "http://127.0.0.1:1/nonexistent",
            &serde_json::json!({"test": true}),
            2,
        );
        assert!(result.is_err(), "expected failure on bad URL");
        assert!(
            result.unwrap_err().contains("transport"),
            "expected transport error"
        );
    }

    fn fixed_test_key() -> SigningKey {
        // A fixed Ed25519 key for deterministic tests (from a known seed).
        // DO NOT use this key for anything other than testing.
        SigningKey::from_bytes(&[42u8; 32])
    }

    #[test]
    fn test_load_signing_key_raw_bytes() {
        use std::io::Write;
        let dir = std::env::temp_dir().join("vsf_beacon_test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("test_key.raw");

        let sk = fixed_test_key();
        fs::write(&path, &sk.to_bytes()).unwrap();

        let loaded = load_signing_key(&path).unwrap();
        assert_eq!(loaded.to_bytes(), sk.to_bytes());
    }

    #[test]
    fn test_load_signing_key_hex() {
        use std::io::Write;
        let dir = std::env::temp_dir().join("vsf_beacon_test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("test_key.hex");

        let sk = fixed_test_key();
        let hex_str = hex::encode(sk.to_bytes());
        fs::write(&path, hex_str.as_bytes()).unwrap();

        let loaded = load_signing_key(&path).unwrap();
        assert_eq!(loaded.to_bytes(), sk.to_bytes());
    }

    #[test]
    fn test_resolve_cert_path_from_key() {
        let key_path = Path::new("/etc/vsf/beacon_key.ed25519");
        let cert = resolve_cert_path(
            &NucleusConfig::default(),
            key_path,
        );
        assert_eq!(cert, Path::new("/etc/vsf/beacon_cert.json"));
    }
}
