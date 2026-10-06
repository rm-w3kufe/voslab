/// s5_caution.rs — ITEM_4.1 M3 — S5 Caution Mode subscriber
///
/// Subscribes to vsf.<id>.s5.caution (NATS).
/// When S5 algedonic subscriber detects high-severity event → publishes
/// {active: true} → this task sets Arc<AtomicBool> → S3 auto-controller holds.
///
/// Beer: S5 can veto S3 autonomy when the system is under stress.
/// This is the nuclear option: all autonomous param changes are suspended
/// until S5 publishes {active: false} or CAUTION_DURATION_S elapses.
///
/// "núcleo primero": NATS_URL unset → graceful no-op (caution stays false).

use futures::StreamExt;
use std::env;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

const CAUTION_SUBJECT_SUFFIX: &str = "s5.caution";

/// Returns an Arc<AtomicBool> that is true when S5 caution mode is active.
/// Spawns a background task that monitors vsf.<vsf_id>.s5.caution.
/// Caller should hold the Arc; task exits if connection drops and retries.
pub fn start_caution_subscriber(vsf_id: &str) -> (Arc<AtomicBool>, tokio::task::JoinHandle<()>) {
    let flag = Arc::new(AtomicBool::new(false));
    let flag_clone = flag.clone();
    let subject = format!("vsf.{}.{}", vsf_id, CAUTION_SUBJECT_SUFFIX);
    let vsf_id = vsf_id.to_string();

    let handle = tokio::spawn(async move {
        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[s5-caution] NATS_URL unset — caution subscriber disabled (caution stays false)");
                return;
            }
        };

        eprintln!("[s5-caution] connecting to {} sub={}", url, subject);

        loop {
            match vsf_agent::nats::connect(&url, "s5-caution").await {
                Ok(client) => {
                    eprintln!("[s5-caution] connected — watching {}", subject);
                    match client.subscribe(subject.clone()).await {
                        Ok(mut sub) => {
                            while let Some(msg) = sub.next().await {
                                let payload = match std::str::from_utf8(&msg.payload) {
                                    Ok(s) => s,
                                    Err(_) => {
                                        eprintln!("[s5-caution] payload parse error — ignoring");
                                        continue;
                                    }
                                };
                                let v: serde_json::Value = match serde_json::from_str(payload) {
                                    Ok(v) => v,
                                    Err(e) => {
                                        eprintln!("[s5-caution] JSON error: {} (payload={})", e, &payload[..payload.len().min(100)]);
                                        continue;
                                    }
                                };
                                let active = v.get("active").and_then(|x| x.as_bool()).unwrap_or(false);
                                let prev = flag_clone.swap(active, Ordering::Release);
                                if prev != active {
                                    let trigger = v.get("trigger_category").and_then(|x| x.as_str()).unwrap_or("?");
                                    let sev = v.get("trigger_sev").and_then(|x| x.as_f64()).unwrap_or(0.0);
                                    if active {
                                        eprintln!(
                                            "[s5-caution] *** CAUTION MODE ACTIVE *** trigger={} sev={:.1} — S3 auto-controller suspended",
                                            trigger, sev
                                        );
                                    } else {
                                        eprintln!("[s5-caution] caution mode CLEARED — S3 auto-controller resumed");
                                    }
                                }
                            }
                            eprintln!("[s5-caution] subscription ended — reconnecting");
                        }
                        Err(e) => eprintln!("[s5-caution] subscribe error: {} — retrying", e),
                    }
                }
                Err(e) => eprintln!("[s5-caution] connect failed: {} — retrying in 10s", e),
            }
            // Reset flag to false on disconnect (fail-safe: no caution when disconnected)
            flag_clone.store(false, Ordering::Release);
            let _ = vsf_id.as_str(); // keep alive
            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
        }
    });

    (flag, handle)
}
