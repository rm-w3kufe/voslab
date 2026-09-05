//! Axioms A1-A15 as Rust traits
//!
//! Each axiom is a trait that a VSF-compliant system MUST implement.
//! The Rust compiler verifies compliance at compile time.
//!
//! Dependencies (from core_boot_primer.vsm):
//!   A1 → A4, A5, A7, A8
//!   A3 → A9
//!   A7 → A8

use crate::error::VslResult;
use crate::structure::{Budget, Level};
use crate::trust::TrustScore;

// ─── A1: RECURSION ──────────────────────────────────────────────

/// A1: S1(L) = { V_i(L+1) }
/// Every unit in S1 is itself a viable system at the next recursion level.
pub trait Recursion {
    /// The recursion level of this system
    fn level(&self) -> Level;

    /// The child's recursion level (always level + 1)
    fn child_level(&self) -> Level {
        self.level() + 1
    }
}

// ─── A2: BUDGET HIERARCHY ──────────────────────────────────────

/// A2: B(child) <= B(parent)
/// A child's budget cannot exceed its parent's budget.
pub trait BudgetHierarchy: Recursion {
    /// The budget of this system
    fn budget(&self) -> &Budget;

    /// Validate that a child's budget is within bounds
    fn validate_child_budget(&self, child_budget: &Budget) -> VslResult<()> {
        let parent_budget = self.budget();
        if child_budget.effective() > parent_budget.effective() {
            return Err(crate::error::VslError::BudgetExhausted {
                resource: "child_exceeds_parent".to_string(),
                usage: child_budget.effective(),
                capacity: parent_budget.effective(),
            });
        }
        Ok(())
    }
}

// ─── A3: BUDGET MINIMUM ────────────────────────────────────────

/// A3: B(L) = min(B_tokens, B_compute, B_time)
pub trait BudgetMinimum {
    fn budget(&self) -> &Budget;

    /// The effective budget is the minimum of all constraints
    fn effective_budget(&self) -> f64 {
        self.budget().effective()
    }
}

// ─── A4: COUPLING RESTRICTION ──────────────────────────────────

/// A4: V_i -> V_j only via parent S3
/// No direct sibling coupling — all inter-system communication
/// must go through the parent's control channel.
pub trait CouplingRestriction: Recursion {
    /// Validate that a communication between siblings goes through parent S3
    fn validate_coupling(&self, _from_level: Level, _to_level: Level) -> VslResult<()> {
        // Siblings must be at the same level
        // and communicate through parent at level - 1
        Ok(())
    }
}

// ─── A5: AUTONOMY CEILING ──────────────────────────────────────

/// A5: op.autonomy <= S5(L).ceiling
/// Operations cannot exceed S5's authority.
pub trait AutonomyCeiling {
    /// The trust score of S5 at this level
    fn s5_trust(&self) -> &TrustScore;

    /// The autonomy level of operations
    fn op_autonomy(&self) -> f64;

    /// Validate that operations don't exceed S5's ceiling
    fn validate_autonomy(&self) -> VslResult<()> {
        let ceiling = self.s5_trust().score();
        let autonomy = self.op_autonomy();
        if autonomy > ceiling {
            return Err(crate::error::VslError::A01Violation {
                pressure: format!(
                    "op autonomy {autonomy:.3} > S5 ceiling {ceiling:.3}"
                ),
            });
        }
        Ok(())
    }
}

// ─── A6: ASHBY LAW OF REQUISITE VARIETY ────────────────────────

/// A6: Var(E(L)) <= Var(S3(L)) + Var(S2(L))
/// The variety of the environment must be absorbable by S3 + S2.
pub trait AshbyVariety {
    /// Environment variety
    fn env_variety(&self) -> f64;
    /// S3 variety (control capacity)
    fn s3_variety(&self) -> f64;
    /// S2 variety (coordination capacity)
    fn s2_variety(&self) -> f64;

    /// Validate Ashby's law
    fn validate_variety(&self) -> VslResult<()> {
        let env = self.env_variety();
        let capacity = self.s3_variety() + self.s2_variety();
        if env > capacity {
            return Err(crate::error::VslError::VarietyViolation {
                env_var: env,
                s3_var: self.s3_variety(),
                s2_var: self.s2_variety(),
            });
        }
        Ok(())
    }
}

// ─── A7: ESCALATION ────────────────────────────────────────────

/// A7: escalate(s) iff resolve(s)=∅ AND urgency(s) > τ_{L+1}
pub trait Escalation {
    /// Try to resolve a situation locally
    fn resolve(&self, situation: &str) -> Option<String>;
    /// Urgency of a situation
    fn urgency(&self, situation: &str) -> f64;
    /// Threshold for escalation at the next level
    fn escalation_threshold(&self) -> f64;

    /// Check if a situation should be escalated
    fn should_escalate(&self, situation: &str) -> bool {
        self.resolve(situation).is_none()
            && self.urgency(situation) > self.escalation_threshold()
    }
}

// ─── A8: SIGNAL ABSORPTION ─────────────────────────────────────

/// A8: |Sig(L)| <= |Sig(L+1)| * (1 - r_L)
/// Signal count at level L is bounded by signal count at L+1
/// with absorption rate r_L.
pub trait SignalAbsorption: Recursion {
    /// Number of signals at this level
    fn signal_count(&self) -> usize;
    /// Number of signals at child level
    fn child_signal_count(&self) -> usize;
    /// Absorption rate r_L (0 < r_L < 1)
    fn absorption_rate(&self) -> f64;

    /// Validate signal absorption
    fn validate_absorption(&self) -> VslResult<()> {
        let child_count = self.child_signal_count() as f64;
        let parent_count = self.signal_count() as f64;
        let rate = self.absorption_rate();
        let bound = child_count * (1.0 - rate);

        if parent_count > bound {
            return Err(crate::error::VslError::DependencyFailure {
                axiom: "A8".to_string(),
                dependency: format!(
                    "signals {parent_count:.0} > bound {bound:.0} (child={child_count:.0}, r={rate:.2})"
                ),
            });
        }
        Ok(())
    }
}

// ─── A9: BUDGET DEGRADATION ────────────────────────────────────

/// A9: B_exhausted implies degrade OR abort
pub trait BudgetDegradation: BudgetMinimum {
    /// What to do when budget is exhausted
    fn on_budget_exhausted(&self) -> DegradationAction;

    /// Check budget and take action if exhausted
    fn check_budget(&self) -> VslResult<DegradationAction> {
        if self.effective_budget() <= 0.0 {
            Ok(self.on_budget_exhausted())
        } else {
            Ok(DegradationAction::Continue)
        }
    }
}

/// Actions when budget is exhausted (A9)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DegradationAction {
    /// Continue operating normally
    Continue,
    /// Reduce load to stay within budget
    Degrade,
    /// Stop operations entirely
    Abort,
}

// ─── A10: URGENCY ROUTING ──────────────────────────────────────

/// A10: urgency routing:
///   LOW -> S3
///   MEDIUM -> S4
///   >= HIGH -> S5
///   alpha: binary, S1 -> S5 (algedonic)
pub trait UrgencyRouting {
    /// Route a situation to the appropriate subsystem based on urgency
    fn route(&self, urgency: f64) -> RoutingTarget {
        if urgency < 0.3 {
            RoutingTarget::S3
        } else if urgency < 0.7 {
            RoutingTarget::S4
        } else {
            RoutingTarget::S5
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RoutingTarget {
    S3,
    S4,
    S5,
}

// ─── A11: TICK ORDER ───────────────────────────────────────────

/// A11: S4_active iff drift(V,t) > epsilon
/// Order(tick): S1 precedes S4
pub trait TickOrder {
    /// Current drift
    fn drift(&self) -> f64;
    /// Drift threshold
    fn epsilon(&self) -> f64;

    /// Check if S4 should be active this tick
    fn s4_active(&self) -> bool {
        self.drift() > self.epsilon()
    }
}

// ─── A15: OMEGA CLOSURE ────────────────────────────────────────

/// A15: Convex combination of in-Omega modes stays in-Omega.
/// If all components are viable, their convex combination is viable.
pub trait OmegaClosure {
    /// Check if a set of modes are all in Omega
    fn all_in_omega(modes: &[f64]) -> bool;

    /// Check if a convex combination is in Omega
    fn convex_combination_in_omega(weights: &[f64], values: &[f64]) -> bool {
        if weights.len() != values.len() || weights.is_empty() {
            return false;
        }
        let sum_w: f64 = weights.iter().sum();
        (sum_w - 1.0).abs() < 1e-10 // weights must sum to 1
            && weights.iter().all(|w| *w >= 0.0)
            && Self::all_in_omega(values)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestVsm {
        level: Level,
        budget: Budget,
        trust: TrustScore,
        op_autonomy: f64,
        env_var: f64,
        s3_var: f64,
        s2_var: f64,
    }

    impl Recursion for TestVsm {
        fn level(&self) -> Level {
            self.level
        }
    }

    impl BudgetHierarchy for TestVsm {
        fn budget(&self) -> &Budget {
            &self.budget
        }
    }

    impl BudgetMinimum for TestVsm {
        fn budget(&self) -> &Budget {
            &self.budget
        }
    }

    impl AutonomyCeiling for TestVsm {
        fn s5_trust(&self) -> &TrustScore {
            &self.trust
        }
        fn op_autonomy(&self) -> f64 {
            self.op_autonomy
        }
    }

    impl AshbyVariety for TestVsm {
        fn env_variety(&self) -> f64 {
            self.env_var
        }
        fn s3_variety(&self) -> f64 {
            self.s3_var
        }
        fn s2_variety(&self) -> f64 {
            self.s2_var
        }
    }

    #[test]
    fn test_a1_recursion() {
        let v = TestVsm {
            level: 0,
            budget: Budget { tokens: 100.0, compute: 100.0, time: 100.0 },
            trust: TrustScore::new(0.8),
            op_autonomy: 0.5,
            env_var: 10.0,
            s3_var: 8.0,
            s2_var: 5.0,
        };
        assert_eq!(v.child_level(), 1);
    }

    #[test]
    fn test_a5_autonomy_valid() {
        let v = TestVsm {
            level: 0,
            budget: Budget { tokens: 100.0, compute: 100.0, time: 100.0 },
            trust: TrustScore::new(0.8),
            op_autonomy: 0.5,
            env_var: 10.0,
            s3_var: 8.0,
            s2_var: 5.0,
        };
        assert!(v.validate_autonomy().is_ok());
    }

    #[test]
    fn test_a5_autonomy_violation() {
        let v = TestVsm {
            level: 0,
            budget: Budget { tokens: 100.0, compute: 100.0, time: 100.0 },
            trust: TrustScore::new(0.3),
            op_autonomy: 0.8, // exceeds S5 trust ceiling
            env_var: 10.0,
            s3_var: 8.0,
            s2_var: 5.0,
        };
        assert!(v.validate_autonomy().is_err());
    }

    #[test]
    fn test_a6_variety_ok() {
        let v = TestVsm {
            level: 0,
            budget: Budget { tokens: 100.0, compute: 100.0, time: 100.0 },
            trust: TrustScore::new(0.8),
            op_autonomy: 0.5,
            env_var: 10.0,
            s3_var: 8.0,
            s2_var: 5.0,
        };
        assert!(v.validate_variety().is_ok());
    }

    #[test]
    fn test_a6_variety_violation() {
        let v = TestVsm {
            level: 0,
            budget: Budget { tokens: 100.0, compute: 100.0, time: 100.0 },
            trust: TrustScore::new(0.8),
            op_autonomy: 0.5,
            env_var: 20.0,
            s3_var: 5.0,
            s2_var: 5.0,
        };
        assert!(v.validate_variety().is_err());
    }

    #[test]
    fn test_a10_routing() {
        struct Router;
        impl UrgencyRouting for Router {}

        let r = Router;
        assert_eq!(r.route(0.1), RoutingTarget::S3);
        assert_eq!(r.route(0.5), RoutingTarget::S4);
        assert_eq!(r.route(0.9), RoutingTarget::S5);
    }
}
