// state_vector.rs — ℝ¹²⁸ kernel state representation
// Spec: docs/vos_kernel_spec.vsm §3 + docs/vos_theory.vsm
// Watermark: ⟦ vsf-nucleus | rmw3 | vsm-0.3 ⟧

/// StateVector: 128-dimensional float vector encoding full kernel state.
///
/// Blocks:
///   A (0..15)   — health: trust history, error rate, governed, lifecycle
///   B (16..23)  — resources: cpu/mem/io pressure, budget, queues
///   C (24..31)  — entropy & cycle: H(t), phase, stasis_cos, N_cycles
///   D (32..47)  — organelle activations (4 initial + 12 reserved)
///   E (48..63)  — VSL signals: φ↑/φ↓ rates, algedonic, ψ, escalation
///   F (64..95)  — attractors: stasis_vec_prev [64..79] + stasis_vec_curr [80..95]
///   G (96..127) — learning: V_ref state, Δ|pattern|, λ, RAP
#[derive(Clone, Debug)]
pub struct StateVector {
    pub dims: [f64; 128],
}

// ── Block A indices — health (0..15) ─────────────────────────────────────────
pub const TRUST_HIST_0:  usize = 0;   // trust_history(t-9..t), indices 0..9
pub const TRUST_HIST_9:  usize = 9;
pub const DTRUST:        usize = 10;  // d/dt[trust]
pub const ERROR_RATE:    usize = 11;  // error_rate(S2)
pub const ABSORPTION:    usize = 12;  // absorption_rate
pub const GOVERNED:      usize = 13;  // ∈ {0.0, 1.0}
pub const DEPTH:         usize = 14;  // recursion_depth (normalized)
pub const LIFECYCLE:     usize = 15;  // ∈ {0.2 onboarding, 0.5 iterating, 0.7 testing, 1.0 production}

// ── Block B indices — resources (16..23) ─────────────────────────────────────
pub const CPU_PRESSURE:   usize = 16;  // ∈ [0,1]
pub const MEM_PRESSURE:   usize = 17;  // ∈ [0,1]
pub const IO_PRESSURE:    usize = 18;  // ∈ [0,1]
pub const BUDGET:         usize = 19;  // budget_remaining (normalized)
pub const CGROUP_HEADROOM: usize = 20; // cgroup_headroom (normalized)
pub const CHILD_COUNT:    usize = 21;  // child_count_normalized
pub const QUEUE_PHI_UP:   usize = 22;  // queue_depth_φ↑ (normalized)
pub const QUEUE_PHI_DOWN: usize = 23;  // queue_depth_φ↓ (normalized)

// ── Block C indices — entropy & cycle (24..31) ────────────────────────────────
pub const H_T:           usize = 24;  // H(t) — current Shannon entropy
pub const H_REST:        usize = 25;  // H_rest — resting entropy
pub const DH:            usize = 26;  // H(t) - H_rest
pub const ENTROPY_PHASE: usize = 27;  // stasis=0.0, inhale=0.5, degen=1.0
pub const STASIS_COS:    usize = 28;  // cosine(state, stasis_vec)
pub const SOPLO_ACTIVE:  usize = 29;  // ∈ {0.0, 1.0}
pub const N_CYCLES:      usize = 30;  // log(N_cycles+1) / log(100) — normalized
pub const TICKS_GROWTH:  usize = 31;  // ticks_since_last_growth (normalized / 1000)

// ── Block D indices — organelles (32..47) ─────────────────────────────────────
pub const ORGANELLE_MEM_MGR:    usize = 32;
pub const ORGANELLE_IO_ROUTER:  usize = 33;
pub const ORGANELLE_SIG_RELAY:  usize = 34;
pub const ORGANELLE_SCHEDULER:  usize = 35;
// [36..47] reserved for future organelles

// ── Block E indices — VSL signals (48..63) ───────────────────────────────────
pub const PHI_UP_RATE:   usize = 48;
pub const PHI_DOWN_RATE: usize = 49;
pub const ALGEDONIC:     usize = 50;  // ∈ {0.0, 1.0}
pub const PSI_ACTIVE:    usize = 51;  // ∈ {0.0, 1.0}
pub const ESCALATION:         usize = 52;
pub const PURPOSE_PROHIBITED: usize = 53;  // A0:   purpose∩prohibited = ∅ iff dim=0  (S5 ethics wire)
pub const COERCION_INDICATOR: usize = 54;  // A0.1: no coercion          iff dim=0  (S5 ethics wire)
// [55..63] reserved

// ── Block F indices — attractors (64..95) ────────────────────────────────────
pub const STASIS_PREV_START: usize = 64;  // stasis_vec_prev  [64..79] 16-dim
pub const STASIS_CURR_START: usize = 80;  // stasis_vec_curr  [80..95] 16-dim

// ── Block G indices — learning (96..127) ─────────────────────────────────────
pub const VREF_START:    usize = 96;   // V_ref.state_compressed [96..111]
pub const DELTA_PATTERN: usize = 112;  // |state_vec(V_vos) - state_vec(V_ref)|
pub const LEARNING_RATE: usize = 113;
pub const EXPERIMENT:    usize = 114;  // experiment_active ∈ {0.0, 1.0}
pub const LAMBDA:        usize = 115;  // λ_current (Lyapunov max exponent)
pub const RAP_START:     usize = 116;  // RAP_activation_pattern [116..127]

impl StateVector {
    pub fn new() -> Self {
        StateVector { dims: [0.0; 128] }
    }

    /// cosine_similarity: O(128) dot product — core viability metric
    pub fn cosine_similarity(&self, other: &StateVector) -> f64 {
        let dot: f64 = self.dims.iter().zip(other.dims.iter()).map(|(a, b)| a * b).sum();
        let norm_a: f64 = self.dims.iter().map(|x| x * x).sum::<f64>().sqrt();
        let norm_b: f64 = other.dims.iter().map(|x| x * x).sum::<f64>().sqrt();
        if norm_a < 1e-10 || norm_b < 1e-10 {
            return 0.0;
        }
        (dot / (norm_a * norm_b)).clamp(-1.0, 1.0)
    }

    /// viable(V,t) = cosine(state_vec, stasis_vec) ≥ 0.70 ∧ H(t) ≤ H_max
    /// per vos_kernel_spec.vsm §8
    pub fn viable(&self, stasis: &StasisVec, h_max: f64) -> bool {
        let cos = self.cosine_similarity(&stasis.current);
        let h_t = self.dims[H_T];
        cos >= 0.70 && h_t <= h_max
    }

    /// L(x) = 0.5·(1 - cos(x,stasis)) + 0.3·H(x)/H_max + 0.2·max(0, overrun)
    /// per vos_attractor_theory.vsm — Lyapunov function
    pub fn lyapunov(&self, stasis: &StasisVec, h_max: f64, budget_overrun: f64) -> f64 {
        let cos = self.cosine_similarity(&stasis.current);
        let h_t = self.dims[H_T];
        0.5 * (1.0 - cos) + 0.3 * (h_t / h_max) + 0.2 * budget_overrun.max(0.0)
    }

    /// Update Block A from kernel state
    /// trust_history: ring buffer — shifts [0..8] ← [1..9], writes trust to [9]
    pub fn update_block_a(
        &mut self,
        trust:      f64,
        prev_trust: f64,
        error_rate: f64,
        absorption: f64,
        governed:   bool,
        depth:      usize,
        lifecycle:  f64,
    ) {
        // shift trust history ring
        for i in TRUST_HIST_0..TRUST_HIST_9 {
            self.dims[i] = self.dims[i + 1];
        }
        self.dims[TRUST_HIST_9] = trust;
        self.dims[DTRUST]    = trust - prev_trust;
        self.dims[ERROR_RATE] = error_rate;
        self.dims[ABSORPTION] = absorption;
        self.dims[GOVERNED]   = if governed { 1.0 } else { 0.0 };
        self.dims[DEPTH]      = (depth as f64 / 16.0).min(1.0);  // normalize depth ≤ 16
        self.dims[LIFECYCLE]  = lifecycle;
    }

    /// Update Block B from resource readings
    pub fn update_block_b(
        &mut self,
        cpu:           f64,
        mem:           f64,
        io:            f64,
        budget:        f64,
        cgroup_head:   f64,
        children:      usize,
        queue_up:      usize,
        queue_down:    usize,
    ) {
        self.dims[CPU_PRESSURE]    = cpu.clamp(0.0, 1.0);
        self.dims[MEM_PRESSURE]    = mem.clamp(0.0, 1.0);
        self.dims[IO_PRESSURE]     = io.clamp(0.0, 1.0);
        self.dims[BUDGET]          = budget.clamp(0.0, 1.0);
        self.dims[CGROUP_HEADROOM] = cgroup_head.clamp(0.0, 1.0);
        self.dims[CHILD_COUNT]     = (children as f64 / 256.0).min(1.0);
        self.dims[QUEUE_PHI_UP]    = (queue_up as f64 / 1000.0).min(1.0);
        self.dims[QUEUE_PHI_DOWN]  = (queue_down as f64 / 1000.0).min(1.0);
    }

    /// Update Block C from entropy state
    pub fn update_block_c(
        &mut self,
        h_t:          f64,
        h_rest:       f64,
        h_max:        f64,
        phase:        EntropyPhase,
        stasis:       &StasisVec,
        soplo_active: bool,
        n_cycles:     u32,
        ticks_growth: u32,
    ) {
        self.dims[H_T]           = h_t / h_max;           // normalize
        self.dims[H_REST]        = h_rest / h_max;
        self.dims[DH]            = (h_t - h_rest) / h_max;
        self.dims[ENTROPY_PHASE] = phase.as_f64();
        self.dims[STASIS_COS]    = self.cosine_similarity(&stasis.current);
        self.dims[SOPLO_ACTIVE]  = if soplo_active { 1.0 } else { 0.0 };
        self.dims[N_CYCLES]      = if n_cycles == 0 { 0.0 } else {
            (n_cycles as f64 + 1.0).ln() / (101.0_f64).ln()  // log(N+1)/log(101)
        };
        self.dims[TICKS_GROWTH]  = (ticks_growth as f64 / 1000.0).min(1.0);
    }

    /// Update Block D from organelle activations (4 values, normalized 0..1)
    pub fn update_block_d(&mut self, activations: &[f64; 4]) {
        self.dims[ORGANELLE_MEM_MGR]   = activations[0].clamp(0.0, 1.0);
        self.dims[ORGANELLE_IO_ROUTER] = activations[1].clamp(0.0, 1.0);
        self.dims[ORGANELLE_SIG_RELAY] = activations[2].clamp(0.0, 1.0);
        self.dims[ORGANELLE_SCHEDULER] = activations[3].clamp(0.0, 1.0);
    }

    /// Update Block E from signal state
    pub fn update_block_e(
        &mut self,
        phi_up_rate:   f64,
        phi_down_rate: f64,
        algedonic:     bool,
        psi_active:    bool,
        escalation:    f64,
    ) {
        self.dims[PHI_UP_RATE]   = phi_up_rate.clamp(0.0, 1.0);
        self.dims[PHI_DOWN_RATE] = phi_down_rate.clamp(0.0, 1.0);
        self.dims[ALGEDONIC]     = if algedonic { 1.0 } else { 0.0 };
        self.dims[PSI_ACTIVE]    = if psi_active { 1.0 } else { 0.0 };
        self.dims[ESCALATION]    = escalation.clamp(0.0, 1.0);
    }

    /// Populate Block G: learning rate + λ_current
    pub fn update_block_g(&mut self, lambda: f64, learning_rate: f64, experiment: bool) {
        self.dims[LAMBDA]        = lambda;
        self.dims[LEARNING_RATE] = learning_rate.clamp(0.0, 1.0);
        self.dims[EXPERIMENT]    = if experiment { 1.0 } else { 0.0 };
    }
}

impl Default for StateVector {
    fn default() -> Self { Self::new() }
}

// ─────────────────────────────────────────────────────────────────────────────
// EntropyPhase
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum EntropyPhase {
    Stasis,   // 0.0
    Inhale,   // 0.5
    Degen,    // 1.0
    Exhale,   // 0.75 — transitional, between degen and stasis
}

impl EntropyPhase {
    pub fn as_f64(self) -> f64 {
        match self {
            EntropyPhase::Stasis => 0.00,
            EntropyPhase::Inhale => 0.50,
            EntropyPhase::Degen  => 1.00,
            EntropyPhase::Exhale => 0.75,
        }
    }

    pub fn from_str(s: &str) -> Self {
        match s {
            "stasis" => EntropyPhase::Stasis,
            "inhale" => EntropyPhase::Inhale,
            "degen"  => EntropyPhase::Degen,
            "exhale" => EntropyPhase::Exhale,
            _        => EntropyPhase::Stasis,
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// StasisVec — running mean of StateVector during stasis phase
// per vos_kernel_spec.vsm §3: stasis_vec(V) = E[state_vector(V,t) | phase=stasis]
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct StasisVec {
    pub current: StateVector,   // E[state | stasis] — current running mean
    pub prev:    StateVector,   // previous stasis attractor
    sum:         [f64; 128],
    n:           u64,
}

impl StasisVec {
    pub fn new() -> Self {
        StasisVec {
            current: StateVector::new(),
            prev:    StateVector::new(),
            sum:     [0.0; 128],
            n:       0,
        }
    }

    /// Observe a state vector during stasis phase — update running mean
    pub fn observe(&mut self, sv: &StateVector) {
        for i in 0..128 {
            self.sum[i] += sv.dims[i];
        }
        self.n += 1;
        self.prev.dims.copy_from_slice(&self.current.dims);
        for i in 0..128 {
            self.current.dims[i] = self.sum[i] / self.n as f64;
        }
    }

    /// Save current as prev (before a soplo event)
    pub fn snapshot_prev(&mut self) {
        self.prev.dims.copy_from_slice(&self.current.dims);
    }

    /// Write current [80..95] and prev [64..79] into stasis_vec's Block F
    /// so the state_vector carries its own attractor history
    pub fn embed_into(&self, sv: &mut StateVector) {
        // compress 128-dim → 16-dim by averaging 8-element windows
        let compressed_curr = compress_16(&self.current.dims);
        let compressed_prev = compress_16(&self.prev.dims);
        sv.dims[STASIS_CURR_START..STASIS_CURR_START + 16]
            .copy_from_slice(&compressed_curr);
        sv.dims[STASIS_PREV_START..STASIS_PREV_START + 16]
            .copy_from_slice(&compressed_prev);
    }

    pub fn n_observations(&self) -> u64 {
        self.n
    }
}

impl Default for StasisVec {
    fn default() -> Self { Self::new() }
}

/// compress 128-dim → 16-dim by averaging 8-element windows
fn compress_16(dims: &[f64; 128]) -> [f64; 16] {
    let mut out = [0.0f64; 16];
    for i in 0..16 {
        let window = &dims[i * 8..(i + 1) * 8];
        out[i] = window.iter().sum::<f64>() / 8.0;
    }
    out
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cosine_identical() {
        let mut sv = StateVector::new();
        sv.dims[0] = 1.0;
        sv.dims[24] = 0.5;
        let cos = sv.cosine_similarity(&sv.clone());
        assert!((cos - 1.0).abs() < 1e-9, "identical vectors must have cosine=1.0, got {}", cos);
    }

    #[test]
    fn cosine_orthogonal() {
        let mut a = StateVector::new();
        let mut b = StateVector::new();
        a.dims[0] = 1.0;
        b.dims[1] = 1.0;
        let cos = a.cosine_similarity(&b);
        assert!(cos.abs() < 1e-9, "orthogonal vectors must have cosine=0.0, got {}", cos);
    }

    #[test]
    fn viable_true_when_converged() {
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();

        // populate a consistent state
        sv.dims[H_T] = 0.4;    // H(t) = 0.4 (below h_max=0.8)
        sv.dims[24..28].copy_from_slice(&[0.4, 0.1, 0.3, 0.0]);
        stasis.observe(&sv);   // stasis_vec = sv → cos = 1.0

        assert!(sv.viable(&stasis, 0.8), "should be viable when cos=1.0 and H≤H_max");
    }

    #[test]
    fn viable_false_when_entropy_high() {
        let mut sv = StateVector::new();
        let stasis = StasisVec::new();  // zero vector

        sv.dims[H_T] = 1.5;  // H(t) > h_max=0.8 (normalized)

        // cos with zero stasis_vec = 0.0 < 0.70
        assert!(!sv.viable(&stasis, 0.8), "should not be viable when cos < 0.70");
    }

    #[test]
    fn lyapunov_zero_at_stasis_low_entropy() {
        let mut sv = StateVector::new();
        let mut stasis = StasisVec::new();
        // H_T = 0 (fully quiescent) + non-zero dim for cosine to work
        sv.dims[H_T] = 0.0;
        sv.dims[0]   = 1.0;  // non-zero so cosine is defined
        stasis.observe(&sv);  // stasis_vec = sv → cosine = 1.0
        // L = 0.5*(1-1.0) + 0.3*(0.0/1.0) + 0.2*0.0 = 0.0
        let l = sv.lyapunov(&stasis, 1.0, 0.0);
        assert!(l.abs() < 1e-9, "Lyapunov at perfect stasis must be 0.0, got {}", l);
    }

    #[test]
    fn stasis_vec_running_mean() {
        let mut stasis = StasisVec::new();
        let mut sv1 = StateVector::new();
        let mut sv2 = StateVector::new();
        sv1.dims[0] = 1.0;
        sv2.dims[0] = 3.0;

        stasis.observe(&sv1);
        stasis.observe(&sv2);

        // mean of [1.0, 3.0] = 2.0
        assert!((stasis.current.dims[0] - 2.0).abs() < 1e-9,
            "stasis_vec running mean [0] should be 2.0, got {}", stasis.current.dims[0]);
    }

    #[test]
    fn block_a_trust_history_shifts() {
        let mut sv = StateVector::new();
        // fill trust history with 0.5
        for i in TRUST_HIST_0..=TRUST_HIST_9 { sv.dims[i] = 0.5; }

        // update with trust=0.9
        sv.update_block_a(0.9, 0.5, 0.0, 1.0, true, 0, 0.7);

        // [9] = 0.9 (new trust), [8] = 0.5 (shifted from [9])
        assert!((sv.dims[TRUST_HIST_9] - 0.9).abs() < 1e-9);
        assert!((sv.dims[TRUST_HIST_9 - 1] - 0.5).abs() < 1e-9);
        // d/dt[trust] = 0.9 - 0.5 = 0.4
        assert!((sv.dims[DTRUST] - 0.4).abs() < 1e-9);
        // governed = 1.0
        assert!((sv.dims[GOVERNED] - 1.0).abs() < 1e-9);
    }

    #[test]
    fn entropy_phase_encoding() {
        assert_eq!(EntropyPhase::Stasis.as_f64(), 0.00);
        assert_eq!(EntropyPhase::Inhale.as_f64(), 0.50);
        assert_eq!(EntropyPhase::Degen.as_f64(),  1.00);
        assert_eq!(EntropyPhase::Exhale.as_f64(), 0.75);
    }

    #[test]
    fn compress_16_averages_windows() {
        let mut dims = [0.0f64; 128];
        // window 0 (dims[0..8]) = all 1.0 → average = 1.0
        for i in 0..8 { dims[i] = 1.0; }
        // window 1 (dims[8..16]) = all 2.0 → average = 2.0
        for i in 8..16 { dims[i] = 2.0; }

        let compressed = compress_16(&dims);
        assert!((compressed[0] - 1.0).abs() < 1e-9);
        assert!((compressed[1] - 2.0).abs() < 1e-9);
        assert!(compressed[2..].iter().all(|&x| x.abs() < 1e-9));
    }
}
