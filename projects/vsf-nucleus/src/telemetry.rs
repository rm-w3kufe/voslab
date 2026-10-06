/// telemetry.rs — φ↑ channel writer
///
/// @vsm 0.3
/// S1(vsf-nucleus).telemetry_writer
/// channel: φ↑ — child → parent (append-only)
///
/// Writes VSF-standard JSONL events to telemetry/{system_id}/events.jsonl.
/// Format must match core/connection_schema.json exactly —
/// parent (vsm-kernel) reads this via /telemetry/vsf-nucleus API.
/// Behavioral equivalence test: parent API returns available=true.

use chrono::Utc;
use serde::Serialize;
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const SYSTEM_ID: &str = "vsf-nucleus";

/// A single VSF telemetry event.
/// Matches the event_schema in core/connection_schema.json.
#[derive(Debug, Serialize)]
pub struct Event {
    pub ts:           String,
    pub system_id:    String,
    pub event_type:   String,
    pub status:       String,
    pub signal_status: String,
    pub duration_s:   f64,
    pub metrics:      Value,
}

impl Event {
    pub fn new(event_type: &str, status: &str, metrics: Value) -> Self {
        Self {
            ts:            Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
            system_id:     SYSTEM_ID.to_string(),
            event_type:    event_type.to_string(),
            status:        status.to_string(),
            signal_status: "resolved".to_string(),
            duration_s:    0.0,
            metrics,
        }
    }
}

/// Telemetry writer — appends events to the φ↑ channel file.
pub struct TelemetryWriter {
    path: PathBuf,
}

impl TelemetryWriter {
    pub fn new(root: &Path) -> std::io::Result<Self> {
        let dir = root.join("telemetry").join(SYSTEM_ID);
        fs::create_dir_all(&dir)?;
        Ok(Self { path: dir.join("events.jsonl") })
    }

    pub fn emit(&self, event: &Event) -> std::io::Result<()> {
        let line = serde_json::to_string(event)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        let mut file = OpenOptions::new().create(true).append(true).open(&self.path)?;
        writeln!(file, "{}", line)
    }

    /// Emit system_start — matches Python kernel's emit pattern.
    pub fn system_start(&self, kernels: &[String]) -> std::io::Result<()> {
        self.emit(&Event::new("system_start", "ok", serde_json::json!({
            "kernels": kernels,
            "system_id": SYSTEM_ID,
        })))
    }

    /// Emit system_stop with final kernel states.
    pub fn system_stop(&self, total_ticks: u32, final_states: Value) -> std::io::Result<()> {
        self.emit(&Event::new("system_stop", "ok", serde_json::json!({
            "total_ticks": total_ticks,
            "final_states": final_states,
            "system_id": SYSTEM_ID,
        })))
    }

    /// Emit kernel_tick — per-tick state snapshot.
    pub fn kernel_tick(
        &self,
        kernel: &str,
        level: u32,
        tick: u32,
        spawned: bool,
        metamorphosed: bool,
        state: Value,
    ) -> std::io::Result<()> {
        self.emit(&Event::new("kernel_tick", "ok", serde_json::json!({
            "kernel": kernel,
            "level": level,
            "tick": tick,
            "spawned": spawned,
            "metamorphosed": metamorphosed,
            "state": state,
        })))
    }

    /// Emit kernel_halt — VSL violation, kernel stops.
    pub fn kernel_halt(
        &self,
        kernel: &str,
        level: u32,
        tick: u32,
        trust: f64,
        violated: &[String],
    ) -> std::io::Result<()> {
        self.emit(&Event::new("kernel_halt", "error", serde_json::json!({
            "kernel": kernel,
            "level": level,
            "tick": tick,
            "trust": trust,
            "violated": violated,
        })))
    }

    /// Emit algedonic_signal — child halt degrades parent trust.
    pub fn algedonic(
        &self,
        from_kernel: &str,
        to_kernel: &str,
        trust_before: f64,
        trust_after: f64,
        violated: &[String],
    ) -> std::io::Result<()> {
        let mut e = Event::new("algedonic_signal", "error", serde_json::json!({
            "from_kernel": from_kernel,
            "to_kernel": to_kernel,
            "trust_before": trust_before,
            "trust_after": trust_after,
            "violated": violated,
        }));
        e.signal_status = "pending".to_string();
        self.emit(&e)
    }

    /// Emit init_step — vsf-nucleus boot sequence (P9: S5 first).
    pub fn init_step(&self, step: &str, status: &str, metrics: Value) -> std::io::Result<()> {
        self.emit(&Event::new("init_step", status, serde_json::json!({
            "step": step,
            "metrics": metrics,
        })))
    }

    /// Emit stasis_boot — kernel declares it is stable and ready for L+1 launch (P10).
    pub fn stasis_boot_event(
        &self,
        kernel: &str,
        level: u32,
        trust: f64,
        entropy: f64,
    ) -> std::io::Result<()> {
        self.emit(&Event::new("stasis_boot", "ok", serde_json::json!({
            "kernel":  kernel,
            "level":   level,
            "trust":   trust,
            "entropy": entropy,
            "signal":  "phi_up_stasis_ready",
        })))
    }

    /// Emit cgroup lifecycle event — create / adjust / destroy (P11/P12/P15).
    pub fn cgroup_event(
        &self,
        event_type: &str,
        kernel: &str,
        path: &str,
        quota: &crate::cgroup::CgroupQuota,
        dry_run: bool,
    ) -> std::io::Result<()> {
        self.emit(&Event::new(event_type, "ok", serde_json::json!({
            "kernel":     kernel,
            "path":       path,
            "cpu_weight": quota.cpu_weight,
            "mem_mib":    quota.mem_bytes / (1 << 20),
            "dry_run":    dry_run,
        })))
    }

    /// Emit kernel_spawn — D4-L2 task decomposition.
    pub fn kernel_spawn(
        &self,
        kernel: &str,
        level: u32,
        tick: u32,
        children: &[String],
        spawn_n: usize,
        complexity_in: f64,
        complexity_out: f64,
        resource_health: f64,
    ) -> std::io::Result<()> {
        self.emit(&Event::new("kernel_spawn", "ok", serde_json::json!({
            "kernel": kernel,
            "level": level,
            "tick": tick,
            "children": children,
            "task_id": format!("{}.spawn", kernel),
            "spawn_n": spawn_n,
            "complexity_in": complexity_in,
            "complexity_out": complexity_out,
            "resource_health": resource_health,
            "d4_level": "L2_class_execution",
            "authorized_by": "S5_viability_yaml",
        })))
    }
}
