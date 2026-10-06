/// vsl.rs — VSL invariant checker
///
/// @vsm 0.3
/// S1(vsf-nucleus).vsl_checker
///
/// Encodes the Viable System Language (VSL) invariants as native Rust predicates.
/// In the Python kernel these are string expressions evaluated at runtime.
/// Here they are type-checked at compile time — zero-cost when passing.
///
/// Core invariant (from vsm_notation_spec.md):
///   governed(V) iff ∀ tick:
///     trust(V)     > τ_L
///     entropy(V)   < ε_max
///     integrity(V) > 0.0
///
/// If any invariant fails → kernel transitions to HALTED → φ↑ algedonic signal.

use std::fmt;

/// The VSL invariant set for a kernel at level L.
/// All fields are the *thresholds*, not the state values.
#[derive(Debug, Clone)]
pub struct VslSpec {
    pub tau_l:     f64,   // trust lower bound   — default 0.2
    pub epsilon:   f64,   // entropy upper bound — default 0.95
    pub integrity: f64,   // integrity lower bound — default 0.0 (exclusive)
}

impl Default for VslSpec {
    fn default() -> Self {
        Self { tau_l: 0.2, epsilon: 0.95, integrity: 0.0 }
    }
}

/// Which invariants a state violates.
#[derive(Debug, Clone, PartialEq)]
pub struct VslViolation {
    pub violated: Vec<String>,
}

impl VslViolation {
    pub fn none() -> Self { Self { violated: vec![] } }
    pub fn is_ok(&self) -> bool { self.violated.is_empty() }
}

impl fmt::Display for VslViolation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[{}]", self.violated.join(", "))
    }
}

/// Check VSL invariants against a state snapshot.
/// Returns Ok(()) if all pass, Err(VslViolation) with all failing conditions.
pub fn check(spec: &VslSpec, trust: f64, entropy: f64, integrity: f64) -> Result<(), VslViolation> {
    let mut violated = Vec::new();

    if trust <= spec.tau_l {
        violated.push(format!("trust {:.4} ≤ τ_L {:.4}", trust, spec.tau_l));
    }
    if entropy >= spec.epsilon {
        violated.push(format!("entropy {:.4} ≥ ε_max {:.4}", entropy, spec.epsilon));
    }
    if integrity <= spec.integrity {
        violated.push(format!("integrity {:.4} ≤ {:.4}", integrity, spec.integrity));
    }

    if violated.is_empty() { Ok(()) } else { Err(VslViolation { violated }) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn healthy_state_passes() {
        let spec = VslSpec::default();
        assert!(check(&spec, 0.8, 0.3, 1.0).is_ok());
    }

    #[test]
    fn low_trust_fails() {
        let spec = VslSpec::default();
        let r = check(&spec, 0.1, 0.3, 1.0);
        assert!(r.is_err());
        let v = r.unwrap_err();
        assert!(v.violated[0].contains("trust"));
    }

    #[test]
    fn high_entropy_fails() {
        let spec = VslSpec::default();
        let r = check(&spec, 0.8, 0.96, 1.0);
        assert!(r.is_err());
        assert!(r.unwrap_err().violated[0].contains("entropy"));
    }

    #[test]
    fn multiple_violations_all_reported() {
        let spec = VslSpec::default();
        let r = check(&spec, 0.1, 0.96, 0.0);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err().violated.len(), 3);
    }
}
