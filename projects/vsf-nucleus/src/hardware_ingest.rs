// hardware_ingest.rs — F5.x.9 — L+4 read-only hardware sensor layer
//
// Implements: docs/theory/dynamics_choice.vsm §G1
//             ("C hybrid — VSF ingests but never commands hardware")
//
// axiom_ref: covenant_ops.vsm#§regulation.Ax_HardwareCeiling@v0.1
// axiom_ref: covenant_ops.vsm#§regulation.Ax_InterfaceOnly@v0.1
//
//   Ax_HardwareCeiling: ∀x: x ∉ Ω_VSF ⇔ governance(x) ∈ {firmware, MMU, thermal_sensor}
//     → hardware is a BOUNDED BLIND SPOT. VSF *reads* sensors, never commands them.
//       This module physically contains no write path to /sys, /proc, firmware or
//       MMU: its only mutating sink is `project_into_state`, which writes a small
//       whitelisted projection into Block B of the ℝ¹²⁸ StateVector — never hardware.
//
//   Ax_InterfaceOnly: VSF certifies φ↑ boundary behavior; hardware internals opaque but bounded
//     → this layer produces ONLY upward `Observation`s (φ↑). There is no `Command`
//       type and no φ↓ emitter here. `certify_boundary` attests that every reading
//       is finite and ∈ [0,1] (the boundary is bounded even though internals are opaque).
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::cgroup::{read_cpu_headroom, read_io_pressure_avg10, read_mem_pressure};
use crate::state_vector::{
    StateVector, CGROUP_HEADROOM, CPU_PRESSURE, IO_PRESSURE, MEM_PRESSURE,
};
use std::fs;
use std::path::Path;

/// Thermal normalization endpoints — match the cgroup budget convention
/// (`cgroup::CgroupQuota::from_trust_and_pressure`): 0 at 40 °C, 1 at 70 °C.
pub const THERMAL_LO_C: f64 = 40.0;
pub const THERMAL_HI_C: f64 = 70.0;

/// Read-only sensor sources at the L+4 hardware boundary.
///
/// Every variant is *passive*: it maps to a sysfs/procfs read or a cgroup read,
/// never a write. Extend with EccErrors / IrqRate when those readers land.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SensorSource {
    CpuTemp,     // /sys/class/thermal — bounded blind-spot input (no governed dim)
    CpuPressure, // /proc/pressure/cpu  (PSI avg10)
    MemPressure, // cgroup memory.current / memory.max
    IoPressure,  // cgroup io.pressure   (PSI avg10)
    CpuHeadroom, // cgroup cpu.stat-derived headroom
    NetErrDrop,  // /proc/net/dev — (rx+tx errs+drops)/packets ratio (network_health blind spot)
    LoadAvg1m,   // /proc/loadavg first token — 1-min load average (S4 env_sample, blind spot)
}

impl SensorSource {
    pub fn name(&self) -> &'static str {
        match self {
            SensorSource::CpuTemp => "cpu_temp",
            SensorSource::CpuPressure => "cpu_pressure",
            SensorSource::MemPressure => "mem_pressure",
            SensorSource::IoPressure => "io_pressure",
            SensorSource::CpuHeadroom => "cpu_headroom",
            SensorSource::NetErrDrop => "net_err_drop",
            SensorSource::LoadAvg1m => "loadavg_1m",
        }
    }

    /// The StateVector dimension this sensor projects into, if any.
    ///
    /// `CpuTemp` returns `None`: per Ax_HardwareCeiling the thermal sensor is a
    /// *bounded blind spot* — VSF reads it (it informs the cgroup budget formula)
    /// but does NOT govern it as a state dimension. All `Some(_)` targets live in
    /// Block B (resources, indices 16..=23); enforced by `INGEST_ALLOWED_INDICES`.
    pub fn target_index(&self) -> Option<usize> {
        match self {
            SensorSource::CpuTemp => None,
            SensorSource::CpuPressure => Some(CPU_PRESSURE),
            SensorSource::MemPressure => Some(MEM_PRESSURE),
            SensorSource::IoPressure => Some(IO_PRESSURE),
            SensorSource::CpuHeadroom => Some(CGROUP_HEADROOM),
            // NetErrDrop: bounded blind spot (like CpuTemp). Block B (16..=23) is fully
            // allocated, so net is absorbed as φ↑ telemetry (manifest target_dim:null —
            // 'absorb-first, assign-later') without a governed dim until the dim budget frees one.
            SensorSource::NetErrDrop => None,
            // LoadAvg1m: bounded blind spot — raw load average for S4 env_sample channel.
            // Block B full; rides φ↑ as Shannon-regime external signal, no governed dim.
            SensorSource::LoadAvg1m => None,
        }
    }
}

/// The closed whitelist of StateVector indices the ingest layer may write.
/// MUST be a subset of Block B (resources). Anything outside — governance
/// (Block A), organelles (D), VSL signals (E) — is unreachable from ingest by
/// construction. `project_into_state` filters against this set; the invariant is
/// asserted by `whitelist_is_within_block_b`.
pub const INGEST_ALLOWED_INDICES: [usize; 4] =
    [CPU_PRESSURE, MEM_PRESSURE, IO_PRESSURE, CGROUP_HEADROOM];

/// A single read-only sensor reading at the hardware boundary.
#[derive(Debug, Clone, Copy)]
pub struct SensorReading {
    pub source: SensorSource,
    /// Raw value in source units (°C for temp, [0,1] for pressures). `None` if unread.
    pub raw: Option<f64>,
    /// Normalized to [0,1]. `None` if the sensor could not be read (dry-run / absent).
    pub normalized: Option<f64>,
}

impl SensorReading {
    /// A reading is *boundary-valid* (Ax_InterfaceOnly) iff it was read and its
    /// normalized value is finite and within [0,1].
    pub fn is_bounded(&self) -> bool {
        matches!(self.normalized, Some(n) if n.is_finite() && (0.0..=1.0).contains(&n))
    }
}

/// A φ↑ upward observation: the set of read-only sensor readings for one tick.
/// There is deliberately no `Command`/φ↓ counterpart in this module.
#[derive(Debug, Clone, Default)]
pub struct Observation {
    pub readings: Vec<SensorReading>,
}

/// Ax_InterfaceOnly certificate: attests φ↑ boundary behavior is bounded even
/// though hardware internals stay opaque.
#[derive(Debug, Clone, Default)]
pub struct BoundaryCert {
    /// True iff every *read* sensor is finite and ∈ [0,1].
    pub all_bounded: bool,
    /// Sources that were read but breached the [0,1] boundary (should be empty).
    pub out_of_bounds: Vec<SensorSource>,
    /// Sources that could not be read (dry-run / sensor absent). Not a breach.
    pub unread: Vec<SensorSource>,
}

impl Observation {
    /// Certify the φ↑ boundary (Ax_InterfaceOnly). Unread sensors are reported
    /// but do not invalidate the boundary — the interface is still bounded.
    pub fn certify_boundary(&self) -> BoundaryCert {
        let mut cert = BoundaryCert {
            all_bounded: true,
            ..Default::default()
        };
        for r in &self.readings {
            match r.normalized {
                None => cert.unread.push(r.source),
                Some(_) if !r.is_bounded() => {
                    cert.all_bounded = false;
                    cert.out_of_bounds.push(r.source);
                }
                Some(_) => {}
            }
        }
        cert
    }

    /// Apply this observation into Block B of `state` — the SOLE mutating sink.
    /// Writes only whitelisted, bounded readings; skips unread / out-of-bounds /
    /// non-projecting (CpuTemp) readings. Returns the indices actually written.
    ///
    /// This is the hardware ceiling made operational: ingest can move resource
    /// dims of the StateVector but cannot touch hardware or any governance block.
    pub fn project_into_state(&self, state: &mut StateVector) -> Vec<usize> {
        let mut written = Vec::new();
        for r in &self.readings {
            let Some(idx) = r.source.target_index() else { continue };
            if !INGEST_ALLOWED_INDICES.contains(&idx) {
                debug_assert!(false, "ingest target {} outside whitelist", idx);
                continue;
            }
            if let Some(n) = r.normalized {
                if n.is_finite() {
                    state.dims[idx] = n.clamp(0.0, 1.0);
                    written.push(idx);
                }
            }
        }
        written
    }
}

/// Read-only hardware ingest layer (L+4). Holds only configuration (paths +
/// normalization bounds); owns no hardware handle and exposes no write method.
#[derive(Debug, Clone)]
pub struct HardwareIngest {
    /// cgroup path for PSI / memory / cpu reads (e.g. the kernel's own cgroup).
    pub cgroup_path: std::path::PathBuf,
    /// Candidate thermal sysfs paths, tried in order (first readable wins).
    pub thermal_paths: Vec<std::path::PathBuf>,
    pub thermal_lo_c: f64,
    pub thermal_hi_c: f64,
}

impl HardwareIngest {
    /// Construct with the canonical n02 thermal candidates.
    /// thermal_zone0 (acpitz, motherboard) is the PRIMARY — matches what S3* (host_probe)
    /// reads independently, so env_temp_divergence compares apples-to-apples between S3 (nucleus)
    /// and S3* (host_probe). hwmon5 (coretemp, CPU package) is fallback if acpitz is unavailable.
    /// ENV-SENSOR-FIX: reordered 2026-07-03 from hwmon5→thermal_zone0 to close 19 false-positive
    /// env_temp_divergence findings.
    pub fn new(cgroup_path: impl Into<std::path::PathBuf>) -> Self {
        HardwareIngest {
            cgroup_path: cgroup_path.into(),
            thermal_paths: vec![
                // Primary: matches host_probe (LXC 107) sensor → S3* sees same value
                std::path::PathBuf::from("/sys/class/thermal/thermal_zone0/temp"),
                // Fallbacks if acpitz is unreachable (dry-run, WSL, container without access)
                std::path::PathBuf::from("/sys/class/hwmon/hwmon5/temp1_input"),
                std::path::PathBuf::from("/sys/class/thermal/thermal_zone9/temp"),
            ],
            thermal_lo_c: THERMAL_LO_C,
            thermal_hi_c: THERMAL_HI_C,
        }
    }

    /// Read CPU package temperature in °C (read-only). `None` on dry-run hosts
    /// (WSL) or when no candidate path is readable.
    pub fn read_cpu_temp_c(&self) -> Option<f64> {
        for p in &self.thermal_paths {
            if let Ok(s) = fs::read_to_string(p) {
                if let Ok(milli) = s.trim().parse::<f64>() {
                    // sysfs thermal is in millidegrees C
                    return Some(milli / 1000.0);
                }
            }
        }
        None
    }

    /// Read /proc/pressure/cpu avg10 → [0,1] (PSI percentage / 100). `None` if absent.
    fn read_cpu_pressure(&self) -> Option<f64> {
        let s = fs::read_to_string("/proc/pressure/cpu").ok()?;
        // line: "some avg10=1.23 avg60=... total=..."
        for tok in s.split_whitespace() {
            if let Some(v) = tok.strip_prefix("avg10=") {
                if let Ok(pct) = v.parse::<f64>() {
                    return Some((pct / 100.0).clamp(0.0, 1.0));
                }
            }
        }
        None
    }

    /// Read /proc/net/dev → cumulative (rx+tx errs+drops)/(rx+tx packets) over non-`lo`
    /// interfaces → [0,1]. A NETWORK-HEALTH blind spot (≈0 healthy; a rising ratio signals
    /// degradation — a silent killer gauges miss). `None` if /proc/net/dev is absent (dry-run).
    /// Read /proc/loadavg 1-minute load average (raw float). `None` if absent (dry-run).
    /// Not normalized to [0,1] — raw value is more informative for S4 projection.
    /// A value of 1.0 means one CPU-worth of runnable processes; S4 interprets it
    /// relative to the host's CPU count via its own context.
    fn read_loadavg_1m(&self) -> Option<f64> {
        let s = fs::read_to_string("/proc/loadavg").ok()?;
        s.split_whitespace().next()?.parse::<f64>().ok()
    }

    fn read_net_err_drop(&self) -> Option<f64> {
        let s = fs::read_to_string("/proc/net/dev").ok()?;
        let (mut errs, mut pkts) = (0f64, 0f64);
        for line in s.lines() {
            let Some((iface, rest)) = line.split_once(':') else { continue };
            if iface.trim() == "lo" {
                continue;
            }
            // rx: bytes packets errs drop fifo frame compressed multicast (idx 0..7)
            // tx: bytes packets errs drop ...                              (idx 8..)
            let f: Vec<f64> = rest.split_whitespace().filter_map(|t| t.parse().ok()).collect();
            if f.len() >= 12 {
                pkts += f[1] + f[9];
                errs += f[2] + f[3] + f[10] + f[11];
            }
        }
        if pkts <= 0.0 {
            return Some(0.0);
        }
        Some((errs / pkts).clamp(0.0, 1.0))
    }

    fn normalize_temp(&self, temp_c: f64) -> f64 {
        let span = (self.thermal_hi_c - self.thermal_lo_c).max(f64::EPSILON);
        ((temp_c - self.thermal_lo_c) / span).clamp(0.0, 1.0)
    }

    /// Read every sensor once and return a φ↑ Observation. Pure read-only.
    pub fn read_all(&self) -> Observation {
        let cg: &Path = &self.cgroup_path;

        let temp = self.read_cpu_temp_c();
        let temp_norm = temp.map(|t| self.normalize_temp(t));

        let cpu_p = self.read_cpu_pressure();
        let net = self.read_net_err_drop();
        let loadavg = self.read_loadavg_1m();

        // cgroup reads return 0.0 when the path is absent (dry-run); treat the
        // absence of the cgroup dir as "unread" so we don't poison Block B.
        let cg_present = cg.exists();
        let mem_p = cg_present.then(|| read_mem_pressure(cg).clamp(0.0, 1.0));
        let io_p = cg_present.then(|| read_io_pressure_avg10(cg).clamp(0.0, 1.0));
        let headroom = cg_present.then(|| read_cpu_headroom(cg).clamp(0.0, 1.0));

        Observation {
            readings: vec![
                SensorReading { source: SensorSource::CpuTemp, raw: temp, normalized: temp_norm },
                SensorReading { source: SensorSource::CpuPressure, raw: cpu_p, normalized: cpu_p },
                SensorReading { source: SensorSource::MemPressure, raw: mem_p, normalized: mem_p },
                SensorReading { source: SensorSource::IoPressure, raw: io_p, normalized: io_p },
                SensorReading { source: SensorSource::CpuHeadroom, raw: headroom, normalized: headroom },
                SensorReading { source: SensorSource::NetErrDrop, raw: net, normalized: net },
                // LoadAvg1m: raw value in `raw`; normalized=None because loadavg is unbounded (>1 normal).
                // certify_boundary() lists it as "unread" (not a breach) — value travels via raw.
                SensorReading { source: SensorSource::LoadAvg1m, raw: loadavg, normalized: None },
            ],
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;
    use crate::state_vector::{
        StateVector, DEPTH, GOVERNED, LIFECYCLE, ORGANELLE_MEM_MGR, PHI_DOWN_RATE,
    };

    fn zero_state() -> StateVector {
        StateVector { dims: [0.0; 128] }
    }

    #[test]
    fn whitelist_is_within_block_b() {
        // Ax_HardwareCeiling: ingest may only reach Block B (16..=23) — never any
        // governance / organelle / VSL dimension.
        for idx in INGEST_ALLOWED_INDICES {
            assert!((16..=23).contains(&idx), "index {} not in Block B", idx);
        }
        // explicit disjointness from sensitive governed dims
        for forbidden in [GOVERNED, DEPTH, LIFECYCLE, ORGANELLE_MEM_MGR, PHI_DOWN_RATE] {
            assert!(!INGEST_ALLOWED_INDICES.contains(&forbidden));
        }
    }

    #[test]
    fn every_projecting_source_targets_whitelist() {
        for src in [
            SensorSource::CpuTemp,
            SensorSource::CpuPressure,
            SensorSource::MemPressure,
            SensorSource::IoPressure,
            SensorSource::CpuHeadroom,
        ] {
            if let Some(idx) = src.target_index() {
                assert!(INGEST_ALLOWED_INDICES.contains(&idx), "{} escapes whitelist", src.name());
            }
        }
    }

    #[test]
    fn cpu_temp_is_a_blind_spot_no_dim() {
        // Ax_HardwareCeiling: thermal sensor is a bounded blind spot, not governed state.
        assert_eq!(SensorSource::CpuTemp.target_index(), None);
    }

    #[test]
    fn net_err_drop_is_a_blind_spot_no_dim() {
        // Phase 3a: NET enters as a bounded blind spot (Block B full) — read into φ↑ telemetry,
        // no governed dim, so it cannot touch the whitelist / Ω.
        assert_eq!(SensorSource::NetErrDrop.target_index(), None);
        assert_eq!(SensorSource::NetErrDrop.name(), "net_err_drop");
    }

    #[test]
    fn loadavg_is_a_blind_spot_no_dim() {
        // ITEM_13.0: loadavg rides φ↑ as Shannon-regime external signal for S4 env_sample.
        // Block B full — no governed dim; raw float, not clamped to [0,1].
        assert_eq!(SensorSource::LoadAvg1m.target_index(), None);
        assert_eq!(SensorSource::LoadAvg1m.name(), "loadavg_1m");
    }

    #[test]
    fn projection_only_touches_whitelisted_dims() {
        let mut s = zero_state();
        s.dims[GOVERNED] = 1.0; // governance dim must be untouched
        let obs = Observation {
            readings: vec![
                SensorReading { source: SensorSource::MemPressure, raw: Some(0.4), normalized: Some(0.4) },
                SensorReading { source: SensorSource::CpuTemp, raw: Some(55.0), normalized: Some(0.5) },
            ],
        };
        let written = obs.project_into_state(&mut s);
        assert_eq!(written, vec![MEM_PRESSURE]);   // temp does NOT write a dim
        assert_eq!(s.dims[MEM_PRESSURE], 0.4);
        assert_eq!(s.dims[GOVERNED], 1.0);          // untouched
    }

    #[test]
    fn projection_clamps_and_skips_unread() {
        let mut s = zero_state();
        let obs = Observation {
            readings: vec![
                SensorReading { source: SensorSource::IoPressure, raw: Some(1.5), normalized: Some(1.5) },
                SensorReading { source: SensorSource::CpuPressure, raw: None, normalized: None },
            ],
        };
        let written = obs.project_into_state(&mut s);
        assert_eq!(written, vec![IO_PRESSURE]);
        assert_eq!(s.dims[IO_PRESSURE], 1.0);        // clamped to [0,1]
        assert_eq!(s.dims[CPU_PRESSURE], 0.0);       // unread → skipped
    }

    #[test]
    fn boundary_cert_flags_out_of_bounds_and_unread() {
        let obs = Observation {
            readings: vec![
                SensorReading { source: SensorSource::MemPressure, raw: Some(0.4), normalized: Some(0.4) },
                SensorReading { source: SensorSource::IoPressure, raw: Some(2.0), normalized: Some(2.0) },
                SensorReading { source: SensorSource::CpuPressure, raw: None, normalized: None },
            ],
        };
        let cert = obs.certify_boundary();
        assert!(!cert.all_bounded);
        assert_eq!(cert.out_of_bounds, vec![SensorSource::IoPressure]);
        assert_eq!(cert.unread, vec![SensorSource::CpuPressure]);
    }

    #[test]
    fn temp_normalization_matches_cgroup_convention() {
        let hw = HardwareIngest::new("/nonexistent");
        assert!((hw.normalize_temp(40.0) - 0.0).abs() < 1e-9);
        assert!((hw.normalize_temp(70.0) - 1.0).abs() < 1e-9);
        assert!((hw.normalize_temp(55.0) - 0.5).abs() < 1e-9);
        assert_eq!(hw.normalize_temp(20.0), 0.0); // clamped
        assert_eq!(hw.normalize_temp(99.0), 1.0); // clamped
    }

    #[test]
    fn read_all_on_dry_run_host_is_all_unread_but_bounded() {
        // /nonexistent cgroup + (likely) no thermal on test host → unread, not a breach.
        let hw = HardwareIngest::new("/nonexistent/cgroup/path");
        let obs = hw.read_all();
        let cert = obs.certify_boundary();
        assert!(cert.all_bounded, "unread sensors must not breach the boundary");
        // projecting an all-unread observation changes nothing
        let mut s = zero_state();
        let before = s.dims;
        let _ = obs.project_into_state(&mut s);
        // mem/io/headroom unread (no cgroup); cpu_pressure may exist on Linux CI,
        // so assert only the cgroup-backed dims are untouched.
        assert_eq!(s.dims[MEM_PRESSURE], before[MEM_PRESSURE]);
        assert_eq!(s.dims[IO_PRESSURE], before[IO_PRESSURE]);
        assert_eq!(s.dims[CGROUP_HEADROOM], before[CGROUP_HEADROOM]);
    }
}
