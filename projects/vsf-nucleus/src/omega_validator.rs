// omega_validator.rs — Ω feasible region membership check
//
// Implements: docs/theory/dynamics_choice.vsm §T1 + doc.eq_1
//             docs/theory/lyapunov_proof.vsm assumption A1
//
// Ω = ⋂_i { x ∈ ℝ¹²⁸ : A_i(x) satisfied }
//
// Constraint types:
//   - BoxConstraint     : index range, lower/upper bounds  (A3, Aε, basic axioms)
//   - LinearConstraint  : aᵀ·x ≤ b                          (semispace, Σbudget ≤ B_max)
//   - EllipsoidConstraint: (x - c)ᵀ M (x - c) ≤ 1          (smooth boundary regions)
//
// A0 / A0.1 are meta-axioms (semantic, not state-space) — checked elsewhere.
// EXP-G-01 (2026-06-15) validated the "ethics as geometry" claim via synthetic dims 53/54:
// setting dims[53]=1 (A0 violated) or dims[54]=1 (A0.1 violated) drives g→0→V=0 in the
// V-functional. They are NOT in canonical() because BoxConstraint distance semantics give
// distance=0 at the good state (must-be-zero constraint ≡ always AT the lower boundary),
// which would incorrectly dominate g. Canonical Ω covers A3/A5/Aε geometry; A0/A0.1 are
// enforced at the compute_g / V-functional layer (see EXP-G-01/results.vsm).
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.7 | vsm-1.0 ⟧

use crate::state_vector::*;

/// Trait for any geometric constraint over the state vector.
///
/// All constraints must answer:
///   - is_satisfied(x): bool
///   - violation(x): f64 (≤ 0 if satisfied; > 0 amount of violation)
///   - distance_to_boundary(x): f64 (signed; positive if interior, negative if exterior)
///
/// The signed distance lets us compute proximity warnings before exit (Cor_AlgedonicTrigger).
pub trait Constraint: std::fmt::Debug {
    /// Human-readable name (for logging, diagnostics).
    fn name(&self) -> &str;

    /// Returns true if x satisfies the constraint.
    fn is_satisfied(&self, x: &StateVector) -> bool {
        self.violation(x) <= 0.0
    }

    /// Amount of violation: ≤ 0 if satisfied, > 0 if violated.
    /// For a half-space aᵀx ≤ b, returns aᵀx - b.
    fn violation(&self, x: &StateVector) -> f64;

    /// Signed distance to the boundary in state-space units.
    /// Positive = interior, zero = on boundary, negative = exterior.
    /// Default: simple proxy via -violation. Override for proper geometric distance.
    fn distance_to_boundary(&self, x: &StateVector) -> f64 {
        -self.violation(x)
    }

    /// Signed distance to the DANGER frontier only, for the early-warning *margin*.
    /// Unlike `distance_to_boundary` (nearest face), this ignores structurally-pinned
    /// faces — the ones the healthy operating point legitimately sits ON — so the
    /// margin is not falsely pinned to 0.0 while the system is healthy (OMEGA-MARGIN-DIAG).
    /// Returns +∞ for constraints that carry no early-warning signal (categorical
    /// validity gates like `governed`/`lifecycle`), excluding them from the margin min.
    /// Default: identical to `distance_to_boundary` — directional constraints
    /// (LinearConstraint, EllipsoidConstraint) already measure toward their sole boundary.
    fn margin_distance(&self, x: &StateVector) -> f64 {
        self.distance_to_boundary(x)
    }
}

/// Which face(s) of a box constraint represent *dynamical danger* (leaving Ω toward a
/// bad state), for the early-warning margin. The healthy operating point of many dims
/// sits ON the opposite, structural face (e.g. pressures rest at the lo bound 0.0,
/// `governed`=1.0 rests at the hi bound), so a nearest-face margin pins to 0.0 while the
/// system is healthy. `margin_distance` measures only toward the danger face; `Skip`
/// drops categorical validity gates whose on-boundary state is the *good* state entirely.
/// Diagnosis + live confirmation: OMEGA-MARGIN-DIAG (TASKS.vsm), tick 66 @101 2026-07-02.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DangerFace {
    /// Danger is falling below `lo` (trust, budget, headroom, stasis_cos).
    Lo,
    /// Danger is rising above `hi` (resource pressures, entropy).
    Hi,
    /// Genuinely two-sided; keep nearest-face semantics.
    Both,
    /// Categorical/validity gate — no early-warning margin; excluded from margin_free.
    Skip,
}

// ─── BOX CONSTRAINT ────────────────────────────────────────────────────────────

/// Box constraint on a single state vector index: lo ≤ x[i] ≤ hi.
///
/// Used for:
///   - trust components ∈ [0, 1]
///   - pressures CPU/MEM/IO ∈ [0, 1]
///   - lifecycle ∈ [0.2, 1.0]
///   - governed ∈ {0.0, 1.0} (use lo=hi to lock)
#[derive(Debug, Clone)]
pub struct BoxConstraint {
    pub label: String,
    pub index: usize,
    pub lo: f64,
    pub hi: f64,
    /// Which face is the dynamical danger boundary for the early-warning margin.
    /// Defaults to `Both` (nearest-face) — validity (`is_member`) is unaffected.
    pub danger: DangerFace,
}

impl BoxConstraint {
    pub fn new(label: impl Into<String>, index: usize, lo: f64, hi: f64) -> Self {
        debug_assert!(lo <= hi, "BoxConstraint: lo must be ≤ hi");
        debug_assert!(index < 128, "BoxConstraint: index must be < 128");
        BoxConstraint { label: label.into(), index, lo, hi, danger: DangerFace::Both }
    }

    /// Declare which face is the dynamical danger boundary (fluent). Only affects the
    /// early-warning `margin_distance`; `violation`/`is_member` validity is unchanged.
    pub fn danger(mut self, face: DangerFace) -> Self {
        self.danger = face;
        self
    }
}

impl Constraint for BoxConstraint {
    fn name(&self) -> &str { &self.label }

    fn violation(&self, x: &StateVector) -> f64 {
        let v = x.dims[self.index];
        // returns max of (lo - v, v - hi); ≤ 0 iff lo ≤ v ≤ hi
        (self.lo - v).max(v - self.hi)
    }

    fn distance_to_boundary(&self, x: &StateVector) -> f64 {
        let v = x.dims[self.index];
        // signed distance: positive interior (min of distances to each face), negative if outside
        if v >= self.lo && v <= self.hi {
            (v - self.lo).min(self.hi - v)
        } else {
            -self.violation(x)
        }
    }

    /// Early-warning margin: distance to the DANGER face only (see `DangerFace`).
    /// Lo/Hi go negative once that face is breached (correct); `Skip` returns +∞ so a
    /// categorical gate never pins the margin_free min at its healthy on-boundary state.
    fn margin_distance(&self, x: &StateVector) -> f64 {
        let v = x.dims[self.index];
        match self.danger {
            DangerFace::Skip => f64::INFINITY,
            DangerFace::Lo   => v - self.lo,
            DangerFace::Hi   => self.hi - v,
            DangerFace::Both => self.distance_to_boundary(x),
        }
    }
}

// ─── LINEAR (HALF-SPACE) CONSTRAINT ────────────────────────────────────────────

/// Half-space constraint: a·x ≤ b. Coefficients a are sparse (only specified indices).
///
/// Used for:
///   - aggregate budget bounds (Σ_i pressures ≤ B_max)
///   - composite trust averages (α₁·trust_b + α₂·trust_s + ... ≤ ceiling)
///   - φ↑/φ↓ rate balance
#[derive(Debug, Clone)]
pub struct LinearConstraint {
    pub label: String,
    pub coeffs: Vec<(usize, f64)>,  // sparse: (index, coefficient)
    pub bound: f64,
    norm_a: f64,                     // cached ‖a‖ for distance computation
}

impl LinearConstraint {
    pub fn new(label: impl Into<String>, coeffs: Vec<(usize, f64)>, bound: f64) -> Self {
        let norm_a = coeffs.iter().map(|(_, c)| c * c).sum::<f64>().sqrt();
        LinearConstraint { label: label.into(), coeffs, bound, norm_a }
    }

    fn dot(&self, x: &StateVector) -> f64 {
        self.coeffs.iter().map(|(i, c)| c * x.dims[*i]).sum()
    }
}

impl Constraint for LinearConstraint {
    fn name(&self) -> &str { &self.label }

    fn violation(&self, x: &StateVector) -> f64 {
        self.dot(x) - self.bound  // ≤ 0 iff a·x ≤ b
    }

    fn distance_to_boundary(&self, x: &StateVector) -> f64 {
        // Signed Euclidean distance: (b - a·x) / ‖a‖
        if self.norm_a == 0.0 { return f64::INFINITY; }
        (self.bound - self.dot(x)) / self.norm_a
    }
}

// ─── ELLIPSOID CONSTRAINT ──────────────────────────────────────────────────────

/// Ellipsoid constraint: (x - c)ᵀ diag(w) (x - c) ≤ 1.
///
/// Diagonal-only weights for tractability (full M ∈ ℝ¹²⁸ˣ¹²⁸ would be 64K params).
/// Used for:
///   - smooth attractor basins around reference centers
///   - composite stability regions where multiple dims interact
///
/// Sparse: only specified indices contribute (others have weight 0 ⇒ unbounded).
#[derive(Debug, Clone)]
pub struct EllipsoidConstraint {
    pub label: String,
    pub center: Vec<(usize, f64)>,  // sparse: (index, c_i)
    pub weights: Vec<(usize, f64)>, // sparse: (index, w_i > 0)
}

impl EllipsoidConstraint {
    pub fn new(
        label: impl Into<String>,
        center: Vec<(usize, f64)>,
        weights: Vec<(usize, f64)>,
    ) -> Self {
        debug_assert!(weights.iter().all(|(_, w)| *w > 0.0), "weights must be > 0");
        EllipsoidConstraint { label: label.into(), center, weights }
    }

    fn quadratic_form(&self, x: &StateVector) -> f64 {
        // Σ w_i · (x_i - c_i)²
        let center_map: std::collections::HashMap<usize, f64> = self.center.iter().copied().collect();
        self.weights.iter().map(|(i, w)| {
            let c = center_map.get(i).copied().unwrap_or(0.0);
            let d = x.dims[*i] - c;
            w * d * d
        }).sum()
    }
}

impl Constraint for EllipsoidConstraint {
    fn name(&self) -> &str { &self.label }

    fn violation(&self, x: &StateVector) -> f64 {
        self.quadratic_form(x) - 1.0  // ≤ 0 iff inside ellipsoid
    }

    /// De-proxy (2026-06-22): the default `-violation` is the Mahalanobis residual
    /// (1 − g) in M-units², NOT a Euclidean distance. First-order signed Euclidean
    /// distance to the boundary g(x)=1, with g(x)=Σ wᵢ(xᵢ−cᵢ)² and ∇g = 2wᵢ(xᵢ−cᵢ):
    ///   dist ≈ (1 − g) / ‖∇g‖  = −violation / ‖∇g‖   (positive interior, negative exterior).
    /// At the center ∇g→0; fall back to −violation (the residual) to avoid 0/0.
    fn distance_to_boundary(&self, x: &StateVector) -> f64 {
        let center_map: std::collections::HashMap<usize, f64> =
            self.center.iter().copied().collect();
        let grad_norm_sq: f64 = self.weights.iter().map(|(i, w)| {
            let c = center_map.get(i).copied().unwrap_or(0.0);
            let d = 2.0 * w * (x.dims[*i] - c);
            d * d
        }).sum();
        let grad_norm = grad_norm_sq.sqrt();
        if grad_norm < 1e-12 {
            return -self.violation(x);  // at/near center: gradient vanishes
        }
        -self.violation(x) / grad_norm
    }
}

// ─── Ω AS COLLECTION OF CONSTRAINTS ────────────────────────────────────────────

/// Ω: feasible region as intersection of constraints.
/// Membership = all constraints satisfied. Lazy evaluation, short-circuits on first violation.
#[derive(Debug)]
pub struct Omega {
    pub constraints: Vec<Box<dyn Constraint>>,
}

impl Default for Omega {
    fn default() -> Self {
        Omega::canonical()
    }
}

impl Omega {
    pub fn new() -> Self {
        Omega { constraints: Vec::new() }
    }

    /// Add a constraint to Ω.
    pub fn add(&mut self, c: Box<dyn Constraint>) -> &mut Self {
        self.constraints.push(c);
        self
    }

    /// Canonical Ω built from VSF axioms A3, A5, Aε against StateVector layout.
    /// Implements baseline geometric constraints derivable from current axioms.
    /// To extend: load from viability.yaml at runtime (future work).
    pub fn canonical() -> Self {
        let mut omega = Omega::new();

        // ── Trust history components ∈ [0, 1] (A5: autonomy bounded) ──────────
        // danger = Lo: low trust is the failure direction (rests near 1.0 when healthy).
        for i in TRUST_HIST_0..=TRUST_HIST_9 {
            omega.constraints.push(Box::new(BoxConstraint::new(
                format!("trust_hist[{}] ∈ [0,1]", i),
                i, 0.0, 1.0,
            ).danger(DangerFace::Lo)));
        }

        // ── Resource pressures ∈ [0, 1] (A3: budget) ──────────────────────────
        // axiom_ref: covenant_ops.vsm#§regulation.A3@v0.1
        //   A3: B(task) ≤ B_available(V) ; B(V) = min(B_cpu, B_mem, B_time).
        //   Enforced as Ω-membership: per-resource box bounds [0,1] below +
        //   the "Σ pressures ≤ 2.5" composite half-space. x ∉ Ω ⇔ budget breached.
        // Danger face per dim: pressures rest at lo (0.0 = idle) and fail toward hi;
        // budget/headroom rest high and fail toward lo (exhaustion).
        for (idx, name, danger) in [
            (CPU_PRESSURE,    "cpu_pressure",    DangerFace::Hi),
            (MEM_PRESSURE,    "mem_pressure",    DangerFace::Hi),
            (IO_PRESSURE,     "io_pressure",     DangerFace::Hi),
            (BUDGET,          "budget",          DangerFace::Lo),
            (CGROUP_HEADROOM, "cgroup_headroom", DangerFace::Lo),
        ] {
            omega.constraints.push(Box::new(BoxConstraint::new(
                format!("{} ∈ [0,1]", name),
                idx, 0.0, 1.0,
            ).danger(danger)));
        }

        // ── Entropy components ∈ [0, 1] normalized (Aε) ───────────────────────
        // danger = Hi: rising entropy → degeneration (rests low in stasis/inhale).
        for (idx, name) in [
            (H_T,    "H_t"),
            (H_REST, "H_rest"),
        ] {
            omega.constraints.push(Box::new(BoxConstraint::new(
                format!("{} ∈ [0,1]", name),
                idx, 0.0, 1.0,
            ).danger(DangerFace::Hi)));
        }

        // ── stasis_cos ∈ [-1, 1] (cosine range) ───────────────────────────────
        // danger = Lo: decoherence (rests near 1.0 = aligned when healthy).
        omega.constraints.push(Box::new(BoxConstraint::new(
            "stasis_cos ∈ [-1,1]",
            STASIS_COS, -1.0, 1.0,
        ).danger(DangerFace::Lo)));

        // ── Lifecycle ∈ [0.2, 1.0] (D7 discrete states, continuous bound) ─────
        // Skip: ordinal/categorical validity gate; production=1.0 sits ON the hi face
        // by design → would pin the margin to 0.0 at a healthy state (OMEGA-MARGIN-DIAG).
        omega.constraints.push(Box::new(BoxConstraint::new(
            "lifecycle ∈ [0.2,1.0]",
            LIFECYCLE, 0.2, 1.0,
        ).danger(DangerFace::Skip)));

        // ── Governed ∈ [0, 1] (boolean stored as float) ───────────────────────
        // Skip: boolean validity gate; governed=1.0 sits ON the hi face by design.
        omega.constraints.push(Box::new(BoxConstraint::new(
            "governed ∈ [0,1]",
            GOVERNED, 0.0, 1.0,
        ).danger(DangerFace::Skip)));

        // ── Aggregate pressure linear bound: Σ pressures ≤ 2.5 (A3 composite) ─
        // Allows e.g. (1, 1, 0.5) but not (1, 1, 1) sustained — physical ceiling
        omega.constraints.push(Box::new(LinearConstraint::new(
            "Σ pressures ≤ 2.5 (A3 composite)",
            vec![(CPU_PRESSURE, 1.0), (MEM_PRESSURE, 1.0), (IO_PRESSURE, 1.0)],
            2.5,
        )));

        omega
    }

    /// Returns true iff x satisfies ALL constraints.
    pub fn is_member(&self, x: &StateVector) -> bool {
        self.constraints.iter().all(|c| c.is_satisfied(x))
    }

    /// Returns names of all violated constraints (empty vec if x ∈ Ω).
    pub fn violations(&self, x: &StateVector) -> Vec<(&str, f64)> {
        self.constraints.iter()
            .filter_map(|c| {
                let v = c.violation(x);
                if v > 0.0 { Some((c.name(), v)) } else { None }
            })
            .collect()
    }

    /// Minimum signed distance to ∂Ω across all constraints.
    /// Positive → safely interior. Near zero → near boundary. Negative → outside.
    pub fn min_distance_to_boundary(&self, x: &StateVector) -> f64 {
        self.constraints.iter()
            .map(|c| c.distance_to_boundary(x))
            .fold(f64::INFINITY, f64::min)
    }

    /// Minimum signed distance to the DANGER frontier of ∂Ω — the usable early-warning
    /// margin. Unlike `min_distance_to_boundary` (nearest-face, structurally pinned to
    /// 0.0 whenever the system is healthy because categorical dims like governed/lifecycle
    /// rest ON a box face — OMEGA-MARGIN-DIAG), this measures each constraint toward its
    /// danger face only and excludes categorical validity gates (they return +∞). Positive
    /// → safely interior; shrinks monotonically as any dim approaches its failure boundary.
    ///
    /// EXCLUDES H_T (normalized entropy) from the min because it structurally saturates
    /// near 1.0 in chronic degen (h_max=log2(4)=2, h_t ≈ 2 → H_T ≈ 1.0 → margin ≈ 0.0),
    /// masking early-warning from all other dims. H_T margin is reported separately via
    /// `margin_entropy` — OMEGA-MARGIN-BINDING-DIAG per Fable design.
    pub fn margin_free(&self, x: &StateVector) -> f64 {
        self.constraints.iter()
            .filter(|c| c.name() != "H_t ∈ [0,1]")  // exclude structurally saturated entropy
            .map(|c| c.margin_distance(x))
            .fold(f64::INFINITY, f64::min)
    }

    /// Returns (binding_constraint_name, margin_free) — the constraint that determines the
    /// margin_free value and the distance. Excludes H_T (same as margin_free) so the binding
    /// is never the saturated entropy dim. Use `margin_entropy` to check H_T separately.
    pub fn margin_free_binding(&self, x: &StateVector) -> (&str, f64) {
        let mut binding = ("(none)", f64::INFINITY);
        for c in &self.constraints {
            if c.name() == "H_t ∈ [0,1]" { continue; }
            let d = c.margin_distance(x);
            if d < binding.1 {
                binding = (c.name(), d);
            }
        }
        binding
    }

    /// Reports H_T constraint's margin specifically (hi danger face: 1.0 - H_T).
    /// H_T structurally saturates near 1.0 in chronic degen (h_max=log2(4)=2, h_t≈2),
    /// so this value is typically ~0.0. Monitored separately so it doesn't dominate
    /// the aggregation. Returns +∞ if no H_T constraint is registered.
    ///
    /// S5 VERDICT 2026-10-22 (rmw3, P-ENTROPY-ALPHABET-DECISION, E-i accepted):
    /// the 4-symbol Boltzmann alphabet (E=[0,.5,1,1.5], h_max=2) and the 0.99
    /// contraction (λ_max, EXP-LY-01) are INTENTIONAL. The attractor lives at
    /// 89.8-97.3% of the ceiling by construction; phases are already h_eq-relative
    /// (CALIBRATE-ENTROPY 2026-07-03); H_T excluded from margin aggregation (B, done).
    /// Widening the alphabet or accelerating relaxation are NOT fixes for a bug —
    /// they may only enter as NEW ratified experiments (EXP-ALPHA-02 / EXP-RATE-02)
    /// if paper v1.0 §6 or T2-F2 live data demand them.
    /// Ref: docs/plans/entropy_alphabet_decision_2026_10_22.vsm (ratified).
    pub fn margin_entropy(&self, x: &StateVector) -> f64 {
        self.constraints.iter()
            .filter(|c| c.name() == "H_t ∈ [0,1]")
            .map(|c| c.margin_distance(x))
            .next()
            .unwrap_or(f64::INFINITY)
    }

    /// Number of constraints (for diagnostics).
    pub fn len(&self) -> usize { self.constraints.len() }

    pub fn is_empty(&self) -> bool { self.constraints.is_empty() }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    fn zero_state() -> StateVector {
        StateVector { dims: [0.0; 128] }
    }

    fn typical_healthy_state() -> StateVector {
        let mut s = zero_state();
        // Healthy trust history
        for i in TRUST_HIST_0..=TRUST_HIST_9 { s.dims[i] = 0.85; }
        s.dims[CPU_PRESSURE]    = 0.3;
        s.dims[MEM_PRESSURE]    = 0.4;
        s.dims[IO_PRESSURE]     = 0.2;
        s.dims[BUDGET]          = 0.7;
        s.dims[CGROUP_HEADROOM] = 0.5;
        s.dims[H_T]             = 0.3;
        s.dims[H_REST]          = 0.25;
        s.dims[STASIS_COS]      = 0.95;
        s.dims[LIFECYCLE]       = 1.0;
        s.dims[GOVERNED]        = 1.0;
        s
    }

    #[test]
    fn box_constraint_basic() {
        let c = BoxConstraint::new("test", TRUST_HIST_0, 0.0, 1.0);
        let mut s = zero_state();
        s.dims[TRUST_HIST_0] = 0.5;
        assert!(c.is_satisfied(&s));
        assert!(c.distance_to_boundary(&s) > 0.0);

        s.dims[TRUST_HIST_0] = 1.5;
        assert!(!c.is_satisfied(&s));
        assert!((c.violation(&s) - 0.5).abs() < 1e-9);
    }

    #[test]
    fn linear_constraint_basic() {
        let c = LinearConstraint::new(
            "Σpressures",
            vec![(CPU_PRESSURE, 1.0), (MEM_PRESSURE, 1.0), (IO_PRESSURE, 1.0)],
            2.5,
        );
        let mut s = zero_state();
        s.dims[CPU_PRESSURE] = 1.0;
        s.dims[MEM_PRESSURE] = 1.0;
        s.dims[IO_PRESSURE]  = 0.4;
        assert!(c.is_satisfied(&s));   // 2.4 ≤ 2.5

        s.dims[IO_PRESSURE] = 0.6;
        assert!(!c.is_satisfied(&s));  // 2.6 > 2.5
        assert!((c.violation(&s) - 0.1).abs() < 1e-9);
    }

    #[test]
    fn ellipsoid_constraint_basic() {
        let c = EllipsoidConstraint::new(
            "stasis_basin",
            vec![(STASIS_COS, 1.0)],         // center at stasis_cos = 1.0
            vec![(STASIS_COS, 100.0)],       // tight: 0.1 deviation hits boundary
        );
        let mut s = zero_state();
        s.dims[STASIS_COS] = 0.95;
        assert!(c.is_satisfied(&s));         // 100·(0.05)² = 0.25 ≤ 1

        s.dims[STASIS_COS] = 0.85;
        assert!(!c.is_satisfied(&s));        // 100·(0.15)² = 2.25 > 1
    }

    #[test]
    fn ellipsoid_distance_is_euclidean_not_mahalanobis() {
        // de-proxy 2026-06-22: distance_to_boundary must be Euclidean, not the
        // Mahalanobis residual (1 − g). center=1.0, w=100 on STASIS_COS.
        let c = EllipsoidConstraint::new(
            "stasis_basin",
            vec![(STASIS_COS, 1.0)],
            vec![(STASIS_COS, 100.0)],
        );
        let mut s = zero_state();
        s.dims[STASIS_COS] = 0.95;   // boundary at x=0.9 (true Euclidean dist 0.05)
        // g = 100·0.05² = 0.25 ; violation = −0.75 ; ‖∇g‖ = |2·100·(−0.05)| = 10
        // first-order Euclidean dist = (1 − g)/‖∇g‖ = 0.75/10 = 0.075
        let d = c.distance_to_boundary(&s);
        assert!((d - 0.075).abs() < 1e-9, "expected 0.075, got {}", d);
        // far smaller than the old proxy (−violation = 0.75); positive = interior
        assert!(d > 0.0 && d < (-c.violation(&s)) * 0.2);
    }

    #[test]
    fn omega_canonical_accepts_healthy_state() {
        let omega = Omega::canonical();
        let s = typical_healthy_state();
        let v = omega.violations(&s);
        assert!(v.is_empty(), "expected no violations, got: {:?}", v);
        assert!(omega.is_member(&s));
        // governed=1.0 and lifecycle=1.0 sit exactly on the upper boundary by design
        // (boolean / categorical max), so min_distance can legitimately be 0.
        assert!(omega.min_distance_to_boundary(&s) >= 0.0);
    }

    #[test]
    fn omega_canonical_rejects_negative_trust() {
        let omega = Omega::canonical();
        let mut s = typical_healthy_state();
        s.dims[TRUST_HIST_0 + 5] = -0.1;
        assert!(!omega.is_member(&s));
        let v = omega.violations(&s);
        assert!(!v.is_empty());
        assert!(v.iter().any(|(name, _)| name.contains("trust_hist")));
    }

    #[test]
    fn omega_canonical_rejects_overpressure() {
        let omega = Omega::canonical();
        let mut s = typical_healthy_state();
        s.dims[CPU_PRESSURE] = 1.0;
        s.dims[MEM_PRESSURE] = 1.0;
        s.dims[IO_PRESSURE]  = 0.8;
        // Σ = 2.8 > 2.5 ⇒ composite linear constraint violated
        assert!(!omega.is_member(&s));
        let v = omega.violations(&s);
        assert!(v.iter().any(|(name, _)| name.contains("Σ pressures")));
    }

    #[test]
    fn omega_distance_to_boundary_smaller_when_closer() {
        // Use a state strictly interior to all box constraints (avoid governed=1, lifecycle=1)
        let mut s = typical_healthy_state();
        s.dims[GOVERNED]  = 0.5;   // strictly interior of [0, 1]
        s.dims[LIFECYCLE] = 0.7;   // strictly interior of [0.2, 1.0]
        s.dims[STASIS_COS] = 0.5;  // strictly interior of [-1, 1]

        let omega = Omega::canonical();
        let d_far = omega.min_distance_to_boundary(&s);
        assert!(d_far > 0.0, "baseline expected strictly interior, got {}", d_far);

        // Push budget close to upper boundary (was 0.7 → now 0.99)
        s.dims[BUDGET] = 0.99;
        let d_near = omega.min_distance_to_boundary(&s);

        assert!(d_near < d_far, "expected d_near < d_far: {} vs {}", d_near, d_far);
        assert!(d_near > 0.0, "expected still interior");
    }

    #[test]
    fn omega_zero_state_violates_lifecycle() {
        // Zero state has lifecycle=0.0 which is below [0.2, 1.0] bound.
        let omega = Omega::canonical();
        let s = zero_state();
        assert!(!omega.is_member(&s));
        let v = omega.violations(&s);
        assert!(v.iter().any(|(name, _)| name.contains("lifecycle")));
    }

    #[test]
    fn margin_free_is_informative_at_healthy_state() {
        // OMEGA-MARGIN-DIAG regression. The nearest-face margin pins to 0.0 at a healthy
        // state because governed=1.0 and lifecycle=1.0 sit ON their upper box face. The
        // danger-face margin_free must exclude those categorical gates and stay strictly
        // positive, then shrink as a real danger (rising pressure) approaches.
        let omega = Omega::canonical();
        let s = typical_healthy_state();

        // baseline: the OLD metric is pinned; the NEW one is informative
        assert_eq!(
            omega.min_distance_to_boundary(&s), 0.0,
            "nearest-face margin is pinned to 0.0 at the healthy state (governed/lifecycle on hi face)"
        );
        let mf = omega.margin_free(&s);
        assert!(mf > 0.0, "margin_free must be strictly positive at a healthy state, got {}", mf);

        // rising CPU pressure toward its hi danger face must shrink the margin
        let mut s_hot = typical_healthy_state();
        s_hot.dims[CPU_PRESSURE] = 0.95;
        assert!(
            omega.margin_free(&s_hot) < mf,
            "margin_free must shrink as a pressure nears its danger face"
        );
    }

    #[test]
    fn margin_free_ignores_governed_and_lifecycle_at_max() {
        // A categorical gate at its healthy max (governed=1.0, lifecycle=1.0) must NOT
        // pin margin_free: it is Skip'd. Contrast with min_distance_to_boundary which does pin.
        let omega = Omega::canonical();
        let mut s = typical_healthy_state();
        s.dims[GOVERNED]  = 1.0;   // on hi face of [0,1]
        s.dims[LIFECYCLE] = 1.0;   // on hi face of [0.2,1.0]
        assert!(omega.is_member(&s), "state is still valid (gates satisfied)");
        assert_eq!(omega.min_distance_to_boundary(&s), 0.0, "old metric pinned by the gates");
        assert!(omega.margin_free(&s) > 0.0, "margin_free excludes the categorical gates");
    }
}
