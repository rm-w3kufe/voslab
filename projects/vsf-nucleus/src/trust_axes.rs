// trust_axes.rs — F5.x.8 — trust as a 4-vector + composition + adaptive update
//
// Implements: docs/theory/dynamics_choice.vsm §G4
//
//   Def_TrustVector:  trust ∈ [0,1]⁴ = (behavioral, structural, predictive, communicative)
//                     per-axis monitoring + a scalar aggregate for the Ω-check.
//   Def_TrustCompose: trust_parent = min( Σ α_i·trust_i , min_i(trust_i) + ε )   (ε = 0.05)
//                     α from S3 allocation. Weakest-link clamp: the parent can exceed its
//                     weakest child by at most ε, no matter how the weights are set.
//   Def_TrustUpdate:  trust(t+1) = (1-λ)·trust(t) + λ·observation     (EMA, per axis)
//                     λ = (0.1·(1 + |ΔH|/H_max)).clamp(0.05, 0.2)   — entropy-adaptive.
//
// EXP-TRUST-01 calibration CLOSED (run_4 / phase B, 2026-06-19): the per-axis λ_i hook is
// resolved — ALL axes share a SINGLE adaptive λ = 0.10 (measured 0.10002 ± 1.8e-5,
// rock-stable). Per-axis λ_i are NOT warranted (H_TRUST2 REFUTED re the per-axis values;
// the shared λ≈0.10 CONFIRMED consistent across axes). The measured rate is pinned as
// `LAMBDA_CALIBRATED` and consumed by the DSN-COUPLE-01 Phase-4 admission gate (coupling.rs).
// Connects to coupling.rs: a TrustVector's `scalar()` feeds the Ax_ψ_Preserve trust clause.
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

pub const N_AXES: usize = 4;
/// Def_TrustCompose ε (caveat ε_value): the parent may exceed its weakest child by ≤ ε.
pub const DEFAULT_EPSILON: f64 = 0.05;
/// Def_TrustUpdate λ bounds.
pub const LAMBDA_MIN: f64 = 0.05;
pub const LAMBDA_MAX: f64 = 0.20;
/// Def_TrustUpdate calibrated base rate — the single shared trust-recovery λ.
/// Source: EXP-TRUST-01 run_4 / phase B (2026-06-19), measured λ = 0.10002 ± 1.8e-5,
/// rock-stable across all four axes (per-axis λ_i NOT warranted). This is the empirical
/// anchor for `adaptive_lambda` and the rate the DSN-COUPLE-01 Phase-4 gate recovers
/// trust at (see `update_calibrated` + coupling.rs::admit_coupling).
pub const LAMBDA_CALIBRATED: f64 = 0.10;

/// The four trust axes (Def_TrustVector).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrustAxis {
    Behavioral,    // does it act as expected?
    Structural,    // is its integrity / binary / config sound?
    Predictive,    // does its forecast match outcomes?
    Communicative, // does it report honestly + on time?
}

/// trust ∈ [0,1]⁴. Construction clamps every axis into [0,1].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TrustVector {
    pub behavioral: f64,
    pub structural: f64,
    pub predictive: f64,
    pub communicative: f64,
}

impl TrustVector {
    pub fn new(behavioral: f64, structural: f64, predictive: f64, communicative: f64) -> Self {
        let c = |v: f64| v.clamp(0.0, 1.0);
        TrustVector {
            behavioral: c(behavioral),
            structural: c(structural),
            predictive: c(predictive),
            communicative: c(communicative),
        }
    }

    /// All four axes equal to `v`.
    pub fn uniform(v: f64) -> Self {
        TrustVector::new(v, v, v, v)
    }

    pub fn as_array(&self) -> [f64; N_AXES] {
        [self.behavioral, self.structural, self.predictive, self.communicative]
    }

    /// Weakest axis — the VSM-conservative view of a system's trust.
    pub fn min_axis(&self) -> f64 {
        self.as_array().iter().copied().fold(f64::INFINITY, f64::min)
    }

    /// Def_TrustVector scalar aggregate for the Ω-check: equal-weight mean.
    /// (For axis weighting, use `scalar_weighted`.)
    pub fn scalar(&self) -> f64 {
        self.as_array().iter().sum::<f64>() / N_AXES as f64
    }

    /// Weighted scalar aggregate. Weights need not sum to 1 (normalized here).
    /// Falls back to the plain mean if the weights sum to ~0.
    pub fn scalar_weighted(&self, weights: [f64; N_AXES]) -> f64 {
        let wsum: f64 = weights.iter().sum();
        if wsum.abs() < 1e-12 {
            return self.scalar();
        }
        let dot: f64 = self.as_array().iter().zip(weights).map(|(a, w)| a * w).sum();
        (dot / wsum).clamp(0.0, 1.0)
    }

    /// Def_TrustUpdate — per-axis EMA toward `observation` with shared λ.
    pub fn update(&self, observation: &TrustVector, lambda: f64) -> TrustVector {
        let l = lambda.clamp(LAMBDA_MIN, LAMBDA_MAX);
        let ema = |old: f64, obs: f64| (1.0 - l) * old + l * obs;
        TrustVector::new(
            ema(self.behavioral, observation.behavioral),
            ema(self.structural, observation.structural),
            ema(self.predictive, observation.predictive),
            ema(self.communicative, observation.communicative),
        )
    }

    /// Def_TrustUpdate at the EXP-TRUST-01-calibrated shared rate (LAMBDA_CALIBRATED).
    /// This is the Phase-4 coupling gate's trust-recovery step: a live coupling's trust
    /// evolves toward its observation at the MEASURED λ=0.10 (not an arbitrary caller λ).
    pub fn update_calibrated(&self, observation: &TrustVector) -> TrustVector {
        self.update(observation, LAMBDA_CALIBRATED)
    }
}

/// Def_TrustUpdate adaptive λ from the entropy change ΔH relative to H_max.
/// λ = LAMBDA_CALIBRATED·(1 + |ΔH|/H_max), clamped to [0.05, 0.2]. Larger entropy
/// swings → faster trust adaptation. `h_max ≤ 0` ⇒ the calibrated base rate.
/// EXP-TRUST-01 (run_4) confirmed the realized λ stays ≈ base (0.10002 ± 1.8e-5) at
/// steady state — the entropy term is a small, bounded modulation of the measured anchor.
pub fn adaptive_lambda(delta_h: f64, h_max: f64) -> f64 {
    let ratio = if h_max > 0.0 { delta_h.abs() / h_max } else { 0.0 };
    (LAMBDA_CALIBRATED * (1.0 + ratio)).clamp(LAMBDA_MIN, LAMBDA_MAX)
}

/// Def_TrustCompose — parent trust from children scalars + S3 allocation weights α.
///
///   trust_parent = min( Σ α_i·trust_i , min_i(trust_i) + ε )
///
/// `children` and `alpha` must be the same non-empty length. α is normalized so the
/// weighted sum is a convex combination (α from S3 allocation; need not pre-sum to 1).
/// Returns None on empty / mismatched / all-zero-weight input.
pub fn compose(children: &[f64], alpha: &[f64], epsilon: f64) -> Option<f64> {
    if children.is_empty() || children.len() != alpha.len() {
        return None;
    }
    let wsum: f64 = alpha.iter().sum();
    if wsum.abs() < 1e-12 {
        return None;
    }
    let weighted: f64 = children.iter().zip(alpha).map(|(t, a)| t * a).sum::<f64>() / wsum;
    let min_child = children.iter().copied().fold(f64::INFINITY, f64::min);
    Some(weighted.min(min_child + epsilon).clamp(0.0, 1.0))
}

/// Convenience: compose a parent from child TrustVectors via their scalar aggregates.
pub fn compose_vectors(children: &[TrustVector], alpha: &[f64], epsilon: f64) -> Option<f64> {
    let scalars: Vec<f64> = children.iter().map(|t| t.scalar()).collect();
    compose(&scalars, alpha, epsilon)
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_clamps_axes() {
        let t = TrustVector::new(1.5, -0.2, 0.5, 0.9);
        assert_eq!(t.behavioral, 1.0);
        assert_eq!(t.structural, 0.0);
        assert_eq!(t.predictive, 0.5);
        assert_eq!(t.communicative, 0.9);
    }

    #[test]
    fn scalar_is_mean_min_is_weakest() {
        let t = TrustVector::new(0.8, 0.6, 0.4, 0.2);
        assert!((t.scalar() - 0.5).abs() < 1e-12);
        assert!((t.min_axis() - 0.2).abs() < 1e-12);
    }

    #[test]
    fn scalar_weighted_normalizes_and_falls_back() {
        let t = TrustVector::new(1.0, 0.0, 0.0, 0.0);
        // all weight on behavioral
        assert!((t.scalar_weighted([2.0, 0.0, 0.0, 0.0]) - 1.0).abs() < 1e-12);
        // zero weights → plain mean
        assert!((t.scalar_weighted([0.0; 4]) - t.scalar()).abs() < 1e-12);
    }

    #[test]
    fn adaptive_lambda_bounds() {
        assert!((adaptive_lambda(0.0, 1.0) - 0.1).abs() < 1e-12);   // no swing → base 0.1
        assert_eq!(adaptive_lambda(10.0, 1.0), LAMBDA_MAX);          // huge swing → capped 0.2
        assert_eq!(adaptive_lambda(0.5, 0.0), 0.1);                  // h_max≤0 → base
        // monotone: bigger |ΔH| ⇒ bigger λ (until cap)
        assert!(adaptive_lambda(0.5, 1.0) > adaptive_lambda(0.1, 1.0));
    }

    #[test]
    fn update_is_ema_toward_observation() {
        let t = TrustVector::uniform(1.0);
        let obs = TrustVector::uniform(0.0);
        let next = t.update(&obs, 0.2);
        // (1-0.2)*1 + 0.2*0 = 0.8 on every axis
        for v in next.as_array() {
            assert!((v - 0.8).abs() < 1e-12);
        }
    }

    #[test]
    fn update_clamps_lambda() {
        let t = TrustVector::uniform(1.0);
        let obs = TrustVector::uniform(0.0);
        // λ=0.9 should clamp to LAMBDA_MAX=0.2 → result 0.8, not 0.1
        let next = t.update(&obs, 0.9);
        assert!((next.behavioral - 0.8).abs() < 1e-12);
    }

    #[test]
    fn lambda_calibrated_in_bounds_and_anchors_adaptive() {
        // EXP-TRUST-01 measured rate must live inside the design clamp …
        assert!(LAMBDA_CALIBRATED >= LAMBDA_MIN && LAMBDA_CALIBRATED <= LAMBDA_MAX);
        // … and be the anchor: zero entropy swing → adaptive λ == calibrated rate.
        assert!((adaptive_lambda(0.0, 1.0) - LAMBDA_CALIBRATED).abs() < 1e-12);
    }

    #[test]
    fn update_calibrated_uses_measured_rate() {
        let t = TrustVector::uniform(1.0);
        let obs = TrustVector::uniform(0.0);
        let next = t.update_calibrated(&obs);
        // (1-0.10)*1 + 0.10*0 = 0.90 on every axis (the measured λ=0.10 recovery step).
        for v in next.as_array() {
            assert!((v - 0.90).abs() < 1e-12);
        }
    }

    #[test]
    fn compose_weakest_link_clamp_dominates() {
        // children 0.9,0.9,0.3 equal weights → weighted=0.7 but min+ε=0.35 → 0.35.
        let r = compose(&[0.9, 0.9, 0.3], &[1.0, 1.0, 1.0], DEFAULT_EPSILON).unwrap();
        assert!((r - 0.35).abs() < 1e-12);
    }

    #[test]
    fn compose_weighted_sum_when_below_clamp() {
        // children all near each other → weighted sum < min+ε → returns weighted.
        let r = compose(&[0.80, 0.82, 0.84], &[1.0, 1.0, 1.0], DEFAULT_EPSILON).unwrap();
        let weighted = (0.80 + 0.82 + 0.84) / 3.0; // 0.82
        // min+ε = 0.80+0.05 = 0.85 > 0.82 → returns weighted
        assert!((r - weighted).abs() < 1e-12);
    }

    #[test]
    fn compose_rejects_bad_input() {
        assert!(compose(&[], &[], DEFAULT_EPSILON).is_none());
        assert!(compose(&[0.5], &[1.0, 1.0], DEFAULT_EPSILON).is_none());
        assert!(compose(&[0.5, 0.5], &[0.0, 0.0], DEFAULT_EPSILON).is_none());
    }

    #[test]
    fn compose_vectors_uses_scalar_aggregate() {
        let a = TrustVector::uniform(0.9);
        let b = TrustVector::uniform(0.3);
        // scalars 0.9, 0.3 equal weights → weighted=0.6, min+ε=0.35 → 0.35
        let r = compose_vectors(&[a, b], &[1.0, 1.0], DEFAULT_EPSILON).unwrap();
        assert!((r - 0.35).abs() < 1e-12);
    }
}
