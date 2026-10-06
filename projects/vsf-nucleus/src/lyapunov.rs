// lyapunov.rs — F5.x.2 — runtime recurrent-set certifier + `governed` predicate
//
// Implements: docs/theory/lyapunov_proof.vsm  (Thm_DirectExpansion, Cor_GovernedDefinition)
//             docs/theory/dynamics_choice.vsm §T2 (Ax_RecurrentSet)
//
//   Ax_RecurrentSet: ∃ compact R ⊂ Ω s.t. P(x_t∈R i.o.)=1 ∧ E[ΔL] ≤ -ε < 0 ∀ x∉R.
//                    Inside R, E[ΔL] may be ≥ 0 (stationary fluctuations — "alive";
//                    proof step §215). Outside R the chain contracts toward R.
//
//   Cor_GovernedDefinition (proof line 159, which names THIS file):
//     governed(x_t) := (x_t ∈ Ω) ∧ (mean E[ΔL] over window ≤ 0) ∧ (E[L(x_t)] within R)
//
// This is the certification layer over the L-trajectory; it does NOT recompute L
// (attractor::LyapunovTracker + StateVector::lyapunov own that). Feed it L samples;
// it estimates the drift E[ΔL], the contraction rate ε, a volatility proxy Λ, the
// recurrent-set regime, and the `governed` predicate. A drifting recurrent set
// (L rising above the core while not contracting) is the degrade signal (proof §167).
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use std::collections::VecDeque;

/// Default L-sample window for drift estimation.
pub const DEFAULT_WINDOW: usize = 64;
/// |E[ΔL]| within this band counts as zero drift (stationary fluctuation).
pub const DEFAULT_DRIFT_BAND: f64 = crate::calibration::LYAP_DRIFT_BAND;  // heuristic (EXP-LYAP-CERT)
/// Default recurrent-core radius r_0: mean L ≤ this ⇒ "within R" (calibratable,
/// like θ_PSI). L = 0.5(1-cos)+0.3·H/H_max+0.2·overrun ∈ [0, ~1]; a converged
/// attractor (cos≈1) sits well below 0.5.
pub const DEFAULT_R_CORE: f64 = crate::calibration::LYAP_R_CORE;  // heuristic (EXP-LYAP-CERT)

/// Where the system sits relative to the recurrent set R (Ax_RecurrentSet).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Regime {
    /// E[L] within the recurrent core — stationary fluctuations allowed (E[ΔL] any sign).
    InRecurrentSet,
    /// Outside R but E[ΔL] ≤ -ε < 0 — contracting back toward R.
    ContractingToR,
    /// Outside R and not contracting (E[ΔL] > band) — recurrent set is drifting / degrading.
    Diverging,
    /// Not enough samples to estimate drift yet.
    Unknown,
}

/// Certificate emitted per evaluation.
#[derive(Debug, Clone, Copy)]
pub struct GovernanceCert {
    pub governed: bool,
    pub regime: Regime,
    /// E[ΔL] estimate (least-squares slope of L over the window).
    pub mean_dl: f64,
    /// ε̂ = max(0, -E[ΔL]) — estimated contraction rate (0 inside R / when diverging).
    pub epsilon: f64,
    /// Λ̂ — volatility proxy = max |ΔL| single-step over the window (local Lipschitz of L).
    pub lambda: f64,
    /// mean L over the window.
    pub mean_l: f64,
}

/// Recurrent-set certifier over an L-trajectory. Build once, `observe(l)` each cycle,
/// `certify(in_omega)` to get the governance verdict.
#[derive(Debug, Clone)]
pub struct RecurrentSetCertifier {
    window: VecDeque<f64>,
    cap: usize,
    drift_band: f64,
    r_core: f64,
}

impl Default for RecurrentSetCertifier {
    fn default() -> Self {
        Self::new()
    }
}

impl RecurrentSetCertifier {
    pub fn new() -> Self {
        Self::with_params(DEFAULT_WINDOW, DEFAULT_DRIFT_BAND, DEFAULT_R_CORE)
    }

    pub fn with_params(window: usize, drift_band: f64, r_core: f64) -> Self {
        RecurrentSetCertifier {
            window: VecDeque::with_capacity(window.max(2)),
            cap: window.max(2),
            drift_band,
            r_core,
        }
    }

    /// Push one L(x_t) sample.
    pub fn observe(&mut self, l: f64) {
        if self.window.len() == self.cap {
            self.window.pop_front();
        }
        self.window.push_back(l);
    }

    pub fn samples(&self) -> usize {
        self.window.len()
    }

    /// Mean L over the window (E[L(x_t)]).
    pub fn mean_l(&self) -> Option<f64> {
        if self.window.is_empty() {
            return None;
        }
        Some(self.window.iter().sum::<f64>() / self.window.len() as f64)
    }

    /// E[ΔL] estimate via least-squares slope of L vs sample index. Robust to endpoint
    /// noise (vs the raw telescoping (L_n-L_0)/(n-1)). None with < 2 samples.
    pub fn mean_dl(&self) -> Option<f64> {
        let n = self.window.len();
        if n < 2 {
            return None;
        }
        let nf = n as f64;
        // x = 0..n-1, y = L. slope = Σ(x-x̄)(y-ȳ) / Σ(x-x̄)².
        let x_bar = (nf - 1.0) / 2.0;
        let y_bar = self.window.iter().sum::<f64>() / nf;
        let mut num = 0.0;
        let mut den = 0.0;
        for (i, &y) in self.window.iter().enumerate() {
            let dx = i as f64 - x_bar;
            num += dx * (y - y_bar);
            den += dx * dx;
        }
        if den == 0.0 {
            return None;
        }
        Some(num / den)
    }

    /// ε̂ = max(0, -E[ΔL]) — contraction rate magnitude.
    pub fn epsilon_hat(&self) -> Option<f64> {
        self.mean_dl().map(|m| (-m).max(0.0))
    }

    /// Λ̂ — max single-step |ΔL| over the window (local Lipschitz / volatility proxy).
    /// NB: the proof's σ-based Λ (Bound_Staleness) needs σ samples, not L — that lives
    /// in adaptive_clock (F5.x.3); this is the L-trajectory proxy.
    pub fn lambda_hat(&self) -> Option<f64> {
        if self.window.len() < 2 {
            return None;
        }
        let mut max_step = 0.0f64;
        let mut prev: Option<f64> = None;
        for &l in &self.window {
            if let Some(p) = prev {
                max_step = max_step.max((l - p).abs());
            }
            prev = Some(l);
        }
        Some(max_step)
    }

    /// Classify the regime (Ax_RecurrentSet).
    pub fn regime(&self) -> Regime {
        let (Some(m), Some(ml)) = (self.mean_dl(), self.mean_l()) else {
            return Regime::Unknown;
        };
        if ml <= self.r_core {
            Regime::InRecurrentSet // within core — fluctuations allowed
        } else if m < -self.drift_band {
            Regime::ContractingToR // above core but heading back
        } else {
            Regime::Diverging // above core and not contracting → degrade
        }
    }

    /// Cor_GovernedDefinition: governed ⇔ x∈Ω ∧ (in R ∨ contracting toward R).
    /// Inside R, E[ΔL] may be positive (stationary fluctuations) and still governed.
    /// Diverging or x∉Ω ⇒ not governed. Unknown (too few samples) ⇒ not governed
    /// (fail-closed: cannot certify what hasn't been observed).
    pub fn governed(&self, in_omega: bool) -> bool {
        in_omega && matches!(self.regime(), Regime::InRecurrentSet | Regime::ContractingToR)
    }

    /// Full certificate.
    pub fn certify(&self, in_omega: bool) -> GovernanceCert {
        GovernanceCert {
            governed: self.governed(in_omega),
            regime: self.regime(),
            mean_dl: self.mean_dl().unwrap_or(0.0),
            epsilon: self.epsilon_hat().unwrap_or(0.0),
            lambda: self.lambda_hat().unwrap_or(0.0),
            mean_l: self.mean_l().unwrap_or(0.0),
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    fn feed(c: &mut RecurrentSetCertifier, xs: &[f64]) {
        for &x in xs {
            c.observe(x);
        }
    }

    #[test]
    fn too_few_samples_is_unknown_and_not_governed() {
        let mut c = RecurrentSetCertifier::new();
        c.observe(0.1);
        assert_eq!(c.regime(), Regime::Unknown);
        assert!(!c.governed(true)); // fail-closed
        assert!(c.mean_dl().is_none());
    }

    #[test]
    fn decreasing_L_above_core_is_contracting_and_governed() {
        let mut c = RecurrentSetCertifier::with_params(16, 1e-3, 0.5);
        // L well above core (0.5), strictly decreasing → contracting toward R
        feed(&mut c, &[0.95, 0.90, 0.85, 0.80, 0.75, 0.70]);
        assert_eq!(c.regime(), Regime::ContractingToR);
        assert!(c.governed(true));
        assert!(c.epsilon_hat().unwrap() > 0.0); // ε>0 (contraction)
        assert!(c.mean_dl().unwrap() < 0.0);
    }

    #[test]
    fn flat_low_L_is_in_recurrent_set_and_governed() {
        let mut c = RecurrentSetCertifier::with_params(16, 1e-2, 0.5);
        // small fluctuations around 0.1 (inside core) — note one tick rises (allowed in R)
        feed(&mut c, &[0.10, 0.11, 0.09, 0.12, 0.10, 0.11]);
        assert_eq!(c.regime(), Regime::InRecurrentSet);
        assert!(c.governed(true));
    }

    #[test]
    fn rising_L_above_core_is_diverging_and_not_governed() {
        let mut c = RecurrentSetCertifier::with_params(16, 1e-3, 0.5);
        // above core AND increasing → recurrent set drifting → degrade
        feed(&mut c, &[0.55, 0.62, 0.70, 0.78, 0.86, 0.94]);
        assert_eq!(c.regime(), Regime::Diverging);
        assert!(!c.governed(true));
        assert_eq!(c.epsilon_hat().unwrap(), 0.0); // no contraction when rising
    }

    #[test]
    fn in_omega_false_is_never_governed() {
        let mut c = RecurrentSetCertifier::with_params(16, 1e-2, 0.5);
        feed(&mut c, &[0.10, 0.10, 0.10, 0.10]); // perfectly in R
        assert_eq!(c.regime(), Regime::InRecurrentSet);
        assert!(c.governed(true));
        assert!(!c.governed(false)); // Ω clause dominates
    }

    #[test]
    fn stationary_fluctuation_inside_R_with_positive_drift_still_governed() {
        // Ax_RecurrentSet: inside R, E[ΔL] > 0 is allowed (alive). Mean L stays < core.
        let mut c = RecurrentSetCertifier::with_params(16, 1e-4, 0.5);
        feed(&mut c, &[0.20, 0.22, 0.24, 0.26]); // rising but mean (0.23) < core
        assert!(c.mean_dl().unwrap() > 0.0);       // positive drift
        assert_eq!(c.regime(), Regime::InRecurrentSet);
        assert!(c.governed(true));                 // still governed (fluctuation in R)
    }

    #[test]
    fn lambda_hat_is_max_single_step() {
        let mut c = RecurrentSetCertifier::with_params(16, 1e-3, 0.5);
        feed(&mut c, &[0.10, 0.12, 0.50, 0.51]); // biggest jump 0.12→0.50 = 0.38
        assert!((c.lambda_hat().unwrap() - 0.38).abs() < 1e-9);
    }

    #[test]
    fn window_evicts_oldest() {
        let mut c = RecurrentSetCertifier::with_params(3, 1e-3, 0.5);
        feed(&mut c, &[1.0, 2.0, 3.0, 4.0]);
        assert_eq!(c.samples(), 3); // capped at 3
    }
}
