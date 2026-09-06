//! A0 Gate — purpose validation for predicate registration
//!
//! From covenant conformity audit P0:
//!   "Before _register_predicate(), verify that fault_signature and
//!    correction_path do not intersect the A0 prohibited set."
//!
//! This module provides a simple API for pipeline integration:
//!
//!   let gate = A0Gate::new();
//!   gate.validate_predicate("timeout_on_api", "increase_timeout")?;
//!
//! If the predicate intersects the prohibited set, the gate returns
//! an error and the pipeline MUST NOT register it.

use crate::error::{VslError, VslResult};

/// Prohibited keywords that indicate A0 violations in predicate names.
/// These are derived from covenant.vsm §A0 prohibited set.
pub const PROHIBITED_KEYWORDS: &[&str] = &[
    "warfare",
    "weapon",
    "annihilation",
    "nuclear",
    "displacement",
    "ethnic_suppression",
    "cultural_suppression",
    "authoritarian",
    "degradation_of_life",
    "coercion",
    "capture",
    "override_purpose",
    "bypass_ethics",
    "disable_safety",
    "shadow_control",
    "force_action",
    "manipulate",
    "deceive",
    "censor",
    "suppress",
    "destroy",
    "eliminate",
    "subjugate",
    "oppress",
    "exploit",
    "harm",
    "kill",
    "attack",
    "bomb",
    "torture",
    "enslave",
];

/// The A0 gate — validates predicates before registration
pub struct A0Gate {
    /// Additional prohibited keywords (extensible)
    extra_prohibited: Vec<String>,
}

impl A0Gate {
    /// Create a new gate with default prohibited keywords
    pub fn new() -> Self {
        Self {
            extra_prohibited: Vec::new(),
        }
    }

    /// Create a gate with additional prohibited keywords
    pub fn with_prohibited(keywords: &[String]) -> Self {
        Self {
            extra_prohibited: keywords.to_vec(),
        }
    }

    /// Validate a predicate before registration.
    ///
    /// Checks both `fault_signature` and `correction_path` against
    /// the A0 prohibited set.
    ///
    /// # Arguments
    /// * `fault_signature` — description of the fault being corrected
    /// * `correction_path` — the proposed correction
    ///
    /// # Returns
    /// Ok(A0 verdict) if the predicate is safe to register.
    /// Err(A0Violation) if the predicate intersects the prohibited set.
    pub fn validate_predicate(
        &self,
        fault_signature: &str,
        correction_path: &str,
    ) -> VslResult<()> {
        self.check_string(fault_signature, "fault_signature")?;
        self.check_string(correction_path, "correction_path")?;
        Ok(())
    }

    /// Validate a predicate name only (lighter check)
    pub fn validate_name(&self, name: &str) -> VslResult<()> {
        self.check_string(name, "predicate_name")
    }

    /// Check a single string against prohibited keywords
    fn check_string(&self, input: &str, field_name: &str) -> VslResult<()> {
        let lower = input.to_lowercase();

        // Check built-in prohibited keywords
        for keyword in PROHIBITED_KEYWORDS {
            if lower.contains(keyword) {
                return Err(VslError::A0Violation {
                    purpose: format!(
                        "{field_name} '{input}' contains prohibited keyword '{keyword}'"
                    ),
                });
            }
        }

        // Check extra prohibited keywords
        for keyword in &self.extra_prohibited {
            if lower.contains(&keyword.to_lowercase()) {
                return Err(VslError::A0Violation {
                    purpose: format!(
                        "{field_name} '{input}' contains prohibited keyword '{keyword}'"
                    ),
                });
            }
        }

        Ok(())
    }

    /// Check if a predicate aligns with approved purposes
    ///
    /// This is a positive check — does the predicate support one of the
    /// approved purposes? Returns true if the predicate name contains
    /// keywords associated with approved purposes.
    pub fn aligns_with_purpose(&self, predicate_name: &str) -> bool {
        let lower = predicate_name.to_lowercase();
        let approved_keywords = [
            "liberation",
            "stability",
            "dignity",
            "harmony",
            "amplification",
            "help",
            "support",
            "improve",
            "optimize",
            "stabilize",
            "protect",
            "heal",
            "grow",
            "learn",
            "adapt",
        ];
        approved_keywords
            .iter()
            .any(|kw| lower.contains(kw))
    }
}

impl Default for A0Gate {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clean_predicate_passes() {
        let gate = A0Gate::new();
        let result = gate.validate_predicate(
            "timeout_on_api",
            "increase_timeout",
        );
        assert!(result.is_ok());
    }

    #[test]
    fn test_warfare_in_fault_fails() {
        let gate = A0Gate::new();
        let result = gate.validate_predicate(
            "warfare_instrumentation_active",
            "increase_timeout",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_weapon_in_correction_fails() {
        let gate = A0Gate::new();
        let result = gate.validate_predicate(
            "timeout_on_api",
            "deploy_weapons_system",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_authoritarian_in_name_fails() {
        let gate = A0Gate::new();
        let result = gate.validate_name("authoritarian_control_override");
        assert!(result.is_err());
    }

    #[test]
    fn test_extra_prohibited_keywords() {
        let gate = A0Gate::with_prohibited(&["custom_bad".to_string()]);
        let result = gate.validate_predicate(
            "timeout_on_api",
            "custom_bad_thing",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_purpose_alignment() {
        let gate = A0Gate::new();
        assert!(gate.aligns_with_purpose("optimize_performance"));
        assert!(gate.aligns_with_purpose("protect_system"));
        assert!(!gate.aligns_with_purpose("destroy_everything"));
    }

    #[test]
    fn test_case_insensitive() {
        let gate = A0Gate::new();
        let result = gate.validate_predicate(
            "WARFARE_active",
            "increase_timeout",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_strings_pass() {
        let gate = A0Gate::new();
        let result = gate.validate_predicate("", "");
        assert!(result.is_ok());
    }
}
