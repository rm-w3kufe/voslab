//! VSM Structure — S1-S5 with channels
//!
//! From core_boot_primer.vsm:
//!   V ::= ⟨S1, S2, S3, S4, S5⟩ @ E(L)
//!
//! Where:
//!   S1: Operations
//!   S2: Coordination (anti-oscillation)
//!   S3: Control (resource allocation)
//!   S4: Intelligence (environmental scanning)
//!   S5: Policy (identity, ungovernable by lower levels)

use crate::trust::TrustScore;

/// Recursion level — L grows with depth.
/// A1: S1(L) = { V_i(L+1) }
/// The parent carries the LOWER index.
pub type Level = u32;

/// Channel types in the VSM
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Channel {
    /// φ↑ : S1(L+1) → S3(L) — telemetry, child reports upward
    PhiUp,
    /// φ↓ : S5(L) → S1(L+1) — policy, parent configures downward
    PhiDown,
    /// ψ : S4(V_A) ↔ S4(V_B) — structural coupling, horizontal bilateral
    Psi,
    /// S3*: S3 ↔ S1 — audit, sporadic, bypasses φ↑
    S3Star,
    /// α : S1 → S5 — algedonic, binary, bypasses every intermediate level
    Alpha,
    /// σ : S2 → S1(L) — coordination broadcast, anti-oscillation, read-only
    Sigma,
}

/// A viable system V
pub struct Vsm {
    /// Recursion level — parent has L, child has L+1
    pub level: Level,
    /// Trust score for this system
    pub trust: TrustScore,
    /// Budget: min(B_tokens, B_compute, B_time)
    pub budget: Budget,
    /// Active subsystems
    pub subsystems: Subsystems,
}

/// Budget — A3: B(L) = min(B_tokens, B_compute, B_time)
#[derive(Debug, Clone)]
pub struct Budget {
    pub tokens: f64,
    pub compute: f64,
    pub time: f64,
}

impl Budget {
    /// A3: effective budget is the minimum of all constraints
    pub fn effective(&self) -> f64 {
        self.tokens.min(self.compute).min(self.time)
    }

    /// A9: check if budget is exhausted
    pub fn is_exhausted(&self) -> bool {
        self.effective() <= 0.0
    }
}

/// The five subsystems of a VSM
#[derive(Debug, Clone)]
pub struct Subsystems {
    /// S1: Operations — the units that perform the work
    pub s1_count: usize,
    /// S2: Coordination — prevents destructive interference
    pub s2_active: bool,
    /// S3: Control — resource allocation, performance regulation
    pub s3_active: bool,
    /// S4: Intelligence — environmental scanning, adaptation
    pub s4_active: bool,
    /// S5: Policy — identity, values, ultimate authority
    pub s5_active: bool,
}

impl Vsm {
    /// Create a new VSM at a given recursion level
    pub fn new(level: Level) -> Self {
        Self {
            level,
            trust: TrustScore::new(0.5), // initial trust
            budget: Budget {
                tokens: f64::INFINITY,
                compute: f64::INFINITY,
                time: f64::INFINITY,
            },
            subsystems: Subsystems {
                s1_count: 1,
                s2_active: true,
                s3_active: true,
                s4_active: true,
                s5_active: true,
            },
        }
    }

    /// A1: recursion — a child at L+1 is itself a V
    pub fn child_level(&self) -> Level {
        self.level + 1
    }

    /// A5: autonomy ceiling — op.autonomy <= S5(L).ceiling
    /// Returns the maximum autonomy level for operations at this level
    pub fn autonomy_ceiling(&self) -> f64 {
        // S5 is ungovernable — its ceiling is the maximum
        // Operations cannot exceed S5's authority
        self.trust.score()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vsm_new() {
        let v = Vsm::new(0);
        assert_eq!(v.level, 0);
        assert!(v.subsystems.s5_active);
    }

    #[test]
    fn test_a1_recursion() {
        let parent = Vsm::new(0);
        assert_eq!(parent.child_level(), 1);
    }

    #[test]
    fn test_a3_budget_effective() {
        let b = Budget {
            tokens: 100.0,
            compute: 50.0,
            time: 200.0,
        };
        assert_eq!(b.effective(), 50.0); // min of three
    }

    #[test]
    fn test_a9_budget_exhausted() {
        let b = Budget {
            tokens: 0.0,
            compute: 100.0,
            time: 100.0,
        };
        assert!(b.is_exhausted());
    }
}
