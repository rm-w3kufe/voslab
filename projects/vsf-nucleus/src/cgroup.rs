/// cgroup.rs — Linux cgroup v2 management for vsf-nucleus kernels
///
/// @vsm 0.3  infrastructure layer  @status=iterating
///
/// Implements:
///   P11 — cgroup_path(V) = "/vsf/{parent_id}/{V.id}" (hierarchical)
///   P12 — quota(V) = base × trust_score(V)
///   P15 — cgroup_lifecycle: on_create / on_update / on_destroy
///
/// Maps each vsf-nucleus kernel to a Linux cgroup v2 subtree:
///   /sys/fs/cgroup/vsf/root/vsf-nucleus-root/
///   /sys/fs/cgroup/vsf/root/child_A/
///   /sys/fs/cgroup/vsf/root/child_A/grandchild_0/
///
/// Proxmox lab: 4 cores (400 cpu.weight units), 24 GiB RAM.
/// Gracefully degrades to dry_run mode if cgroup v2 is not writable.

use std::fs;
use std::path::{Path, PathBuf};

/// Base allocations for Proxmox lab (4 cores, 24 GiB).
/// cpu.weight: kernel default=100, max=10000 (kernel sched docs)
/// mem_bytes: 1 GiB per kernel baseline; scales with trust
pub const BASE_CPU_WEIGHT: u64 = 100;
pub const BASE_MEM_BYTES:  u64 = 1 << 30;  // 1 GiB

/// quota(V) = base × trust_score(V)  [P12]
/// trust is not just a number — it has physical resource consequences in real time.
#[derive(Debug, Clone)]
pub struct CgroupQuota {
    pub cpu_weight: u64,  // cpu.weight: 1..10000
    pub mem_bytes:  u64,  // memory.max: bytes
}

impl CgroupQuota {
    pub fn from_trust(trust: f64) -> Self {
        let t = trust.clamp(0.01, 1.0);  // never zero — kernel must get some resources
        CgroupQuota {
            cpu_weight: ((BASE_CPU_WEIGHT as f64) * t).round().max(1.0) as u64,
            mem_bytes:  ((BASE_MEM_BYTES  as f64) * t).round() as u64,
        }
    }

    /// S3 budget formula under shared thermal pressure:
    ///   cpu_weight = base × trust × (1 - 0.6 × thermal_pressure)
    /// thermal_pressure ∈ [0.0, 1.0] — 0 at 40°C, 1 at 70°C
    /// The 0.6 factor preserves 40% budget floor even at maximum pressure.
    pub fn from_trust_and_pressure(trust: f64, thermal_pressure: f64) -> Self {
        let t = trust.clamp(0.01, 1.0);
        let p = thermal_pressure.clamp(0.0, 1.0);
        let scale = t * (1.0 - 0.6 * p);
        CgroupQuota {
            cpu_weight: ((BASE_CPU_WEIGHT as f64) * scale).round().max(1.0) as u64,
            mem_bytes:  ((BASE_MEM_BYTES  as f64) * t).round() as u64,
        }
    }
}

/// cgroup v2 manager — wraps /sys/fs/cgroup/vsf/
pub struct CgroupManager {
    pub vsf_root: PathBuf,
    /// True when cgroup v2 is not writable — all ops succeed silently (Proxmox will work)
    pub dry_run:  bool,
}

impl CgroupManager {
    pub fn new() -> Self {
        let vsf_root = PathBuf::from("/sys/fs/cgroup/vsf");
        let dry_run  = !Self::cgroup_v2_writable();
        if dry_run {
            eprintln!("  cgroup: /sys/fs/cgroup/vsf not writable — dry_run mode (deploy on Proxmox)");
        }
        CgroupManager { vsf_root, dry_run }
    }

    /// Experiment-scoped manager using an explicit root path.
    /// Caller is responsible for creating the root and enabling subtree_control.
    pub fn with_root(root: PathBuf) -> Self {
        let dry_run = !root.exists();
        CgroupManager { vsf_root: root, dry_run }
    }

    fn cgroup_v2_writable() -> bool {
        // cgroup v2 unified hierarchy requires cgroup.controllers at root
        let controllers = Path::new("/sys/fs/cgroup/cgroup.controllers");
        if !controllers.exists() { return false; }
        // Probe: try to create + remove a temporary cgroup directory at root level
        let probe_dir = Path::new("/sys/fs/cgroup/vsf-probe-tmp");
        if fs::create_dir(probe_dir).is_ok() {
            let _ = fs::remove_dir(probe_dir);
            true
        } else {
            // If probe dir already exists, we likely have write access (leftover from prev run)
            Path::new("/sys/fs/cgroup/vsf").exists()
        }
    }

    /// cgroup_path(V) = "/vsf/{parent_id}/{V.id}"  [P11]
    pub fn kernel_path(&self, parent_id: &str, kernel_id: &str) -> PathBuf {
        self.vsf_root.join(parent_id).join(kernel_id)
    }

    /// on_create(V): create cgroup directory + assign limits  [P15]
    ///
    /// Returns the cgroup path (real or simulated in dry_run mode).
    pub fn create(
        &self, parent_id: &str, kernel_id: &str, quota: &CgroupQuota,
    ) -> Result<PathBuf, String> {
        let path = self.kernel_path(parent_id, kernel_id);
        if self.dry_run { return Ok(path); }

        // Ensure vsf root exists
        fs::create_dir_all(&self.vsf_root)
            .map_err(|e| format!("cannot create /sys/fs/cgroup/vsf: {}", e))?;

        // Ensure parent directory exists (for nested kernels)
        let parent_dir = self.vsf_root.join(parent_id);
        fs::create_dir_all(&parent_dir)
            .map_err(|e| format!("cannot create parent cgroup {}: {}", parent_id, e))?;

        // Enable controllers in parent so children can use them
        // cgroup v2 requires explicit subtree_control delegation
        let parent_subtree = parent_dir.join("cgroup.subtree_control");
        if parent_subtree.exists() {
            // +cpu +memory — needed for cpu.weight and memory.max in children
            let _ = fs::write(&parent_subtree, "+cpu +memory\n");
        } else {
            // vsf root — enable on the vsf_root itself too
            let vsf_subtree = self.vsf_root.join("cgroup.subtree_control");
            let _ = fs::write(&vsf_subtree, "+cpu +memory\n");
        }

        // Create kernel cgroup directory
        fs::create_dir_all(&path)
            .map_err(|e| format!("cannot create cgroup {}: {}", path.display(), e))?;

        self.write_quota(&path, quota)?;
        Ok(path)
    }

    /// on_update(V): adjust quota when trust changes  [P15]
    ///
    /// Called after every trust_score change — trust has physical consequences.
    pub fn adjust(
        &self, parent_id: &str, kernel_id: &str, quota: &CgroupQuota,
    ) -> Result<(), String> {
        if self.dry_run { return Ok(()); }
        let path = self.kernel_path(parent_id, kernel_id);
        if path.exists() {
            self.write_quota(&path, quota)
        } else {
            Err(format!("cgroup {} does not exist — cannot adjust", path.display()))
        }
    }

    /// on_destroy(V): remove cgroup after drain protocol  [P15]
    pub fn destroy(&self, parent_id: &str, kernel_id: &str) -> Result<(), String> {
        if self.dry_run { return Ok(()); }
        let path = self.kernel_path(parent_id, kernel_id);
        if path.exists() {
            fs::remove_dir(&path)
                .map_err(|e| format!("cannot remove cgroup {}: {}", path.display(), e))?;
        }
        Ok(())
    }

    /// Assign a PID to this cgroup (writes to cgroup.procs).
    pub fn assign_pid(&self, parent_id: &str, kernel_id: &str, pid: u32) -> Result<(), String> {
        if self.dry_run { return Ok(()); }
        let path = self.kernel_path(parent_id, kernel_id);
        fs::write(path.join("cgroup.procs"), format!("{}\n", pid))
            .map_err(|e| format!("cgroup.procs write failed for pid {}: {}", pid, e))
    }

    fn write_quota(&self, path: &Path, quota: &CgroupQuota) -> Result<(), String> {
        // cpu.weight — cgroup v2 CPU proportional scheduling
        fs::write(path.join("cpu.weight"), format!("{}\n", quota.cpu_weight))
            .map_err(|e| format!("cpu.weight write failed: {}", e))?;

        // memory.max — hard memory limit
        if quota.mem_bytes > 0 {
            fs::write(path.join("memory.max"), format!("{}\n", quota.mem_bytes))
                .map_err(|e| format!("memory.max write failed: {}", e))?;
        }
        Ok(())
    }
}

// ─── Block B sensors ──────────────────────────────────────────────────────────
//
// Real hardware pressure readings for Block B of StateVector.
// All functions return 0.0 on any read/parse error (graceful degradation).

/// mem_pressure = memory.current / memory.max
/// Returns 0.0 if memory.max == "max" (unlimited) or on error.
pub fn read_mem_pressure(cgroup_path: &Path) -> f64 {
    let current = fs::read_to_string(cgroup_path.join("memory.current"))
        .ok()
        .and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(0);
    let max_str = fs::read_to_string(cgroup_path.join("memory.max"))
        .unwrap_or_default();
    let max_str = max_str.trim();
    if max_str == "max" || max_str.is_empty() { return 0.0; }
    let max = match max_str.parse::<u64>() {
        Ok(v) if v > 0 => v,
        _ => return 0.0,
    };
    (current as f64 / max as f64).clamp(0.0, 1.0)
}

/// io_pressure = "some avg10" field from io.pressure, divided by 100.
/// Format: "some avg10=X.XX avg60=X.XX avg300=X.XX total=NNN"
/// Returns 0.0 if file absent or field missing.
pub fn read_io_pressure_avg10(cgroup_path: &Path) -> f64 {
    let s = fs::read_to_string(cgroup_path.join("io.pressure"))
        .unwrap_or_default();
    for line in s.lines() {
        if line.starts_with("some") {
            for token in line.split_whitespace() {
                if let Some(v) = token.strip_prefix("avg10=") {
                    return v.parse::<f64>().unwrap_or(0.0) / 100.0;
                }
            }
        }
    }
    0.0
}

/// cpu_headroom = 1.0 - cpu_utilization_delta
/// Reads cpu.stat usage_usec across two calls separated by ~10ms.
/// Returns 1.0 (full headroom) on any error.
pub fn read_cpu_headroom(cgroup_path: &Path) -> f64 {
    fn read_usage_usec(p: &Path) -> Option<u64> {
        let s = fs::read_to_string(p.join("cpu.stat")).ok()?;
        for line in s.lines() {
            if let Some(rest) = line.strip_prefix("usage_usec ") {
                return rest.trim().parse::<u64>().ok();
            }
        }
        None
    }
    let t0 = read_usage_usec(cgroup_path);
    std::thread::sleep(std::time::Duration::from_millis(10));
    let t1 = read_usage_usec(cgroup_path);
    match (t0, t1) {
        (Some(a), Some(b)) if b > a => {
            let cpu_delta   = (b - a) as f64;
            let wall_usec   = 10_000.0;   // 10ms in µs
            let utilization = (cpu_delta / wall_usec).min(1.0);
            1.0 - utilization
        }
        _ => 1.0,
    }
}
