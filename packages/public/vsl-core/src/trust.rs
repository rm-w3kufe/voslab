//! Trust model — composable, verifiable trust
//!
//! From definitions_core.vsm (D5-D13):
//!   trust(t+1) = (1-lambda)*decay(trust(t), lambda) + lambda*observation(t)
//!
//! From definitions_theory.vsm (D18):
//!   trust_parent = min(sum(w_i * trust_i), min_i(trust_i) + epsilon)

use crate::error::{VslError, VslResult};

/// Trust score — bounded [0.0, 1.0]
/// Below threshold = degraded governance
/// Zero = revoked (A0 violation)
#[derive(Debug, Clone, Copy)]
pub struct TrustScore(f64);

impl TrustScore {
    /// Create a new trust score
    pub fn new(score: f64) -> Self {
        Self(score.clamp(0.0, 1.0))
    }

    /// Get the raw score
    pub fn score(&self) -> f64 {
        self.0
    }

    /// Check if trust is above a threshold
    pub fn above(&self, threshold: f64) -> bool {
        self.0 >= threshold
    }

    /// A0 violation: trust → 0, channels revoked, status = compromised
    pub fn revoke(&mut self) {
        self.0 = 0.0;
    }

    /// Trust update: trust(t+1) = (1-λ)*decay(trust(t), λ) + λ*observation(t)
    /// λ is the learning rate (0 < λ < 1)
    pub fn update(&mut self, observation: f64, lambda: f64) {
        let decay_factor = 1.0 - lambda;
        self.0 = (decay_factor * self.0 + lambda * observation).clamp(0.0, 1.0);
    }

    /// Compose trust from children (A5 corollary + D18):
    /// trust_parent = min(Σ w_i * trust_i, min_i(trust_i) + ε)
    pub fn compose_weighted(children: &[(TrustScore, f64)]) -> VslResult<Self> {
        if children.is_empty() {
            return Ok(Self(0.0));
        }

        let epsilon = 0.01; // small margin

        // Weighted sum
        let weighted_sum: f64 = children
            .iter()
            .map(|(t, w)| t.score() * w)
            .sum();

        // Minimum trust + epsilon
        let min_trust = children
            .iter()
            .map(|(t, _)| t.score())
            .fold(f64::INFINITY, f64::min);

        let composed = weighted_sum.min(min_trust + epsilon);
        Ok(Self(composed.clamp(0.0, 1.0)))
    }
}

/// Trust policy — parametrizable thresholds
/// (Addresses the ChatGPT critique: "constant TrustPolicy instead of hardcoded 0.6")
#[derive(Debug, Clone)]
pub struct TrustPolicy {
    /// Below this: degraded governance (S5 authority reduced)
    pub degraded_threshold: f64,
    /// Below this: compromised (A0 violation, channels revoked)
    pub compromised_threshold: f64,
    /// Learning rate for trust updates
    pub lambda: f64,
}

impl Default for TrustPolicy {
    fn default() -> Self {
        Self {
            degraded_threshold: 0.3,
            compromised_threshold: 0.1,
            lambda: 0.4,
        }
    }
}

impl TrustPolicy {
    /// Evaluate trust against this policy
    pub fn evaluate(&self, trust: &TrustScore) -> TrustLevel {
        if trust.score() <= self.compromised_threshold {
            TrustLevel::Compromised
        } else if trust.score() <= self.degraded_threshold {
            TrustLevel::Degraded
        } else {
            TrustLevel::Healthy
        }
    }
}

/// Trust evaluation result
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrustLevel {
    Healthy,
    Degraded,
    Compromised,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_trust_bounds() {
        let t = TrustScore::new(1.5);
        assert_eq!(t.score(), 1.0); // clamped

        let t = TrustScore::new(-0.5);
        assert_eq!(t.score(), 0.0); // clamped
    }

    #[test]
    fn test_trust_update() {
        let mut t = TrustScore::new(0.5);
        t.update(1.0, 0.4); // observation=1.0, λ=0.4
        // 0.6 * 0.5 + 0.4 * 1.0 = 0.3 + 0.4 = 0.7
        assert!((t.score() - 0.7).abs() < 0.001);
    }

    #[test]
    fn test_trust_revoke() {
        let mut t = TrustScore::new(0.9);
        t.revoke();
        assert_eq!(t.score(), 0.0);
    }

    #[test]
    fn test_trust_compose() {
        let children = vec![
            (TrustScore::new(0.8), 0.5),
            (TrustScore::new(0.6), 0.5),
        ];
        let composed = TrustScore::compose_weighted(&children).unwrap();
        // weighted_sum = 0.8*0.5 + 0.6*0.5 = 0.7
        // min_trust = 0.6, min_trust + epsilon = 0.61
        // min(0.7, 0.61) = 0.61
        assert!((composed.score() - 0.61).abs() < 0.001);
    }

    #[test]
    fn test_trust_policy() {
        let policy = TrustPolicy::default();
        assert_eq!(policy.evaluate(&TrustScore::new(0.5)), TrustLevel::Healthy);
        assert_eq!(policy.evaluate(&TrustScore::new(0.2)), TrustLevel::Degraded);
        assert_eq!(policy.evaluate(&TrustScore::new(0.05)), TrustLevel::Compromised);
    }

    #[test]
    fn test_trust_policy_parametrizable() {
        let policy = TrustPolicy {
            degraded_threshold: 0.7,
            compromised_threshold: 0.3,
            lambda: 0.2,
        };
        assert_eq!(policy.evaluate(&TrustScore::new(0.5)), TrustLevel::Degraded);
        assert_eq!(policy.evaluate(&TrustScore::new(0.1)), TrustLevel::Compromised);
    }
}
