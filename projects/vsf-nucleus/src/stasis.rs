/// stasis.rs — stasis_boot / stasis_drain signal conditions
///
/// @vsm 0.3  S3*(vsf-nucleus).stasis_signals  @status=iterating
///
/// Implements P10 from ChatGPT integration analysis:
///   stasis_boot(L)  — L is ready to accept child launches
///   stasis_drain(L) — L is ready to shut down cleanly
///
/// Stasis is not a passive condition — it is an active declaration.
/// L3 emits φ↑("stasis_boot") when the conditions hold.
/// L4 must wait for this signal before starting its own init.
///
/// P10 key addition: trust_variation < δ as stasis_drain condition.
/// Without it: L could declare stasis with trust oscillating → L4 starts unstable.

use crate::kernel::KernelState;

// ── Thresholds ────────────────────────────────────────────────────────────────

/// Maximum entropy for stasis_boot — kernel must be quiet before signaling ready
pub const EPSILON_BOOT:   f64 = 0.10;

/// Minimum trust for stasis_boot — kernel must be minimally governed
pub const TAU_BOOT:       f64 = 0.40;

/// Maximum trust variation between ticks for stasis_drain  [P10]
pub const DELTA_TRUST:    f64 = 0.05;


// ── stasis_boot ───────────────────────────────────────────────────────────────

/// stasis_boot(L) = entropy(L) < ε_L ∧ trust(L) ≥ τ_boot ∧ φ↑(L).active
///
/// Returns true when the kernel is stable enough to signal readiness to L+1.
pub fn stasis_boot(state: &KernelState) -> bool {
    state.active
        && state.entropy < EPSILON_BOOT
        && state.trust   >= TAU_BOOT
}


// ── stasis_drain ──────────────────────────────────────────────────────────────

/// Input to stasis_drain check — collects the conditions that cannot be
/// derived purely from KernelState (trust variation, child states).
pub struct StasisDrainInput {
    /// No pending tasks in S1
    pub pending_tasks:      usize,
    /// Telemetry buffer fully flushed (async_buffered_write complete)
    pub telemetry_flushed:  bool,
    /// |trust(t) - trust(t-1)| — trust must be stable before draining  [P10]
    pub trust_variation:    f64,
    /// All children are idle or already drained  [P10]
    pub all_children_idle:  bool,
}

/// stasis_drain(L) conditions [P10]:
///   pending = ∅ ∧ telemetry_flushed ∧ φ↑.stable_rate < ε
///            ∧ trust_variation < δ ∧ all_children ∈ {idle, drained}
///
/// trust_variation < δ is the critical addition from ChatGPT-B:
///   without it, a kernel with oscillating trust could start the drain sequence
///   while still unstable, causing L4 (which just launched) to see inconsistent state.
pub fn stasis_drain(input: &StasisDrainInput) -> bool {
    input.pending_tasks   == 0
        && input.telemetry_flushed
        && input.trust_variation < DELTA_TRUST
        && input.all_children_idle
}


// ── StasisTracker ─────────────────────────────────────────────────────────────

/// Tracks trust variation between ticks to compute stasis_drain condition.
///
/// Usage:
///   let mut tracker = StasisTracker::new(initial_trust);
///   on each tick: tracker.update(current_trust);
///   stasis_drain condition: tracker.variation() < DELTA_TRUST
pub struct StasisTracker {
    prev_trust: f64,
    pub variation: f64,
}

impl StasisTracker {
    pub fn new(initial_trust: f64) -> Self {
        StasisTracker { prev_trust: initial_trust, variation: 0.0 }
    }

    pub fn update(&mut self, current_trust: f64) {
        self.variation = (current_trust - self.prev_trust).abs();
        self.prev_trust = current_trust;
    }
}
