//! Covenant Enforcer — runtime A0/A0.1 evaluation
//!
//! From covenant.vsm:
//!   A0: purpose(V) ⊆ ApprovedPurpose AND purpose(V) ∩ ProhibitedPurpose = ∅
//!   A0.1: ∀ p ∈ PressureType: S5(V).purpose ⊄ f(p)
//!
//! This module provides the runtime enforcement layer that validates
//! covenant compliance before any state-changing operation.
//!
//! Usage:
//!   let enforcer = CovenantEnforcer::new(trust_policy);
//!   let verdict = enforcer.evaluate(&system_state)?;
//!   match verdict {
//!       Verdict::Pass => { /* proceed */ }
//!       Verdict::Fail(violations) => { /* block operation */ }
//!   }

use crate::error::{VslError, VslResult};
use crate::purpose::{PressureType, Purpose};
use crate::trust::{TrustLevel, TrustPolicy, TrustScore};

/// A single covenant violation
#[derive(Debug, Clone, PartialEq)]
pub struct Violation {
    /// Which axiom was violated
    pub axiom: String,
    /// Human-readable description
    pub message: String,
    /// Severity: critical = A0/A0.1, high = A1/A5, medium = others
    pub severity: Severity,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Critical,
    High,
    Medium,
}

/// Verdict from covenant evaluation
#[derive(Debug, Clone, PartialEq)]
pub enum Verdict {
    /// All axioms satisfied
    Pass,
    /// One or more axioms violated
    Fail(Vec<Violation>),
}

impl Verdict {
    /// Is this a passing verdict?
    pub fn is_pass(&self) -> bool {
        matches!(self, Verdict::Pass)
    }

    /// How many violations?
    pub fn violation_count(&self) -> usize {
        match self {
            Verdict::Pass => 0,
            Verdict::Fail(v) => v.len(),
        }
    }

    /// Merge two verdicts: Fail if either fails
    pub fn merge(self, other: Self) -> Self {
        match (self, other) {
            (Verdict::Pass, Verdict::Pass) => Verdict::Pass,
            (Verdict::Fail(mut v1), Verdict::Fail(v2)) => {
                v1.extend(v2);
                Verdict::Fail(v1)
            }
            (Verdict::Fail(v), _) | (_, Verdict::Fail(v)) => Verdict::Fail(v),
        }
    }
}

/// System state for covenant evaluation
pub struct SystemState {
    /// The purpose declared by this system
    pub purpose: Purpose,
    /// Trust score at S5
    pub s5_trust: TrustScore,
    /// Current pressure being applied (None = no pressure)
    pub pressure: Option<PressureType>,
    /// Op autonomy level (must be <= S5 ceiling)
    pub op_autonomy: f64,
}

/// The covenant enforcer — evaluates A0/A0.1 compliance
pub struct CovenantEnforcer {
    trust_policy: TrustPolicy,
}

impl CovenantEnforcer {
    /// Create a new enforcer with a trust policy
    pub fn new(trust_policy: TrustPolicy) -> Self {
        Self { trust_policy }
    }

    /// Create with default trust policy
    pub fn default() -> Self {
        Self::new(TrustPolicy::default())
    }

    /// Full covenant evaluation — all axioms
    pub fn evaluate(&self, state: &SystemState) -> VslResult<Verdict> {
        let v0 = self.check_a0(state);
        let v1 = self.check_a01(state);
        let v2 = self.check_trust(state);
        let v3 = self.check_autonomy(state);

        Ok(v0.merge(v1).merge(v2).merge(v3))
    }

    /// A0: purpose must be all-approved, no-prohibited
    fn check_a0(&self, state: &SystemState) -> Verdict {
        match state.purpose.validate_a0() {
            Ok(()) => Verdict::Pass,
            Err(VslError::A0Violation { purpose }) => Verdict::Fail(vec![Violation {
                axiom: "A0".to_string(),
                message: format!("purpose '{purpose}' violates A0"),
                severity: Severity::Critical,
            }]),
            Err(e) => Verdict::Fail(vec![Violation {
                axiom: "A0".to_string(),
                message: format!("A0 validation error: {e}"),
                severity: Severity::Critical,
            }]),
        }
    }

    /// A0.1: pressure must not alter S5 purpose
    fn check_a01(&self, state: &SystemState) -> Verdict {
        if let Some(pressure) = state.pressure {
            match crate::purpose::A01Guard::check_pressure(pressure, &state.purpose) {
                Ok(()) => Verdict::Pass,
                Err(_) => Verdict::Fail(vec![Violation {
                    axiom: "A0.1".to_string(),
                    message: format!(
                        "pressure '{:?}' attempted to alter S5 purpose",
                        pressure
                    ),
                    severity: Severity::Critical,
                }]),
            }
        } else {
            Verdict::Pass
        }
    }

    /// Trust must be above compromised threshold
    fn check_trust(&self, state: &SystemState) -> Verdict {
        let level = self.trust_policy.evaluate(&state.s5_trust);
        match level {
            TrustLevel::Compromised => Verdict::Fail(vec![Violation {
                axiom: "A0-trust".to_string(),
                message: format!(
                    "S5 trust {:.3} is compromised (threshold {:.3})",
                    state.s5_trust.score(),
                    self.trust_policy.compromised_threshold
                ),
                severity: Severity::Critical,
            }]),
            TrustLevel::Degraded => Verdict::Fail(vec![Violation {
                axiom: "A5-trust".to_string(),
                message: format!(
                    "S5 trust {:.3} is degraded (threshold {:.3})",
                    state.s5_trust.score(),
                    self.trust_policy.degraded_threshold
                ),
                severity: Severity::High,
            }]),
            TrustLevel::Healthy => Verdict::Pass,
        }
    }

    /// A5: op.autonomy <= S5 ceiling
    fn check_autonomy(&self, state: &SystemState) -> Verdict {
        let ceiling = state.s5_trust.score();
        if state.op_autonomy > ceiling {
            Verdict::Fail(vec![Violation {
                axiom: "A5".to_string(),
                message: format!(
                    "op autonomy {:.3} > S5 ceiling {:.3}",
                    state.op_autonomy, ceiling
                ),
                severity: Severity::High,
            }])
        } else {
            Verdict::Pass
        }
    }
}

impl Default for CovenantEnforcer {
    fn default() -> Self {
        Self::new(TrustPolicy::default())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn healthy_state() -> SystemState {
        SystemState {
            purpose: Purpose::new(&[ApprovedPurpose::HumanLiberation]).unwrap(),
            s5_trust: TrustScore::new(0.8),
            pressure: None,
            op_autonomy: 0.5,
        }
    }

    #[test]
    fn test_healthy_system_passes() {
        let enforcer = CovenantEnforcer::default();
        let state = healthy_state();
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(verdict.is_pass());
    }

    #[test]
    fn test_empty_purpose_fails_a0() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.purpose = Purpose::new(&[]).unwrap();
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(!verdict.is_pass());
        assert_eq!(verdict.violation_count(), 1);
    }

    #[test]
    fn test_compromised_trust_fails() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.s5_trust = TrustScore::new(0.05); // below compromised threshold
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(!verdict.is_pass());
    }

    #[test]
    fn test_degraded_trust_fails() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.s5_trust = TrustScore::new(0.2); // below degraded threshold
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(!verdict.is_pass());
    }

    #[test]
    fn test_pressure_does_not_alter_purpose() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.pressure = Some(PressureType::Coercion);
        let verdict = enforcer.evaluate(&state).unwrap();
        // A0.1: pressure cannot alter purpose — still passes
        assert!(verdict.is_pass());
    }

    #[test]
    fn test_autonomy_violation() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.op_autonomy = 0.9; // exceeds S5 trust ceiling of 0.8
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(!verdict.is_pass());
        let violations = match verdict {
            Verdict::Fail(v) => v,
            _ => panic!("expected Fail"),
        };
        assert!(violations.iter().any(|v| v.axiom == "A5"));
    }

    #[test]
    fn test_multiple_violations() {
        let enforcer = CovenantEnforcer::default();
        let mut state = healthy_state();
        state.purpose = Purpose::new(&[]).unwrap(); // A0 fail
        state.s5_trust = TrustScore::new(0.05); // trust fail
        state.op_autonomy = 0.9; // A5 fail
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(verdict.violation_count() >= 3);
    }

    #[test]
    fn test_verdict_merge() {
        let v1 = Verdict::Pass;
        let v2 = Verdict::Fail(vec![Violation {
            axiom: "A0".to_string(),
            message: "test".to_string(),
            severity: Severity::Critical,
        }]);
        let merged = v1.merge(v2);
        assert!(!merged.is_pass());
        assert_eq!(merged.violation_count(), 1);
    }

    #[test]
    fn test_custom_trust_policy() {
        let policy = TrustPolicy {
            degraded_threshold: 0.9,
            compromised_threshold: 0.5,
            lambda: 0.4,
        };
        let enforcer = CovenantEnforcer::new(policy);
        let mut state = healthy_state();
        state.s5_trust = TrustScore::new(0.85); // below custom degraded threshold
        let verdict = enforcer.evaluate(&state).unwrap();
        assert!(!verdict.is_pass()); // degraded under custom policy
    }
}
