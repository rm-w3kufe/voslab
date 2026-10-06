// kernel_step.rs — deep-wiring W1 + W4b — the shared entropy-relaxation kernel dynamics.
//
// ENTROPY-SATURATION-REVIEW P2-A (2026-07-03): persist p across restarts so the
// kernel's entropy relaxation is NOT reset to uniform on every restart. Checkpoint
// written every tick to /var/lib/vsf/nucleus_kernel_step.json; on boot, if file is
// valid (p sums approx 1, entries > 0), load it. Fail-safe: corrupt/missing → uniform.
//
// One reusable step of the VALIDATED core dynamics (the same Boltzmann relaxation that
// EXP-LY-01 measured at λ_max = ln(0.99) < 0 — a stable point sink; EXP-TDA-01 β₀=1∧β₁=0;
// EXP-MC-01 basin volume ≈ 1.0). Used to give the LIVE daemon tick a real ℝ¹²⁸ trajectory
// instead of synthetic constants. spec_boot/basin_* share this model (single-source migration
// is W1.b follow-up; this is the canonical core they should converge to).
//
// W4b — HOMEOSTATIC FEEDBACK (S5-ratified 2026-06-19, deep_wiring_design.vsm §W4b_block_b_feedback):
// real Block-B pressure now MODULATES the dynamics via the EFFECTIVE TEMPERATURE coupling (Option A).
// kT_eff = 1 + γ·pressure raises the Boltzmann temperature → flatter (higher-entropy) equilibrium
// (load = heat = entropy). γ=0 / pressure=0 ⇒ EXACT prior behavior — a pure extension, no regression.
// The 0.99 contraction rate is UNCHANGED ⇒ λ_max = ln(0.99) < 0 is structurally preserved; p_eq is
// always a valid simplex point ⇒ Ω preserved. The moving fixed point is the homeostatic response.
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::state_vector::{EntropyPhase, StasisVec, StateVector};
use std::path::PathBuf;

/// W4b effective-temperature gain (S5-ratified 2026-06-19). kT_eff = 1 + γ·pressure, pressure∈[0,1].
/// γ=1.0 ⇒ kT ranges [1,2] over idle→max load. S5-tunable; tune DOWN if the dry-run acceptance
/// criterion (steady-state β₀=1∧β₁=0 under a realistic pressure trace) is violated.
pub const GAMMA_PRESSURE: f64 = 1.0;

// ─── EXP-SEN-01 (Option F, env-gated VSF_EXP_ADAPTIVE_HREST) ──────────────────
// docs/experiments/senescence_adaptive/spec.vsm. Adaptive resting entropy: h_rest tracks the
// ACTUAL resting entropy (the attractor sits at h≈1.8, not the 0.40 placeholder). A fast warmup
// EMA calibrates h_rest to that value, snapshots h_rest_ref; then a slow EMA measures the
// senescence drift = h_rest − h_rest_ref. Default OFF ⇒ h_rest constant ⇒ byte-identical to prod.
pub const H_REST_EMA_WARMUP:   f64 = 1e-2;   // fast: calibrate to the true resting entropy
pub const H_REST_EMA_MEASURE:  f64 = 1e-4;   // slow: measure lifetime senescence drift
pub const H_REST_STASIS_GATE:  f64 = 0.95;   // sample only AT REST (stasis_cos high)
pub const H_REST_CONVERGED_EPS: f64 = 0.02;  // |h_t − h_rest| < eps ⇒ calibrated ⇒ snapshot ref

/// The 4 Boltzmann energy levels (fixed; EXP-LY-01/TDA-01 characterized the attractor at these).
const ENERGIES: [f64; 4] = [0.0, 0.5, 1.0, 1.5];

/// Boltzmann equilibrium occupation p_eq(i) = exp(-E_i/kT) / Z(kT) over ENERGIES.
/// At kT=1.0 this reproduces the original fixed equilibrium exactly.
pub fn boltzmann_p_eq(kt: f64) -> [f64; 4] {
    let kt = kt.max(1e-6); // guard: kT>0 (pressure∈[0,1] ⇒ kT≥1 in practice)
    let mut b = [0.0f64; 4];
    for i in 0..4 {
        b[i] = (-ENERGIES[i] / kt).exp();
    }
    let z: f64 = b.iter().sum();
    [b[0] / z, b[1] / z, b[2] / z, b[3] / z]
}

/// Per-tick output of the kernel dynamics (what the live tick emits + feeds to lyapunov W2).
#[derive(Debug, Clone, Copy)]
pub struct StepOutput {
    pub stasis_cos: f64,
    pub l_x: f64,
    pub h_t: f64,
    pub trust: f64,
    pub entropy_phase: &'static str,
    pub viable: bool,
}

/// Checkpoint data for persisting kernel state across restarts (ENTROPY-SATURATION-REVIEW P2-A).
/// Serialized as JSON to /var/lib/vsf/nucleus_kernel_step.json every tick.
/// Integrity: all p entries > 0, sum ≈ 1.0. Corrupt/missing → fail-safe to uniform.
const CHECKPOINT_PATH: &str = "/var/lib/vsf/nucleus_kernel_step.json";

/// Lightweight checkpoint container for JSON serialization (ENTROPY-SATURATION-REVIEW P2-A).
#[derive(serde::Serialize, serde::Deserialize)]
struct Checkpoint {
    p: [f64; 4],
    trust: f64,
    n_cycles: u32,
    ticks_growth: u32,
    h_rest: f64,
    h_rest_ref: f64,
    adaptive_h_rest: bool,
    warmup_done: bool,
}

/// Holds the evolving entropy-cycle state (the 4-state Boltzmann occupation + trust + counters).
#[derive(Debug, Clone)]
pub struct KernelStepper {
    p: [f64; 4],
    pub trust: f64,
    n_cycles: u32,
    ticks_growth: u32,
    pub h_max: f64,
    h_rest: f64,
    // EXP-SEN-01 (env-gated): adaptive resting entropy. Default off ⇒ these are inert ⇒ byte-identical.
    h_rest_ref: f64,        // calibrated resting entropy (snapshot post-warmup) = senescence baseline
    adaptive_h_rest: bool,  // VSF_EXP_ADAPTIVE_HREST (set only via enable_adaptive_h_rest)
    warmup_done: bool,      // h_rest has converged to the true resting entropy; ref is valid
    /// If Some, persist state to this path after every step().
    checkpoint_path: Option<PathBuf>,
}

impl Default for KernelStepper {
    fn default() -> Self {
        Self::new()
    }
}

impl KernelStepper {
    pub fn new() -> Self {
        let h_max = (4.0f64).log2();
        // Try to load persisted checkpoint; if missing/corrupt → uniform start
        let checkpoint_path = PathBuf::from(CHECKPOINT_PATH);
        let persisted = Self::try_load_checkpoint(&checkpoint_path);
        KernelStepper {
            p: persisted.as_ref().map_or([0.25; 4], |c| c.p),
            trust: persisted.as_ref().map_or(0.80, |c| c.trust),
            n_cycles: persisted.as_ref().map_or(0, |c| c.n_cycles),
            ticks_growth: persisted.as_ref().map_or(0, |c| c.ticks_growth),
            h_max,
            h_rest: persisted.as_ref().map_or(0.20 * h_max, |c| c.h_rest),
            h_rest_ref: persisted.as_ref().map_or(0.20 * h_max, |c| c.h_rest_ref),
            adaptive_h_rest: persisted.as_ref().map_or(false, |c| c.adaptive_h_rest),
            warmup_done: persisted.as_ref().map_or(false, |c| c.warmup_done),
            checkpoint_path: Some(checkpoint_path),
        }
    }

    /// Construct with a custom checkpoint path (for tests or alternate data dirs).
    /// If the file is readable and passes integrity check, state is loaded from it;
    /// otherwise, uniform start with no checkpoint writes.
    pub fn with_checkpoint(path: impl Into<PathBuf>) -> Self {
        let pbuf = path.into();
        let persisted = Self::try_load_checkpoint(pbuf.as_path());
        let h_max = (4.0f64).log2();
        KernelStepper {
            p: persisted.as_ref().map_or([0.25; 4], |c| c.p),
            trust: persisted.as_ref().map_or(0.80, |c| c.trust),
            n_cycles: persisted.as_ref().map_or(0, |c| c.n_cycles),
            ticks_growth: persisted.as_ref().map_or(0, |c| c.ticks_growth),
            h_max,
            h_rest: persisted.as_ref().map_or(0.20 * h_max, |c| c.h_rest),
            h_rest_ref: persisted.as_ref().map_or(0.20 * h_max, |c| c.h_rest_ref),
            adaptive_h_rest: persisted.as_ref().map_or(false, |c| c.adaptive_h_rest),
            warmup_done: persisted.as_ref().map_or(false, |c| c.warmup_done),
            checkpoint_path: Some(pbuf),
        }
    }

    /// Try to load and validate a checkpoint. Integrity check: all p > 0, sum ≈ 1.0.
    /// Returns None if file is missing, corrupt, or fails validation.
    fn try_load_checkpoint(path: &std::path::Path) -> Option<Checkpoint> {
        let data = std::fs::read_to_string(path).ok()?;
        let cp: Checkpoint = serde_json::from_str(&data).ok()?;
        // Integrity: all entries positive, sum ≈ 1.0 within numerical tolerance
        let sum: f64 = cp.p.iter().sum();
        if cp.p.iter().all(|&v| v > 0.0) && (sum - 1.0).abs() < 1e-6 {
            eprintln!("[kernel_step] loaded checkpoint from {} (sum={:.6})", path.display(), sum);
            Some(cp)
        } else {
            eprintln!("[kernel_step] checkpoint corrupt at {}: p={:?} sum={:.6} — fail-safe to uniform", path.display(), cp.p, sum);
            None
        }
    }

    /// Persist the current kernel state as JSON. Called at end of step().
    /// Silently ignores errors (non-fatal — next restart just starts uniform).
    fn save_checkpoint(&self) {
        if let Some(ref path) = self.checkpoint_path {
            let cp = Checkpoint {
                p: self.p,
                trust: self.trust,
                n_cycles: self.n_cycles,
                ticks_growth: self.ticks_growth,
                h_rest: self.h_rest,
                h_rest_ref: self.h_rest_ref,
                adaptive_h_rest: self.adaptive_h_rest,
                warmup_done: self.warmup_done,
            };
            let json = serde_json::to_string(&cp);
            if let Ok(j) = json {
                if let Err(e) = std::fs::write(path, &j) {
                    eprintln!("[kernel_step] checkpoint write to {} failed: {} (non-fatal)", path.display(), e);
                }
            }
        }
    }

    /// Advance one tick: relax p toward the (pressure-modulated) equilibrium, recompute
    /// entropy/blocks, observe stasis, return the live stasis_cos + Lyapunov value.
    ///
    /// W4b: `pressure` ∈ [0,1] is the real Block-B load (mean cpu/mem/io, EMA-smoothed by ingest).
    /// It raises kT_eff = 1 + γ·pressure → flatter equilibrium (load = heat = entropy). pressure=0
    /// reproduces the original fixed attractor EXACTLY. The 0.99 contraction (λ_max=ln(0.99)<0) and
    /// the simplex/Ω validity of p_eq are preserved for all pressure ∈ [0,1].
    pub fn step(&mut self, sv: &mut StateVector, stasis: &mut StasisVec, pressure: f64) -> StepOutput {
        // ── W4b effective-temperature equilibrium (S5-ratified Option A) ──
        let kt_eff = 1.0 + GAMMA_PRESSURE * pressure.clamp(0.0, 1.0);
        let p_eq = boltzmann_p_eq(kt_eff);
        // ── Boltzmann relaxation (the contraction; λ_max = ln(0.99), EXP-LY-01) ──
        for i in 0..4 {
            self.p[i] = 0.99 * self.p[i] + 0.01 * p_eq[i];
        }
        let s: f64 = self.p.iter().sum();
        let h_t: f64 = -self
            .p
            .iter()
            .map(|&pi| {
                let q = pi / s;
                if q > 0.0 { q * q.log2() } else { 0.0 }
            })
            .sum::<f64>();

        // CALIBRATE-ENTROPY (2026-07-03): h_eq = H(attractor) at current kT_eff.
        // Phase thresholds RELATIVE to h_eq (not absolute h_max·0.70, which
        // labeled the healthy attractor h_eq=1.796 as degen since 1.4 < 1.796).
        //   stasis = h_t ≤ h_rest·1.1      (same as before — very quiet state)
        //   inhale = h_t < h_eq + δ         (near the attractor — healthy range)
        //   degen  = h_t ≥ h_eq + δ         (above attractor by δ — genuine excursion)
        // δ = 0.05 ≈ same magnitude as h_rest·1.1 - h_rest = 0.04.
        let h_eq: f64 = -p_eq.iter()
            .map(|&q| if q > 0.0 { q * q.log2() } else { 0.0 })
            .sum::<f64>();
        const CAL_ENTROPY_DELTA: f64 = 0.05;
        let phase_str = if h_t <= self.h_rest * 1.1 {
            "stasis"
        } else if h_t < h_eq + CAL_ENTROPY_DELTA {
            self.ticks_growth += 1;
            "inhale"
        } else {
            "degen"
        };
        let phase = EntropyPhase::from_str(phase_str);

        // ── governed trust drift toward health (uses pre-observe cosine) ──
        let cos_pre = if stasis.n_observations() > 0 {
            sv.cosine_similarity(&stasis.current)
        } else {
            1.0
        };
        let prev_trust = self.trust;
        self.trust = (self.trust + 0.025 * cos_pre - 0.04 * (1.0 - cos_pre)).clamp(0.0, 1.0);

        // ── EXP-SEN-01 (env-gated): adaptive resting entropy ──────────────────
        // Default OFF ⇒ this block is skipped ⇒ h_rest constant ⇒ byte-identical to prod.
        // ON: at rest (cos_pre high) EMA h_rest toward h_t. WARMUP (fast EMA) calibrates h_rest to
        // the TRUE resting entropy (attractor ≈1.8, not the 0.40 placeholder); on convergence snapshot
        // h_rest_ref. Then SLOW EMA; drift = h_rest − h_rest_ref is the senescence signal.
        if self.adaptive_h_rest && cos_pre >= H_REST_STASIS_GATE {
            let rate = if self.warmup_done { H_REST_EMA_MEASURE } else { H_REST_EMA_WARMUP };
            self.h_rest = (1.0 - rate) * self.h_rest + rate * h_t;
            if !self.warmup_done && (h_t - self.h_rest).abs() < H_REST_CONVERGED_EPS {
                self.h_rest_ref = self.h_rest;  // calibrated resting entropy = senescence baseline
                self.warmup_done = true;
            }
        }

        // ── state-vector update (Blocks A/B/C/D/G — same layout as spec_boot/basin_floor) ──
        let norm = [self.p[0] / s, self.p[1] / s, self.p[2] / s, self.p[3] / s];
        sv.update_block_a(self.trust, prev_trust, 0.0, 1.0, true, 1, 1.0);
        sv.update_block_b(h_t / self.h_max, 0.0, 0.0, 1.0 - h_t / self.h_max, 1.0, 0, 0, 0);
        sv.update_block_c(h_t, self.h_rest, self.h_max, phase, stasis, false, self.n_cycles, self.ticks_growth);
        sv.update_block_d(&norm);
        sv.update_block_g(0.0, 0.02, true);

        stasis.observe(sv);
        let stasis_cos = sv.cosine_similarity(&stasis.current);
        let l_x = sv.lyapunov(stasis, self.h_max, 0.0);
        let viable = stasis_cos > 0.70 && self.trust > 0.50;

        // ENTROPY-SATURATION-REVIEW P2-A: persist checkpoint after every tick.
        self.save_checkpoint();

        StepOutput { stasis_cos, l_x, h_t, trust: self.trust, entropy_phase: phase_str, viable }
    }

    /// CHECO-WHATIF (CH.c) what-if hook: displace the DYNAMICAL occupation toward maximum entropy
    /// (uniform [0.25;4]) by fraction s∈[0,1]. s=0 leaves p unchanged; s=1 sets p fully uniform (the
    /// maximal perturbation). Perturbing the emitted `sv` alone would be overwritten next step — the
    /// private occupation `p` is what must move for the globally-contracting dynamics to respond.
    /// The subsequent relaxation's MIN stasis_cos is the excursion envelope θ_env (see checo_whatif.rs).
    pub fn perturb_occupation(&mut self, s: f64) {
        let s = s.clamp(0.0, 1.0);
        for i in 0..4 {
            self.p[i] = (1.0 - s) * self.p[i] + s * 0.25;
        }
    }

    /// EXP-OE-02 demon hand: concentrate the occupation toward the low-energy corner E_0
    /// ([1,0,0,0]) by `bias`∈[0,1]. Mirror of `perturb_occupation`, opposite direction
    /// (minimum entropy instead of maximum). Called only by `run_maxwell_demon_real` under
    /// condition B; absent any call the dynamics are byte-identical (pure additive hook).
    pub fn demon_sort(&mut self, bias: f64) {
        let bias = bias.clamp(0.0, 1.0);
        self.p[0] = (1.0 - bias) * self.p[0] + bias; // toward E_0
        for i in 1..4 {
            self.p[i] = (1.0 - bias) * self.p[i];
        }
    }

    /// Read-only view of the 4-state Boltzmann occupation (the real dynamical DOF).
    /// EXP-OE-02 computes the canonical D_eff heuristic (active_dims + trust·2) over this,
    /// exactly as spec_boot does over its 4-element activation array (threshold 0.15).
    pub fn occupation(&self) -> [f64; 4] {
        self.p
    }

    // ─── EXP-SEN-01 (Option F) — adaptive resting entropy accessors ──────────────
    /// Turn ON adaptive resting entropy. Called ONLY from the experiment path
    /// (operational.rs reads VSF_EXP_ADAPTIVE_HREST). Tests/spec_boot never call it ⇒ adaptive
    /// stays false ⇒ byte-identical. See docs/experiments/senescence_adaptive/spec.vsm.
    pub fn enable_adaptive_h_rest(&mut self) {
        self.adaptive_h_rest = true;
    }

    /// Current resting-entropy set-point (drifts only when adaptive + at rest).
    pub fn h_rest(&self) -> f64 { self.h_rest }

    /// Calibrated resting-entropy baseline (snapshot at warmup convergence).
    pub fn h_rest_ref(&self) -> f64 { self.h_rest_ref }

    /// Senescence signal: drift of the resting set-point from its calibrated baseline.
    /// 0 until warmup completes (no baseline yet).
    pub fn h_rest_drift(&self) -> f64 {
        if self.warmup_done { self.h_rest - self.h_rest_ref } else { 0.0 }
    }

    /// Whether the warmup calibration has completed (h_rest_ref is valid).
    pub fn warmup_done(&self) -> bool { self.warmup_done }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converges_to_attractor() {
        // Run the dynamics; it must converge to the stable attractor (high stasis_cos, low L,
        // viable) — the point sink characterized by EXP-LY-01/TDA-01/MC-01.
        let mut stepper = KernelStepper::new();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        let mut last = stepper.step(&mut sv, &mut stasis, 0.0);
        for _ in 0..2000 {
            last = stepper.step(&mut sv, &mut stasis, 0.0);
        }
        // The stable attractor is the Boltzmann fixed point — a STABLE state (stasis_cos→1),
        // which sits at HIGH entropy (h≈1.8, the equilibrium), NOT the low-entropy "stasis" phase
        // label. Stability is stasis_cos→1, not the phase name (matches EXP-TSM: H_t≈1.9, cos=1.0).
        assert!(last.stasis_cos > 0.95, "expected convergence, stasis_cos={}", last.stasis_cos);
        assert!(last.l_x < 0.40, "expected bounded Lyapunov value at attractor, L={}", last.l_x);
        assert!(last.viable, "expected viable at the attractor (cos>0.7 ∧ trust>0.5)");
    }

    #[test]
    fn trust_recovers_to_healthy() {
        let mut stepper = KernelStepper::new();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for _ in 0..2000 {
            stepper.step(&mut sv, &mut stasis, 0.0);
        }
        assert!(stepper.trust > 0.9, "trust should climb at the attractor, got {}", stepper.trust);
    }

    #[test]
    fn stasis_cos_is_bounded() {
        let mut stepper = KernelStepper::new();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for _ in 0..50 {
            let o = stepper.step(&mut sv, &mut stasis, 0.0);
            assert!(o.stasis_cos >= -1.0 && o.stasis_cos <= 1.0);
            assert!(o.l_x.is_finite());
        }
    }

    // ── W4b — effective-temperature Block-B feedback ────────────────────────────

    #[test]
    fn boltzmann_p_eq_baseline_matches_original() {
        // kT=1.0 must reproduce the original fixed equilibrium (energies [0,.5,1,1.5]).
        let p = boltzmann_p_eq(1.0);
        let s: f64 = p.iter().sum();
        assert!((s - 1.0).abs() < 1e-12, "p_eq must be a distribution, sum={}", s);
        // monotone decreasing in energy at kT=1: p0>p1>p2>p3.
        assert!(p[0] > p[1] && p[1] > p[2] && p[2] > p[3]);
    }

    #[test]
    fn higher_pressure_raises_equilibrium_entropy() {
        // kT_eff rises with pressure ⇒ flatter distribution ⇒ higher entropy.
        let h = |p: [f64; 4]| -> f64 {
            -p.iter().map(|&q| if q > 0.0 { q * q.log2() } else { 0.0 }).sum::<f64>()
        };
        let h_idle = h(boltzmann_p_eq(1.0 + GAMMA_PRESSURE * 0.0));
        let h_load = h(boltzmann_p_eq(1.0 + GAMMA_PRESSURE * 0.8));
        assert!(h_load > h_idle, "load should flatten p_eq: h_idle={} h_load={}", h_idle, h_load);
        // never exceeds the uniform cap log2(4)=2.0.
        assert!(h_load <= 2.0 + 1e-12);
    }

    #[test]
    fn pressure_zero_trace_is_deterministic() {
        // Regression guard: two independent instances with the same checkpoint must trace
        // the same trajectory (deterministic dynamics). Uses relative tolerance because the
        // CALIBRATE-ENTROPY phase threshold change (absolute h_max·0.70 → relative h_eq+δ)
        // alters the EntropyPhase written to block_c, producing ULP-level stasis_cos
        // differences that are structurally irrelevant (both instances still identical).
        let mut a = KernelStepper::new();
        let mut sv_a = StateVector::new();
        let mut st_a = StasisVec::new();
        let mut b = KernelStepper::new();
        let mut sv_b = StateVector::new();
        let mut st_b = StasisVec::new();
        for _ in 0..500 {
            let oa = a.step(&mut sv_a, &mut st_a, 0.0);
            let ob = b.step(&mut sv_b, &mut st_b, 0.0);
            let max_diff = (oa.stasis_cos - ob.stasis_cos).abs()
                .max((oa.h_t - ob.h_t).abs());
            assert!(max_diff < 1e-12, "determinism violation: stasis_cos diff={}, h_t diff={}",
                oa.stasis_cos - ob.stasis_cos, oa.h_t - ob.h_t);
        }
    }

    #[test]
    fn under_load_still_converges_and_contracts() {
        // With sustained real pressure the system must STILL converge (stasis_cos→high) and stay
        // contractive (bounded L) — the moving fixed point preserves λ_max<0.
        let mut stepper = KernelStepper::new();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        let mut last = stepper.step(&mut sv, &mut stasis, 0.6);
        for _ in 0..2000 {
            last = stepper.step(&mut sv, &mut stasis, 0.6);
        }
        assert!(last.stasis_cos > 0.95, "must converge under load, stasis_cos={}", last.stasis_cos);
        assert!(last.l_x < 0.40, "must stay contractive under load, L={}", last.l_x);
        assert!(last.l_x.is_finite());
    }

    #[test]
    fn varying_pressure_preserves_point_attractor_topology() {
        // W4b ACCEPTANCE CRITERION (deep_wiring_design.vsm §W4b_block_b_feedback): under a REALISTIC
        // varying pressure trace, the live attractor must STILL read as a point sink (β₀=1 ∧ β₁=0) at
        // the EXP-TDA-01 cosine scale — i.e., the effective-temperature smear does not fracture the
        // basin topology (no false `vr_topology_break` algedonic). This is the gate to a prod deploy.
        use crate::vr_complex::{VrComplex, VR_EPSILON_COSINE};
        let trace = |t: usize| 0.4 + 0.3 * ((t as f64) * 0.05).sin(); // ∈ [0.1, 0.7], smooth
        let mut stepper = KernelStepper::new();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for t in 0..1500 {
            stepper.step(&mut sv, &mut stasis, trace(t)); // settle under the varying load
        }
        let mut window: Vec<StateVector> = Vec::new();
        for t in 1500..1532 {
            stepper.step(&mut sv, &mut stasis, trace(t));
            window.push(sv.clone());
        }
        let betti = VrComplex::from_points_cosine(&window, VR_EPSILON_COSINE).betti();
        assert_eq!(betti.b0, 1, "varying pressure must keep a connected basin (β₀=1), got {}", betti.b0);
        assert_eq!(betti.b1, 0, "varying pressure must not open a loop (β₁=0), got {}", betti.b1);
    }

    // ── EXP-SEN-01 — adaptive resting entropy (env-gated, Option F) ─────────────

    #[test]
    fn adaptive_off_keeps_h_rest_constant_byte_identical() {
        // HARD GATE: with adaptive OFF (default), h_rest never moves, drift is always 0,
        // warmup never fires — the byte-identical guarantee for prod.
        let mut stepper = KernelStepper::new();
        let h0 = stepper.h_rest();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for _ in 0..3000 {
            stepper.step(&mut sv, &mut stasis, 0.0);
        }
        assert_eq!(stepper.h_rest().to_bits(), h0.to_bits(), "h_rest must NOT drift when adaptive OFF");
        assert_eq!(stepper.h_rest_drift(), 0.0);
        assert!(!stepper.warmup_done());
    }

    #[test]
    fn adaptive_on_calibrates_then_null_at_closed_attractor() {
        // H_SEN1 (null): adaptive ON, closed system (pressure=0). h_rest calibrates to the TRUE
        // resting entropy (attractor ≈1.8, far above the 0.40 placeholder), warmup completes, and
        // post-warmup drift stays ≈0 — a stable closed system does not senesce.
        let mut stepper = KernelStepper::new();
        stepper.enable_adaptive_h_rest();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for _ in 0..20000 {
            stepper.step(&mut sv, &mut stasis, 0.0);
        }
        assert!(stepper.warmup_done(), "warmup should converge in a closed system");
        assert!(stepper.h_rest() > 1.5,
            "h_rest must calibrate up to the real resting entropy (~1.8), got {}", stepper.h_rest());
        assert!(stepper.h_rest_drift().abs() < 0.05,
            "closed-system drift must be ~0 (H_null), got {}", stepper.h_rest_drift());
    }

    #[test]
    fn adaptive_on_drifts_under_sustained_stress() {
        // H_SEN2: calibrate at the closed attractor, then apply sustained pressure (raises the
        // equilibrium entropy) → the resting set-point drifts UP from its baseline → the first
        // nonzero δ term. This is senescence manifesting under an external stressor.
        let mut stepper = KernelStepper::new();
        stepper.enable_adaptive_h_rest();
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        for _ in 0..20000 { stepper.step(&mut sv, &mut stasis, 0.0); }   // calibrate (ref snapshot)
        assert!(stepper.warmup_done());
        let drift_before = stepper.h_rest_drift();
        for _ in 0..20000 { stepper.step(&mut sv, &mut stasis, 0.8); }   // sustained stressor
        let drift_after = stepper.h_rest_drift();
        assert!(drift_after > drift_before + 0.02,
            "sustained stress must raise the resting set-point (senescence): before={} after={}",
            drift_before, drift_after);
    }
}
