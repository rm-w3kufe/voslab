/// nats_publisher.rs — γ.2 — Optional NATS replicator for events.jsonl
///
/// @vsm 0.3
/// canonical: matches connection_schema.json v0.2.1 §upward_channel + §algedonic_channel
///
/// Design principle: "núcleo primero" — NATS is optional. If NATS_URL env var is
/// not set, this module does nothing. The canonical ledger (events.jsonl, via
/// telemetry_canonical.rs) is always the source of truth.
///
/// When configured:
///   1. Connect to NATS (UDS preferred via nats://unix:///tmp/nats.sock, TCP fallback).
///   2. Tail /var/lib/vsf/{system_id}/events.jsonl (disk flush from canonical writer).
///   3. Publish each new event to vsf.{vsf_id}.{system_id}.up.{event_type}.
///   4. Algedonic events also publish to vsf.{vsf_id}.algedonic (NATS Core path).
///   5. Reconnect on disconnect with exponential backoff. Buffer events locally.
///
/// Reconnect strategy: async-nats handles it internally. We log + continue.
/// Buffering: a bounded queue (tokio mpsc) in front of publish.
///
/// Subject builder follows information_flow_architecture.md §7 hierarchy.

use crate::telemetry_canonical::CanonicalEvent;
use async_nats::Client;
use serde_json;
use std::env;
use std::path::Path;
use std::time::Duration;
use tokio::fs::File;
use tokio::io::{AsyncBufReadExt, AsyncSeekExt, BufReader, SeekFrom};
use tokio::sync::mpsc;
use tokio::time;

pub const DEFAULT_VSF_ID: &str = "alpha"; // first VSF instance; multi-VSF will parameterize
pub const POLL_INTERVAL_MS: u64 = 200; // tail polling interval
pub const QUEUE_CAPACITY: usize = 1024;

/// Build the canonical subject for a given event.
pub fn subject_for_event(vsf_id: &str, system_id: &str, event: &CanonicalEvent) -> String {
    if event.event_type == "algedonic_emit" {
        format!("vsf.{}.algedonic", vsf_id)
    } else {
        format!(
            "vsf.{}.{}.up.{}",
            vsf_id, system_id, event.event_type
        )
    }
}

/// Connect to NATS with the given URL. Returns None if URL unset.
pub async fn maybe_connect() -> Option<Client> {
    let url = env::var("NATS_URL").ok()?;
    if url.is_empty() {
        return None;
    }
    match vsf_agent::nats::connect(&url, "vsf-nucleus").await {
        Ok(c) => {
            eprintln!("[nats_publisher] connected to {}", url);
            Some(c)
        }
        Err(e) => {
            eprintln!("[nats_publisher] connect to {} failed: {} — continuing without NATS", url, e);
            None
        }
    }
}

/// Spawn the publisher background task. Returns a JoinHandle. Does nothing if NATS unconfigured.
pub fn start_publisher_task(
    system_id: String,
    events_jsonl_path: std::path::PathBuf,
) -> tokio::task::JoinHandle<()> {
    let vsf_id = env::var("VSF_ID").unwrap_or_else(|_| DEFAULT_VSF_ID.to_string());

    tokio::spawn(async move {
        let client = match maybe_connect().await {
            Some(c) => c,
            None => {
                eprintln!("[nats_publisher] NATS_URL unset or unreachable — running with events.jsonl only");
                return;
            }
        };

        // Bounded queue between tailer and publisher to handle bursts.
        // Carries (parsed event — for subject routing, raw line — published verbatim).
        let (tx, mut rx) = mpsc::channel::<(CanonicalEvent, String)>(QUEUE_CAPACITY);

        // Tailer task: poll the disk events.jsonl and push new events into the queue.
        let path = events_jsonl_path.clone();
        let _tailer = tokio::spawn(async move {
            if let Err(e) = tail_events(&path, tx).await {
                eprintln!("[nats_publisher tailer] error: {}", e);
            }
        });

        // Publisher loop: drain the queue and publish.
        while let Some((event, raw_line)) = rx.recv().await {
            let subject = subject_for_event(&vsf_id, &system_id, &event);
            // LEDGER-DEAF-P3 Leg B fix: publish the RAW events.jsonl line, NOT a
            // re-serialisation (serde_json::to_vec). The from_str → to_vec round-trip
            // could flip a metrics number's serde_json PosInt/Float classification,
            // which canonical_hash encodes differently (u64 tag vs f64 tag) → a
            // subscriber recomputing canonical_hash (S3*) diverged from the stored
            // hash and raised FALSE content_tamper. The file line is the exact bytes
            // whose parse produced the stored hash (verified: the independent Python
            // verifier over the file matches 100%), so publishing it verbatim makes
            // any recompute match the writer. Subject still comes from the parsed event.
            if let Err(e) = client.publish(subject.clone(), raw_line.into_bytes().into()).await {
                eprintln!("[nats_publisher] publish to {} failed: {}", subject, e);
                // async-nats handles reconnect internally; we just continue.
            }
        }
    })
}

/// Tail an events.jsonl file: read existing tail position, then poll for new lines.
async fn tail_events(
    path: &Path,
    tx: mpsc::Sender<(CanonicalEvent, String)>,
) -> std::io::Result<()> {
    let mut pos: u64 = 0;
    // Initial: skip existing content (we don't republish history on restart;
    // operators can manually replay if needed).
    if let Ok(meta) = tokio::fs::metadata(path).await {
        pos = meta.len();
    }

    loop {
        let mut file = match File::open(path).await {
            Ok(f) => f,
            Err(_) => {
                // File not yet created; wait.
                time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
                continue;
            }
        };
        let size = file.metadata().await?.len();
        if size <= pos {
            time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
            continue;
        }
        file.seek(SeekFrom::Start(pos)).await?;
        let reader = BufReader::new(file);
        let mut lines = reader.lines();
        while let Some(line) = lines.next_line().await? {
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<CanonicalEvent>(&line) {
                Ok(ev) => {
                    // Send the parsed event (subject routing) AND the raw line
                    // (published verbatim — see the publisher loop, LEDGER-DEAF-P3).
                    if tx.send((ev, line)).await.is_err() {
                        return Ok(()); // publisher dropped
                    }
                }
                Err(e) => eprintln!("[nats_publisher tailer] skip malformed line: {}", e),
            }
        }
        pos = size;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_event(event_type: &str) -> CanonicalEvent {
        CanonicalEvent {
            ts: "2026-05-24T00:00:00Z".into(),
            system_id: "vsf-nucleus".into(),
            event_type: event_type.into(),
            status: "ok".into(),
            signal_status: "resolved".into(),
            duration_s: 0.0,
            metrics: serde_json::json!({}),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        }
    }

    #[test]
    fn subject_normal_event() {
        let e = make_event("kernel_tick");
        let s = subject_for_event("alpha", "vsf-nucleus", &e);
        assert_eq!(s, "vsf.alpha.vsf-nucleus.up.kernel_tick");
    }

    #[test]
    fn subject_algedonic_event() {
        let e = make_event("algedonic_emit");
        let s = subject_for_event("alpha", "vsf-nucleus", &e);
        assert_eq!(s, "vsf.alpha.algedonic");
    }
}
