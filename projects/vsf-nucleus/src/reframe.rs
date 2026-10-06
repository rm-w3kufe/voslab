// reframe.rs — F5.x.7 — staged reframe() with mandatory S5 approval + re-certification
//
// Implements: docs/theory/dynamics_choice.vsm §G5
//             ("staged auto-execution with mandatory S5 approval + post-commit re-certification")
//
// axiom_ref: covenant_ops.vsm#§regulation.Ax_ReframeScope@v0.1
//
//   Ax_ReframeScope: parameter_drift ∈ L2 ; axiom_or_topology_change ∈ L3 ;
//                    capability_extension ∈ L2 + audit
//     → this module classifies every reframe request into a loop class and REFUSES
//       to auto-execute an L3 (axiom/topology) change without an explicit human
//       approval (A5 ceiling / D4-L3 double-loop). Parameter drift (L2) is kernel-
//       autonomous within the ceiling; capability extension is L2 + mandatory audit.
//
//   Def_Reframe_Staged: propose → S5.approve → execute → certify(τ_recert) → commit
//   Def_RecertEpoch:    τ_recert = 2·τ_rec ; Lyapunov-monitor active ;
//                       rollback if stasis_cos < θ_PSI during the recert window
//
// Snapshot/rollback is atomic: execute() clones the full ℝ¹²⁸ state before mutating;
// a failed re-certification restores it byte-for-byte (caveats_for_implementation
// §rollback_protocol).
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::state_vector::{StateVector, STASIS_COS};
use chrono::Utc;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

/// Empirical PSI re-certification floor (EXP-PSI-01 / critical_angle: θ_PSI < 0.9377;
/// measured θ_PSI ≈ 0.79). If stasis_cos drops below this during the recert window
/// the reframe is rolled back.
pub const THETA_PSI: f64 = crate::calibration::THETA_PSI;  // single source (EXP-TP-01)

/// Default τ_rec (recovery time) in ticks — matches main.rs TAU_RECOVERY.
/// τ_recert = 2·τ_rec (Def_RecertEpoch).
pub const DEFAULT_TAU_REC: u32 = crate::calibration::TAU_REC;  // single source (EXP-TC-01)

// ─── S5 approval token (signed by the OFFLINE root; verified here) ──────────────
// Closes the unauthenticated `Human { signatory: String }` hole: an L3 approval must carry an
// ed25519 signature by the offline S5 ROOT — the SAME root AX-STATE/witness pin. Default-deny:
// no valid token ⇒ no L3 change. Signing side = scripts/state/s5_ca.py `approve` (certified, 21/0).
// The canonical_payload below MUST byte-match s5_ca.py `_payload(DOMAIN_APPROVAL, …)` exactly, or no
// signature ever verifies — certified by a cross-language fixture test. docs/spec/s5_approval_channel.

const DOMAIN_APPROVAL: &[u8] = b"VSF-S5-APPROVAL-v1";
const APPROVAL_T_NAME: u8 = 0x01;
const APPROVAL_T_STR: u8 = 0x02;

/// The signed approval token — 1:1 with the JSON `s5_ca.py approve` emits.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct ApprovalToken {
    pub v: u64,
    #[serde(rename = "type")]
    pub typ: String,
    pub proposal_id: String,
    pub proposal_hash: String,
    pub decision: String,
    pub nonce: String,
    pub not_before: String,
    pub not_after: String,
    pub root_id: String,
    pub sig: String,
}

fn approval_frame(out: &mut Vec<u8>, tag: u8, b: &[u8]) {
    out.push(tag);
    out.extend_from_slice(&(b.len() as u32).to_be_bytes());
    out.extend_from_slice(b);
}

/// Decode a fixed-length hex string into `out`; false on bad length / non-hex.
fn hex_into(s: &str, out: &mut [u8]) -> bool {
    if s.len() != out.len() * 2 {
        return false;
    }
    for (i, byte) in out.iter_mut().enumerate() {
        match u8::from_str_radix(&s[2 * i..2 * i + 2], 16) {
            Ok(v) => *byte = v,
            Err(_) => return false,
        }
    }
    true
}

/// SHA-256 of `id || ":" || description` — canonical proposal content hash.
/// Used by `propose()` and MUST match `token.proposal_hash` for any L3 approval.
fn compute_content_hash(id: &str, description: &str) -> String {
    let mut h = Sha256::new();
    h.update(id.as_bytes());
    h.update(b":");
    h.update(description.as_bytes());
    hex::encode(h.finalize())
}

impl ApprovalToken {
    /// Canonical signing payload — MUST byte-match s5_ca.py `_payload(DOMAIN_APPROVAL, …)`.
    /// Fixed field order; each value is its string form (v rendered as decimal) utf8.
    pub fn canonical_payload(&self) -> Vec<u8> {
        let v_str = self.v.to_string();
        let fields: [(&str, &str); 9] = [
            ("v", &v_str),
            ("type", &self.typ),
            ("proposal_id", &self.proposal_id),
            ("proposal_hash", &self.proposal_hash),
            ("decision", &self.decision),
            ("nonce", &self.nonce),
            ("not_before", &self.not_before),
            ("not_after", &self.not_after),
            ("root_id", &self.root_id),
        ];
        let mut out = Vec::with_capacity(256);
        out.extend_from_slice(DOMAIN_APPROVAL);
        for (name, val) in &fields {
            approval_frame(&mut out, APPROVAL_T_NAME, name.as_bytes());
            approval_frame(&mut out, APPROVAL_T_STR, val.as_bytes());
        }
        out
    }

    /// Full semantic gate: sig + decision + binding + in-window + nonce-unseen.
    /// On success the nonce is recorded in `seen_nonces` (prevents replay).
    /// PSI L3 escalation uses this same function — one gate, one offline root.
    pub fn verify_for_proposal(
        &self,
        proposal_id: &str,
        content_hash: &str,
        root_pub: &[u8; 32],
        seen_nonces: &mut HashSet<String>,
    ) -> Result<(), &'static str> {
        if !self.sig_verifies(root_pub) {
            return Err("signature invalid");
        }
        if self.decision != "approve" {
            return Err("decision != approve");
        }
        if self.proposal_id != proposal_id {
            return Err("proposal_id mismatch");
        }
        if self.proposal_hash != content_hash {
            return Err("proposal_hash mismatch");
        }
        let now = Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();
        if self.not_before.as_str() > now.as_str() {
            return Err("token not yet valid");
        }
        if now.as_str() > self.not_after.as_str() {
            return Err("token expired");
        }
        if seen_nonces.contains(&self.nonce) {
            return Err("nonce replay");
        }
        seen_nonces.insert(self.nonce.clone());
        Ok(())
    }

    /// True iff the ed25519 signature verifies under the given 32-byte root pubkey.
    /// Does NOT check decision / window / proposal binding / nonce — that is `verify_for_proposal`.
    pub fn sig_verifies(&self, root_pub: &[u8; 32]) -> bool {
        let vk = match VerifyingKey::from_bytes(root_pub) {
            Ok(k) => k,
            Err(_) => return false,
        };
        let mut sig_arr = [0u8; 64];
        if !hex_into(&self.sig, &mut sig_arr) {
            return false;
        }
        let sig = Signature::from_bytes(&sig_arr);
        vk.verify(&self.canonical_payload(), &sig).is_ok()
    }
}

// ─── Ax_ReframeScope — scope → loop class ──────────────────────────────────────

/// What a reframe request changes. Drives the loop-class (and thus the approval
/// requirement) per Ax_ReframeScope.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReframeScope {
    /// Drift of operator parameters {α, β, γ, δ}, μ_s, τ — within the existing class.
    ParameterDrift,
    /// Adding a new capability / mode within the authorized class.
    CapabilityExtension,
    /// Changing Ω, L_max, or an axiom — redefines the class itself.
    AxiomOrTopology,
}

/// Loop class per D4 / Ax_ReframeScope.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LoopClass {
    /// Single-loop, kernel-autonomous WITHIN the A5 ceiling.
    L2Autonomous,
    /// Single-loop but with a mandatory audit record.
    L2Audit,
    /// Double-loop — REQUIRES human approval (A5 / D4-L3). Never auto-executed.
    L3RequiresHuman,
}

impl ReframeScope {
    pub fn loop_class(&self) -> LoopClass {
        match self {
            ReframeScope::ParameterDrift => LoopClass::L2Autonomous,
            ReframeScope::CapabilityExtension => LoopClass::L2Audit,
            ReframeScope::AxiomOrTopology => LoopClass::L3RequiresHuman,
        }
    }

    /// True iff a human signatory is required to approve (Ax_ReframeScope / A5).
    pub fn requires_human(&self) -> bool {
        self.loop_class() == LoopClass::L3RequiresHuman
    }
}

// ─── Approval (provided by S5 — the kernel cannot self-grant human approval) ────

/// Approval token presented to `approve`. The kernel may synthesize an autonomous
/// approval ONLY for L2; for L3 the human approval MUST be cryptographically signed
/// by the offline S5 root. The kernel cannot forge a `HumanSigned` token.
#[derive(Debug, Clone)]
pub enum Approval {
    /// Kernel-autonomous approval (valid for L2 single-loop only).
    Autonomous,
    /// Unauthenticated string label (valid for L2 only; L3 rejects this).
    Human { signatory: String },
    /// Offline-root ed25519 signed approval — REQUIRED for L3 (A5/D4-L3).
    /// Carries the token AND the pinned root pubkey bytes so the kernel can verify
    /// without a network connection (same root as AX-STATE/witness_verify).
    HumanSigned { token: ApprovalToken, root_pub: [u8; 32] },
}

// ─── Staged state machine (Def_Reframe_Staged) ─────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReframeStage {
    Proposed,
    Approved,
    Certifying,
    Committed,
    RolledBack,
    Rejected,
}

/// Re-certification window config (Def_RecertEpoch).
#[derive(Debug, Clone, Copy)]
pub struct RecertConfig {
    pub tau_rec: u32,
    pub theta_psi: f64,
}

impl Default for RecertConfig {
    fn default() -> Self {
        RecertConfig { tau_rec: DEFAULT_TAU_REC, theta_psi: THETA_PSI }
    }
}

impl RecertConfig {
    /// Def_RecertEpoch: τ_recert = 2·τ_rec.
    pub fn tau_recert(&self) -> u32 {
        self.tau_rec.saturating_mul(2)
    }
}

/// A single reframe proposal moving through the staged machine.
#[derive(Debug, Clone)]
pub struct ReframeProposal {
    pub id: String,
    pub scope: ReframeScope,
    pub description: String,
    /// SHA-256 of `id || ":" || description` — must match `token.proposal_hash` for L3 approvals.
    pub content_hash: String,
    pub stage: ReframeStage,
    pub recert: RecertConfig,
    /// Whether this proposal must be written to the audit log on commit
    /// (true for CapabilityExtension and every L3).
    pub audit_required: bool,
    /// Pre-reframe snapshot of the full state — set at execute(), used by rollback.
    snapshot: Option<StateVector>,
    /// Ticks elapsed inside the recert window.
    recert_ticks: u32,
    /// Approver recorded at approval time (for the audit trail).
    pub approved_by: Option<String>,
}

/// Outcome of a single re-certification tick.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CertifyOutcome {
    /// Still inside the recert window, stasis above θ_PSI — keep monitoring.
    Monitoring,
    /// Window elapsed with stasis maintained — proposal committed.
    Committed,
    /// stasis_cos breached θ_PSI — proposal rolled back to the snapshot.
    RolledBack,
}

impl ReframeProposal {
    /// Stage 1 — propose. Classifies scope; sets audit flag; computes content_hash.
    pub fn propose(
        id: impl Into<String>,
        scope: ReframeScope,
        description: impl Into<String>,
        recert: RecertConfig,
    ) -> Self {
        let id = id.into();
        let description = description.into();
        let content_hash = compute_content_hash(&id, &description);
        let audit_required = matches!(
            scope.loop_class(),
            LoopClass::L2Audit | LoopClass::L3RequiresHuman
        );
        ReframeProposal {
            id,
            scope,
            description,
            content_hash,
            stage: ReframeStage::Proposed,
            recert,
            audit_required,
            snapshot: None,
            recert_ticks: 0,
            approved_by: None,
        }
    }

    /// Stage 2 — S5 approval. Enforces Ax_ReframeScope (A5/D4-L3):
    ///   L3 requires `HumanSigned` with a fully-verified token (sig + hash + window + nonce).
    ///   L2 accepts any `Approval` variant.
    /// `seen_nonces` is checked + updated on HumanSigned calls (cross-proposal replay guard).
    /// Returns true if approved (→ Approved), false if rejected (→ Rejected).
    pub fn approve(&mut self, approval: Approval, seen_nonces: &mut HashSet<String>) -> bool {
        if self.stage != ReframeStage::Proposed {
            return false;
        }
        let requires_human = self.scope.requires_human();
        let (ok, approver) = match (requires_human, approval) {
            // L3: MUST be HumanSigned with a fully-verified token.
            (true, Approval::HumanSigned { token, root_pub }) => {
                match token.verify_for_proposal(&self.id, &self.content_hash, &root_pub, seen_nonces) {
                    Ok(()) => (true, format!("human-signed:{}", token.root_id)),
                    Err(_) => (false, String::new()),
                }
            }
            // L3: unauthenticated forms (Human or Autonomous) — rejected.
            (true, _) => (false, String::new()),
            // L2: all forms accepted.
            (false, Approval::HumanSigned { token, .. }) => (true, format!("human-signed:{}", token.root_id)),
            (false, Approval::Human { signatory }) => (true, signatory),
            (false, Approval::Autonomous) => (true, "kernel(L2-autonomous)".to_string()),
        };
        if ok {
            self.approved_by = Some(approver);
            self.stage = ReframeStage::Approved;
        } else {
            self.stage = ReframeStage::Rejected;
        }
        ok
    }

    /// Stage 3 — execute. Snapshots `state` atomically, then applies `change`.
    /// Only valid from Approved. Transitions to Certifying. The closure is where
    /// the actual parameter/mode/Ω mutation happens — applied to a COPY-then-swap
    /// so a failed certify restores the snapshot exactly.
    pub fn execute<F: FnOnce(&mut StateVector)>(
        &mut self,
        state: &mut StateVector,
        change: F,
    ) -> bool {
        if self.stage != ReframeStage::Approved {
            return false;
        }
        self.snapshot = Some(state.clone());
        change(state);
        self.recert_ticks = 0;
        self.stage = ReframeStage::Certifying;
        true
    }

    /// Stage 4 — certify one tick (Def_RecertEpoch). Feed the current stasis_cos.
    /// Lyapunov-monitor semantics: if stasis_cos < θ_PSI at any point in the
    /// window → immediate atomic rollback. If the window (τ_recert) elapses with
    /// stasis maintained → commit.
    pub fn certify_tick(&mut self, state: &mut StateVector, stasis_cos: f64) -> CertifyOutcome {
        if self.stage != ReframeStage::Certifying {
            return CertifyOutcome::Monitoring;
        }
        if stasis_cos < self.recert.theta_psi {
            self.rollback(state);
            return CertifyOutcome::RolledBack;
        }
        self.recert_ticks = self.recert_ticks.saturating_add(1);
        if self.recert_ticks >= self.recert.tau_recert() {
            self.stage = ReframeStage::Committed;
            self.snapshot = None; // commit: discard the rollback point
            CertifyOutcome::Committed
        } else {
            CertifyOutcome::Monitoring
        }
    }

    /// Atomic rollback to the pre-reframe snapshot. Idempotent once RolledBack.
    fn rollback(&mut self, state: &mut StateVector) {
        if let Some(snap) = self.snapshot.take() {
            *state = snap;
        }
        self.stage = ReframeStage::RolledBack;
    }

    /// Convenience: read stasis_cos straight from a state vector.
    pub fn stasis_of(state: &StateVector) -> f64 {
        state.dims[STASIS_COS]
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    fn state_with_stasis(cos: f64) -> StateVector {
        let mut s = StateVector { dims: [0.0; 128] };
        s.dims[STASIS_COS] = cos;
        s
    }

    #[test]
    fn scope_maps_to_loop_class_per_axiom() {
        assert_eq!(ReframeScope::ParameterDrift.loop_class(), LoopClass::L2Autonomous);
        assert_eq!(ReframeScope::CapabilityExtension.loop_class(), LoopClass::L2Audit);
        assert_eq!(ReframeScope::AxiomOrTopology.loop_class(), LoopClass::L3RequiresHuman);
        assert!(ReframeScope::AxiomOrTopology.requires_human());
        assert!(!ReframeScope::ParameterDrift.requires_human());
    }

    #[test]
    fn l3_rejects_autonomous_approval() {
        // Ax_ReframeScope / A5: axiom-or-topology change cannot be self-approved.
        let mut p = ReframeProposal::propose(
            "r1", ReframeScope::AxiomOrTopology, "modify Ω boundary", RecertConfig::default());
        assert!(!p.approve(Approval::Autonomous, &mut HashSet::new()));
        assert_eq!(p.stage, ReframeStage::Rejected);
    }

    #[test]
    fn l3_rejects_plain_human_for_l3() {
        // L3 now requires HumanSigned; unauthenticated Human is no longer sufficient.
        let mut p = ReframeProposal::propose(
            "r2", ReframeScope::AxiomOrTopology, "modify L_max", RecertConfig::default());
        assert!(!p.approve(Approval::Human { signatory: "rmw3".into() }, &mut HashSet::new()));
        assert_eq!(p.stage, ReframeStage::Rejected);
        assert!(p.audit_required);
    }

    #[test]
    fn l2_parameter_drift_is_autonomous() {
        let mut p = ReframeProposal::propose(
            "r3", ReframeScope::ParameterDrift, "nudge α", RecertConfig::default());
        assert!(p.approve(Approval::Autonomous, &mut HashSet::new()));
        assert_eq!(p.stage, ReframeStage::Approved);
        assert!(!p.audit_required);
    }

    #[test]
    fn capability_extension_requires_audit_but_is_l2() {
        let mut p = ReframeProposal::propose(
            "r4", ReframeScope::CapabilityExtension, "add mode μ_6", RecertConfig::default());
        assert!(p.approve(Approval::Autonomous, &mut HashSet::new())); // L2 — autonomous OK
        assert!(p.audit_required);                                      // but flagged for audit
    }

    #[test]
    fn full_happy_path_commits_after_recert_window() {
        let cfg = RecertConfig { tau_rec: 3, theta_psi: 0.79 }; // τ_recert = 6
        let mut p = ReframeProposal::propose("r5", ReframeScope::ParameterDrift, "α+", cfg);
        assert!(p.approve(Approval::Autonomous, &mut HashSet::new()));
        let mut state = state_with_stasis(0.95);
        assert!(p.execute(&mut state, |s| { s.dims[19] = 0.5; })); // mutate BUDGET
        assert_eq!(p.stage, ReframeStage::Certifying);
        // 6 ticks above θ_PSI → commit
        let mut outcome = CertifyOutcome::Monitoring;
        for _ in 0..6 {
            outcome = p.certify_tick(&mut state, 0.95);
        }
        assert_eq!(outcome, CertifyOutcome::Committed);
        assert_eq!(p.stage, ReframeStage::Committed);
        assert_eq!(state.dims[19], 0.5); // change persisted
    }

    #[test]
    fn breach_triggers_atomic_rollback() {
        let cfg = RecertConfig { tau_rec: 50, theta_psi: 0.79 };
        let mut p = ReframeProposal::propose("r6", ReframeScope::ParameterDrift, "α+", cfg);
        assert!(p.approve(Approval::Autonomous, &mut HashSet::new()));
        let mut state = state_with_stasis(0.95);
        let original = state.clone();
        p.execute(&mut state, |s| { s.dims[19] = 0.9; });
        // a few healthy ticks
        assert_eq!(p.certify_tick(&mut state, 0.95), CertifyOutcome::Monitoring);
        // stasis collapses below θ_PSI → rollback
        assert_eq!(p.certify_tick(&mut state, 0.60), CertifyOutcome::RolledBack);
        assert_eq!(p.stage, ReframeStage::RolledBack);
        // state restored byte-for-byte
        assert_eq!(state.dims, original.dims);
    }

    #[test]
    fn cannot_execute_without_approval() {
        let mut p = ReframeProposal::propose(
            "r7", ReframeScope::ParameterDrift, "x", RecertConfig::default());
        let mut state = state_with_stasis(0.95);
        assert!(!p.execute(&mut state, |_s| {})); // still Proposed
        assert_eq!(p.stage, ReframeStage::Proposed);
    }

    #[test]
    fn tau_recert_is_double_tau_rec() {
        assert_eq!(RecertConfig { tau_rec: 50, theta_psi: 0.79 }.tau_recert(), 100);
    }

    // ── S5 approval token — cross-language interop with s5_ca.py ────────────────
    #[test]
    fn approval_payload_byte_matches_python_and_sig_verifies() {
        // Fixture generated by s5_ca.py make_approval (fixed seed = bytes(range(32))). Certifies the
        // Rust canonical_payload byte-matches s5_ca.py _payload AND the offline-root ed25519 sig verifies.
        const ROOT_PUB_HEX: &str =
            "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8";
        const TOKEN_JSON: &str = r#"{"v": 1, "type": "vsf-s5-approval", "proposal_id": "reframe-fixture-1", "proposal_hash": "abababababababababababababababababababababababababababababababab", "decision": "approve", "nonce": "3d33734212d94e790282f03a7db14c43", "not_before": "2026-06-22T13:46:14Z", "not_after": "2058-02-28T15:37:54Z", "root_id": "ed25519:56475aa75463474c", "sig": "67ba1a0bd5e91c6d8164151ea3c0e4af03590e9156431b9f4d2adc963fd5b9f539e2150a63fb44b8482bc65cc35fccb8decb8f0a3d8a9dc9ef58c9c2960f8708"}"#;
        const PAYLOAD_HEX: &str = "5653462d53352d415050524f56414c2d7631010000000176020000000131010000000474797065020000000f7673662d73352d617070726f76616c010000000b70726f706f73616c5f6964020000001172656672616d652d666978747572652d31010000000d70726f706f73616c5f6861736802000000406162616261626162616261626162616261626162616261626162616261626162616261626162616261626162616261626162616261626162616261626162616201000000086465636973696f6e0200000007617070726f766501000000056e6f6e636502000000203364333337333432313264393465373930323832663033613764623134633433010000000a6e6f745f6265666f72650200000014323032362d30362d32325431333a34363a31345a01000000096e6f745f61667465720200000014323035382d30322d32385431353a33373a35345a0100000007726f6f745f69640200000018656432353531393a35363437356161373534363334373463";

        let tok: ApprovalToken = serde_json::from_str(TOKEN_JSON).unwrap();
        // 1. the canonical payload byte-matches Python's _payload framing
        let got: String = tok.canonical_payload().iter().map(|b| format!("{:02x}", b)).collect();
        assert_eq!(got, PAYLOAD_HEX, "Rust framing must byte-match s5_ca.py _payload");
        // 2. the offline-root signature verifies
        let mut root = [0u8; 32];
        assert!(hex_into(ROOT_PUB_HEX, &mut root));
        assert!(tok.sig_verifies(&root), "fixture token sig must verify against the root pubkey");
        // 3. negatives: a flipped root pubkey, and a tampered field, both fail
        let mut bad_root = root;
        bad_root[0] ^= 0xff;
        assert!(!tok.sig_verifies(&bad_root), "wrong root must reject");
        let mut tampered = tok.clone();
        tampered.decision = "deny".to_string();
        assert!(!tampered.sig_verifies(&root), "tampering any signed field must reject");
    }

    // ── verify_for_proposal + approve L3 gate ───────────────────────────────────
    const FIXTURE_ROOT: &str =
        "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8";
    const FIXTURE_TOKEN: &str = r#"{"v": 1, "type": "vsf-s5-approval", "proposal_id": "reframe-fixture-1", "proposal_hash": "abababababababababababababababababababababababababababababababab", "decision": "approve", "nonce": "3d33734212d94e790282f03a7db14c43", "not_before": "2026-06-22T13:46:14Z", "not_after": "2058-02-28T15:37:54Z", "root_id": "ed25519:56475aa75463474c", "sig": "67ba1a0bd5e91c6d8164151ea3c0e4af03590e9156431b9f4d2adc963fd5b9f539e2150a63fb44b8482bc65cc35fccb8decb8f0a3d8a9dc9ef58c9c2960f8708"}"#;
    const FIXTURE_HASH: &str = "abababababababababababababababababababababababababababababababab";

    fn fixture_root() -> [u8; 32] {
        let mut r = [0u8; 32];
        assert!(hex_into(FIXTURE_ROOT, &mut r));
        r
    }

    fn fixture_token() -> ApprovalToken {
        serde_json::from_str(FIXTURE_TOKEN).unwrap()
    }

    fn l3_proposal_with_fixture_hash() -> ReframeProposal {
        let mut p = ReframeProposal::propose(
            "reframe-fixture-1", ReframeScope::AxiomOrTopology, "x", RecertConfig::default());
        p.content_hash = FIXTURE_HASH.to_string();
        p
    }

    #[test]
    fn l3_accepts_human_signed_valid_token() {
        let mut p = l3_proposal_with_fixture_hash();
        let ok = p.approve(
            Approval::HumanSigned { token: fixture_token(), root_pub: fixture_root() },
            &mut HashSet::new(),
        );
        assert!(ok, "valid HumanSigned token must approve L3");
        assert_eq!(p.stage, ReframeStage::Approved);
        assert!(p.approved_by.as_deref().unwrap_or("").starts_with("human-signed:"));
    }

    #[test]
    fn l3_rejects_hash_mismatch() {
        // content_hash NOT overridden — sha256("reframe-fixture-1:x") ≠ FIXTURE_HASH
        let mut p = ReframeProposal::propose(
            "reframe-fixture-1", ReframeScope::AxiomOrTopology, "x", RecertConfig::default());
        let ok = p.approve(
            Approval::HumanSigned { token: fixture_token(), root_pub: fixture_root() },
            &mut HashSet::new(),
        );
        assert!(!ok, "token with mismatched proposal_hash must be rejected");
        assert_eq!(p.stage, ReframeStage::Rejected);
    }

    #[test]
    fn l3_rejects_replay_nonce() {
        let mut nonces = HashSet::new();
        // First approval: nonce recorded
        let mut p1 = l3_proposal_with_fixture_hash();
        assert!(p1.approve(
            Approval::HumanSigned { token: fixture_token(), root_pub: fixture_root() },
            &mut nonces,
        ));
        // Second approval with same nonce in the same set → replay rejected
        let mut p2 = l3_proposal_with_fixture_hash();
        assert!(!p2.approve(
            Approval::HumanSigned { token: fixture_token(), root_pub: fixture_root() },
            &mut nonces,
        ), "replayed nonce must be rejected");
        assert_eq!(p2.stage, ReframeStage::Rejected);
    }
}
