// attractor.rs — Lyapunov convergence tracking for vOS kernels
// Spec: docs/vos_attractor_theory.vsm + docs/vos_kernel_spec.vsm §4
// Watermark: ⟦ vsf-nucleus | rmw3 | vsm-0.3 ⟧

use crate::state_vector::{StateVector, StasisVec};

/// LyapunovTracker: tracks L(x) per breath cycle and detects convergence.
///
/// Per vos_attractor_theory.vsm:
///   L(x) = 0.5·(1-cos(x,stasis)) + 0.3·H(x)/H_max + 0.2·max(0, overrun)
///   convergence: E[dL/dt] ≤ 0 per breath cycle
///
/// A kernel is converging to its attractor when successive soplo events
/// reduce L(x) on average — i.e. the running mean of ΔL_cycle is ≤ 0.
pub struct LyapunovTracker {
    /// L(x) recorded at the end of each completed breath cycle
    cycle_values: Vec<f64>,

    /// Running sum of ΔL across cycles (for running mean)
    delta_sum: f64,

    /// Minimum cycles required before declaring convergence
    pub min_cycles: usize,

    /// D_KY per cycle (fractal dimension estimate)
    dky_values: Vec<f64>,

    /// H_stasis per cycle (H(t) at stasis entry)
    h_stasis_values: Vec<f64>,
}

impl LyapunovTracker {
    pub fn new() -> Self {
        LyapunovTracker {
            cycle_values:    Vec::new(),
            delta_sum:       0.0,
            min_cycles:      3,   // need ≥3 cycles for meaningful convergence signal
            dky_values:      Vec::new(),
            h_stasis_values: Vec::new(),
        }
    }

    /// Record L(x) at the end of a breath cycle (called on soplo event).
    /// Returns (dL, running_mean_dL, converged).
    pub fn record_cycle(
        &mut self,
        sv:           &StateVector,
        stasis:       &StasisVec,
        h_max:        f64,
        budget_overrun: f64,
        d_ky:         f64,
        h_stasis:     f64,
    ) -> CycleRecord {
        let l = sv.lyapunov(stasis, h_max, budget_overrun);
        self.dky_values.push(d_ky);
        self.h_stasis_values.push(h_stasis);

        let (dl, mean_dl) = if let Some(&prev_l) = self.cycle_values.last() {
            let dl = l - prev_l;
            self.delta_sum += dl;
            let mean = self.delta_sum / self.cycle_values.len() as f64;
            (dl, mean)
        } else {
            (0.0, 0.0)
        };

        self.cycle_values.push(l);

        let converged = self.is_converged();
        let growth    = self.detect_growth();

        CycleRecord {
            cycle:    self.n_cycles(),
            l,
            dl,
            mean_dl,
            converged,
            growth,
        }
    }

    /// is_converged: E[dL/dt] ≤ 0 with ≥ min_cycles completed
    /// per vos_attractor_theory.vsm: convergence: E[dL/dt] ≤ 0 per cycle
    pub fn is_converged(&self) -> bool {
        if self.n_cycles() < self.min_cycles { return false; }
        let n = (self.cycle_values.len() - 1) as f64;  // number of deltas
        if n < 1.0 { return false; }
        (self.delta_sum / n) <= 0.0
    }

    /// detect_growth: A_auto growth criterion
    /// growth(V) = H(stasis_new) < H(stasis_old) ∧ D_KY_new ≥ D_KY_old
    /// per vos_attractor_theory.vsm A_auto
    pub fn detect_growth(&self) -> bool {
        let n = self.cycle_values.len();
        if n < 2 { return false; }
        let h_new  = self.h_stasis_values[n - 1];
        let h_old  = self.h_stasis_values[n - 2];
        let dky_new = self.dky_values[n - 1];
        let dky_old = self.dky_values[n - 2];
        h_new < h_old && dky_new >= dky_old
    }

    pub fn n_cycles(&self) -> usize {
        self.cycle_values.len()
    }

    pub fn last_l(&self) -> Option<f64> {
        self.cycle_values.last().copied()
    }

    /// running_mean_dl: E[dL/dt] across all cycles
    pub fn running_mean_dl(&self) -> f64 {
        let n = self.cycle_values.len().saturating_sub(1);
        if n == 0 { return 0.0; }
        self.delta_sum / n as f64
    }

    /// trajectory: all recorded L values (for plotting / telemetry)
    pub fn trajectory(&self) -> &[f64] {
        &self.cycle_values
    }

    /// summary: human-readable state
    pub fn summary(&self) -> String {
        let n = self.n_cycles();
        if n == 0 {
            return "no cycles yet".to_string();
        }
        let last_l = self.last_l().unwrap_or(0.0);
        let mdl    = self.running_mean_dl();
        let conv   = if self.is_converged() { "CONVERGING" } else { "not yet" };
        format!("n={} L={:.4} mean_dL={:.5} convergence={}", n, last_l, mdl, conv)
    }
}

impl Default for LyapunovTracker {
    fn default() -> Self { Self::new() }
}

// ─────────────────────────────────────────────────────────────────────────────
// CycleRecord — result of one record_cycle() call
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct CycleRecord {
    pub cycle:     usize,
    pub l:         f64,    // L(x) this cycle
    pub dl:        f64,    // L(x) - L(x-1)
    pub mean_dl:   f64,    // E[dL/dt] running mean
    pub converged: bool,   // E[dL/dt] ≤ 0 ∧ n ≥ min_cycles
    pub growth:    bool,   // A_auto growth criterion met
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn mock_sv_with_h(h_normalized: f64) -> (StateVector, StasisVec) {
        let mut sv     = StateVector::new();
        let mut stasis = StasisVec::new();
        // set H_T dim (dim 24) so lyapunov has something to work with
        sv.dims[state_vector::H_T]  = h_normalized;
        sv.dims[0]                  = 1.0 - h_normalized;  // opposing dim for contrast
        stasis.observe(&sv);
        // cos(sv, stasis.current) = 1.0 (identical) → L = 0.3*h_normalized
        (sv, stasis)
    }

    use crate::state_vector;

    #[test]
    fn no_convergence_before_min_cycles() {
        let mut tracker = LyapunovTracker::new();
        tracker.min_cycles = 3;

        let (sv, stasis) = mock_sv_with_h(0.2);
        for _ in 0..2 {
            tracker.record_cycle(&sv, &stasis, 1.0, 0.0, 3.0, 0.4);
        }
        assert!(!tracker.is_converged(), "need ≥3 cycles");
    }

    #[test]
    fn converges_when_dl_negative() {
        let mut tracker = LyapunovTracker::new();
        tracker.min_cycles = 3;

        // decreasing L values: 0.5 → 0.4 → 0.3
        // We need to control L directly, so we'll use different sv configs
        let h_max = 2.0;

        // cycle 1: high entropy → high L
        let (sv1, stasis1) = mock_sv_with_h(0.8);
        tracker.record_cycle(&sv1, &stasis1, h_max, 0.0, 3.0, 0.8);

        // cycle 2: medium
        let (sv2, stasis2) = mock_sv_with_h(0.5);
        tracker.record_cycle(&sv2, &stasis2, h_max, 0.0, 3.5, 0.5);

        // cycle 3: low entropy → L smaller
        let (sv3, stasis3) = mock_sv_with_h(0.2);
        let rec = tracker.record_cycle(&sv3, &stasis3, h_max, 0.0, 4.0, 0.2);

        // mean_dL should be ≤ 0 (decreasing L across cycles)
        assert!(rec.mean_dl <= 0.0,
            "mean_dL should be ≤ 0 for decreasing L, got {}", rec.mean_dl);
        assert!(rec.converged, "should be converging after 3 cycles with decreasing L");
    }

    #[test]
    fn not_converged_when_dl_positive() {
        let mut tracker = LyapunovTracker::new();
        let h_max = 2.0;

        // increasing L: low → high entropy (diverging)
        let (sv1, stasis1) = mock_sv_with_h(0.1);
        tracker.record_cycle(&sv1, &stasis1, h_max, 0.0, 4.0, 0.1);

        let (sv2, stasis2) = mock_sv_with_h(0.5);
        tracker.record_cycle(&sv2, &stasis2, h_max, 0.0, 3.5, 0.5);

        let (sv3, stasis3) = mock_sv_with_h(0.9);
        let rec = tracker.record_cycle(&sv3, &stasis3, h_max, 0.0, 3.0, 0.9);

        assert!(rec.mean_dl > 0.0, "mean_dL should be > 0 for increasing L");
        assert!(!rec.converged, "should not converge with increasing L");
    }

    #[test]
    fn growth_detected_when_h_drops_dky_rises() {
        let mut tracker = LyapunovTracker::new();
        let (sv, stasis) = mock_sv_with_h(0.5);
        let h_max = 1.0;

        // cycle 1: H=0.8, D_KY=3.0
        tracker.record_cycle(&sv, &stasis, h_max, 0.0, 3.0, 0.8);
        // cycle 2: H=0.6 (< 0.8), D_KY=3.5 (> 3.0) → growth!
        let rec = tracker.record_cycle(&sv, &stasis, h_max, 0.0, 3.5, 0.6);

        assert!(rec.growth, "growth should be detected: H dropped, D_KY rose");
    }

    #[test]
    fn no_growth_when_h_rises() {
        let mut tracker = LyapunovTracker::new();
        let (sv, stasis) = mock_sv_with_h(0.5);
        let h_max = 1.0;

        tracker.record_cycle(&sv, &stasis, h_max, 0.0, 3.0, 0.4);
        let rec = tracker.record_cycle(&sv, &stasis, h_max, 0.0, 3.5, 0.8);  // H rose

        assert!(!rec.growth, "growth should not be detected when H rises");
    }

    #[test]
    fn trajectory_length_matches_cycles() {
        let mut tracker = LyapunovTracker::new();
        let (sv, stasis) = mock_sv_with_h(0.3);

        for _ in 0..5 {
            tracker.record_cycle(&sv, &stasis, 1.0, 0.0, 3.0, 0.3);
        }
        assert_eq!(tracker.trajectory().len(), 5);
        assert_eq!(tracker.n_cycles(), 5);
    }

    #[test]
    fn summary_is_nonempty_after_cycles() {
        let mut tracker = LyapunovTracker::new();
        assert_eq!(tracker.summary(), "no cycles yet");

        let (sv, stasis) = mock_sv_with_h(0.3);
        tracker.record_cycle(&sv, &stasis, 1.0, 0.0, 3.0, 0.3);
        assert!(tracker.summary().contains("n=1"));
    }
}
