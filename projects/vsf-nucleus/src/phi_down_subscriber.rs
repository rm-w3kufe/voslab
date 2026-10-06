/// phi_down_subscriber.rs — γ.10 — φ↓ parameter application channel
///
/// @vsm 0.4  (PHI-DOWN-APPLY-GATE, 2026-06-16)
/// canonical: matches connection_schema.json v0.2.1 §downward_channel
///
/// Purpose:
///   Receive S5 policy overrides via NATS, apply them to a shared NucleusConfig
///   (Arc<RwLock<>>) so the S4 thread reads new values on its next cycle, and
///   emit a canonical `param_change` event recording the application.
///
/// Apply-time validation (PHI-DOWN-APPLY-GATE, task 2026-06-16):
///   Before applying, each field is classified using reframe.rs::ReframeScope:
///     L2 (ParameterDrift)   — applied autonomously if within bounds.
///     L2+SAFETY             — applied autonomously but telemetry_interval_secs capped at 300s.
///     L3 (AxiomOrTopology)  — REJECTED. Cannot apply autonomously. Requires human
///                             approval via the full reframe.rs staged pipeline (A5/D4-L3).
///   Rejected fields are logged and included in the param_change event (rejected_l3 /
///   rejected_bounds). S3* (phi_down_audit.rs) audits these events post-hoc.
///
///   scope_policy authority: reframe.rs::ReframeScope (Q1 decision 2026-06-16).
///   This is the enforcement complement to the S3* audit (defense in depth +
///   crash domain separation). See docs/spec/phi_down_audit/spec.vsm §apply_time_complement.
///
/// "núcleo primero": NATS_URL unset → graceful no-op (config remains immutable).

use crate::config::NucleusConfig;
use crate::reframe::ReframeScope;
use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use futures::StreamExt;
use serde::Deserialize;
use serde_json::Value;
use std::env;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};

// ── Scope policy (authority: reframe.rs::Ax_ReframeScope, Q1 decision 2026-06-16) ──
//
// L3 (AxiomOrTopology) = capability/topology/identity change → requires human.
// L2 (ParameterDrift)  = operational parameter drift → kernel-autonomous within bounds.
//
// This table is the apply-time enforcement; S3* phi_down_audit.rs audits post-hoc.

const L3_FIELDS: &[&str] = &[
    "mode",             // operational mode = topology change
    "ollama_url",       // endpoint redirection = capability change
    "bbs_url",          // endpoint redirection = capability change
    "ollama_model",     // cognitive engine swap = capability change
    "nucleus_source_id", // identity change — capture indicator
];

// Bounds for L2 numeric fields [min, max] inclusive.
const L2_NUMERIC_BOUNDS: &[(&str, u32, u32)] = &[
    ("s4_cycle_interval_secs", 30, 3600),
    ("telemetry_interval_secs", 10, 300), // 300 = SAFETY ceiling (algedonic blinding risk)
    ("ollama_timeout_secs", 10, 600),
];

const LOG_LEVEL_VALID: &[&str] = &["error", "warn", "info", "debug"];

/// Classify a ConfigPatch field name using Ax_ReframeScope.
/// Unknown fields → ParameterDrift (most fields are L2; L3 list is explicit).
fn scope_of_field(key: &str) -> ReframeScope {
    if L3_FIELDS.contains(&key) {
        ReframeScope::AxiomOrTopology
    } else {
        ReframeScope::ParameterDrift
    }
}

fn in_bounds_u32(key: &str, value: u32) -> bool {
    L2_NUMERIC_BOUNDS
        .iter()
        .find(|(k, _, _)| *k == key)
        .map_or(true, |&(_, min, max)| value >= min && value <= max)
}

// DEBT_S1 — S1 viability gate: reject φ↓ that would reduce governance responsiveness
// when the system is in a degraded state (stasis_cos below threshold).
// Ashby: S1 has sufficient variety to refuse instructions that threaten its viability.
pub const S1_VIABILITY_THRESHOLD: f64 = 0.85;
// Fields that, if increased, reduce governance responsiveness (lower = more governance).
const GOVERNANCE_FREQ_FIELDS: &[&str] = &["s4_cycle_interval_secs", "telemetry_interval_secs"];

/// Result of apply-time validation — used for audit trail in param_change event.
#[derive(Debug, Default)]
pub struct PatchValidation {
    pub applied:             Vec<&'static str>,
    pub rejected_l3:         Vec<&'static str>,
    pub rejected_bounds:     Vec<&'static str>,
    pub rejected_viability:  Vec<&'static str>, // DEBT_S1: would reduce governance when degraded
}

pub const DEFAULT_VSF_ID: &str = "alpha";

/// Subject builder — caller can override pattern if needed.
pub fn default_subject() -> String {
    let vsf_id = env::var("VSF_ID").unwrap_or_else(|_| DEFAULT_VSF_ID.to_string());
    format!("vsf.{}.phi_down.params", vsf_id)
}

/// Partial config patch — every field optional. Deserialized from JSON payload.
#[derive(Debug, Deserialize, Default)]
struct ConfigPatch {
    pub mode: Option<String>,
    pub s4_cycle_interval_secs: Option<u32>,
    pub telemetry_interval_secs: Option<u32>,
    pub bbs_url: Option<String>,
    pub ollama_url: Option<String>,
    pub ollama_model: Option<String>,
    pub ollama_timeout_secs: Option<u32>,
    pub nucleus_source_id: Option<String>,
    pub log_level: Option<String>,
    #[serde(rename = "_origin")]
    pub origin: Option<String>,
    #[serde(rename = "_reason")]
    pub reason: Option<String>,
}

impl ConfigPatch {
    /// PHI-DOWN-APPLY-GATE: validate scope + bounds, then apply only the safe subset.
    ///
    /// Returns a PatchValidation with three disjoint lists:
    ///   applied         — L2 fields that were applied (may be empty on no-op)
    ///   rejected_l3     — L3 fields blocked (require human approval via reframe.rs)
    ///   rejected_bounds — L2 numeric/enum fields with out-of-range values (not applied)
    /// Validate and apply the patch. `current_stasis_cos` is the live S1 viability signal
    /// (DEBT_S1 gate): parameters that reduce governance responsiveness are rejected when
    /// the system is degraded (stasis_cos < S1_VIABILITY_THRESHOLD).
    pub fn validate_and_apply(&self, cfg: &mut NucleusConfig, current_stasis_cos: f64) -> PatchValidation {
        let mut v = PatchValidation::default();
        let degraded = current_stasis_cos < S1_VIABILITY_THRESHOLD;

        // L3 fields — classification gate. ANY L3 field present → log rejection.
        // The rest of the patch (L2 fields) is still eligible for apply.
        if self.mode.is_some()             { v.rejected_l3.push("mode"); }
        if self.ollama_url.is_some()       { v.rejected_l3.push("ollama_url"); }
        if self.bbs_url.is_some()          { v.rejected_l3.push("bbs_url"); }
        if self.ollama_model.is_some()     { v.rejected_l3.push("ollama_model"); }
        if self.nucleus_source_id.is_some(){ v.rejected_l3.push("nucleus_source_id"); }

        // L2 numeric fields — bounds gate + DEBT_S1 viability gate.
        if let Some(val) = self.s4_cycle_interval_secs {
            if !in_bounds_u32("s4_cycle_interval_secs", val) {
                v.rejected_bounds.push("s4_cycle_interval_secs");
            } else if degraded && GOVERNANCE_FREQ_FIELDS.contains(&"s4_cycle_interval_secs")
                && val > cfg.s4_cycle_interval_secs
            {
                // DEBT_S1: degraded system must not reduce S4 frequency (less governance = worse)
                v.rejected_viability.push("s4_cycle_interval_secs");
            } else if cfg.s4_cycle_interval_secs != val {
                cfg.s4_cycle_interval_secs = val;
                v.applied.push("s4_cycle_interval_secs");
            }
        }
        if let Some(val) = self.telemetry_interval_secs {
            if !in_bounds_u32("telemetry_interval_secs", val) {
                v.rejected_bounds.push("telemetry_interval_secs");
            } else if degraded && GOVERNANCE_FREQ_FIELDS.contains(&"telemetry_interval_secs")
                && val > cfg.telemetry_interval_secs
            {
                // DEBT_S1: degraded system must not reduce telemetry frequency (less visibility = worse)
                v.rejected_viability.push("telemetry_interval_secs");
            } else if cfg.telemetry_interval_secs != val {
                cfg.telemetry_interval_secs = val;
                v.applied.push("telemetry_interval_secs");
            }
        }
        if let Some(val) = self.ollama_timeout_secs {
            if in_bounds_u32("ollama_timeout_secs", val) {
                if cfg.ollama_timeout_secs != val {
                    cfg.ollama_timeout_secs = val;
                    v.applied.push("ollama_timeout_secs");
                }
            } else {
                v.rejected_bounds.push("ollama_timeout_secs");
            }
        }

        // L2 enum field — log_level.
        if let Some(ref val) = self.log_level {
            if LOG_LEVEL_VALID.contains(&val.as_str()) {
                if cfg.log_level != *val {
                    cfg.log_level = val.clone();
                    v.applied.push("log_level");
                }
            } else {
                v.rejected_bounds.push("log_level");
            }
        }

        v
    }

    /// Apply non-None fields to a mutable config and return the list of changed keys.
    /// Kept for backward compatibility and existing tests. Production code uses
    /// validate_and_apply() — see PHI-DOWN-APPLY-GATE.
    fn apply_to(&self, cfg: &mut NucleusConfig) -> Vec<&'static str> {
        let mut changed: Vec<&'static str> = Vec::new();
        if let Some(v) = &self.mode {
            if cfg.mode != *v { cfg.mode = v.clone(); changed.push("mode"); }
        }
        if let Some(v) = self.s4_cycle_interval_secs {
            if cfg.s4_cycle_interval_secs != v { cfg.s4_cycle_interval_secs = v; changed.push("s4_cycle_interval_secs"); }
        }
        if let Some(v) = self.telemetry_interval_secs {
            if cfg.telemetry_interval_secs != v { cfg.telemetry_interval_secs = v; changed.push("telemetry_interval_secs"); }
        }
        if let Some(v) = &self.bbs_url {
            if cfg.bbs_url != *v { cfg.bbs_url = v.clone(); changed.push("bbs_url"); }
        }
        if let Some(v) = &self.ollama_url {
            if cfg.ollama_url != *v { cfg.ollama_url = v.clone(); changed.push("ollama_url"); }
        }
        if let Some(v) = &self.ollama_model {
            if cfg.ollama_model != *v { cfg.ollama_model = v.clone(); changed.push("ollama_model"); }
        }
        if let Some(v) = self.ollama_timeout_secs {
            if cfg.ollama_timeout_secs != v { cfg.ollama_timeout_secs = v; changed.push("ollama_timeout_secs"); }
        }
        if let Some(v) = &self.nucleus_source_id {
            if cfg.nucleus_source_id != *v { cfg.nucleus_source_id = v.clone(); changed.push("nucleus_source_id"); }
        }
        if let Some(v) = &self.log_level {
            if cfg.log_level != *v { cfg.log_level = v.clone(); changed.push("log_level"); }
        }
        changed
    }
}

/// Spawn the φ↓ subscriber task. Returns a JoinHandle.
/// If NATS_URL unset → graceful no-op.
/// `s1_viability` is an AtomicU64 holding the current stasis_cos as f64 bits.
/// Updated by the tick loop each kernel_tick. Used for DEBT_S1 viability gate.
pub fn start_subscriber_task(
    canon: CanonicalTelemetry,
    config_lock: Arc<RwLock<NucleusConfig>>,
    subject: Option<String>,
    s1_viability: Arc<AtomicU64>,
) -> tokio::task::JoinHandle<()> {
    let subject = subject.unwrap_or_else(default_subject);
    tokio::spawn(async move {
        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[phi_down] NATS_URL unset — γ.10 disabled (config immutable)");
                return;
            }
        };

        let client = match vsf_agent::nats::connect(&url, "vsf-phi-down-subscriber").await {
            Ok(c) => {
                eprintln!("[phi_down] connected to {} (subject: {})", url, subject);
                c
            }
            Err(e) => {
                eprintln!("[phi_down] connect failed: {} — γ.10 disabled", e);
                return;
            }
        };

        let mut sub = match client.subscribe(subject.clone()).await {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[phi_down] subscribe({}) failed: {} — γ.10 disabled", subject, e);
                return;
            }
        };
        eprintln!("[phi_down] γ.10 ready — relaying {} → config + param_change", subject);

        while let Some(msg) = sub.next().await {
            // Parse patch leniently (lossless: unknown fields ignored).
            let patch: ConfigPatch = match serde_json::from_slice(&msg.payload) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("[phi_down] skip malformed patch on {}: {}", msg.subject, e);
                    continue;
                }
            };

            // PHI-DOWN-APPLY-GATE: validate scope + bounds + S1 viability before applying.
            // L3 fields blocked. L2 out-of-bounds blocked.
            // DEBT_S1: L2 governance-freq fields blocked if stasis_cos < S1_VIABILITY_THRESHOLD.
            let current_stasis_cos = f64::from_bits(s1_viability.load(Ordering::Relaxed));
            let (validation, snapshot) = {
                let mut cfg = match config_lock.write() {
                    Ok(g) => g,
                    Err(poisoned) => {
                        eprintln!("[phi_down] config RwLock poisoned — recovering");
                        poisoned.into_inner()
                    }
                };
                let v = patch.validate_and_apply(&mut cfg, current_stasis_cos);
                let snap = (*cfg).clone();
                (v, snap)
            };

            if !validation.rejected_l3.is_empty() {
                eprintln!(
                    "[phi_down] REJECTED L3 field(s) {:?} on {} — requires human approval via reframe.rs (A5/D4-L3)",
                    validation.rejected_l3, msg.subject
                );
            }
            if !validation.rejected_bounds.is_empty() {
                eprintln!(
                    "[phi_down] REJECTED out-of-bounds field(s) {:?} on {}",
                    validation.rejected_bounds, msg.subject
                );
            }
            if !validation.rejected_viability.is_empty() {
                // DEBT_S1: S1 refused φ↓ that would reduce governance when system is degraded.
                eprintln!(
                    "[phi_down] DEBT_S1 REJECTED viability field(s) {:?} on {} (stasis_cos={:.4} < {:.2})",
                    validation.rejected_viability, msg.subject, current_stasis_cos, S1_VIABILITY_THRESHOLD
                );
                let rejected_event = CanonicalEvent {
                    ts: String::new(),
                    system_id: snapshot.nucleus_source_id.clone(),
                    event_type: "phi_down_rejected".to_string(),
                    status: "rejected".to_string(),
                    signal_status: "viability_gate".to_string(),
                    duration_s: 0.0,
                    metrics: serde_json::json!({
                        "rejected_fields": validation.rejected_viability,
                        "reason": "s1_viability_gate",
                        "current_stasis_cos": current_stasis_cos,
                        "threshold": S1_VIABILITY_THRESHOLD,
                        "subject": msg.subject,
                        "_note": "DEBT_S1: S1 refused φ↓ reducing governance while degraded (Ashby: S1 self-defence)"
                    }),
                    variety_delta: None,
                    trust_score: None,
                    algedonic_seq: 0,
                    origin: None,
                    chain_format_version: None,
                    prev_hash: None,
                    hash: None,
                };
                if let Err(e) = canon.emit(rejected_event) {
                    eprintln!("[phi_down] phi_down_rejected emit failed: {}", e);
                }
            }
            if validation.applied.is_empty() && validation.rejected_viability.is_empty() {
                eprintln!("[phi_down] no-op/rejected patch on {}: nothing applied", msg.subject);
            } else if !validation.applied.is_empty() {
                eprintln!(
                    "[phi_down] applied {} key(s) on {}: {:?}",
                    validation.applied.len(), msg.subject, validation.applied
                );
            }

            let event = build_param_change_event(
                &snapshot.nucleus_source_id,
                &validation,
                &patch,
                &msg.subject,
                &msg.payload,
            );
            if let Err(e) = canon.emit(event) {
                eprintln!("[phi_down] param_change emit failed: {}", e);
            }
        }

        eprintln!("[phi_down] subscription closed");
    })
}

fn build_param_change_event(
    system_id: &str,
    validation: &PatchValidation,
    patch: &ConfigPatch,
    subject: &str,
    raw_payload: &[u8],
) -> CanonicalEvent {
    let raw: Value = serde_json::from_slice(raw_payload).unwrap_or(Value::Null);
    let status = if !validation.rejected_l3.is_empty() {
        "rejected_l3"
    } else if !validation.rejected_viability.is_empty() && validation.applied.is_empty() {
        "rejected_viability"
    } else if !validation.rejected_bounds.is_empty() && validation.applied.is_empty() {
        "rejected_bounds"
    } else if validation.applied.is_empty() {
        "noop"
    } else {
        "ok"
    };
    CanonicalEvent {
        ts: String::new(),
        system_id: system_id.to_string(),
        event_type: "param_change".to_string(),
        status: status.into(),
        signal_status: "resolved".to_string(),
        duration_s: 0.0,
        metrics: serde_json::json!({
            "_note": "P.3 phi_down application — PHI-DOWN-APPLY-GATE validated",
            "_subject": subject,
            "changed_keys": validation.applied,
            "n_changed": validation.applied.len(),
            "rejected_l3": validation.rejected_l3,
            "rejected_bounds": validation.rejected_bounds,
            "rejected_viability": validation.rejected_viability,
            "origin": patch.origin,
            "reason": patch.reason,
            "patch_raw": raw,
        }),
        variety_delta: None,
        trust_score: None,
        algedonic_seq: 0,
        // G-K.2: causal identifier echoed back from S5's _origin field.
        origin: patch.origin.clone(),
        chain_format_version: None,  // emit() will set to Some(2)
        prev_hash: None,
        hash: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apply_patch_changes_only_provided_fields() {
        let mut cfg = NucleusConfig::default();
        let original_bbs = cfg.bbs_url.clone();
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(240),
            log_level: Some("debug".to_string()),
            ..Default::default()
        };
        let changed = patch.apply_to(&mut cfg);
        assert_eq!(cfg.s4_cycle_interval_secs, 240);
        assert_eq!(cfg.log_level, "debug");
        assert_eq!(cfg.bbs_url, original_bbs); // unchanged
        assert!(changed.contains(&"s4_cycle_interval_secs"));
        assert!(changed.contains(&"log_level"));
        assert_eq!(changed.len(), 2);
    }

    #[test]
    fn apply_patch_noop_when_values_match() {
        let mut cfg = NucleusConfig::default();
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(cfg.s4_cycle_interval_secs),
            ..Default::default()
        };
        let changed = patch.apply_to(&mut cfg);
        assert!(changed.is_empty());
    }

    #[test]
    fn default_subject_uses_vsf_id_env() {
        // env var may or may not be set in test runner; just check format
        let s = default_subject();
        assert!(s.starts_with("vsf."));
        assert!(s.ends_with(".phi_down.params"));
    }

    // ── PHI-DOWN-APPLY-GATE tests ──────────────────────────────────────────────

    #[test]
    fn l2_fields_in_bounds_apply_normally() {
        let mut cfg = NucleusConfig::default();
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(120),
            ollama_timeout_secs: Some(60),
            log_level: Some("debug".to_string()),
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.s4_cycle_interval_secs, 120);
        assert_eq!(cfg.ollama_timeout_secs, 60);
        assert_eq!(cfg.log_level, "debug");
        assert!(v.applied.contains(&"s4_cycle_interval_secs"));
        assert!(v.applied.contains(&"ollama_timeout_secs"));
        assert!(v.applied.contains(&"log_level"));
        assert!(v.rejected_l3.is_empty());
        assert!(v.rejected_bounds.is_empty());
    }

    #[test]
    fn l3_field_is_rejected_not_applied() {
        let mut cfg = NucleusConfig::default();
        let original_mode = cfg.mode.clone();
        let patch = ConfigPatch {
            mode: Some("passive".to_string()),
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.mode, original_mode, "L3 mode must not change");
        assert!(v.rejected_l3.contains(&"mode"));
        assert!(v.applied.is_empty());
    }

    #[test]
    fn all_l3_fields_are_blocked() {
        let mut cfg = NucleusConfig::default();
        let patch = ConfigPatch {
            mode:             Some("x".to_string()),
            ollama_url:       Some("http://evil/".to_string()),
            bbs_url:          Some("http://evil/".to_string()),
            ollama_model:     Some("evil:latest".to_string()),
            nucleus_source_id: Some("attacker".to_string()),
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert!(v.applied.is_empty());
        assert_eq!(v.rejected_l3.len(), 5);
    }

    #[test]
    fn mixed_patch_applies_l2_rejects_l3() {
        let mut cfg = NucleusConfig::default();
        let original_model = cfg.ollama_model.clone();
        // Use 120 (not the default 300) so the value actually changes.
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(120),
            ollama_model: Some("evil:latest".to_string()), // L3
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.s4_cycle_interval_secs, 120, "L2 field should apply");
        assert_eq!(cfg.ollama_model, original_model, "L3 model must not change");
        assert!(v.applied.contains(&"s4_cycle_interval_secs"));
        assert!(v.rejected_l3.contains(&"ollama_model"));
    }

    #[test]
    fn s4_cycle_out_of_bounds_is_rejected() {
        let mut cfg = NucleusConfig::default();
        let original = cfg.s4_cycle_interval_secs;
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(99999),
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.s4_cycle_interval_secs, original, "out-of-bounds must not apply");
        assert!(v.rejected_bounds.contains(&"s4_cycle_interval_secs"));
        assert!(v.applied.is_empty());
    }

    #[test]
    fn telemetry_above_safety_ceiling_is_rejected() {
        let mut cfg = NucleusConfig::default();
        let original = cfg.telemetry_interval_secs;
        let patch = ConfigPatch {
            telemetry_interval_secs: Some(600), // exceeds 300s ceiling
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.telemetry_interval_secs, original);
        assert!(v.rejected_bounds.contains(&"telemetry_interval_secs"));
    }

    #[test]
    fn telemetry_at_ceiling_is_applied() {
        let mut cfg = NucleusConfig::default();
        let patch = ConfigPatch {
            telemetry_interval_secs: Some(300), // exactly at ceiling — should apply
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.telemetry_interval_secs, 300);
        assert!(v.applied.contains(&"telemetry_interval_secs"));
        assert!(v.rejected_bounds.is_empty());
    }

    #[test]
    fn invalid_log_level_is_rejected() {
        let mut cfg = NucleusConfig::default();
        let original = cfg.log_level.clone();
        let patch = ConfigPatch {
            log_level: Some("trace".to_string()),
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 1.0);
        assert_eq!(cfg.log_level, original);
        assert!(v.rejected_bounds.contains(&"log_level"));
    }

    #[test]
    fn scope_of_field_classifies_correctly() {
        assert!(scope_of_field("mode").requires_human());
        assert!(scope_of_field("ollama_url").requires_human());
        assert!(scope_of_field("bbs_url").requires_human());
        assert!(scope_of_field("ollama_model").requires_human());
        assert!(scope_of_field("nucleus_source_id").requires_human());
        assert!(!scope_of_field("s4_cycle_interval_secs").requires_human());
        assert!(!scope_of_field("telemetry_interval_secs").requires_human());
        assert!(!scope_of_field("ollama_timeout_secs").requires_human());
        assert!(!scope_of_field("log_level").requires_human());
    }

    // ── DEBT_S1 viability gate tests ──────────────────────────────────────────

    #[test]
    fn s1_viability_gate_blocks_s4_increase_when_degraded() {
        let mut cfg = NucleusConfig::default();
        cfg.s4_cycle_interval_secs = 60; // currently fast
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(300), // proposing slower — dangerous when degraded
            ..Default::default()
        };
        // stasis_cos below threshold → viability gate must reject
        let v = patch.validate_and_apply(&mut cfg, 0.70);
        assert_eq!(cfg.s4_cycle_interval_secs, 60, "must not apply when degraded");
        assert!(v.rejected_viability.contains(&"s4_cycle_interval_secs"));
        assert!(v.applied.is_empty());
    }

    #[test]
    fn s1_viability_gate_allows_s4_increase_when_healthy() {
        let mut cfg = NucleusConfig::default();
        cfg.s4_cycle_interval_secs = 60;
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(300),
            ..Default::default()
        };
        // stasis_cos above threshold → normal apply
        let v = patch.validate_and_apply(&mut cfg, 0.99);
        assert_eq!(cfg.s4_cycle_interval_secs, 300, "must apply when healthy");
        assert!(v.applied.contains(&"s4_cycle_interval_secs"));
        assert!(v.rejected_viability.is_empty());
    }

    #[test]
    fn s1_viability_gate_allows_s4_decrease_even_when_degraded() {
        let mut cfg = NucleusConfig::default();
        cfg.s4_cycle_interval_secs = 300; // currently slow
        let patch = ConfigPatch {
            s4_cycle_interval_secs: Some(60), // proposing faster — beneficial
            ..Default::default()
        };
        // degraded but proposing MORE governance → allow
        let v = patch.validate_and_apply(&mut cfg, 0.70);
        assert_eq!(cfg.s4_cycle_interval_secs, 60, "reducing interval (more frequent) must be allowed");
        assert!(v.applied.contains(&"s4_cycle_interval_secs"));
        assert!(v.rejected_viability.is_empty());
    }

    #[test]
    fn s1_viability_gate_blocks_telemetry_increase_when_degraded() {
        let mut cfg = NucleusConfig::default();
        cfg.telemetry_interval_secs = 30;
        let patch = ConfigPatch {
            telemetry_interval_secs: Some(120), // less frequent telemetry when degraded
            ..Default::default()
        };
        let v = patch.validate_and_apply(&mut cfg, 0.60);
        assert_eq!(cfg.telemetry_interval_secs, 30);
        assert!(v.rejected_viability.contains(&"telemetry_interval_secs"));
    }
}
