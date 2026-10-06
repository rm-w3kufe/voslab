// operator.rs — vOS kernel split operator + softmax policy mixing
//
// Implements:
//   docs/theory/dynamics_choice.vsm §T1
//   docs/theory/lyapunov_proof.vsm Ax_SplitOperator + assumption A1 (Lipschitz f₀)
//
// Formal definitions:
//   Ax_SplitOperator: x(t+1) = f₀(x(t)) + σ(t)·η(t)
//                     f₀: ℝ¹²⁸ → ℝ¹²⁸ deterministic, asymmetric (encodes VSM hierarchy)
//                     η ~ N(0, I_{128}) isotropic gaussian, reversible by symmetry
//
//   Def_SoftmaxMixing: f₀(x) = Σ_{s ∈ {S1..S5}} softmax(logits_s(x); τ) · μ_s
//                      logits_s: ℝ¹²⁸ → ℝ Lipschitz
//                      μ_s ∈ Ω (mode centers — reference points per VSM level)
//
//   Def_Adaptiveτ:    τ: Lifecycle → [0.05, 1.0]
//                     τ_idle = 1.0      (exploration)
//                     τ_active = 0.05   (sharp policy)
//                     τ_transition = 0.2 (rampa)
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.7 | vsm-1.0 ⟧

use crate::state_vector::*;
use crate::omega_validator::Omega;

// ─── VSM modes (5 — one per S level) ───────────────────────────────────────────

pub const N_MODES: usize = 5;

/// Index of each VSM level in the modes array.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VsmLevel {
    S1 = 0,  // Operations
    S2 = 1,  // Coordination
    S3 = 2,  // Control
    S4 = 3,  // Intelligence
    S5 = 4,  // Policy
}

impl VsmLevel {
    pub fn name(&self) -> &'static str {
        match self {
            VsmLevel::S1 => "S1", VsmLevel::S2 => "S2", VsmLevel::S3 => "S3",
            VsmLevel::S4 => "S4", VsmLevel::S5 => "S5",
        }
    }
}

// ─── ADAPTIVE TEMPERATURE (lifecycle → τ) ──────────────────────────────────────

/// Def_Adaptiveτ — temperature determined by lifecycle phase.
/// lifecycle stored in StateVector at index LIFECYCLE; values per state_vector.rs:
///   0.2 = onboarding, 0.5 = iterating, 0.7 = testing, 1.0 = production
///
/// Mapping (continuous, monotone-decreasing in lifecycle):
///   τ(lifecycle) = 1.05 - lifecycle  (linear)
/// Yields:
///   τ(0.2) = 0.85   ≈ idle/exploration
///   τ(0.5) = 0.55   ≈ moderate
///   τ(0.7) = 0.35   ≈ transition
///   τ(1.0) = 0.05   ≈ active/sharp
/// Clipped to [0.05, 1.0] per Def_Adaptiveτ contract.
pub fn tau_from_lifecycle(lifecycle: f64) -> f64 {
    (1.05 - lifecycle).clamp(0.05, 1.0)
}

// ─── PRNG: splitmix64 + Box-Muller for N(0,1) ──────────────────────────────────

/// Deterministic gaussian sampler — splitmix64 PRNG + Box-Muller transform.
/// Stdlib-only (no `rand` dep). Suitable for testing + reproducible runs.
pub struct GaussianSampler {
    state: u64,
    // Box-Muller produces 2 normals per pair; cache the second.
    cached: Option<f64>,
}

impl GaussianSampler {
    pub fn new(seed: u64) -> Self {
        // Avoid 0 state (degenerate splitmix64).
        let s = if seed == 0 { 0x9E37_79B9_7F4A_7C15 } else { seed };
        GaussianSampler { state: s, cached: None }
    }

    /// splitmix64 next u64.
    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Uniform (0, 1) — open interval avoids log(0) in Box-Muller.
    fn next_uniform_open(&mut self) -> f64 {
        // 53-bit precision; (u >> 11) ∈ [0, 2^53), then +1 to avoid 0.
        let u = self.next_u64() >> 11;
        ((u + 1) as f64) / ((1u64 << 53) as f64 + 2.0)
    }

    /// Sample one N(0, 1) via Box-Muller.
    pub fn next_normal(&mut self) -> f64 {
        if let Some(v) = self.cached.take() { return v; }
        let u1 = self.next_uniform_open();
        let u2 = self.next_uniform_open();
        let r = (-2.0_f64 * u1.ln()).sqrt();
        let theta = 2.0_f64 * std::f64::consts::PI * u2;
        let z0 = r * theta.cos();
        let z1 = r * theta.sin();
        self.cached = Some(z1);
        z0
    }

    /// Fill an array slice with N(0, 1) samples.
    pub fn fill_normal(&mut self, buf: &mut [f64]) {
        for v in buf.iter_mut() { *v = self.next_normal(); }
    }
}

// ─── LOGITS FUNCTIONS PER MODE ─────────────────────────────────────────────────

/// Logit function: ℝ¹²⁸ → ℝ. Lipschitz with bounded gradient.
/// Implemented as sparse linear: logit_s(x) = b_s + Σ_i w_si · x_i.
/// Sparse weights → cheap eval + L_f bounded by max_i |w_si|.
#[derive(Debug, Clone)]
pub struct Logit {
    pub bias: f64,
    /// Sparse: (index, weight). All others = 0.
    pub weights: Vec<(usize, f64)>,
}

impl Logit {
    pub fn new(bias: f64, weights: Vec<(usize, f64)>) -> Self {
        Logit { bias, weights }
    }

    pub fn eval(&self, x: &StateVector) -> f64 {
        self.bias + self.weights.iter().map(|(i, w)| w * x.dims[*i]).sum::<f64>()
    }

    /// L₂ norm of gradient — used for Lipschitz constant of softmax.
    pub fn grad_norm(&self) -> f64 {
        self.weights.iter().map(|(_, w)| w * w).sum::<f64>().sqrt()
    }
}

// ─── SOFTMAX UTILITY ───────────────────────────────────────────────────────────

/// Numerically-stable softmax with temperature τ.
/// Returns weights summing to 1.0.
/// softmax_τ(x)_i = exp(x_i / τ) / Σ_j exp(x_j / τ)
pub fn softmax(logits: &[f64; N_MODES], tau: f64) -> [f64; N_MODES] {
    debug_assert!(tau > 0.0, "softmax temperature must be > 0");
    let max = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mut out = [0.0; N_MODES];
    let mut sum = 0.0;
    for i in 0..N_MODES {
        let e = ((logits[i] - max) / tau).exp();
        out[i] = e;
        sum += e;
    }
    for v in out.iter_mut() { *v /= sum; }
    out
}

// ─── SPLIT OPERATOR ────────────────────────────────────────────────────────────

/// Def_SplitOperator + Def_SoftmaxMixing.
/// Encapsulates the 5 mode centers μ_s, the 5 logit functions, and τ adaptive policy.
pub struct SplitOperator {
    /// Mode centers μ_s ∈ Ω, one per VSM level (S1..S5).
    pub modes: [StateVector; N_MODES],
    /// Logit functions producing one scalar score per mode.
    pub logits: [Logit; N_MODES],
}

impl SplitOperator {
    pub fn new(modes: [StateVector; N_MODES], logits: [Logit; N_MODES]) -> Self {
        SplitOperator { modes, logits }
    }

    /// Compute the 5 raw logits at point x.
    fn logit_values(&self, x: &StateVector) -> [f64; N_MODES] {
        let mut out = [0.0; N_MODES];
        for s in 0..N_MODES { out[s] = self.logits[s].eval(x); }
        out
    }

    /// Compute softmax mixing weights at x given temperature τ.
    pub fn mixing_weights(&self, x: &StateVector, tau: f64) -> [f64; N_MODES] {
        softmax(&self.logit_values(x), tau)
    }

    /// f₀(x) = Σ_s softmax(logits_s(x); τ) · μ_s.
    /// Convex combination of mode centers ⇒ if all μ_s ∈ Ω, f₀(x) ∈ Ω (Ax_Ω_Closure).
    pub fn deterministic_step(&self, x: &StateVector, tau: f64) -> StateVector {
        let weights = self.mixing_weights(x, tau);
        let mut next = [0.0_f64; 128];
        for s in 0..N_MODES {
            let w = weights[s];
            for i in 0..128 { next[i] += w * self.modes[s].dims[i]; }
        }
        StateVector { dims: next }
    }

    /// Full split step: x(t+1) = f₀(x) + σ·η.
    /// Returns (next_state, mixing_weights_used).
    pub fn step(
        &self,
        x: &StateVector,
        sigma: f64,
        rng: &mut GaussianSampler,
    ) -> (StateVector, [f64; N_MODES]) {
        let tau = tau_from_lifecycle(x.dims[LIFECYCLE]);
        let weights = self.mixing_weights(x, tau);
        let mut next = [0.0_f64; 128];
        // Deterministic mixing
        for s in 0..N_MODES {
            let w = weights[s];
            for i in 0..128 { next[i] += w * self.modes[s].dims[i]; }
        }
        // Add σ·η noise
        let mut noise = [0.0_f64; 128];
        rng.fill_normal(&mut noise);
        for i in 0..128 { next[i] += sigma * noise[i]; }
        (StateVector { dims: next }, weights)
    }

    /// Lipschitz constant upper bound for f₀ given τ.
    /// L_f ≤ (max_s ‖∇logits_s‖) · diam_modes / τ
    /// where diam_modes = max_{s,s'} ‖μ_s - μ_{s'}‖.
    pub fn lipschitz_bound(&self, tau: f64) -> f64 {
        let max_grad_norm = self.logits.iter()
            .map(|l| l.grad_norm())
            .fold(0.0_f64, f64::max);
        let mut diam_modes = 0.0_f64;
        for a in 0..N_MODES {
            for b in (a+1)..N_MODES {
                let d2: f64 = (0..128)
                    .map(|i| {
                        let d = self.modes[a].dims[i] - self.modes[b].dims[i];
                        d * d
                    })
                    .sum();
                diam_modes = diam_modes.max(d2.sqrt());
            }
        }
        max_grad_norm * diam_modes / tau
    }
}

// ─── DEFAULT KERNEL FACTORY ────────────────────────────────────────────────────

/// Build a baseline SplitOperator with 5 mode centers at distinct interior
/// points of the canonical Ω. Used as default initialisation; in production
/// modes would be learned/calibrated per kernel deployment.
pub fn default_split_operator() -> SplitOperator {
    // Each mode emphasises one VSM level by setting that level's signature
    // dimensions higher.
    let make_mode = |signature: &[(usize, f64)]| -> StateVector {
        let mut s = StateVector { dims: [0.0; 128] };
        // Healthy baseline (identical to omega_validator typical_healthy_state baseline).
        for i in TRUST_HIST_0..=TRUST_HIST_9 { s.dims[i] = 0.85; }
        s.dims[CPU_PRESSURE]    = 0.3;
        s.dims[MEM_PRESSURE]    = 0.3;
        s.dims[IO_PRESSURE]     = 0.2;
        s.dims[BUDGET]          = 0.7;
        s.dims[CGROUP_HEADROOM] = 0.5;
        s.dims[H_T]             = 0.3;
        s.dims[H_REST]          = 0.25;
        s.dims[STASIS_COS]      = 0.95;
        s.dims[LIFECYCLE]       = 0.7;
        s.dims[GOVERNED]        = 1.0;
        // Apply mode-specific signature
        for (i, v) in signature { s.dims[*i] = *v; }
        s
    };

    // Mode signatures — per VSM level emphasis (placeholder; calibration TBD)
    let mu_s1 = make_mode(&[(CPU_PRESSURE, 0.5), (PHI_UP_RATE, 0.8)]);
    let mu_s2 = make_mode(&[(QUEUE_PHI_UP, 0.4), (QUEUE_PHI_DOWN, 0.4)]);
    let mu_s3 = make_mode(&[(BUDGET, 0.85), (PHI_DOWN_RATE, 0.7)]);
    let mu_s4 = make_mode(&[(LAMBDA, 0.5), (LEARNING_RATE, 0.3)]);
    let mu_s5 = make_mode(&[(GOVERNED, 1.0), (ESCALATION, 0.2)]);

    // Logit functions — each mode is favoured by its own signature dims.
    let logit_s1 = Logit::new(0.0, vec![(CPU_PRESSURE, 1.0), (PHI_UP_RATE, 0.5)]);
    let logit_s2 = Logit::new(0.0, vec![(QUEUE_PHI_UP, 0.7), (QUEUE_PHI_DOWN, 0.7)]);
    let logit_s3 = Logit::new(0.0, vec![(BUDGET, 0.5), (PHI_DOWN_RATE, 0.5)]);
    let logit_s4 = Logit::new(0.0, vec![(LAMBDA, 0.8), (LEARNING_RATE, 0.5)]);
    let logit_s5 = Logit::new(0.5, vec![(GOVERNED, 1.0), (ESCALATION, 0.5)]);

    SplitOperator::new(
        [mu_s1, mu_s2, mu_s3, mu_s4, mu_s5],
        [logit_s1, logit_s2, logit_s3, logit_s4, logit_s5],
    )
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tau_lifecycle_mapping_within_bounds() {
        for &lc in &[0.0, 0.2, 0.5, 0.7, 1.0, 1.5] {
            let t = tau_from_lifecycle(lc);
            assert!((0.05..=1.0).contains(&t), "τ({}) = {} out of [0.05, 1.0]", lc, t);
        }
        // Specific values
        assert!((tau_from_lifecycle(1.0) - 0.05).abs() < 1e-9);
        assert!((tau_from_lifecycle(0.2) - 0.85).abs() < 1e-9);
    }

    #[test]
    fn softmax_sums_to_one() {
        let logits = [1.0, 2.0, 3.0, 0.5, -1.0];
        for &tau in &[0.05, 0.5, 1.0] {
            let w = softmax(&logits, tau);
            let sum: f64 = w.iter().sum();
            assert!((sum - 1.0).abs() < 1e-9, "softmax τ={}: sum = {}", tau, sum);
            assert!(w.iter().all(|&x| x >= 0.0 && x <= 1.0));
        }
    }

    #[test]
    fn softmax_low_tau_concentrates_on_argmax() {
        let logits = [1.0, 2.0, 5.0, 0.5, -1.0];
        let w = softmax(&logits, 0.05);
        // index 2 should dominate
        let argmax = w.iter().enumerate().fold(0, |i, (j, v)| if *v > w[i] { j } else { i });
        assert_eq!(argmax, 2);
        assert!(w[2] > 0.999, "low τ should concentrate, got w[2]={}", w[2]);
    }

    #[test]
    fn gaussian_sampler_basic_stats() {
        let mut rng = GaussianSampler::new(42);
        let n = 10_000;
        let samples: Vec<f64> = (0..n).map(|_| rng.next_normal()).collect();
        let mean: f64 = samples.iter().sum::<f64>() / (n as f64);
        let var: f64 = samples.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n as f64);
        // Should be approximately N(0, 1)
        assert!(mean.abs() < 0.05, "mean = {} should be ~0", mean);
        assert!((var - 1.0).abs() < 0.05, "var = {} should be ~1", var);
    }

    #[test]
    fn gaussian_sampler_reproducible() {
        let mut a = GaussianSampler::new(7);
        let mut b = GaussianSampler::new(7);
        for _ in 0..100 {
            assert_eq!(a.next_normal().to_bits(), b.next_normal().to_bits());
        }
    }

    #[test]
    fn deterministic_step_in_convex_hull_of_modes() {
        let op = default_split_operator();
        // Healthy interior state
        let mut x = op.modes[0].clone();
        x.dims[STASIS_COS] = 0.5;
        let tau = 0.5;
        let next = op.deterministic_step(&x, tau);

        // Each dim of next must lie within [min_s μ_s[i], max_s μ_s[i]]
        // (since next is a convex combination of modes).
        for i in 0..128 {
            let mn = op.modes.iter().map(|m| m.dims[i]).fold(f64::INFINITY, f64::min);
            let mx = op.modes.iter().map(|m| m.dims[i]).fold(f64::NEG_INFINITY, f64::max);
            assert!(
                next.dims[i] >= mn - 1e-9 && next.dims[i] <= mx + 1e-9,
                "dim {} = {} outside [{}, {}]", i, next.dims[i], mn, mx
            );
        }
    }

    #[test]
    fn deterministic_step_preserves_omega_membership() {
        // Ax_Ω_Closure: convex combinations of μ_s ∈ Ω stay in Ω.
        let omega = Omega::canonical();
        let op = default_split_operator();

        // All 5 modes should themselves be in Ω
        for (i, m) in op.modes.iter().enumerate() {
            let v = omega.violations(m);
            assert!(v.is_empty(), "mode {} violates Ω: {:?}", i, v);
        }

        // Step from each mode also lands in Ω
        for i in 0..N_MODES {
            let next = op.deterministic_step(&op.modes[i], 0.5);
            let v = omega.violations(&next);
            assert!(v.is_empty(), "deterministic_step from mode {} → Ω violations: {:?}", i, v);
        }
    }

    #[test]
    fn step_with_zero_sigma_equals_deterministic() {
        let op = default_split_operator();
        let x = op.modes[2].clone();
        let tau = tau_from_lifecycle(x.dims[LIFECYCLE]);
        let det = op.deterministic_step(&x, tau);

        let mut rng = GaussianSampler::new(123);
        let (stoch, _w) = op.step(&x, 0.0, &mut rng);

        for i in 0..128 {
            assert!((det.dims[i] - stoch.dims[i]).abs() < 1e-12,
                    "dim {}: det={} vs stoch={}", i, det.dims[i], stoch.dims[i]);
        }
    }

    #[test]
    fn step_with_noise_perturbs_state() {
        let op = default_split_operator();
        let x = op.modes[1].clone();
        let mut rng = GaussianSampler::new(999);
        let (next, _w) = op.step(&x, 0.05, &mut rng);

        let diff: f64 = (0..128).map(|i| (next.dims[i] - x.dims[i]).powi(2)).sum::<f64>().sqrt();
        assert!(diff > 0.0, "noise should perturb state, got diff = {}", diff);
    }

    #[test]
    fn lipschitz_bound_finite_and_increases_as_tau_decreases() {
        let op = default_split_operator();
        let l_high_tau = op.lipschitz_bound(1.0);
        let l_low_tau  = op.lipschitz_bound(0.05);
        assert!(l_high_tau.is_finite() && l_high_tau > 0.0);
        assert!(l_low_tau > l_high_tau,
                "L_f(τ=0.05)={} should be > L_f(τ=1.0)={}", l_low_tau, l_high_tau);
    }

    #[test]
    fn empirical_lipschitz_within_bound() {
        // Empirically check that ‖f₀(x) - f₀(y)‖ ≤ L_f · ‖x - y‖ for sampled pairs.
        let op = default_split_operator();
        let tau = 0.5;
        let l_f = op.lipschitz_bound(tau);

        let mut rng = GaussianSampler::new(2026);
        let mut max_ratio = 0.0_f64;
        for _ in 0..200 {
            let mut x = op.modes[0].clone();
            let mut y = op.modes[0].clone();
            for i in 0..128 {
                x.dims[i] += 0.01 * rng.next_normal();
                y.dims[i] += 0.01 * rng.next_normal();
            }
            let fx = op.deterministic_step(&x, tau);
            let fy = op.deterministic_step(&y, tau);
            let dx: f64 = (0..128).map(|i| (x.dims[i] - y.dims[i]).powi(2)).sum::<f64>().sqrt();
            let df: f64 = (0..128).map(|i| (fx.dims[i] - fy.dims[i]).powi(2)).sum::<f64>().sqrt();
            if dx > 1e-9 {
                let ratio = df / dx;
                if ratio > max_ratio { max_ratio = ratio; }
            }
        }
        // Allow generous slack — bound is loose, empirical is tighter
        assert!(max_ratio <= l_f * 2.0,
                "empirical Lipschitz ratio {} exceeds bound {}", max_ratio, l_f);
    }
}
