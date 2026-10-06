// calibration.rs — single source of truth for empirically-calibrated kernel constants.
//
// Mirror of docs/experiments/calibration.vsm. Each constant cites the experiment that
// established it. Modules reference THESE (e.g. `crate::calibration::THETA_PSI`) instead of
// scattering literals — closing the E→C loop (experiment result → code) systematically.
// Pattern parallels the coupling_registry (declarative contract, one home).
//
// CONFIRMED  = established by a run experiment (index.vsm status=done).
// HEURISTIC  = a working default NOT yet validated by a loop (flagged; needs the named experiment).
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

// ─── CONFIRMED (experiment-backed) ──────────────────────────────────────────────

/// Viability hard floor: sv.viable() requires stasis_cos ≥ this (definitional, vos_attractor_theory).
pub const VIABLE_THRESHOLD: f64 = 0.70;

/// PSI basin floor / re-certification threshold. EXP-TP-01 (theta_psi_stress): min stasis_cos under
/// max activation perturbation δ=1.0. Consumed by reframe.rs, lyapunov(recert), s4.rs, vr_complex(recert).
pub const THETA_PSI: f64 = 0.79;

/// Viable boundary under maximum thermal stress (67-69°C). EXP-CA-01 (critical_angle). Paper §6.
pub const THETA_PSI_UPPER: f64 = 0.9377;

/// Conservative WORST-CASE minimum stasis_cos under perturbation. EXP-AB-01 (basin_floor): impulsive
/// ground-state kick (the hardest direction) saturates at 0.875. EXP-MC-01 (basin_mc) confirms it is
/// worst-case: random-direction floor is 0.945 and basin_volume_fraction ≈ 1.0 (200/200 recover).
/// Density-backed by 2 experiments. An observed value below it is BEYOND the envelope (anomaly).
pub const BASIN_FLOOR: f64 = 0.875;

/// Resilience margin = BASIN_FLOOR − VIABLE_THRESHOLD. EXP-AB-01: 0.175 head-room before non-viable.
pub const RESILIENCE_MARGIN: f64 = BASIN_FLOOR - VIABLE_THRESHOLD;

/// Algedonic dip floor — the VSF-exclusive S5 signature. EXP-TC-01 (thermal_cycling) + NC controls
/// (no negative-control variant reproduces 0.942).
pub const DIP_FLOOR: f64 = 0.942;

/// Recovery time τ_rec in ticks. EXP-TC-01 (<30s elastic recovery). Consumed by reframe (τ_recert=2·τ_rec).
pub const TAU_REC: u32 = 50;

/// Vietoris-Rips cosine scale ε — inside the β₀=1 plateau. EXP-TDA-01 (H_TDA1). Consumed by vr_complex.
pub const VR_EPSILON_COSINE: f64 = 0.30;

/// Persistent-homology absolute noise floor. EXP-TDA-01 — separates real topology from sampling noise.
pub const VR_PERSIST_FLOOR: f64 = 0.05;

/// Effective (ACTIVE-dimension) heuristic = active_dims + trust×2. EXP-SB-01 (spec_boot). NB: this is
/// NOT the Kaplan-Yorke dimension — for the stable fixed point KY-dim = 0 (EXP-LY-01). Distinct notions.
pub const D_EFF: f64 = 3.00;

/// Largest Lyapunov exponent (per tick). EXP-LY-01 (Benettin): -0.01005 = ln(0.99), the relaxation rate.
/// λ_max < 0 ⇒ stable fixed point (rigorous convergence; point sink, consistent with EXP-TDA-01/MC-01).
pub const LAMBDA_MAX: f64 = -0.01005;

/// Measured g at the attractor (EXP-G-01, certifier-validation suite, 2026-06-15).
/// Binding constraint: A3_cpu — Boltzmann equilibrium at H≈0.9·H_max consumes cpu/budget slack.
/// g=0.102 tells the operator that the cpu feasibility margin is the practical limit of V;
/// it is NOT a crisis value but the operational working point of the kernel.
/// All ethical faces (A0, A0.1) are fully slack (slack=1.0) at the attractor.
pub const G_ATTRACTOR_MEASURED: f64 = 0.102;

/// Trust-drift inflection θ_A^{drift}: the cosine at which trust drift changes sign (EXP-CORE-01).
/// Derivation: trust_drift = 0.025·cos − 0.04·(1−cos) = 0; cos* = 0.04/0.065 = 0.6154.
/// This is the kernel's natural fixed point — DISTINCT from THETA_A=0.88 (Fierro, Jacobian bound
/// on the contractive core Ω_A). Both are correct; they describe different operators.
pub const THETA_A_DRIFT: f64 = 0.6154;

// ─── HEURISTIC (NOT yet experiment-confirmed — each names the loop that would confirm it) ───────

/// Cor_4 capture-gap threshold for ψ-coupling. HEURISTIC — needs EXP-TRUST-01. Consumed by VSI/coupling.
pub const TRUST_TAU_THRESHOLD: f64 = 0.20;

/// Lyapunov recurrent-core radius (mean L ≤ this ⇒ "within R"). CONFIRMED EXP-LYAP-CERT 2026-06-03:
/// live steady-state mean_l = 0.146 ± 0.005 (n=357 in_recurrent_set ticks); 6σ bound = 0.174. Set to
/// 0.20 (conservative round-up for the modest ~6h sample + false-Diverging→algedonic cost). 0.50 was
/// 74σ loose ⇒ `governed` trivially true; 0.20 is discriminative (an L-excursion above the 0.146 core
/// now classifies Diverging) yet steady-state-neutral (0.146 < 0.20 ⇒ still in_recurrent_set).
pub const LYAP_R_CORE: f64 = 0.20;

/// Lyapunov |E[ΔL]| zero band. CONFIRMED EXP-LYAP-CERT 2026-06-03: live steady-state σ_ΔL = 3.68e-4
/// (n=357); 3σ noise floor = 1.10e-3 ≈ the original heuristic. Kept at 1e-3 (within 10% of the measured
/// floor; consistent with W4 steady mean_dl < band ⇒ σ_clock = 0).
pub const LYAP_DRIFT_BAND: f64 = 1e-3;

/// Deep-wiring W4 — σ-adaptive clock drift gain. Maps the live mean ΔL (drift of the
/// Lyapunov trajectory) into the dimensionless σ_global of the adaptive clock:
///   σ = max(0, mean_dl) · SIGMA_DRIFT_GAIN   (=0 inside the recurrent set, where mean_dl ≤ 0).
/// At mean_dl ≈ 0.01 (clear drift) σ ≈ 1 ⇒ Δt halves; gross divergence saturates to the floor.
/// HEURISTIC — should be calibrated against observed drift-noise vs the tick-staleness bound
/// under real contention (EXP-LYAP-CERT / T4.sub1). Consumed by operational.rs kernel_tick.
pub const SIGMA_DRIFT_GAIN: f64 = 100.0;

/// Deep-wiring W4 — maximum tick speedup factor under instability. The adaptive tick Δt is
/// floored at base_interval / CLOCK_MAX_SPEEDUP so a drifting trajectory regulates faster
/// without flooding the canonical chain. Steady state keeps the baseline cadence exactly.
pub const CLOCK_MAX_SPEEDUP: f64 = 10.0;

// ─── HELPERS ────────────────────────────────────────────────────────────────────

/// EXP-AB-01 envelope check: true iff stasis_cos is within the empirically-characterized resilience
/// envelope (≥ BASIN_FLOOR). A value below means the system is operating beyond what EXP-AB-01 observed
/// — a candidate anomaly signal once a real stasis_cos is available (deep_wiring W1 consumer).
pub fn within_resilience_envelope(stasis_cos: f64) -> bool {
    stasis_cos >= BASIN_FLOOR
}

/// True iff stasis_cos is still viable (≥ VIABLE_THRESHOLD) but below the PSI precautionary threshold.
pub fn in_precautionary_band(stasis_cos: f64) -> bool {
    stasis_cos >= VIABLE_THRESHOLD && stasis_cos < THETA_PSI
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resilience_margin_is_consistent() {
        assert!((RESILIENCE_MARGIN - 0.175).abs() < 1e-9);
        assert_eq!(BASIN_FLOOR, VIABLE_THRESHOLD + RESILIENCE_MARGIN);
    }

    #[test]
    fn envelope_and_bands() {
        assert!(within_resilience_envelope(0.95));
        assert!(!within_resilience_envelope(0.80)); // below 0.875 → beyond envelope
        assert!(in_precautionary_band(0.75));        // viable but < θ_PSI
        assert!(!in_precautionary_band(0.95));       // healthy
        assert!(!in_precautionary_band(0.50));       // not viable
    }

    #[test]
    fn ordering_sanity() {
        assert!(VIABLE_THRESHOLD < THETA_PSI);
        assert!(THETA_PSI < BASIN_FLOOR);          // 0.79 < 0.875 — precautionary < empirical floor
        assert!(BASIN_FLOOR < THETA_PSI_UPPER);    // 0.875 < 0.9377
        assert!(THETA_PSI_UPPER < DIP_FLOOR);      // 0.9377 < 0.942
    }
}
