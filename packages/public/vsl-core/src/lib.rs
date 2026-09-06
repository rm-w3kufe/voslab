//! VSL Core — formal language for viable systems
//!
//! Implements the VSF formal specification:
//! - A0/A0.1: Ethical purpose + anti-fragility against capture
//! - A1-A11: Universal axioms (recursion, budget, Ashby, etc.)
//! - A12-A15: Extension axioms (hardware ceiling, recurrent set, etc.)
//! - Trust model: Composable, verifiable trust
//! - VSM structure: S1-S5 with channels
//!
//! This crate is the runtime substrate for covenant enforcement.
//! Every axiom is a Rust trait — the compiler verifies compliance.

pub mod axioms;
pub mod error;
pub mod purpose;
pub mod structure;
pub mod trust;

pub use error::VslError;
pub use purpose::Purpose;
pub use structure::{Channel, Level, Vsm};
pub use trust::TrustScore;
