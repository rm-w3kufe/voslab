// coupling_registry.rs — DSN-COUPLE-01 Phase 3b — manifest-driven sensor registry
//
// Generalizes hardware_ingest's fixed `SensorSource` enum (Phase 3a) into a RUNTIME
// registry that parses per-S1 coupling manifests (`/etc/vsf/coupling/*.coupling.json`,
// schema core/coupling_manifest.schema.json) and honors the governed-dim budget
//
//   B ∪ B' = {16,17,18,20} ∪ [56..63]
//
// (B = Block-B ingest slots already used by hardware_ingest; B' = Block-E reserved
// tail [56..63], filled LAZILY — a dim is claimed only when a manifest declares a
// load_bearing sensor targeting it). This is the exact whitelist validator.py
// enforces (_COUPLING_GOVERNED_DIMS); the kernel now mirrors it at runtime.
//
// axiom_ref: covenant_ops.vsm#§regulation.Ax_HardwareCeiling@v0.1
// axiom_ref: covenant_ops.vsm#§regulation.Ax_InterfaceOnly@v0.1
//   Like hardware_ingest, this module is READ-ONLY: its sole mutating sink is
//   `read_and_project`, which writes whitelisted, bounded, normalized readings into
//   B∪B' of the ℝ¹²⁸ StateVector — never hardware, never a governance/organelle dim.
//   In-nucleus reads are restricted to self-contained procfs/sysfs scalar paths
//   (the hot-loop ceiling). exec_cmd / http_metric / nats_subject / prometheus /
//   journal / kmsg are DECLARED + inventoried but DEFERRED to a sidecar reader —
//   the kernel hot loop never shells out, opens a socket, or blocks on the network.
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use serde::Deserialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

/// B' operational extension — Block-E reserved tail [56..63] (8 dims).
pub const B_PRIME_START: usize = 56;
pub const B_PRIME_END: usize = 63; // inclusive

/// Default manifest directory (override with VSF_COUPLING_DIR — matches topology_reconcile).
pub const DEFAULT_MANIFEST_DIR: &str = "/etc/vsf/coupling";

/// B ∪ B' governed-dim whitelist. Mirror of validator.py `_COUPLING_GOVERNED_DIMS`
/// = {16,17,18,20} ∪ [56..63]. A sensor may take a governed dim ONLY here; anything
/// else would breach the ingest whitelist / Ω (Ax_HardwareCeiling).
pub fn is_governed_dim(idx: usize) -> bool {
    matches!(idx, 16 | 17 | 18 | 20) || (B_PRIME_START..=B_PRIME_END).contains(&idx)
}

/// Is `idx` in the lazy B' extension tail?
pub fn is_bprime_dim(idx: usize) -> bool {
    (B_PRIME_START..=B_PRIME_END).contains(&idx)
}

/// Manifest read-kinds (mirror of validator.py `_COUPLING_READ_KINDS`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReadKind {
    SysfsPath,
    ProcfsPath,
    CgroupField,
    HttpMetric,
    NatsSubject,
    ExecCmd,
    PrometheusEndpoint,
    Journal,
    Kmsg,
}

impl ReadKind {
    pub fn parse(s: &str) -> Option<ReadKind> {
        Some(match s {
            "sysfs_path" => ReadKind::SysfsPath,
            "procfs_path" => ReadKind::ProcfsPath,
            "cgroup_field" => ReadKind::CgroupField,
            "http_metric" => ReadKind::HttpMetric,
            "nats_subject" => ReadKind::NatsSubject,
            "exec_cmd" => ReadKind::ExecCmd,
            "prometheus_endpoint" => ReadKind::PrometheusEndpoint,
            "journal" => ReadKind::Journal,
            "kmsg" => ReadKind::Kmsg,
            _ => return None,
        })
    }

    /// In-nucleus read-kinds are self-contained file reads (no shelling out, no
    /// socket, no blocking). Everything else is deferred to a sidecar reader to
    /// keep the kernel hot loop within the hardware ceiling.
    pub fn is_in_nucleus(&self) -> bool {
        matches!(self, ReadKind::SysfsPath | ReadKind::ProcfsPath)
    }
}

/// Sensor criticality (mirror of the schema enum).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Criticality {
    LoadBearing,
    Important,
    Informational,
}

impl Criticality {
    fn parse(s: &str) -> Criticality {
        match s {
            "load_bearing" => Criticality::LoadBearing,
            "important" => Criticality::Important,
            _ => Criticality::Informational,
        }
    }
}

/// A processed, validated sensor binding from a coupling manifest.
#[derive(Debug, Clone)]
pub struct ManifestSensor {
    pub system_id: String,
    pub name: String,
    pub source: String,
    pub read_kind: ReadKind,
    pub category: String,
    pub criticality: Criticality,
    /// (lo, hi) normalization endpoints → maps raw into [0,1].
    pub normalize: (f64, f64),
    /// Validated governed dim ∈ B∪B', or None (φ↑ telemetry only — the default).
    pub target_dim: Option<usize>,
}

impl ManifestSensor {
    /// Normalize a raw reading into [0,1] using the declared endpoints, clamped.
    pub fn normalize_value(&self, raw: f64) -> f64 {
        let (lo, hi) = self.normalize;
        let span = (hi - lo).abs().max(f64::EPSILON);
        ((raw - lo) / span).clamp(0.0, 1.0)
    }
}

/// Why a declared sensor (or its dim claim) was rejected during registry build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Rejection {
    BadReadKind { sensor: String, kind: String },
    BadTargetDim { sensor: String, dim: usize },
    DimCollision { sensor: String, dim: usize, held_by: String },
    NonLoadBearingDim { sensor: String, dim: usize },
}

// ── Raw manifest deserialization (only the fields the registry consumes) ─────────

fn default_hi() -> f64 {
    1.0
}

#[derive(Debug, Deserialize)]
struct RawNormalize {
    #[serde(default)]
    lo: f64,
    #[serde(default = "default_hi")]
    hi: f64,
}

#[derive(Debug, Deserialize)]
struct RawSensor {
    name: String,
    #[serde(default)]
    source: String,
    read_kind: String,
    #[serde(default)]
    category: String,
    #[serde(default)]
    criticality: String,
    #[serde(default)]
    normalize: Option<RawNormalize>,
    #[serde(default)]
    target_dim: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct RawOpMap {
    #[serde(default)]
    sensors: Vec<RawSensor>,
}

#[derive(Debug, Deserialize)]
struct RawIdentity {
    system_id: String,
}

#[derive(Debug, Deserialize)]
struct RawManifest {
    identity: RawIdentity,
    operational_map: RawOpMap,
}

/// The runtime sensor registry: the parsed, validated union of all coupling
/// manifests, plus the lazy B' allocation map and the rejection log.
#[derive(Debug, Default)]
pub struct SensorRegistry {
    pub sensors: Vec<ManifestSensor>,
    /// dim → "system_id:name" that holds it (lazy B' + the fixed B slots in use).
    pub dim_assignments: BTreeMap<usize, String>,
    pub rejections: Vec<Rejection>,
    /// Manifests parsed (system_id list), for the inventory.
    pub manifests: Vec<String>,
}

impl SensorRegistry {
    /// Load + validate every `*.coupling.json` in `dir`. Missing dir → empty
    /// registry (safe no-op). Malformed files are skipped (logged to stderr).
    pub fn load_dir(dir: impl AsRef<Path>) -> SensorRegistry {
        let dir = dir.as_ref();
        let mut reg = SensorRegistry::default();
        let Ok(entries) = fs::read_dir(dir) else {
            return reg; // absent dir → empty registry (the prod-today case)
        };

        // Deterministic order (mirrors topology_reconcile's sorted glob).
        let mut paths: Vec<_> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.ends_with(".coupling.json"))
                    .unwrap_or(false)
            })
            .collect();
        paths.sort();

        for path in paths {
            match fs::read_to_string(&path) {
                Ok(text) => reg.ingest_manifest_str(&text, &path.display().to_string()),
                Err(e) => eprintln!("[coupling_registry] read {} failed: {}", path.display(), e),
            }
        }
        reg
    }

    /// Convenience: load from VSF_COUPLING_DIR or DEFAULT_MANIFEST_DIR.
    pub fn load_default() -> SensorRegistry {
        let dir = std::env::var("VSF_COUPLING_DIR")
            .unwrap_or_else(|_| DEFAULT_MANIFEST_DIR.to_string());
        SensorRegistry::load_dir(dir)
    }

    /// Parse one manifest's JSON text and merge its sensors into the registry,
    /// applying the B∪B' whitelist + lazy B' allocation + collision detection.
    pub fn ingest_manifest_str(&mut self, text: &str, src_label: &str) {
        let raw: RawManifest = match serde_json::from_str(text) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("[coupling_registry] parse {} failed: {}", src_label, e);
                return;
            }
        };
        let system_id = raw.identity.system_id;
        self.manifests.push(system_id.clone());

        for s in raw.operational_map.sensors {
            let qual = format!("{}:{}", system_id, s.name);

            let Some(read_kind) = ReadKind::parse(&s.read_kind) else {
                self.rejections.push(Rejection::BadReadKind {
                    sensor: qual,
                    kind: s.read_kind,
                });
                continue;
            };
            let criticality = Criticality::parse(&s.criticality);
            let normalize = s
                .normalize
                .map(|n| (n.lo, n.hi))
                .unwrap_or((0.0, 1.0));

            // ── target_dim validation + ownership ──────────────────────────────
            // Accept any dim ∈ B∪B' (matches validator.py). But OWNERSHIP differs:
            //   fixed-B {16,17,18,20} = hardware_ingest's domain (host self-monitoring);
            //     a manifest may declare it (e.g. a self-manifest) but the registry
            //     NEVER re-projects it — that would double-write the host's own ingest.
            //   B' [56..63] = the registry's domain — the coupled-S1 governance
            //     extension, load_bearing-only, lazily claimed, collision-checked.
            let mut target_dim = s.target_dim;
            if let Some(d) = target_dim {
                if !is_governed_dim(d) {
                    self.rejections.push(Rejection::BadTargetDim { sensor: qual.clone(), dim: d });
                    target_dim = None; // demote to φ↑ telemetry — never write an illegal dim
                } else if is_bprime_dim(d) {
                    // B' governance dim — load_bearing only, lazy claim, no collisions.
                    if criticality != Criticality::LoadBearing {
                        self.rejections.push(Rejection::NonLoadBearingDim { sensor: qual.clone(), dim: d });
                        target_dim = None;
                    } else if let Some(holder) = self.dim_assignments.get(&d) {
                        self.rejections.push(Rejection::DimCollision {
                            sensor: qual.clone(),
                            dim: d,
                            held_by: holder.clone(),
                        });
                        target_dim = None;
                    } else {
                        // lazy claim: a B' dim is consumed only now, by this sensor.
                        self.dim_assignments.insert(d, qual.clone());
                    }
                }
                // else: fixed-B slot — valid declaration, host-owned. target_dim is
                // kept for fidelity; read_and_project skips it (is_bprime_dim gate).
            }

            self.sensors.push(ManifestSensor {
                system_id: system_id.clone(),
                name: s.name,
                source: s.source,
                read_kind,
                category: s.category,
                criticality,
                normalize,
                target_dim,
            });
        }
    }

    /// The lowest free B' dim, or None if [56..63] is exhausted. For tooling that
    /// auto-assigns a dim to a newly confirmed load_bearing sensor.
    pub fn next_free_bprime(&self) -> Option<usize> {
        (B_PRIME_START..=B_PRIME_END).find(|d| !self.dim_assignments.contains_key(d))
    }

    /// Read a single scalar for an in-nucleus (procfs/sysfs) sensor. Heuristic:
    /// prefer a PSI `avg10=` token; else the first parseable float in the file.
    /// `None` if the file is absent/unparseable or the read-kind is deferred.
    pub fn read_scalar(sensor: &ManifestSensor) -> Option<f64> {
        if !sensor.read_kind.is_in_nucleus() {
            return None;
        }
        let text = fs::read_to_string(&sensor.source).ok()?;
        for tok in text.split_whitespace() {
            if let Some(v) = tok.strip_prefix("avg10=") {
                if let Ok(x) = v.parse::<f64>() {
                    return Some(x);
                }
            }
        }
        text.split_whitespace().find_map(|t| t.parse::<f64>().ok())
    }

    /// Read every in-nucleus sensor → (qualified name, normalized [0,1]). For φ↑
    /// telemetry (no state mutation). Deferred read-kinds are omitted.
    pub fn telemetry_read(&self) -> Vec<(String, f64)> {
        self.sensors
            .iter()
            .filter(|s| s.read_kind.is_in_nucleus())
            .filter_map(|s| {
                Self::read_scalar(s)
                    .filter(|v| v.is_finite())
                    .map(|raw| (format!("{}:{}", s.system_id, s.name), s.normalize_value(raw)))
            })
            .collect()
    }

    /// Project load_bearing, B'-mapped, in-nucleus sensors into `state`. The SOLE
    /// mutating sink. The registry governs ONLY B' [56..63] — fixed-B {16,17,18,20}
    /// is hardware_ingest's domain and is never re-projected here (no double-write).
    /// Returns the dims written. Today (motor2 only, no B' claim) this is a no-op —
    /// the path is real and tested; B' is consumed only when a manifest claims it.
    pub fn read_and_project(&self, state: &mut crate::state_vector::StateVector) -> Vec<usize> {
        let mut written = Vec::new();
        for s in &self.sensors {
            let Some(d) = s.target_dim else { continue };
            if !is_bprime_dim(d) {
                continue; // fixed-B is host-owned; non-B' never reaches here
            }
            if !s.read_kind.is_in_nucleus() {
                continue; // deferred reader owns this one
            }
            if let Some(raw) = Self::read_scalar(s) {
                if raw.is_finite() {
                    state.dims[d] = s.normalize_value(raw);
                    written.push(d);
                }
            }
        }
        written
    }

    /// Pure inventory summary for φ↑ (no I/O). Counts + B' assignments + rejections.
    pub fn summary(&self) -> RegistrySummary {
        let mut load_bearing = 0usize;
        let mut in_nucleus = 0usize;
        let mut deferred = 0usize;
        for s in &self.sensors {
            if s.criticality == Criticality::LoadBearing {
                load_bearing += 1;
            }
            if s.read_kind.is_in_nucleus() {
                in_nucleus += 1;
            } else {
                deferred += 1;
            }
        }
        let bprime: Vec<usize> = self
            .dim_assignments
            .keys()
            .copied()
            .filter(|d| is_bprime_dim(*d))
            .collect();
        RegistrySummary {
            manifests: self.manifests.len(),
            sensors: self.sensors.len(),
            load_bearing,
            in_nucleus,
            deferred,
            bprime_assigned: bprime,
            rejections: self.rejections.len(),
        }
    }
}

/// Compact, serializable registry inventory for the φ↑ kernel_tick block.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegistrySummary {
    pub manifests: usize,
    pub sensors: usize,
    pub load_bearing: usize,
    pub in_nucleus: usize,
    pub deferred: usize,
    pub bprime_assigned: Vec<usize>,
    pub rejections: usize,
}

impl RegistrySummary {
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "manifests": self.manifests,
            "sensors": self.sensors,
            "load_bearing": self.load_bearing,
            "in_nucleus": self.in_nucleus,
            "deferred": self.deferred,
            "bprime_assigned": self.bprime_assigned,
            "rejections": self.rejections,
        })
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;
    use crate::state_vector::StateVector;
    use std::io::Write;

    fn zero_state() -> StateVector {
        StateVector { dims: [0.0; 128] }
    }

    fn manifest(system_id: &str, sensors_json: &str) -> String {
        format!(
            r#"{{"identity":{{"system_id":"{}"}},"operational_map":{{"sensors":{}}}}}"#,
            system_id, sensors_json
        )
    }

    #[test]
    fn whitelist_matches_validator_b_union_bprime() {
        // {16,17,18,20} ∪ [56..63]; everything else rejected.
        for d in [16, 17, 18, 20, 56, 60, 63] {
            assert!(is_governed_dim(d), "{} should be governed", d);
        }
        for d in [0, 15, 19, 21, 22, 23, 48, 49, 55, 64, 127] {
            assert!(!is_governed_dim(d), "{} should NOT be governed", d);
        }
    }

    #[test]
    fn parses_motor2_shape_and_classifies_readers() {
        // mirror of examples/coupling/vsf-motor2.coupling.json operational_map
        let sensors = r#"[
            {"name":"cpu_pressure","source":"/proc/pressure/cpu","read_kind":"procfs_path","criticality":"important","normalize":{"lo":0,"hi":100},"target_dim":16},
            {"name":"mem_pressure","source":"memory.current/memory.max","read_kind":"cgroup_field","criticality":"important","target_dim":17},
            {"name":"disk_free_pct","source":"/var/lib/vsf","read_kind":"exec_cmd","criticality":"load_bearing","target_dim":null},
            {"name":"http_latency_p50","source":"http://x/health","read_kind":"http_metric","criticality":"important","target_dim":null}
        ]"#;
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("vsf-motor2", sensors), "test");
        assert_eq!(reg.sensors.len(), 4);
        let s = reg.summary();
        assert_eq!(s.manifests, 1);
        // cpu_pressure(procfs) is in-nucleus; cgroup/exec/http are deferred
        assert_eq!(s.in_nucleus, 1);
        assert_eq!(s.deferred, 3);
        assert_eq!(s.load_bearing, 1);
    }

    #[test]
    fn rejects_bad_read_kind() {
        let sensors = r#"[{"name":"x","read_kind":"black_magic","criticality":"important"}]"#;
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("s", sensors), "t");
        assert_eq!(reg.sensors.len(), 0);
        assert_eq!(reg.rejections.len(), 1);
        assert!(matches!(reg.rejections[0], Rejection::BadReadKind { .. }));
    }

    #[test]
    fn rejects_target_dim_outside_whitelist_but_keeps_sensor_as_telemetry() {
        // dim 22 ∈ Block B but NOT in the ingest whitelist {16,17,18,20} → rejected.
        let sensors = r#"[{"name":"q","source":"/x","read_kind":"procfs_path","criticality":"load_bearing","target_dim":22}]"#;
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("s", sensors), "t");
        assert_eq!(reg.sensors.len(), 1);
        assert_eq!(reg.sensors[0].target_dim, None); // demoted, not dropped
        assert!(matches!(reg.rejections[0], Rejection::BadTargetDim { dim: 22, .. }));
    }

    #[test]
    fn non_load_bearing_dim_is_demoted() {
        let sensors = r#"[{"name":"g","source":"/x","read_kind":"procfs_path","criticality":"important","target_dim":56}]"#;
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("s", sensors), "t");
        assert_eq!(reg.sensors[0].target_dim, None);
        assert!(matches!(reg.rejections[0], Rejection::NonLoadBearingDim { dim: 56, .. }));
        assert!(reg.dim_assignments.is_empty());
    }

    #[test]
    fn fixed_b_slot_claim_is_host_owned_not_projected() {
        // A manifest may declare a fixed-B dim {16,17,18,20} (e.g. a self-manifest),
        // but the registry never re-projects it — hardware_ingest owns those. No
        // rejection (it's a valid declaration), no B' claim, no write.
        let tf = tempfile_with("0.50");
        let sensors = format!(
            r#"[{{"name":"cpu","source":"{}","read_kind":"procfs_path","criticality":"load_bearing","normalize":{{"lo":0,"hi":1}},"target_dim":16}}]"#,
            tf.path_string()
        );
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("host", &sensors), "t");
        assert!(reg.rejections.is_empty(), "fixed-B claim is valid, not a rejection");
        assert!(reg.dim_assignments.is_empty(), "fixed-B is not a lazy B' claim");
        assert_eq!(reg.sensors[0].target_dim, Some(16)); // declaration kept for fidelity
        let mut st = zero_state();
        let written = reg.read_and_project(&mut st);
        assert!(written.is_empty(), "registry must not double-write hardware_ingest dims");
        assert_eq!(st.dims[16], 0.0);
    }

    #[test]
    fn lazy_bprime_allocation_and_collision() {
        // two load_bearing sensors both claim B' dim 56 → first wins, second collides.
        let sensors = r#"[
            {"name":"a","source":"/x","read_kind":"procfs_path","criticality":"load_bearing","target_dim":56},
            {"name":"b","source":"/y","read_kind":"procfs_path","criticality":"load_bearing","target_dim":56}
        ]"#;
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("s", sensors), "t");
        assert_eq!(reg.dim_assignments.get(&56).map(|s| s.as_str()), Some("s:a"));
        assert_eq!(reg.sensors[0].target_dim, Some(56));
        assert_eq!(reg.sensors[1].target_dim, None); // collided → telemetry only
        assert!(reg.rejections.iter().any(|r| matches!(r, Rejection::DimCollision { dim: 56, .. })));
        assert_eq!(reg.next_free_bprime(), Some(57));
    }

    #[test]
    fn next_free_bprime_exhaustion() {
        let mut reg = SensorRegistry::default();
        for d in B_PRIME_START..=B_PRIME_END {
            reg.dim_assignments.insert(d, format!("s:{}", d));
        }
        assert_eq!(reg.next_free_bprime(), None);
    }

    #[test]
    fn read_scalar_avg10_and_first_float() {
        let mut psi = tempfile_with("some avg10=12.50 avg60=3.0 total=999");
        let s_psi = procfs_sensor("/proc/x", (0.0, 100.0));
        // point the sensor at our temp file
        let mut s = s_psi.clone();
        s.source = psi.path_string();
        assert_eq!(SensorRegistry::read_scalar(&s), Some(12.50));

        let mut bare = tempfile_with("0.42");
        let mut s2 = procfs_sensor("/proc/y", (0.0, 1.0));
        s2.source = bare.path_string();
        assert_eq!(SensorRegistry::read_scalar(&s2), Some(0.42));
        drop(&mut psi);
        drop(&mut bare);
    }

    #[test]
    fn read_and_project_writes_only_bprime_load_bearing_file_sensors() {
        // a load_bearing procfs sensor targeting B' dim 56 → projected; an exec_cmd
        // load_bearing sensor targeting 57 → deferred (not read in-nucleus).
        let tf = tempfile_with("0.30");
        let sensors = format!(
            r#"[
              {{"name":"fd","source":"{}","read_kind":"procfs_path","criticality":"load_bearing","normalize":{{"lo":0,"hi":1}},"target_dim":56}},
              {{"name":"disk","source":"df /x","read_kind":"exec_cmd","criticality":"load_bearing","target_dim":57}}
            ]"#,
            tf.path_string()
        );
        let mut reg = SensorRegistry::default();
        reg.ingest_manifest_str(&manifest("s", &sensors), "t");
        let mut st = zero_state();
        let written = reg.read_and_project(&mut st);
        assert_eq!(written, vec![56]);            // only the procfs one
        assert!((st.dims[56] - 0.30).abs() < 1e-9);
        assert_eq!(st.dims[57], 0.0);             // exec_cmd deferred → untouched
    }

    #[test]
    fn empty_dir_is_safe_no_op() {
        let reg = SensorRegistry::load_dir("/nonexistent/coupling/dir");
        assert_eq!(reg.sensors.len(), 0);
        assert_eq!(reg.summary().sensors, 0);
        let mut st = zero_state();
        assert!(reg.read_and_project(&mut st).is_empty());
    }

    #[test]
    fn normalize_clamps() {
        let s = procfs_sensor("/x", (0.0, 100.0));
        assert!((s.normalize_value(50.0) - 0.5).abs() < 1e-9);
        assert_eq!(s.normalize_value(200.0), 1.0); // clamp hi
        assert_eq!(s.normalize_value(-5.0), 0.0);  // clamp lo
    }

    // ── test helpers ────────────────────────────────────────────────────────────
    fn procfs_sensor(source: &str, normalize: (f64, f64)) -> ManifestSensor {
        ManifestSensor {
            system_id: "s".into(),
            name: "n".into(),
            source: source.into(),
            read_kind: ReadKind::ProcfsPath,
            category: "gauge".into(),
            criticality: Criticality::Important,
            normalize,
            target_dim: None,
        }
    }

    struct TempFile {
        path: std::path::PathBuf,
    }
    impl TempFile {
        fn path_string(&self) -> String {
            self.path.display().to_string()
        }
    }
    impl Drop for TempFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.path);
        }
    }
    fn tempfile_with(contents: &str) -> TempFile {
        let mut p = std::env::temp_dir();
        let uniq = format!(
            "vsf_cr_test_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        p.push(uniq);
        let mut f = fs::File::create(&p).unwrap();
        f.write_all(contents.as_bytes()).unwrap();
        TempFile { path: p }
    }
}
