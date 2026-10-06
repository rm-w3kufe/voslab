// adaptive_clock.rs — F5.x.3 — σ-adaptive tick clock (SeqLock σ_global + staleness bound)
//
// Implements: docs/theory/dynamics_choice.vsm §T4
//
//   Def_SeqLockσ:    atomic sequence counter + σ_global; readers retry on mismatch →
//                    linearizable read of max_i(σ_i) without a mutex. Single-writer per
//                    σ_i slot (each worker owns its slot); the reader is this clock.
//   Bound_Staleness: |σ(t₁)-σ(t₀)| ≤ 2·Λ·Δt_max and Lyapunov violation ≤ ½‖∇²L‖(2ΛΔt_max)²
//                    ⇒ Δt_max ≤ √(ε/‖∇²L‖)/Λ.
//   tick law:        Δt = C/(1+σ²)  (σ↑ ⇒ faster ticks), clamped to the lifecycle band.
//   lifecycle modes: Idle 0.5 Hz | Active 100 Hz | Transition (ramp between).
//   T4.sub1:         reader retries are counted (retry_rate); if > 5% under load, escalate
//                    the σ_global path to RCU (decision deferred to profiling, per spec).
//
// Lock-free, stdlib-only (no `crossbeam`). ε and Λ come from F5.x.2 lyapunov.rs.
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use std::sync::atomic::{AtomicU64, Ordering};

/// Idle tick rate (Hz) → max Δt.
pub const IDLE_HZ: f64 = 0.5;
/// Active tick rate (Hz) → min Δt.
pub const ACTIVE_HZ: f64 = 100.0;

/// Lifecycle-driven clock mode (maps from StateVector LIFECYCLE ∈ {0.2..1.0}).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockMode {
    Idle,       // exploration / onboarding — 0.5 Hz
    Transition, // ramp
    Active,     // production — 100 Hz
}

impl ClockMode {
    /// Map lifecycle ∈ [0,1] → mode. ≤0.3 Idle, ≥0.9 Active, else Transition.
    pub fn from_lifecycle(lifecycle: f64) -> Self {
        if lifecycle <= 0.3 {
            ClockMode::Idle
        } else if lifecycle >= 0.9 {
            ClockMode::Active
        } else {
            ClockMode::Transition
        }
    }

    /// (min_dt, max_dt) seconds for this mode. Active is fastest (smallest Δt).
    pub fn dt_bounds(&self) -> (f64, f64) {
        let active_dt = 1.0 / ACTIVE_HZ; // 0.01 s
        let idle_dt = 1.0 / IDLE_HZ; // 2.0 s
        match self {
            ClockMode::Active => (active_dt, active_dt * 10.0), // 0.01..0.1
            ClockMode::Idle => (idle_dt / 2.0, idle_dt),        // 1.0..2.0
            ClockMode::Transition => (active_dt * 10.0, idle_dt / 2.0), // 0.1..1.0
        }
    }
}

/// Δt = C/(1+σ²). Higher σ (instability) ⇒ shorter tick (faster regulation).
pub fn dt_from_sigma(c: f64, sigma: f64) -> f64 {
    c / (1.0 + sigma * sigma)
}

/// Bound_Staleness: Δt_max ≤ √(ε/‖∇²L‖)/Λ. Returns ∞ when Λ→0 (no Lipschitz pressure)
/// or hessian_norm→0; returns 0 when ε≤0 (no contraction margin → must tick immediately).
pub fn dt_staleness_bound(epsilon: f64, hessian_norm: f64, lambda: f64) -> f64 {
    if epsilon <= 0.0 {
        return 0.0;
    }
    if hessian_norm <= 0.0 || lambda <= 0.0 {
        return f64::INFINITY;
    }
    (epsilon / hessian_norm).sqrt() / lambda
}

/// SeqLock-protected σ_global = max_i(σ_i) over per-worker slots (Def_SeqLockσ).
/// Each worker owns one slot (single-writer); the reader takes the max with a
/// generation-stamped retry so the read is linearizable without a mutex.
pub struct AdaptiveClock {
    /// Per-worker σ_i as f64 bits (single-writer each).
    slots: Vec<AtomicU64>,
    /// Sequence/generation counter — bumped on every slot write (the SeqLock seq).
    generation: AtomicU64,
    /// Reader-retry counter (T4.sub1 contention profiling).
    reads: AtomicU64,
    retries: AtomicU64,
}

impl AdaptiveClock {
    /// One slot per worker thread.
    pub fn new(n_workers: usize) -> Self {
        let n = n_workers.max(1);
        let mut slots = Vec::with_capacity(n);
        for _ in 0..n {
            slots.push(AtomicU64::new(0.0f64.to_bits()));
        }
        AdaptiveClock {
            slots,
            generation: AtomicU64::new(0),
            reads: AtomicU64::new(0),
            retries: AtomicU64::new(0),
        }
    }

    pub fn n_slots(&self) -> usize {
        self.slots.len()
    }

    /// Single-writer update of worker `i`'s σ_i. Releases the value, then bumps the
    /// generation so concurrent readers re-check (SeqLock write side).
    pub fn set_sigma(&self, i: usize, sigma: f64) {
        if let Some(slot) = self.slots.get(i) {
            slot.store(sigma.max(0.0).to_bits(), Ordering::Release);
            self.generation.fetch_add(1, Ordering::Release);
        }
    }

    /// Linearizable read of σ_global = max_i(σ_i) (Def_SeqLockσ). Reads the generation,
    /// scans all slots, re-reads the generation; if it changed, a concurrent write
    /// occurred → retry. Counts reads/retries for T4.sub1.
    pub fn sigma_global(&self) -> f64 {
        self.reads.fetch_add(1, Ordering::Relaxed);
        loop {
            let g0 = self.generation.load(Ordering::Acquire);
            let mut max = 0.0f64;
            for slot in &self.slots {
                let v = f64::from_bits(slot.load(Ordering::Acquire));
                if v > max {
                    max = v;
                }
            }
            let g1 = self.generation.load(Ordering::Acquire);
            if g0 == g1 {
                return max;
            }
            self.retries.fetch_add(1, Ordering::Relaxed);
        }
    }

    /// Fraction of reads that needed ≥1 retry-iteration (T4.sub1: escalate to RCU if > 0.05).
    pub fn retry_rate(&self) -> f64 {
        let reads = self.reads.load(Ordering::Relaxed);
        if reads == 0 {
            return 0.0;
        }
        self.retries.load(Ordering::Relaxed) as f64 / reads as f64
    }

    /// Recommended tick Δt: the σ-adaptive law, capped by the staleness bound, then
    /// clamped to the lifecycle mode's [min,max]. `c` is the base time-constant.
    pub fn recommended_dt(
        &self,
        c: f64,
        mode: ClockMode,
        epsilon: f64,
        hessian_norm: f64,
        lambda: f64,
    ) -> f64 {
        let sigma = self.sigma_global();
        let dt_sigma = dt_from_sigma(c, sigma);
        let dt_bound = dt_staleness_bound(epsilon, hessian_norm, lambda);
        let (lo, hi) = mode.dt_bounds();
        dt_sigma.min(dt_bound).clamp(lo, hi)
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[test]
    fn dt_from_sigma_monotone() {
        assert!((dt_from_sigma(1.0, 0.0) - 1.0).abs() < 1e-12); // σ=0 → C
        assert!(dt_from_sigma(1.0, 2.0) < dt_from_sigma(1.0, 1.0)); // σ↑ → Δt↓
        assert!((dt_from_sigma(1.0, 1.0) - 0.5).abs() < 1e-12); // 1/(1+1)=0.5
    }

    #[test]
    fn staleness_bound_formula_and_edges() {
        // ε=4, ‖∇²L‖=1, Λ=2 → √4 / 2 = 1.0
        assert!((dt_staleness_bound(4.0, 1.0, 2.0) - 1.0).abs() < 1e-12);
        assert_eq!(dt_staleness_bound(0.0, 1.0, 1.0), 0.0); // no margin → tick now
        assert_eq!(dt_staleness_bound(1.0, 0.0, 1.0), f64::INFINITY); // no hessian
        assert_eq!(dt_staleness_bound(1.0, 1.0, 0.0), f64::INFINITY); // no Lipschitz
    }

    #[test]
    fn clock_mode_from_lifecycle() {
        assert_eq!(ClockMode::from_lifecycle(0.2), ClockMode::Idle);
        assert_eq!(ClockMode::from_lifecycle(0.5), ClockMode::Transition);
        assert_eq!(ClockMode::from_lifecycle(1.0), ClockMode::Active);
    }

    #[test]
    fn sigma_global_is_max_over_slots() {
        let clk = AdaptiveClock::new(4);
        clk.set_sigma(0, 0.3);
        clk.set_sigma(1, 0.9);
        clk.set_sigma(2, 0.1);
        clk.set_sigma(3, 0.5);
        assert!((clk.sigma_global() - 0.9).abs() < 1e-12);
    }

    #[test]
    fn set_sigma_clamps_negative_and_ignores_oob() {
        let clk = AdaptiveClock::new(2);
        clk.set_sigma(0, -5.0); // clamped to 0
        clk.set_sigma(99, 1.0); // out of bounds → ignored
        assert_eq!(clk.sigma_global(), 0.0);
    }

    #[test]
    fn recommended_dt_clamped_to_mode_band() {
        let clk = AdaptiveClock::new(1);
        clk.set_sigma(0, 0.0); // dt_sigma = C
        // "no staleness pressure" = Δt_max ∞ via hessian_norm=0 (NOT epsilon=0, which
        // means "no contraction margin → tick now"). Active band 0.01..0.1; C=10 → clamp 0.1.
        let dt = clk.recommended_dt(10.0, ClockMode::Active, 1.0, 0.0, 0.0);
        assert!((dt - 0.1).abs() < 1e-12);
        // Idle band 1.0..2.0; tiny C clamps up to 1.0
        let dt2 = clk.recommended_dt(0.001, ClockMode::Idle, 1.0, 0.0, 0.0);
        assert!((dt2 - 1.0).abs() < 1e-12);
    }

    #[test]
    fn staleness_bound_can_force_faster_tick() {
        let clk = AdaptiveClock::new(1);
        clk.set_sigma(0, 0.0);
        // ε small, Λ large → tiny Δt_max → recommended_dt hits the staleness bound
        // (then clamped to the Active floor 0.01).
        let dt = clk.recommended_dt(10.0, ClockMode::Active, 1e-6, 1.0, 1000.0);
        assert!((dt - 0.01).abs() < 1e-12); // clamped to Active min
    }

    #[test]
    fn retry_rate_zero_without_contention() {
        let clk = AdaptiveClock::new(2);
        clk.set_sigma(0, 0.5);
        let _ = clk.sigma_global();
        assert_eq!(clk.retry_rate(), 0.0);
    }

    #[test]
    fn concurrent_writers_reader_sees_a_valid_max() {
        // Lock-free smoke test: writers hammer their own slots, reader takes max.
        let clk = Arc::new(AdaptiveClock::new(4));
        let mut handles = Vec::new();
        for i in 0..4 {
            let c = Arc::clone(&clk);
            handles.push(std::thread::spawn(move || {
                for k in 0..1000 {
                    c.set_sigma(i, (i as f64) * 0.1 + (k % 7) as f64 * 0.001);
                }
            }));
        }
        // concurrent reads must never panic and stay within [0, max possible].
        for _ in 0..2000 {
            let g = clk.sigma_global();
            assert!(g >= 0.0 && g <= 3.0 + 0.01);
        }
        for h in handles {
            h.join().unwrap();
        }
        // final max ≈ slot 3 base 0.3 + up to 0.006
        let g = clk.sigma_global();
        assert!(g >= 0.3 && g <= 0.31);
    }
}
