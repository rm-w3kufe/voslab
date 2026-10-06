/// observability.rs — γ.8 — Light observability layer (health + watchdog)
///
/// @vsm 0.3
/// Per Qwen consensus ronda 4: between γ.7 (deploy) and 24h validation we need
/// minimal observability so γ.6 drift detection isn't blind. This module adds:
///
///   1. health.json writer — atomic write every N seconds with last
///      invariant_check results, cycle counters, uptime, last event hash.
///   2. systemd watchdog notifier — sd_notify("WATCHDOG=1") every 10s while
///      the operational loop is healthy. systemd unit can use WatchdogSec=30
///      to auto-restart if we stop reporting.
///
/// Design principle: "núcleo primero" — single small file, no external deps.
/// systemd's NotifySocket is opened directly via env var; no `systemd` crate.

use serde::Serialize;
use std::env;
use std::fs;
use std::io::Write;
use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::time;

pub const HEALTH_FILE: &str = "/var/lib/vsf/health.json";
pub const HEALTH_INTERVAL_MS: u64 = 5_000; // 5 sec
pub const WATCHDOG_INTERVAL_MS: u64 = 10_000; // 10 sec

/// ── Main-thread liveness check (NUCLEUS-WATCHDOG-HARDENING) ─────────────────
///
/// Wall-clock timestamp (ms since UNIX_EPOCH) of the last completed main-loop tick.
/// Written by the S1 supervised emitter after each successful tick.
/// Read by the watchdog thread before sending WATCHDOG=1.
///
/// If this timestamp stalls for longer than MAX_STALL_MS, the watchdog stops
/// pinging and allows systemd's real watchdog (WatchdogSec=30) to escalate.
///
/// ## False-positive risk (documented per directive)
///
/// Under maximal stability (sigma→0), the adaptive clock sleeps for
/// `canon_base_secs` (default 60s) between ticks. The phi_down S5 governor
/// can raise telemetry_interval_secs up to 300s. At 300s with a 120s stall
/// threshold, the watchdog would incorrectly conclude the main loop is stuck.
/// Mitigation: MAX_STALL_MS = 120s covers the default 60s base with 2× margin.
/// The coupling between S5 gov telemetry_interval_secs and this threshold
/// is NOT yet implemented (known gap). If the S5 gov raises the interval
/// significantly, the watchdog threshold becomes stale — log a warning if
/// any stall > WARN_STALL_MS is observed, even if not yet at escalation.
///
/// ## Root-cause caveat
///
/// The original SIGKILL crashes that motivated this hardening had an
/// UNCONFIRMED root cause — this is a robustness/diagnostics improvement,
/// not a guaranteed fix for the double-bounce pattern.
pub const MAX_STALL_MS: u64 = 120_000;   // 120s — stall threshold before watchdog desists
pub const WARN_STALL_MS: u64 = 60_000;   // 60s  — warn at ½ the stall threshold

/// Monotonic wall-clock timestamp (ms) of the last completed main-loop tick.
/// 0 = no tick reported yet (startup).
static LAST_TICK_AT_MS: AtomicU64 = AtomicU64::new(0);

/// Signal main-loop liveness after completing one kernel tick.
/// Must be called AFTER `emit_kernel_tick()` but BEFORE the adaptive sleep,
/// so the timestamp reflects the completed tick, not the idle wait between ticks.
pub fn report_tick_completed() {
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;
    LAST_TICK_AT_MS.store(ms, Ordering::Release);
}

#[derive(Debug, Default, Serialize, Clone)]
pub struct HealthSnapshot {
    pub ts: String,
    pub uptime_sec: u64,
    pub pid: u32,
    pub system_id: String,

    /// Most recent invariant check results.
    pub last_var1_pass: Option<bool>,
    pub last_trust1_pass: Option<bool>,
    pub last_alg1_pass: Option<bool>,

    /// Counter of total invariant_check events emitted since boot.
    pub invariant_checks_total: u64,
    /// Counter of total drift_alerts emitted since boot.
    pub drift_alerts_total: u64,
    /// Counter of algedonic emissions since boot.
    pub algedonic_total: u64,

    /// Last events.jsonl hash (Merkle chain head).
    pub last_event_hash: Option<String>,

    /// Last S4 cycle outcome.
    pub last_s4_cycle_ts: Option<String>,
    pub last_s4_cycle_ok: Option<bool>,

    /// Last telemetry write timestamp.
    pub last_telemetry_ts: Option<String>,
}

pub struct HealthReporter {
    inner: Arc<Mutex<HealthSnapshot>>,
    start: Instant,
    out_path: PathBuf,
}

impl HealthReporter {
    pub fn new(system_id: &str) -> Self {
        Self::with_path(system_id, Path::new(HEALTH_FILE))
    }

    pub fn with_path(system_id: &str, out_path: &Path) -> Self {
        let mut snap = HealthSnapshot::default();
        snap.system_id = system_id.to_string();
        snap.pid = std::process::id();
        Self {
            inner: Arc::new(Mutex::new(snap)),
            start: Instant::now(),
            out_path: out_path.to_path_buf(),
        }
    }

    pub fn handle(&self) -> Arc<Mutex<HealthSnapshot>> { self.inner.clone() }

    /// Convenience: record an invariant outcome (called by InvariantChecker hook).
    pub fn record_invariant(handle: &Arc<Mutex<HealthSnapshot>>, id: &str, pass: bool) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.invariant_checks_total += 1;
        match id {
            "VAR-1" => s.last_var1_pass = Some(pass),
            "TRUST-1" => s.last_trust1_pass = Some(pass),
            "ALG-1" => s.last_alg1_pass = Some(pass),
            _ => {}
        }
    }

    pub fn record_drift_alert(handle: &Arc<Mutex<HealthSnapshot>>) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.drift_alerts_total += 1;
    }

    pub fn record_algedonic(handle: &Arc<Mutex<HealthSnapshot>>) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.algedonic_total += 1;
    }

    pub fn record_s4_cycle(handle: &Arc<Mutex<HealthSnapshot>>, ok: bool) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.last_s4_cycle_ts = Some(chrono::Utc::now().to_rfc3339());
        s.last_s4_cycle_ok = Some(ok);
    }

    pub fn record_telemetry(handle: &Arc<Mutex<HealthSnapshot>>) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.last_telemetry_ts = Some(chrono::Utc::now().to_rfc3339());
    }

    pub fn record_event_hash(handle: &Arc<Mutex<HealthSnapshot>>, hash: String) {
        let mut s = handle.lock().expect("health snapshot lock");
        s.last_event_hash = Some(hash);
    }

    /// Spawn the background task that writes health.json every HEALTH_INTERVAL_MS.
    /// Returns the JoinHandle so caller can keep it alive.
    pub fn start_writer_task(self: Arc<Self>) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            // Best-effort parent dir create.
            if let Some(parent) = self.out_path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            let mut tick = time::interval(Duration::from_millis(HEALTH_INTERVAL_MS));
            loop {
                tick.tick().await;
                if let Err(e) = self.write_snapshot() {
                    eprintln!("[observability] write health.json error: {}", e);
                }
            }
        })
    }

    fn write_snapshot(&self) -> std::io::Result<()> {
        let mut snap = self.inner.lock().expect("health snapshot lock").clone();
        snap.uptime_sec = self.start.elapsed().as_secs();
        snap.ts = chrono::Utc::now().to_rfc3339();
        let json = serde_json::to_string_pretty(&snap)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        // Atomic write: tmp file + rename
        let tmp = self.out_path.with_extension("json.tmp");
        {
            let mut f = fs::OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(&tmp)?;
            f.write_all(json.as_bytes())?;
            f.sync_data()?;
        }
        fs::rename(&tmp, &self.out_path)?;
        Ok(())
    }
}

/// Spawn the systemd watchdog notifier (no-op if NOTIFY_SOCKET unset).
/// Sends `WATCHDOG=1` to the notify socket every WATCHDOG_INTERVAL_MS,
/// BUT only if the main-loop tick timestamp has advanced recently.
///
/// If the main loop stalls for > MAX_STALL_MS, the watchdog thread stops
/// sending WATCHDOG=1, allowing systemd's real watchdog to escalate (SIGABRT
/// then SIGKILL per WatchdogSec=30). The thread also logs at warning level
/// when the timestamp approaches the stall threshold (WARN_STALL_MS).
///
/// Runs on a DEDICATED OS thread so kernel liveness is NEVER starved by tokio
/// scheduler contention (R10 enforcement — see s4_ollama_decouple.vsm layer 3).
///
/// ## Change history
/// - NUCLEUS-WATCHDOG-HARDENING 2026-07-27: added main-loop liveness check
///   (timestamp-based, WARN_STALL_MS/MAX_STALL_MS) and success logging on
///   every WATCHDOG=1 send (was previously silent on success).
pub fn start_watchdog_task() -> std::thread::JoinHandle<()> {
    std::thread::Builder::new()
        .name("vsf-watchdog".into())
        .spawn(move || {
            let sock_path = match env::var("NOTIFY_SOCKET") {
                Ok(v) if !v.is_empty() => v,
                _ => {
                    eprintln!("[observability] NOTIFY_SOCKET unset — systemd watchdog disabled");
                    return;
                }
            };
            // Initial READY=1
            if let Err(e) = sd_notify_send(&sock_path, "READY=1") {
                eprintln!("[observability] sd_notify READY=1 failed: {}", e);
            }

            // Startup grace: don't check stall until the first tick arrives.
            let mut ever_saw_tick = false;

            loop {
                std::thread::sleep(Duration::from_millis(WATCHDOG_INTERVAL_MS));

                let now_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis() as u64;
                let last_tick = LAST_TICK_AT_MS.load(Ordering::Acquire);
                let stall_ms = now_ms.saturating_sub(last_tick);

                if last_tick == 0 {
                    // Startup — no tick reported yet; keep pinging as before.
                    ever_saw_tick = false;
                    if let Err(e) = sd_notify_send(&sock_path, "WATCHDOG=1") {
                        eprintln!("[observability] sd_notify WATCHDOG=1 failed: {}", e);
                    } else {
                        println!("[observability] WATCHDOG=1 (startup, no tick yet)");
                    }
                } else if stall_ms <= MAX_STALL_MS {
                    // Main loop is alive — send WATCHDOG=1 with success log.
                    ever_saw_tick = true;
                    if stall_ms >= WARN_STALL_MS {
                        // Approaching threshold — log warning but keep pinging.
                        eprintln!(
                            "[observability] WARN: main-loop tick stale for {}ms \
                             (threshold {}ms) — still pinging",
                            stall_ms, MAX_STALL_MS
                        );
                    }
                    if let Err(e) = sd_notify_send(&sock_path, "WATCHDOG=1") {
                        eprintln!("[observability] sd_notify WATCHDOG=1 failed: {}", e);
                    } else {
                        println!(
                            "[observability] WATCHDOG=1 (last_tick={}ms ago, threshold={}ms)",
                            stall_ms, MAX_STALL_MS
                        );
                    }
                } else {
                    // Stall exceeded threshold — STOP pinging.
                    // Systemd's real watchdog (WatchdogSec=30) will escalate:
                    // SIGABRT → if process doesn't respond → SIGKILL.
                    eprintln!(
                        "[observability] FATAL: main-loop tick stall detected — \
                         {}ms since last tick (>{}ms). STOPPING watchdog pings — \
                         letting systemd escalate.",
                        stall_ms, MAX_STALL_MS
                    );
                    // Do NOT send WATCHDOG=1. Wait silently for systemd to act.
                    loop {
                        // Check if the main loop recovers (unlikely but possible
                        // if a transient condition clears).
                        std::thread::sleep(Duration::from_millis(WATCHDOG_INTERVAL_MS));
                        let now_ms = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_millis() as u64;
                        let last_tick = LAST_TICK_AT_MS.load(Ordering::Acquire);
                        let stall_ms = now_ms.saturating_sub(last_tick);
                        if last_tick != 0 && stall_ms <= MAX_STALL_MS {
                            eprintln!(
                                "[observability] main-loop appears to have recovered \
                                 (last_tick={}ms ago) — RESUMING watchdog pings",
                                stall_ms
                            );
                            break; // back to outer loop
                        }
                    }
                }
            }
        })
        .expect("watchdog thread")
}

fn sd_notify_send(sock_path: &str, msg: &str) -> std::io::Result<()> {
    // Connect to the abstract Unix socket. Abstract paths start with '\0'.
    let sock = UnixDatagram::unbound()?;
    let path = if sock_path.starts_with('@') {
        // Abstract namespace: replace leading '@' with '\0'
        let bytes = sock_path.as_bytes();
        let mut p = vec![0u8];
        p.extend_from_slice(&bytes[1..]);
        // Note: std::os::unix::net::SocketAddr cannot be constructed from raw abstract bytes
        // easily. For pragmatic case, support file-path NOTIFY_SOCKET only here.
        // Abstract sockets used by systemd in some configs require nix crate; we keep this
        // minimal and document the limitation.
        let _ = p;
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            "abstract notify socket not supported in this minimal implementation",
        ));
    } else {
        sock_path
    };
    sock.send_to(msg.as_bytes(), path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_default_has_pid_and_system_id() {
        let r = HealthReporter::new("test-sys");
        let s = r.inner.lock().unwrap().clone();
        assert_eq!(s.system_id, "test-sys");
        assert_ne!(s.pid, 0);
    }

    #[test]
    fn record_invariant_updates_counters_and_flags() {
        let r = HealthReporter::new("test-counters");
        let h = r.handle();
        HealthReporter::record_invariant(&h, "VAR-1", true);
        HealthReporter::record_invariant(&h, "TRUST-1", false);
        HealthReporter::record_invariant(&h, "ALG-1", true);
        let s = h.lock().unwrap().clone();
        assert_eq!(s.invariant_checks_total, 3);
        assert_eq!(s.last_var1_pass, Some(true));
        assert_eq!(s.last_trust1_pass, Some(false));
        assert_eq!(s.last_alg1_pass, Some(true));
    }

    #[test]
    fn write_snapshot_creates_valid_json() {
        let tmp = std::env::temp_dir().join(format!("vsf-health-{}.json", std::process::id()));
        let r = HealthReporter::with_path("test-write", &tmp);
        let h = r.handle();
        HealthReporter::record_invariant(&h, "VAR-1", true);
        HealthReporter::record_drift_alert(&h);
        r.write_snapshot().unwrap();
        let content = std::fs::read_to_string(&tmp).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
        assert_eq!(parsed["system_id"], "test-write");
        assert_eq!(parsed["invariant_checks_total"], 1);
        assert_eq!(parsed["drift_alerts_total"], 1);
        let _ = std::fs::remove_file(&tmp);
    }
}
