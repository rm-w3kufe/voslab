/// bbh_subscriber.rs — γ.9 — Cross-system event subscriber for BBH (or any S1)
///
/// @vsm 0.3
/// canonical: matches connection_schema.json v0.2.1 §upward_channel
///
/// Purpose:
///   Subscribe to NATS subjects emitted by BBH (running as S1 inside V_vsf),
///   persist each event into the SHARED canonical events.jsonl chain so that
///   GATE_3 K_φ↑ measurement can observe cross-system variety in one ordered
///   ledger. BBH's local chain (if any) and VSF's chain become the same chain
///   by virtue of this subscriber's emit() calls.
///
/// Design principle: "núcleo primero" — no parallel ChainState. We consume the
/// CanonicalTelemetry handle from operational.rs (single Merkle chain). Per
/// CanonicalTelemetry::emit() contract, prev_hash + hash are overwritten on
/// emit, so we can accept any incoming hash and re-chain it inside VSF.
///
/// Pattern: subscribe "bbh.>" — catch-all for all BBH instances + channels.
///   BBH publisher subjects (per gate3_experimental_plan §4.1):
///     bbh.<inst>.phi_up.<event_type>
///     bbh.<inst>.algedonic
///   We do NOT subscribe to vsf.> (would re-ingest our own outbound).
///
/// Phase carrying:
///   BBH puts `phase` field inside metrics object so we do NOT need to extend
///   CanonicalEvent schema. Markov analysis reads metrics.phase.
///
/// Errors are logged, never propagated. NATS_URL unset = no-op (covenant: no
/// hidden dependency on NATS availability).

use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use futures::StreamExt;
use serde_json::Value;
use std::env;

pub const DEFAULT_BBH_SUBJECT: &str = "bbh.>";

/// Spawn the BBH subscriber background task. Returns a JoinHandle.
/// If NATS_URL is unset, the task connects-not and immediately exits (no-op).
pub fn start_subscriber_task(
    canon: CanonicalTelemetry,
    subject_pattern: Option<String>,
) -> tokio::task::JoinHandle<()> {
    let subject = subject_pattern.unwrap_or_else(|| DEFAULT_BBH_SUBJECT.to_string());

    tokio::spawn(async move {
        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!(
                    "[bbh_subscriber] NATS_URL unset — running with VSF-local events only"
                );
                return;
            }
        };

        let client = match vsf_agent::nats::connect(&url, "vsf-bbh-subscriber").await {
            Ok(c) => {
                eprintln!("[bbh_subscriber] connected to {} (pattern: {})", url, subject);
                c
            }
            Err(e) => {
                eprintln!(
                    "[bbh_subscriber] connect to {} failed: {} — γ.9 disabled",
                    url, e
                );
                return;
            }
        };

        let mut sub = match client.subscribe(subject.clone()).await {
            Ok(s) => s,
            Err(e) => {
                eprintln!(
                    "[bbh_subscriber] subscribe({}) failed: {} — γ.9 disabled",
                    subject, e
                );
                return;
            }
        };
        eprintln!(
            "[bbh_subscriber] ready — relaying {} → events.jsonl",
            subject
        );

        let mut received: u64 = 0;
        let mut emitted: u64 = 0;
        while let Some(msg) = sub.next().await {
            received = received.wrapping_add(1);

            // Parse payload leniently. BBH publishers may evolve schema.
            let raw: Value = match serde_json::from_slice(&msg.payload) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!(
                        "[bbh_subscriber] skip malformed payload on {}: {}",
                        msg.subject, e
                    );
                    continue;
                }
            };

            // Build a CanonicalEvent. Missing fields fall back to safe defaults.
            let event = build_event_from_value(&msg.subject, raw);

            if let Err(e) = canon.emit(event) {
                eprintln!("[bbh_subscriber] canonical emit failed: {}", e);
                continue;
            }
            emitted = emitted.wrapping_add(1);
            if emitted % 100 == 0 {
                eprintln!(
                    "[bbh_subscriber] relayed {} events (received={})",
                    emitted, received
                );
            }
        }

        eprintln!(
            "[bbh_subscriber] subscription closed (received={}, emitted={})",
            received, emitted
        );
    })
}

/// Translate a raw BBH NATS payload + subject into a CanonicalEvent for our chain.
///
/// Rules (lenient — never panic):
///   - `event_type`: prefer payload.event_type; else derive from last subject token
///   - `system_id`: prefer payload.system_id; else "bbh" (subject namespace)
///   - `ts`: prefer payload.ts; else canon.emit() will fill with Utc::now()
///   - `metrics`: pass-through payload.metrics; else wrap whole payload
///   - prev_hash / hash: ALWAYS None — emit() owns the chain
fn build_event_from_value(subject: &str, raw: Value) -> CanonicalEvent {
    let payload_obj = raw.as_object();

    let event_type = payload_obj
        .and_then(|m| m.get("event_type"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| derive_event_type_from_subject(subject));

    let system_id = payload_obj
        .and_then(|m| m.get("system_id"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| "bbh".to_string());

    let ts = payload_obj
        .and_then(|m| m.get("ts"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_default();

    let status = payload_obj
        .and_then(|m| m.get("status"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| "ok".to_string());

    let signal_status = payload_obj
        .and_then(|m| m.get("signal_status"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| "resolved".to_string());

    let duration_s = payload_obj
        .and_then(|m| m.get("duration_s"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);

    // Preserve metrics block (where BBH carries `phase` + scan-specific data).
    // If absent, wrap the whole payload so nothing is lost.
    let metrics = payload_obj
        .and_then(|m| m.get("metrics"))
        .cloned()
        .unwrap_or_else(|| {
            let mut wrap = serde_json::Map::new();
            wrap.insert("_origin_subject".to_string(), Value::String(subject.to_string()));
            wrap.insert("_raw_payload".to_string(), raw.clone());
            Value::Object(wrap)
        });

    let variety_delta = payload_obj
        .and_then(|m| m.get("variety_delta"))
        .and_then(|v| v.as_f64());
    let trust_score = payload_obj
        .and_then(|m| m.get("trust_score"))
        .and_then(|v| v.as_f64());

    CanonicalEvent {
        ts,
        system_id,
        event_type,
        status,
        signal_status,
        duration_s,
        metrics,
        variety_delta,
        trust_score,
        algedonic_seq: 0, // canon.emit() bumps for algedonic_emit
        origin: None,
        chain_format_version: None,
        prev_hash: None,  // canon.emit() overwrites
        hash: None,       // canon.emit() computes
    }
}

/// Fallback: subject `bbh.alpha.phi_up.tool_run` → "tool_run".
fn derive_event_type_from_subject(subject: &str) -> String {
    subject
        .rsplit('.')
        .next()
        .unwrap_or("bbh_unknown")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derive_event_type_from_terminal_token() {
        assert_eq!(
            derive_event_type_from_subject("bbh.alpha.phi_up.tool_run"),
            "tool_run"
        );
        assert_eq!(
            derive_event_type_from_subject("bbh.beta.algedonic"),
            "algedonic"
        );
    }

    #[test]
    fn build_event_with_full_payload() {
        let raw = serde_json::json!({
            "ts": "2026-05-25T12:00:00Z",
            "system_id": "bbh",
            "event_type": "phase_complete",
            "status": "ok",
            "signal_status": "resolved",
            "duration_s": 1.5,
            "metrics": { "phase": "B2_ACTIVE", "findings": 3 },
            "variety_delta": 0.2,
            "trust_score": 0.9
        });
        let e = build_event_from_value("bbh.alpha.phi_up.phase_complete", raw);
        assert_eq!(e.event_type, "phase_complete");
        assert_eq!(e.system_id, "bbh");
        assert_eq!(e.duration_s, 1.5);
        assert_eq!(
            e.metrics.get("phase").and_then(|v| v.as_str()),
            Some("B2_ACTIVE")
        );
        assert!(e.prev_hash.is_none());
        assert!(e.hash.is_none());
    }

    #[test]
    fn build_event_with_minimal_payload() {
        let raw = serde_json::json!({});
        let e = build_event_from_value("bbh.alpha.phi_up.tool_run", raw);
        assert_eq!(e.event_type, "tool_run"); // derived from subject
        assert_eq!(e.system_id, "bbh"); // default
        assert_eq!(e.status, "ok");
        assert!(e.metrics.is_object()); // wrapped raw
    }
}
