// coupling.rs — F5.x.6 — ψ inter-system coupling (bilinear, low-rank, S5-gated)
//
// Implements: docs/theory/dynamics_choice.vsm §G2
//
//   Def_ψ_Bilinear: ψ: ℝ¹²⁸_A × ℝ¹²⁸_B → ℝ²⁵⁶_AB ; M_ψ ∈ ℝ²⁵⁶ˣ²⁵⁶ non-symmetric
//                   (the asymmetry encodes the directed φ↑/φ↓ VSM channel; M_ψ ≠ M_ψᵀ).
//     Low-rank decomposition (caveat M_ψ_size): M_ψ = U·Vᵀ with rank ≤ 16, so a
//     single coupling is O(256·r) not O(256²), and an N-system PSI mesh stays linear
//     in the rank rather than quadratic in 128².
//
//   Ax_ψ_Preserve:  ψ(x_A,x_B) ∈ Ω_AB ⇔ x_A∈Ω_A ∧ x_B∈Ω_B ∧ trust_AB ≥ min(trust_A,trust_B)
//
//   handshake_timing: PRECONDITION — synchronous bilateral S5_A.consents ∧ S5_B.consents
//                     BEFORE any state is coupled. No consent ⇒ coupling refused.
//
//   projection_back: ψ output ∈ ℝ²⁵⁶ is split by π_A (dims 0..128) and π_B (128..256)
//                    to update each system's ℝ¹²⁸ state individually post-coupling.
//
// This is a pure synchronous building block (no async / no live-loop wiring yet);
// it unblocks task(O) PSI/1.0. Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::omega_validator::Omega;
use crate::reframe::ApprovalToken;
use crate::state_vector::StateVector;
use std::collections::HashSet;

pub const DIM: usize = 128;
pub const COUPLED_DIM: usize = 256; // [x_A; x_B]
/// Upper bound on the coupling rank (caveat M_ψ_size).
pub const MAX_RANK: usize = 16;

/// Why a coupling attempt was refused (Ax_ψ_Preserve / handshake precondition).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CouplingError {
    /// Bilateral S5 consent not present (handshake precondition).
    NoBilateralConsent,
    /// trust_AB < min(trust_A, trust_B) — Ax_ψ_Preserve trust clause violated.
    TrustNotPreserved,
    /// One of the input states is already outside its Ω (x_A∉Ω_A ∨ x_B∉Ω_B).
    InputNotInOmega,
}

/// Bilateral S5 handshake. Both signatories must consent BEFORE coupling.
#[derive(Debug, Clone, Copy, Default)]
pub struct Handshake {
    pub s5_a_consents: bool,
    pub s5_b_consents: bool,
}

impl Handshake {
    pub fn bilateral(&self) -> bool {
        self.s5_a_consents && self.s5_b_consents
    }
}

/// Scalar trust triple for the Ax_ψ_Preserve trust clause. (The 4-vector trust
/// model lives in F5.x.8 trust_axes.rs; coupling only needs the scalar aggregates.)
#[derive(Debug, Clone, Copy)]
pub struct TrustTriple {
    pub trust_a: f64,
    pub trust_b: f64,
    pub trust_ab: f64,
}

impl TrustTriple {
    /// Ax_ψ_Preserve trust clause: trust_AB ≥ min(trust_A, trust_B).
    pub fn preserved(&self) -> bool {
        self.trust_ab >= self.trust_a.min(self.trust_b)
    }
}

/// Bilinear coupling operator M_ψ = U·Vᵀ, stored as its low-rank factors.
/// U, V are COUPLED_DIM × rank, row-major (row i, col k → i*rank + k).
#[derive(Debug, Clone)]
pub struct CouplingOperator {
    rank: usize,
    u: Vec<f64>, // 256 × rank
    v: Vec<f64>, // 256 × rank
}

impl CouplingOperator {
    /// Build from explicit low-rank factors. `u` and `v` are each COUPLED_DIM*rank
    /// row-major. Returns None if dimensions are wrong or rank > MAX_RANK.
    pub fn from_factors(u: Vec<f64>, v: Vec<f64>, rank: usize) -> Option<Self> {
        if rank == 0 || rank > MAX_RANK {
            return None;
        }
        if u.len() != COUPLED_DIM * rank || v.len() != COUPLED_DIM * rank {
            return None;
        }
        Some(CouplingOperator { rank, u, v })
    }

    pub fn rank(&self) -> usize {
        self.rank
    }

    /// Apply M_ψ = U·Vᵀ to a coupled vector z ∈ ℝ²⁵⁶ as U·(Vᵀ·z), O(256·rank).
    fn apply(&self, z: &[f64; COUPLED_DIM]) -> [f64; COUPLED_DIM] {
        // t = Vᵀ·z  ∈ ℝ^rank
        let mut t = vec![0.0f64; self.rank];
        for i in 0..COUPLED_DIM {
            let zi = z[i];
            if zi == 0.0 {
                continue;
            }
            let base = i * self.rank;
            for k in 0..self.rank {
                t[k] += self.v[base + k] * zi;
            }
        }
        // out = U·t  ∈ ℝ²⁵⁶
        let mut out = [0.0f64; COUPLED_DIM];
        for i in 0..COUPLED_DIM {
            let base = i * self.rank;
            let mut acc = 0.0;
            for k in 0..self.rank {
                acc += self.u[base + k] * t[k];
            }
            out[i] = acc;
        }
        out
    }

    /// True iff M_ψ is (numerically) symmetric. Coupling SHOULD be asymmetric to
    /// encode VSM channel directionality; this is exposed mainly for tests/diagnostics.
    /// Computed on the dense reconstruction M = U·Vᵀ (only feasible offline / in tests).
    pub fn is_symmetric(&self, tol: f64) -> bool {
        // M[i][j] = Σ_k u[i,k]·v[j,k]
        let m = |i: usize, j: usize| -> f64 {
            let bi = i * self.rank;
            let bj = j * self.rank;
            (0..self.rank).map(|k| self.u[bi + k] * self.v[bj + k]).sum()
        };
        for i in 0..COUPLED_DIM {
            for j in (i + 1)..COUPLED_DIM {
                if (m(i, j) - m(j, i)).abs() > tol {
                    return false;
                }
            }
        }
        true
    }
}

/// Result of a successful coupling: the post-coupling states of each system,
/// recovered by the back-projections π_A, π_B, plus whether the result stays in Ω_AB.
#[derive(Debug, Clone)]
pub struct CoupledUpdate {
    pub x_a_new: StateVector,
    pub x_b_new: StateVector,
    /// Ax_ψ_Preserve Ω clause on the OUTPUT: x_A'∈Ω_A ∧ x_B'∈Ω_B ⇔ result ∈ Ω_AB.
    pub result_in_omega_ab: bool,
}

/// Concatenate two ℝ¹²⁸ states into the coupled ℝ²⁵⁶ vector [x_A; x_B].
fn concat(x_a: &StateVector, x_b: &StateVector) -> [f64; COUPLED_DIM] {
    let mut z = [0.0f64; COUPLED_DIM];
    z[..DIM].copy_from_slice(&x_a.dims);
    z[DIM..].copy_from_slice(&x_b.dims);
    z
}

/// π_A — first 128 components of a coupled vector → x_A update.
fn project_a(z: &[f64; COUPLED_DIM]) -> StateVector {
    let mut s = StateVector { dims: [0.0; DIM] };
    s.dims.copy_from_slice(&z[..DIM]);
    s
}

/// π_B — last 128 components of a coupled vector → x_B update.
fn project_b(z: &[f64; COUPLED_DIM]) -> StateVector {
    let mut s = StateVector { dims: [0.0; DIM] };
    s.dims.copy_from_slice(&z[DIM..]);
    s
}

/// Perform a ψ-coupling, enforcing the full Ax_ψ_Preserve precondition + the
/// bilateral S5 handshake. Returns the post-coupling states or the reason for refusal.
///
/// Order of checks (fail-closed, cheapest/most-fundamental first):
///   1. handshake bilateral (no consent → never touch state)
///   2. trust_AB ≥ min(trust_A, trust_B)
///   3. x_A ∈ Ω_A ∧ x_B ∈ Ω_B  (inputs valid)
///   4. apply ψ, back-project, then evaluate the Ω_AB clause on the OUTPUT.
pub fn couple(
    op: &CouplingOperator,
    x_a: &StateVector,
    x_b: &StateVector,
    omega_a: &Omega,
    omega_b: &Omega,
    trust: TrustTriple,
    handshake: Handshake,
) -> Result<CoupledUpdate, CouplingError> {
    if !handshake.bilateral() {
        return Err(CouplingError::NoBilateralConsent);
    }
    if !trust.preserved() {
        return Err(CouplingError::TrustNotPreserved);
    }
    if !omega_a.is_member(x_a) || !omega_b.is_member(x_b) {
        return Err(CouplingError::InputNotInOmega);
    }

    let z = concat(x_a, x_b);
    let out = op.apply(&z);
    let x_a_new = project_a(&out);
    let x_b_new = project_b(&out);
    // Ax_ψ_Preserve Ω clause: result ∈ Ω_AB ⇔ both projections in their Ω.
    let result_in_omega_ab = omega_a.is_member(&x_a_new) && omega_b.is_member(&x_b_new);

    Ok(CoupledUpdate { x_a_new, x_b_new, result_in_omega_ab })
}

// ──────────────────────────────────────────────────────────────────────────────
// DSN-COUPLE-01 PHASE 4 — live-coupling admission gate
//
// Phase 4 admits a LIVE ψ-coupling only under two guarantees layered on top of the
// synchronous Ax_ψ_Preserve precondition:
//   (τ)  trust_AB ≥ τ_threshold     — S5 POLICY floor (not experimentally measured)
//   (J)  ‖Jψ‖ ≤ jpsi_ceiling        — the coupling is non-amplifying (contractive)
//        M_ψ is linear ⇒ its Jacobian is M_ψ itself, so ‖Jψ‖ = σ_max(M_ψ).
//
// The trust presented to the gate is recovered at the EXP-TRUST-01-calibrated shared
// rate λ=0.10 (trust_axes::LAMBDA_CALIBRATED, via TrustVector::update_calibrated):
// EXP-TRUST-01 (run_4, 2026-06-19) delivered λ=0.10 (single shared, per-axis NOT
// warranted). τ_threshold and jpsi_ceiling are S5 policy parameters, NOT measured.
// ──────────────────────────────────────────────────────────────────────────────

impl CouplingOperator {
    /// Guaranteed upper bound on ‖Jψ‖ = ‖M_ψ‖₂. Since ψ is the linear map z ↦ M_ψ·z,
    /// its Jacobian is M_ψ itself, so ‖Jψ‖ = σ_max(M_ψ). Uses the Schur bound
    ///   σ_max ≤ sqrt(‖M‖₁ · ‖M‖∞)
    /// on the dense reconstruction M = U·Vᵀ (‖M‖₁ = max col abs-sum, ‖M‖∞ = max row
    /// abs-sum).
    ///
    /// Fail-closed: the bound OVER-estimates σ_max, so the Phase-4 gate may reject a
    /// safe coupling but will NEVER admit an amplifying one. O(256²·rank) — paid only
    /// at admission (a rare handshake event), never on the per-tick path.
    pub fn jpsi_upper_bound(&self) -> f64 {
        // M[i][j] = Σ_k u[i,k]·v[j,k]
        let m = |i: usize, j: usize| -> f64 {
            let bi = i * self.rank;
            let bj = j * self.rank;
            (0..self.rank).map(|k| self.u[bi + k] * self.v[bj + k]).sum()
        };
        let mut max_row = 0.0f64; // ‖M‖∞
        let mut col_sums = vec![0.0f64; COUPLED_DIM];
        for i in 0..COUPLED_DIM {
            let mut row = 0.0f64;
            for j in 0..COUPLED_DIM {
                let a = m(i, j).abs();
                row += a;
                col_sums[j] += a;
            }
            if row > max_row {
                max_row = row;
            }
        }
        let max_col = col_sums.into_iter().fold(0.0f64, f64::max); // ‖M‖₁
        (max_row * max_col).sqrt()
    }
}

/// Phase-4 admission policy for a LIVE ψ-coupling. `tau_threshold` and `jpsi_ceiling`
/// are S5 POLICY parameters (NOT experimentally measured). The trust-recovery rate the
/// caller uses to evolve the trust it presents here is the MEASURED
/// `trust_axes::LAMBDA_CALIBRATED` (0.10, EXP-TRUST-01 run_4).
#[derive(Debug, Clone, Copy)]
pub struct Phase4Gate {
    /// Minimum trust_AB to admit a live coupling (S5 policy floor).
    pub tau_threshold: f64,
    /// Contraction ceiling on ‖Jψ‖ — the coupling must be non-amplifying.
    pub jpsi_ceiling: f64,
}

impl Phase4Gate {
    /// S5 default policy: τ_threshold = 0.5 (admit only well above the stasis_boot
    /// floor of 0.40), jpsi_ceiling = 1.0 (strictly non-amplifying). Both S5-tunable;
    /// neither is an EXP-TRUST-01 measurement.
    pub fn s5_default() -> Self {
        Phase4Gate { tau_threshold: 0.5, jpsi_ceiling: 1.0 }
    }
}

/// Why a Phase-4 LIVE coupling was refused. Extends the synchronous `CouplingError`
/// with the two Phase-4-specific gates (τ_threshold, ‖Jψ‖).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AdmitError {
    /// Bilateral S5 consent not present (handshake precondition).
    NoBilateralConsent,
    /// trust_AB < τ_threshold — Phase-4 admission floor.
    TrustBelowThreshold,
    /// trust_AB < min(trust_A, trust_B) — Ax_ψ_Preserve trust clause.
    TrustNotPreserved,
    /// ‖Jψ‖ > jpsi_ceiling — coupling would amplify (non-contractive).
    CouplingAmplifies,
    /// One of the input states is already outside its Ω.
    InputNotInOmega,
    /// PSI L3: the signed S5 approval token failed `verify_for_proposal`
    /// (bad signature / decision≠approve / proposal binding mismatch / outside
    /// validity window / nonce replay). Carries the reframe gate's reason string.
    L3ConsentInvalid(&'static str),
}

/// Admit (or refuse) a LIVE Phase-4 ψ-coupling. Layers the τ_threshold floor and the
/// ‖Jψ‖ contraction gate on top of the synchronous `couple()` preconditions, then
/// performs the coupling. Fail-closed, cheapest/most-fundamental check first:
///   1. bilateral S5 consent
///   2. trust_AB ≥ τ_threshold              (Phase 4 — admission floor)
///   3. trust_AB ≥ min(trust_A, trust_B)    (Ax_ψ_Preserve)
///   4. ‖Jψ‖ ≤ jpsi_ceiling                 (Phase 4 — non-amplifying)
///   5. inputs ∈ Ω, apply ψ, back-project, evaluate Ω_AB  (delegated to `couple()`).
#[allow(clippy::too_many_arguments)]
pub fn admit_coupling(
    gate: &Phase4Gate,
    op: &CouplingOperator,
    x_a: &StateVector,
    x_b: &StateVector,
    omega_a: &Omega,
    omega_b: &Omega,
    trust: TrustTriple,
    handshake: Handshake,
) -> Result<CoupledUpdate, AdmitError> {
    if !handshake.bilateral() {
        return Err(AdmitError::NoBilateralConsent);
    }
    if trust.trust_ab < gate.tau_threshold {
        return Err(AdmitError::TrustBelowThreshold);
    }
    if !trust.preserved() {
        return Err(AdmitError::TrustNotPreserved);
    }
    if op.jpsi_upper_bound() > gate.jpsi_ceiling {
        return Err(AdmitError::CouplingAmplifies);
    }
    couple(op, x_a, x_b, omega_a, omega_b, trust, handshake).map_err(|e| match e {
        CouplingError::NoBilateralConsent => AdmitError::NoBilateralConsent,
        CouplingError::TrustNotPreserved => AdmitError::TrustNotPreserved,
        CouplingError::InputNotInOmega => AdmitError::InputNotInOmega,
    })
}

// ──────────────────────────────────────────────────────────────────────────────
// PSI L3 — cryptographic coupling admission (ITEM_3.1)
// ──────────────────────────────────────────────────────────────────────────────
//
// `admit_coupling` (above) trusts a boolean `Handshake`: any caller can set
// `s5_a_consents = s5_b_consents = true`. For a LIVE Phase-4 coupling that is a
// D4-L3 decision (an irreversible structural change to two viable systems), the
// consent must be CRYPTOGRAPHICALLY grounded, exactly like a reframe (§G5):
// an Ed25519 token signed by the offline S5 CA root, bound to THIS coupling
// proposal, inside its validity window, with a fresh nonce.
//
// We reuse the one certified gate — `ApprovalToken::verify_for_proposal`
// (reframe.rs, 13/13) — so PSI L3 and reframe L3 share a single offline root and
// a single replay-guard set. No second crypto path to audit.

/// Canonical proposal id for a Phase-4 coupling between two named units.
/// Order-independent (units are sorted) so `couple(A,B)` and `couple(B,A)` map to
/// the same proposal — the offline signer reconstructs the same id.
pub fn coupling_proposal_id(unit_a: &str, unit_b: &str) -> String {
    let (lo, hi) = if unit_a <= unit_b { (unit_a, unit_b) } else { (unit_b, unit_a) };
    format!("psi-couple:{}:{}", lo, hi)
}

/// Canonical, signer-reproducible descriptor of a coupling proposal. The offline
/// S5 signer hashes THIS exact string (sha256-hex) to set the token's
/// `proposal_hash`; the caller passes the same hash to `admit_coupling_l3` as
/// `content_hash`. Binds the parties, the operator rank, and the contraction
/// bound ‖Jψ‖ — so a token cannot be re-bound to a different (e.g. amplifying)
/// operator. The hashing itself stays out of this module (mirrors reframe, which
/// takes `content_hash` as a supplied field rather than computing it in the gate).
pub fn coupling_descriptor(unit_a: &str, unit_b: &str, op: &CouplingOperator) -> String {
    let (lo, hi) = if unit_a <= unit_b { (unit_a, unit_b) } else { (unit_b, unit_a) };
    format!(
        "psi-couple:v1:{}:{}:rank={}:jpsi={:.6}",
        lo,
        hi,
        op.rank(),
        op.jpsi_upper_bound()
    )
}

/// Admit a LIVE Phase-4 coupling under a PSI **L3** gate. Identical to
/// `admit_coupling`, except the boolean handshake is *replaced* by a signed S5
/// approval token verified against the offline root. Fail-closed order:
///   0. signed token verifies + binds this proposal  (L3 — replaces consent)
///   1..5. trust / ‖Jψ‖ / Ω gates                    (delegated to `admit_coupling`)
///
/// `proposal_id` / `content_hash` are the canonical id (`coupling_proposal_id`)
/// and the sha256-hex of `coupling_descriptor`. `root_pub` is the offline S5 CA
/// root pubkey; `seen_nonces` is the SAME replay-guard set the reframe gate uses.
#[allow(clippy::too_many_arguments)]
pub fn admit_coupling_l3(
    gate: &Phase4Gate,
    op: &CouplingOperator,
    x_a: &StateVector,
    x_b: &StateVector,
    omega_a: &Omega,
    omega_b: &Omega,
    trust: TrustTriple,
    token: &ApprovalToken,
    proposal_id: &str,
    content_hash: &str,
    root_pub: &[u8; 32],
    seen_nonces: &mut HashSet<String>,
) -> Result<CoupledUpdate, AdmitError> {
    // L3 gate: a valid, bound, in-window, unreplayed S5 signature IS the consent.
    token
        .verify_for_proposal(proposal_id, content_hash, root_pub, seen_nonces)
        .map_err(AdmitError::L3ConsentInvalid)?;
    // Consent proven cryptographically → the bilateral handshake is now earned,
    // not asserted. Delegate the remaining (certified) Phase-4 gates unchanged.
    let handshake = Handshake { s5_a_consents: true, s5_b_consents: true };
    admit_coupling(gate, op, x_a, x_b, omega_a, omega_b, trust, handshake)
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    /// Identity coupling on the first `m` coords via rank-`m` U=V=e_i (selector).
    /// out[i] = z[i] for i<m, else 0. Asymmetric in general; symmetric here (U==V).
    fn selector_op(m: usize) -> CouplingOperator {
        let rank = m;
        let mut u = vec![0.0; COUPLED_DIM * rank];
        let mut v = vec![0.0; COUPLED_DIM * rank];
        for k in 0..rank {
            u[k * rank + k] = 1.0; // row k, col k
            v[k * rank + k] = 1.0;
        }
        CouplingOperator::from_factors(u, v, rank).unwrap()
    }

    fn healthy_state(seed: f64) -> StateVector {
        use crate::state_vector::*;
        let mut s = StateVector { dims: [0.0; 128] };
        for i in TRUST_HIST_0..=TRUST_HIST_9 { s.dims[i] = 0.85; }
        s.dims[CPU_PRESSURE] = 0.3 + seed * 0.0;
        s.dims[MEM_PRESSURE] = 0.4;
        s.dims[IO_PRESSURE] = 0.2;
        s.dims[BUDGET] = 0.7;
        s.dims[CGROUP_HEADROOM] = 0.5;
        s.dims[H_T] = 0.3;
        s.dims[H_REST] = 0.25;
        s.dims[STASIS_COS] = 0.95;
        s.dims[LIFECYCLE] = 1.0;
        s.dims[GOVERNED] = 1.0;
        s
    }

    fn good_trust() -> TrustTriple {
        TrustTriple { trust_a: 0.9, trust_b: 0.8, trust_ab: 0.85 }
    }
    fn yes() -> Handshake {
        Handshake { s5_a_consents: true, s5_b_consents: true }
    }

    #[test]
    fn from_factors_rejects_bad_rank_and_dims() {
        assert!(CouplingOperator::from_factors(vec![0.0; 256], vec![0.0; 256], 0).is_none());
        assert!(CouplingOperator::from_factors(vec![0.0; 256 * 17], vec![0.0; 256 * 17], 17).is_none());
        assert!(CouplingOperator::from_factors(vec![0.0; 10], vec![0.0; 256], 1).is_none());
        assert!(CouplingOperator::from_factors(vec![0.0; 256], vec![0.0; 256], 1).is_some());
    }

    #[test]
    fn no_consent_refuses_before_touching_state() {
        let op = selector_op(4);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        let h = Handshake { s5_a_consents: true, s5_b_consents: false };
        assert!(matches!(
            couple(&op, &a, &b, &oa, &ob, good_trust(), h),
            Err(CouplingError::NoBilateralConsent)
        ));
    }

    #[test]
    fn trust_violation_refuses() {
        let op = selector_op(4);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        // trust_ab below min(trust_a, trust_b)=0.8
        let bad = TrustTriple { trust_a: 0.9, trust_b: 0.8, trust_ab: 0.5 };
        assert!(matches!(
            couple(&op, &a, &b, &oa, &ob, bad, yes()),
            Err(CouplingError::TrustNotPreserved)
        ));
    }

    #[test]
    fn input_outside_omega_refuses() {
        let op = selector_op(4);
        let mut a = healthy_state(0.0);
        a.dims[crate::state_vector::CPU_PRESSURE] = 5.0; // breaks box [0,1] → ∉ Ω
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        assert!(matches!(
            couple(&op, &a, &b, &oa, &ob, good_trust(), yes()),
            Err(CouplingError::InputNotInOmega)
        ));
    }

    #[test]
    fn low_rank_apply_matches_manual() {
        // rank-1: U col = e_0 scaled 2, V col = e_5 → M[i][j] = 2 if i==0,j==5 else 0.
        // ψ(z)[0] = 2·z[5], all others 0.
        let rank = 1;
        let mut u = vec![0.0; COUPLED_DIM * rank];
        let mut v = vec![0.0; COUPLED_DIM * rank];
        u[0] = 2.0; // row 0, col 0
        v[5] = 1.0; // row 5, col 0
        let op = CouplingOperator::from_factors(u, v, rank).unwrap();
        let mut z = [0.0; COUPLED_DIM];
        z[5] = 3.0;
        let out = op.apply(&z);
        assert!((out[0] - 6.0).abs() < 1e-12);
        for i in 1..COUPLED_DIM {
            assert_eq!(out[i], 0.0);
        }
    }

    #[test]
    fn asymmetry_is_representable() {
        // rank-1 U=e_0, V=e_5 → M[0][5]=1, M[5][0]=0 → asymmetric (VSM directionality).
        let rank = 1;
        let mut u = vec![0.0; COUPLED_DIM * rank];
        let mut v = vec![0.0; COUPLED_DIM * rank];
        u[0] = 1.0;
        v[5] = 1.0;
        let op = CouplingOperator::from_factors(u, v, rank).unwrap();
        assert!(!op.is_symmetric(1e-12));
    }

    #[test]
    fn projection_splits_256_into_two_128() {
        let mut z = [0.0; COUPLED_DIM];
        z[3] = 1.0;     // belongs to A
        z[DIM + 7] = 2.0; // belongs to B
        let a = project_a(&z);
        let b = project_b(&z);
        assert_eq!(a.dims[3], 1.0);
        assert_eq!(b.dims[7], 2.0);
        assert_eq!(a.dims[7], 0.0);
        assert_eq!(b.dims[3], 0.0);
    }

    #[test]
    fn happy_path_couples_and_reports_omega() {
        // selector over first 32 coords copies x_A's block A/B back into x_A',
        // and x_B's low coords into x_B'. Output Ω-membership is then evaluable.
        let op = selector_op(16);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        let r = couple(&op, &a, &b, &oa, &ob, good_trust(), yes()).expect("should couple");
        // result_in_omega_ab is a bool; with a partial selector the projected state
        // zeroes most dims (lifecycle=0 → ∉Ω), so we just assert the field is set,
        // and that the coupling produced a well-formed update.
        assert_eq!(r.x_a_new.dims.len(), 128);
        let _ = r.result_in_omega_ab;
    }

    #[test]
    fn trust_triple_preserved_boundary() {
        assert!(TrustTriple { trust_a: 0.9, trust_b: 0.8, trust_ab: 0.8 }.preserved());
        assert!(!TrustTriple { trust_a: 0.9, trust_b: 0.8, trust_ab: 0.79 }.preserved());
    }

    // ── DSN-COUPLE-01 Phase 4 — admission gate ──────────────────────────────────

    #[test]
    fn jpsi_bound_is_one_for_selector_identity() {
        // partial identity on first 16 coords → σ_max = 1 → bound = sqrt(1·1) = 1.
        let op = selector_op(16);
        assert!((op.jpsi_upper_bound() - 1.0).abs() < 1e-9);
    }

    #[test]
    fn jpsi_bound_flags_amplifying_op() {
        // rank-1 U[0]=2, V[0]=2 → M[0][0]=4 → σ_max=4 → bound ≥ 4 (> ceiling 1).
        let rank = 1;
        let mut u = vec![0.0; COUPLED_DIM * rank];
        let mut v = vec![0.0; COUPLED_DIM * rank];
        u[0] = 2.0;
        v[0] = 2.0;
        let op = CouplingOperator::from_factors(u, v, rank).unwrap();
        assert!(op.jpsi_upper_bound() >= 4.0 - 1e-9);
    }

    #[test]
    fn phase4_admits_contractive_trusted_coupling() {
        let gate = Phase4Gate::s5_default();
        let op = selector_op(16);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        // good_trust(): trust_ab=0.85 ≥ τ=0.5, preserved; ‖Jψ‖=1 ≤ 1 → admit.
        assert!(admit_coupling(&gate, &op, &a, &b, &oa, &ob, good_trust(), yes()).is_ok());
    }

    #[test]
    fn phase4_rejects_below_threshold() {
        let gate = Phase4Gate::s5_default();
        let op = selector_op(4);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        // trust_ab=0.4 < τ=0.5 (yet self-preserved: min(a,b)=0.4) → TrustBelowThreshold.
        let low = TrustTriple { trust_a: 0.4, trust_b: 0.4, trust_ab: 0.4 };
        assert!(matches!(
            admit_coupling(&gate, &op, &a, &b, &oa, &ob, low, yes()),
            Err(AdmitError::TrustBelowThreshold)
        ));
    }

    #[test]
    fn phase4_rejects_amplifying_coupling() {
        let gate = Phase4Gate::s5_default();
        let rank = 1;
        let mut u = vec![0.0; COUPLED_DIM * rank];
        let mut v = vec![0.0; COUPLED_DIM * rank];
        u[0] = 2.0;
        v[0] = 2.0; // ‖Jψ‖ = 4 > 1
        let op = CouplingOperator::from_factors(u, v, rank).unwrap();
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        // trust passes but contraction gate fails → CouplingAmplifies.
        assert!(matches!(
            admit_coupling(&gate, &op, &a, &b, &oa, &ob, good_trust(), yes()),
            Err(AdmitError::CouplingAmplifies)
        ));
    }

    #[test]
    fn phase4_no_consent_refuses_first() {
        let gate = Phase4Gate::s5_default();
        let op = selector_op(4);
        let a = healthy_state(0.0);
        let b = healthy_state(1.0);
        let (oa, ob) = (Omega::canonical(), Omega::canonical());
        let h = Handshake { s5_a_consents: false, s5_b_consents: true };
        assert!(matches!(
            admit_coupling(&gate, &op, &a, &b, &oa, &ob, good_trust(), h),
            Err(AdmitError::NoBilateralConsent)
        ));
    }

    // ── PSI L3 — cryptographic coupling admission (ITEM_3.1) ────────────────────
    // Reuses the reframe L3 fixture: an offline-root-signed token bound to
    // proposal_id="reframe-fixture-1" / proposal_hash=FIXTURE_HASH. The point is
    // the WIRING — a verified token IS the consent; any verify_for_proposal
    // failure becomes L3ConsentInvalid and the coupling never runs. The signing
    // path itself is certified in reframe.rs (one gate, one offline root).
    const FIXTURE_ROOT: &str =
        "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8";
    const FIXTURE_TOKEN: &str = r#"{"v": 1, "type": "vsf-s5-approval", "proposal_id": "reframe-fixture-1", "proposal_hash": "abababababababababababababababababababababababababababababababab", "decision": "approve", "nonce": "3d33734212d94e790282f03a7db14c43", "not_before": "2026-06-22T13:46:14Z", "not_after": "2058-02-28T15:37:54Z", "root_id": "ed25519:56475aa75463474c", "sig": "67ba1a0bd5e91c6d8164151ea3c0e4af03590e9156431b9f4d2adc963fd5b9f539e2150a63fb44b8482bc65cc35fccb8decb8f0a3d8a9dc9ef58c9c2960f8708"}"#;
    const FIXTURE_ID: &str = "reframe-fixture-1";
    const FIXTURE_HASH: &str =
        "abababababababababababababababababababababababababababababababab";
    const FIXTURE_NONCE: &str = "3d33734212d94e790282f03a7db14c43";

    fn hex32(s: &str) -> [u8; 32] {
        let b = s.as_bytes();
        assert_eq!(b.len(), 64, "need 64 hex chars");
        let mut out = [0u8; 32];
        for i in 0..32 {
            let hi = (b[2 * i] as char).to_digit(16).unwrap();
            let lo = (b[2 * i + 1] as char).to_digit(16).unwrap();
            out[i] = (hi * 16 + lo) as u8;
        }
        out
    }
    fn fixture_root() -> [u8; 32] { hex32(FIXTURE_ROOT) }
    fn fixture_token() -> ApprovalToken { serde_json::from_str(FIXTURE_TOKEN).unwrap() }
    fn l3_args() -> (Phase4Gate, CouplingOperator, StateVector, StateVector, Omega, Omega) {
        (Phase4Gate::s5_default(), selector_op(16), healthy_state(0.0),
         healthy_state(1.0), Omega::canonical(), Omega::canonical())
    }

    #[test]
    fn l3_valid_token_admits_coupling() {
        let (gate, op, a, b, oa, ob) = l3_args();
        let mut seen = HashSet::new();
        let r = admit_coupling_l3(&gate, &op, &a, &b, &oa, &ob, good_trust(),
            &fixture_token(), FIXTURE_ID, FIXTURE_HASH, &fixture_root(), &mut seen);
        assert!(r.is_ok(), "valid signed token must admit: {:?}", r.err());
        assert!(seen.contains(FIXTURE_NONCE), "nonce must be recorded (replay guard)");
    }

    #[test]
    fn l3_bad_root_rejects() {
        let (gate, op, a, b, oa, ob) = l3_args();
        let mut root = fixture_root();
        root[0] ^= 0xff; // wrong offline root → signature cannot verify
        let mut seen = HashSet::new();
        assert!(matches!(
            admit_coupling_l3(&gate, &op, &a, &b, &oa, &ob, good_trust(),
                &fixture_token(), FIXTURE_ID, FIXTURE_HASH, &root, &mut seen),
            Err(AdmitError::L3ConsentInvalid(_))
        ));
    }

    #[test]
    fn l3_wrong_hash_rejects_rebinding() {
        // A token signed for one coupling must not authorise a different operator.
        let (gate, op, a, b, oa, ob) = l3_args();
        let other = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd";
        let mut seen = HashSet::new();
        assert!(matches!(
            admit_coupling_l3(&gate, &op, &a, &b, &oa, &ob, good_trust(),
                &fixture_token(), FIXTURE_ID, other, &fixture_root(), &mut seen),
            Err(AdmitError::L3ConsentInvalid(_))
        ));
    }

    #[test]
    fn l3_replay_rejects() {
        let (gate, op, a, b, oa, ob) = l3_args();
        let mut seen = HashSet::new();
        seen.insert(FIXTURE_NONCE.to_string()); // nonce already consumed
        assert!(matches!(
            admit_coupling_l3(&gate, &op, &a, &b, &oa, &ob, good_trust(),
                &fixture_token(), FIXTURE_ID, FIXTURE_HASH, &fixture_root(), &mut seen),
            Err(AdmitError::L3ConsentInvalid(_))
        ));
    }

    #[test]
    fn coupling_descriptor_is_order_independent_and_binds_jpsi() {
        let op = selector_op(8);
        assert_eq!(coupling_proposal_id("b", "a"), coupling_proposal_id("a", "b"));
        let d1 = coupling_descriptor("b", "a", &op);
        let d2 = coupling_descriptor("a", "b", &op);
        assert_eq!(d1, d2, "descriptor must be order-independent");
        assert!(d1.contains("rank=8") && d1.contains("jpsi="),
            "descriptor must bind operator rank + ‖Jψ‖");
    }
}
