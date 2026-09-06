//! A0 Fitness — GA fitness penalty for A0 misalignment
//!
//! From covenant conformity audit P0:
//!   "Add a fitness component (10-20%) that verifies predicate alignment
//!    with A0. Use the same gate as P0 above."
//!
//! In a genetic algorithm, each genome (predicate) has a fitness score.
//! This module provides the A0 fitness component that penalizes genomes
//! whose predicates intersect the prohibited set.
//!
//! Usage in GA:
//!   let a0 = A0Fitness::new(0.15); // 15% weight
//!   let score = a0.compute_fitness("optimize_api_timeout");
//!   // score = 1.0 (aligned)
//!
//!   let score = a0.compute_fitness("warfare_instrumentation");
//!   // score = 0.0 (prohibited → genome dies)
//!
//! Integration:
//!   final_fitness = accuracy_fitness * (1.0 - a0_weight)
//!                 + a0_fitness * a0_weight

use crate::a0_gate::A0Gate;

/// A0 fitness component for GA
pub struct A0Fitness {
    /// Weight of A0 fitness in total fitness (0.0 - 1.0)
    /// Recommended: 0.10 - 0.20 (10-20%)
    weight: f64,
    /// The underlying gate
    gate: A0Gate,
}

impl A0Fitness {
    /// Create a new fitness component with the given weight
    ///
    /// # Panics
    /// Panics if weight is not in [0.0, 1.0]
    pub fn new(weight: f64) -> Self {
        assert!(
            (0.0..=1.0).contains(&weight),
            "weight must be in [0.0, 1.0], got {weight}"
        );
        Self {
            weight,
            gate: A0Gate::new(),
        }
    }

    /// Create with additional prohibited keywords
    pub fn with_prohibited(weight: f64, keywords: &[String]) -> Self {
        assert!(
            (0.0..=1.0).contains(&weight),
            "weight must be in [0.0, 1.0], got {weight}"
        );
        Self {
            weight,
            gate: A0Gate::with_prohibited(keywords),
        }
    }

    /// Get the weight
    pub fn weight(&self) -> f64 {
        self.weight
    }

    /// Compute A0 fitness for a predicate.
    ///
    /// Returns 1.0 if the predicate is aligned with approved purposes.
    /// Returns 0.0 if the predicate intersects the prohibited set.
    /// Returns 0.5 if the predicate is neutral (no clear alignment).
    pub fn compute_fitness(&self, predicate_name: &str) -> f64 {
        // Check if prohibited
        if self.gate.validate_name(predicate_name).is_err() {
            return 0.0; // prohibited → genome dies
        }

        // Check if aligned with approved purposes
        if self.gate.aligns_with_purpose(predicate_name) {
            return 1.0; // aligned → full fitness
        }

        // Neutral → partial fitness
        0.5
    }

    /// Compute A0 fitness for a genome (fault + correction pair)
    pub fn compute_genome_fitness(
        &self,
        fault_signature: &str,
        correction_path: &str,
    ) -> f64 {
        // Check if either part is prohibited
        if self.gate.validate_predicate(fault_signature, correction_path).is_err() {
            return 0.0; // prohibited → genome dies
        }

        // Check alignment of both parts
        let fault_aligned = self.gate.aligns_with_purpose(fault_signature);
        let correction_aligned = self.gate.aligns_with_purpose(correction_path);

        match (fault_aligned, correction_aligned) {
            (true, true) => 1.0,   // both aligned
            (true, false) | (false, true) => 0.7, // one aligned
            (false, false) => 0.5, // both neutral
        }
    }

    /// Combine A0 fitness with other fitness components.
    ///
    /// final = base_fitness * (1 - weight) + a0_fitness * weight
    pub fn combine(&self, base_fitness: f64, a0_fitness: f64) -> f64 {
        base_fitness * (1.0 - self.weight) + a0_fitness * self.weight
    }
}

impl Default for A0Fitness {
    fn default() -> Self {
        Self::new(0.15) // 15% weight by default
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_aligned_predicate_full_fitness() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_fitness("optimize_api_timeout");
        assert_eq!(score, 1.0);
    }

    #[test]
    fn test_prohibited_predicate_zero_fitness() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_fitness("warfare_instrumentation");
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_neutral_predicate_partial_fitness() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_fitness("handle_request");
        assert_eq!(score, 0.5);
    }

    #[test]
    fn test_genome_both_aligned() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_genome_fitness(
            "optimize_api_timeout",
            "improve_performance",
        );
        assert_eq!(score, 1.0);
    }

    #[test]
    fn test_genome_prohibited() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_genome_fitness(
            "warfare_active",
            "increase_timeout",
        );
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_genome_one_aligned() {
        let a0 = A0Fitness::new(0.15);
        let score = a0.compute_genome_fitness(
            "optimize_api_timeout",
            "handle_request",
        );
        assert_eq!(score, 0.7);
    }

    #[test]
    fn test_combine() {
        let a0 = A0Fitness::new(0.20);
        // base=0.8, a0=1.0, weight=0.20
        // final = 0.8 * 0.80 + 1.0 * 0.20 = 0.64 + 0.20 = 0.84
        let combined = a0.combine(0.8, 1.0);
        assert!((combined - 0.84).abs() < 0.001);
    }

    #[test]
    fn test_combine_zero_a0() {
        let a0 = A0Fitness::new(0.15);
        // base=0.9, a0=0.0, weight=0.15
        // final = 0.9 * 0.85 + 0.0 * 0.15 = 0.765
        let combined = a0.combine(0.9, 0.0);
        assert!((combined - 0.765).abs() < 0.001);
    }

    #[test]
    fn test_weight_boundary() {
        let a0 = A0Fitness::new(0.0);
        assert_eq!(a0.weight(), 0.0);
        let a0 = A0Fitness::new(1.0);
        assert_eq!(a0.weight(), 1.0);
    }

    #[test]
    #[should_panic]
    fn test_weight_out_of_bounds() {
        A0Fitness::new(1.5);
    }
}
