//! Error types for VSL Core

use thiserror::Error;

/// Core VSL errors — every variant maps to a covenant violation
#[derive(Error, Debug, Clone, PartialEq)]
pub enum VslError {
    /// A0: purpose intersects prohibited set
    #[error("A0 violation: purpose '{purpose}' intersects prohibited set")]
    A0Violation { purpose: String },

    /// A0.1: purpose altered under resource pressure
    #[error("A0.1 violation: purpose altered under {pressure}")]
    A01Violation { pressure: String },

    /// Axiom dependency failure — if A1 fails, A4/A5/A7/A8 are invalid
    #[error("axiom {axiom} invalidated by failure of {dependency}")]
    DependencyFailure { axiom: String, dependency: String },

    /// Trust score below threshold
    #[error("trust score {score:.3} below threshold {threshold:.3}")]
    TrustBelowThreshold { score: f64, threshold: f64 },

    /// Omega membership failure — state outside viable set
    #[error("state outside viable set Omega: {reason}")]
    OmegaViolation { reason: String },

    /// Budget exhausted — A9 degradation/abort triggered
    #[error("budget exhausted: {resource} at {usage:.1}% of {capacity}")]
    BudgetExhausted {
        resource: String,
        usage: f64,
        capacity: f64,
    },

    /// Variety violation — A6 Ashby law
    #[error("variety violation: env {env_var:.1} > s3 {s3_var:.1} + s2 {s2_var:.1}")]
    VarietyViolation {
        env_var: f64,
        s3_var: f64,
        s2_var: f64,
    },
}

/// Result type for VSL operations
pub type VslResult<T> = Result<T, VslError>;
