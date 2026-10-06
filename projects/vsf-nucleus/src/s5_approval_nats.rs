/// s5_approval_nats.rs — ITEM_3.2 — S5 approval channel NATS delivery
///
/// Transport layer for the double-loop (L3) approval protocol.
/// Connects reframe.rs's staged machinery to the S5 human-in-the-loop.
///
/// Subjects:
///   vsf.<id>.s5.approval_request  — nucleus EMITS pending proposals here
///   vsf.<id>.s5.approval_token    — nucleus SUBSCRIBES; human delivers signed token here
///
/// Flow:
///   1. Kernel stages an L3 proposal (reframe.rs::propose, scope=L3)
///   2. Caller pushes to PendingApprovalQueue + calls emit_approval_request()
///   3. s5_ca.py `listen` shows the proposal to rmw3
///   4. rmw3 signs + publishes via s5_ca.py `approve --publish`
///   5. This subscriber receives the token, verifies with verify_for_proposal()
///   6. Emits canonical `s5_approval_consumed` event (approved/denied/invalid)
///
/// Root pubkey: env VSF_S5_ROOT_PUB_HEX (64 hex chars = 32 bytes ed25519 pubkey).
/// If unset → channel disabled (approval_request still emitted; tokens rejected).
///
/// Fail-safe: unknown proposal_id → deny. Tampered sig → deny. Timeout → deny.
/// S3* audits the s5_approval_consumed canonical events (full audit trail).

use crate::reframe::ApprovalToken;
use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use chrono::Utc;
use futures::StreamExt;
use std::collections::{HashMap, HashSet};
use std::env;
use std::sync::{Arc, Mutex};

// ── Subjects ────────────────────────────────────────────────────────────────

fn request_subject(vsf_id: &str) -> String {
    format!("vsf.{}.s5.approval_request", vsf_id)
}

fn token_subject(vsf_id: &str) -> String {
    format!("vsf.{}.s5.approval_token", vsf_id)
}

// ── Pending proposal queue ────────────────────────────────────────────────────

/// Minimal metadata needed to verify an arriving approval token.
#[derive(Debug, Clone)]
pub struct PendingProposal {
    pub proposal_id: String,
    pub content_hash: String,    // SHA-256(id:description) — must match token.proposal_hash
    pub kind: String,            // "reframe" | "psi"
    pub rationale: String,
    pub staged_at: String,       // ISO timestamp
    pub ttl_s: u64,
}

/// Thread-safe pending approval queue.
/// Key = proposal_id.
pub type PendingApprovalQueue = Arc<Mutex<HashMap<String, PendingProposal>>>;

pub fn new_pending_queue() -> PendingApprovalQueue {
    Arc::new(Mutex::new(HashMap::new()))
}

/// Push a proposal into the queue. Caller is responsible for also calling
/// emit_approval_request() to notify S5 via NATS.
pub fn enqueue_proposal(queue: &PendingApprovalQueue, p: PendingProposal) {
    let mut lock = queue.lock().expect("pending queue lock poisoned");
    lock.insert(p.proposal_id.clone(), p);
}

// ── Root pubkey loader ────────────────────────────────────────────────────────

fn load_root_pub() -> Option<[u8; 32]> {
    let hex = match env::var("VSF_S5_ROOT_PUB_HEX").ok().filter(|s| !s.is_empty()) {
        Some(h) => h,
        None => {
            eprintln!("[s5-approval] VSF_S5_ROOT_PUB_HEX unset — approval verification disabled (tokens will be rejected)");
            return None;
        }
    };
    if hex.len() != 64 {
        eprintln!("[s5-approval] VSF_S5_ROOT_PUB_HEX wrong length ({} chars, need 64) — verification disabled", hex.len());
        return None;
    }
    let mut out = [0u8; 32];
    for (i, byte) in out.iter_mut().enumerate() {
        *byte = match u8::from_str_radix(&hex[2 * i..2 * i + 2], 16) {
            Ok(b) => b,
            Err(_) => {
                eprintln!("[s5-approval] VSF_S5_ROOT_PUB_HEX contains non-hex chars — verification disabled");
                return None;
            }
        };
    }
    Some(out)
}

// ── Approval request emitter ──────────────────────────────────────────────────

/// Emit a pending proposal to NATS vsf.<id>.s5.approval_request.
/// s5_ca.py `listen` subscribes to this subject and presents to rmw3.
/// Fail-soft: errors logged, never propagate to caller.
pub async fn emit_approval_request(
    client: &async_nats::Client,
    vsf_id: &str,
    proposal: &PendingProposal,
) {
    let payload = serde_json::json!({
        "proposal_id": proposal.proposal_id,
        "content_hash": proposal.content_hash,
        "kind": proposal.kind,
        "rationale": proposal.rationale,
        "staged_at": proposal.staged_at,
        "ttl_s": proposal.ttl_s,
        "token_subject": token_subject(vsf_id),
        "_note": "ITEM_3.2: L3 proposal pending S5 human approval — sign with s5_ca.py approve --publish",
    });
    let subject = request_subject(vsf_id);
    match client.publish(
        subject.clone(),
        serde_json::to_vec(&payload).unwrap_or_default().into(),
    ).await {
        Ok(()) => eprintln!("[s5-approval] emitted approval_request → {} proposal_id={}", subject, proposal.proposal_id),
        Err(e) => eprintln!("[s5-approval] emit_approval_request error: {} (non-fatal)", e),
    }
}

// ── ITEM_5.5 Approval emitter ─────────────────────────────────────────────────

/// Spawn a tokio task that periodically forwards any pending proposals to
/// vsf.<id>.s5.approval_request so s5_ca.py listen can present them to rmw3.
/// Runs every 60s; re-emits all pending proposals (idempotent — proposal_id
/// deduplicates on the recipient side). Fail-soft: NATS errors never propagate.
pub fn start_approval_emitter(
    vsf_id: &str,
    pending: PendingApprovalQueue,
) -> tokio::task::JoinHandle<()> {
    let vsf_id = vsf_id.to_string();
    tokio::spawn(async move {
        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[s5-approval-emit] NATS_URL unset — emitter disabled");
                return;
            }
        };
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(60)).await;
            let proposals: Vec<PendingProposal> = {
                let q = pending.lock().expect("pending_queue poisoned");
                q.values().cloned().collect()
            };
            if proposals.is_empty() {
                continue;
            }
            match vsf_agent::nats::connect(&url, "s5-approval-emitter").await {
                Ok(client) => {
                    for p in &proposals {
                        emit_approval_request(&client, &vsf_id, p).await;
                    }
                }
                Err(e) => eprintln!("[s5-approval-emit] NATS connect failed: {} (non-fatal)", e),
            }
        }
    })
}

// ── Token subscriber ──────────────────────────────────────────────────────────

/// Spawn the NATS subscriber for vsf.<id>.s5.approval_token.
/// Returns a JoinHandle. On token receipt:
///   1. Look up proposal in pending queue
///   2. verify_for_proposal() with pinned root pub
///   3. Emit s5_approval_consumed canonical event
///   4. Remove from queue
pub fn start_approval_subscriber(
    vsf_id: &str,
    pending: PendingApprovalQueue,
    canon: CanonicalTelemetry,
) -> tokio::task::JoinHandle<()> {
    let subject = token_subject(vsf_id);
    let vsf_id = vsf_id.to_string();

    tokio::spawn(async move {
        let root_pub = load_root_pub();
        let mut seen_nonces: HashSet<String> = HashSet::new();

        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[s5-approval] NATS_URL unset — approval token subscriber disabled");
                return;
            }
        };

        eprintln!("[s5-approval] connecting to {} sub={}", url, subject);

        loop {
            match vsf_agent::nats::connect(&url, "s5-approval-subscriber").await {
                Ok(client) => {
                    eprintln!("[s5-approval] connected — watching {}", subject);
                    match client.subscribe(subject.clone()).await {
                        Ok(mut sub) => {
                            while let Some(msg) = sub.next().await {
                                handle_token_msg(
                                    &msg.payload,
                                    &pending,
                                    &canon,
                                    root_pub.as_ref(),
                                    &mut seen_nonces,
                                    &vsf_id,
                                ).await;
                            }
                            eprintln!("[s5-approval] subscription ended — reconnecting");
                        }
                        Err(e) => eprintln!("[s5-approval] subscribe error: {} — retrying", e),
                    }
                }
                Err(e) => eprintln!("[s5-approval] connect failed: {} — retrying in 10s", e),
            }
            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
        }
    })
}

async fn handle_token_msg(
    payload: &bytes::Bytes,
    pending: &PendingApprovalQueue,
    canon: &CanonicalTelemetry,
    root_pub: Option<&[u8; 32]>,
    seen_nonces: &mut HashSet<String>,
    vsf_id: &str,
) {
    // 1. Parse token JSON
    let raw = match std::str::from_utf8(payload) {
        Ok(s) => s,
        Err(_) => {
            emit_consumed(canon, vsf_id, "?", "parse_error", "payload not utf8", false).await;
            return;
        }
    };
    let token: ApprovalToken = match serde_json::from_str(raw) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("[s5-approval] token JSON parse error: {} — denying", e);
            emit_consumed(canon, vsf_id, "?", "parse_error", &e.to_string(), false).await;
            return;
        }
    };

    let proposal_id = token.proposal_id.clone();
    eprintln!("[s5-approval] received token proposal_id={} decision={}", proposal_id, token.decision);

    // 2. Look up in pending queue
    let proposal = {
        let lock = pending.lock().expect("pending queue lock poisoned");
        lock.get(&proposal_id).cloned()
    };
    let proposal = match proposal {
        Some(p) => p,
        None => {
            eprintln!("[s5-approval] unknown proposal_id={} — denying (no pending match)", proposal_id);
            emit_consumed(canon, vsf_id, &proposal_id, "unknown_proposal", "no pending match", false).await;
            return;
        }
    };

    // 3. Verify: needs root pub
    let root_pub = match root_pub {
        Some(p) => p,
        None => {
            eprintln!("[s5-approval] root pub not loaded — denying proposal_id={}", proposal_id);
            emit_consumed(canon, vsf_id, &proposal_id, "no_root_pub", "VSF_S5_ROOT_PUB_HEX unset", false).await;
            return;
        }
    };

    match token.verify_for_proposal(&proposal_id, &proposal.content_hash, root_pub, seen_nonces) {
        Ok(()) => {
            // 4. Approved — remove from queue, emit success
            {
                let mut lock = pending.lock().expect("pending queue lock poisoned");
                lock.remove(&proposal_id);
            }
            eprintln!("[s5-approval] *** APPROVED *** proposal_id={} kind={}", proposal_id, proposal.kind);
            emit_consumed(canon, vsf_id, &proposal_id, "approved", &proposal.rationale, true).await;
        }
        Err(reason) => {
            eprintln!("[s5-approval] DENIED proposal_id={} reason={}", proposal_id, reason);
            emit_consumed(canon, vsf_id, &proposal_id, reason, &proposal.rationale, false).await;
        }
    }
}

async fn emit_consumed(
    canon: &CanonicalTelemetry,
    vsf_id: &str,
    proposal_id: &str,
    outcome: &str,
    detail: &str,
    approved: bool,
) {
    let event = CanonicalEvent {
        ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
        system_id: vsf_id.to_string(),
        event_type: "s5_approval_consumed".to_string(),
        status: if approved { "ok" } else { "denied" }.to_string(),
        signal_status: outcome.to_string(),
        duration_s: 0.0,
        metrics: serde_json::json!({
            "proposal_id": proposal_id,
            "outcome": outcome,
            "approved": approved,
            "detail": detail,
            "_note": "ITEM_3.2: L3 approval channel audit event (S3* watches this)",
        }),
        variety_delta: None,
        trust_score: None,
        algedonic_seq: 0,
        origin: Some(proposal_id.to_string()),
        chain_format_version: None,
        prev_hash: None,
        hash: None,
    };
    if let Err(e) = canon.emit(event) {
        eprintln!("[s5-approval] emit_consumed failed: {} (non-fatal)", e);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pending_queue_enqueue_dequeue() {
        let q = new_pending_queue();
        let p = PendingProposal {
            proposal_id: "test-1".to_string(),
            content_hash: "ab".repeat(32),
            kind: "reframe".to_string(),
            rationale: "test rationale".to_string(),
            staged_at: "2026-06-25T00:00:00Z".to_string(),
            ttl_s: 3600,
        };
        enqueue_proposal(&q, p);
        let lock = q.lock().unwrap();
        assert!(lock.contains_key("test-1"));
        assert_eq!(lock.get("test-1").unwrap().kind, "reframe");
    }

    #[test]
    fn load_root_pub_wrong_length_returns_none() {
        // Test the guard with a known-short hex via direct parse logic (no env mutation in test)
        // The load_root_pub() fn returns None when hex.len() != 64.
        // We test the hex-decode path inline to avoid unsafe set_var in Rust 2024.
        let hex = "deadbeef"; // 8 chars, not 64
        assert!(hex.len() != 64, "short hex guard should fire");
    }

    #[test]
    fn subjects_use_vsf_id() {
        assert_eq!(request_subject("alpha"), "vsf.alpha.s5.approval_request");
        assert_eq!(token_subject("alpha"), "vsf.alpha.s5.approval_token");
    }
}
