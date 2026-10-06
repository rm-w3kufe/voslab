//! s3_star_audit.rs — Phase 4.4 (γ.11) — S4 consumes S3* audit findings.
//!
//! Per Qwen Q6 + Q8 option_b: S4 should see S3* audit findings to factor into
//! planning (Beer: intelligence adapts to audit signals). Subscribes the
//! audit channel read-only, buffers recent findings, exposes them to S4's
//! Qwen prompt context.
//!
//! Subject: vsf.<vsf_id>.s3_star.audit.>
//! No ledger coupling — pure observation via NATS channel.
//! No-op gracefully if NATS_URL unset.

use futures::StreamExt;
use serde_json::Value;
use std::collections::VecDeque;
use std::env;
use std::sync::{Arc, Mutex};

/// Bounded buffer of recent S3* audit findings received via NATS.
/// Shared between the subscriber task (tokio) and S4Orchestrator (std thread).
#[derive(Clone)]
pub struct AuditBuffer {
    inner: Arc<Mutex<VecDeque<Value>>>,
    capacity: usize,
}

impl AuditBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(VecDeque::with_capacity(capacity))),
            capacity,
        }
    }

    fn push(&self, v: Value) {
        let mut g = self.inner.lock().expect("audit buffer lock");
        if g.len() >= self.capacity {
            g.pop_front();
        }
        g.push_back(v);
    }

    /// Compact text summary of recent audit findings, for Qwen prompt.
    /// Returns empty string if no findings (S4 prompt omits the block).
    pub fn summarize(&self, max_items: usize) -> String {
        let g = self.inner.lock().expect("audit buffer lock");
        if g.is_empty() {
            return String::new();
        }
        let start = g.len().saturating_sub(max_items);
        let mut out = String::new();
        for f in g.iter().skip(start) {
            let cat = f.get("category").and_then(|v| v.as_str()).unwrap_or("?");
            let sev = f.get("severity").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let target = f.get("audit_target").and_then(|v| v.as_str()).unwrap_or("?");
            let detail = f.get("detail").and_then(|v| v.as_str()).unwrap_or("");
            let detail_short = if detail.len() > 80 { &detail[..80] } else { detail };
            out.push_str(&format!(
                "  - S3* audit: target={} category={} sev={:.1} {}\n",
                target, cat, sev, detail_short
            ));
        }
        out.trim_end().to_string()
    }

    pub fn len(&self) -> usize {
        self.inner.lock().expect("audit buffer lock").len()
    }
}

/// Spawn the subscriber for an EXISTING buffer (must be called inside a tokio
/// runtime). The buffer can be created earlier (AuditBuffer::new) and shared
/// with the S4 std::thread before this subscriber runs.
pub fn spawn_subscriber_for(
    buffer: AuditBuffer,
    vsf_id: &str,
) -> tokio::task::JoinHandle<()> {
    let buf_clone = buffer;
    let subject = format!("vsf.{}.s3_star.audit.>", vsf_id);

    tokio::spawn(async move {
        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[s3_star_audit] NATS_URL unset — γ.11 disabled (S4 has no audit context)");
                return;
            }
        };
        let client = match vsf_agent::nats::connect(&url, "vsf-nucleus-s3star-audit-sub").await {
            Ok(c) => {
                eprintln!("[s3_star_audit] γ.11 connected to {} (pattern: {})", url, subject);
                c
            }
            Err(e) => {
                eprintln!("[s3_star_audit] connect failed: {} — γ.11 disabled", e);
                return;
            }
        };
        let mut sub = match client.subscribe(subject.clone()).await {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[s3_star_audit] subscribe({}) failed: {}", subject, e);
                return;
            }
        };
        eprintln!("[s3_star_audit] γ.11 ready — buffering findings for S4 context");
        while let Some(msg) = sub.next().await {
            if let Ok(v) = serde_json::from_slice::<Value>(&msg.payload) {
                buf_clone.push(v);
            }
        }
        eprintln!("[s3_star_audit] subscription closed");
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn summarize_formats_recent_findings() {
        let b = AuditBuffer::new(5);
        b.push(json!({"audit_target":"covenant","category":"covenant_drift","severity":10.0,"detail":"local!=canonical"}));
        b.push(json!({"audit_target":"cycle","category":"cycle_summary","severity":0.0,"detail":"findings_emitted=1"}));
        let s = b.summarize(5);
        assert!(s.contains("covenant_drift"));
        assert!(s.contains("sev=10.0"));
        assert!(s.contains("cycle_summary"));
    }

    #[test]
    fn summarize_empty_returns_empty() {
        let b = AuditBuffer::new(5);
        assert_eq!(b.summarize(5), "");
    }

    #[test]
    fn capacity_evicts() {
        let b = AuditBuffer::new(2);
        b.push(json!({"category":"a"}));
        b.push(json!({"category":"b"}));
        b.push(json!({"category":"c"}));
        assert_eq!(b.len(), 2);
    }
}
