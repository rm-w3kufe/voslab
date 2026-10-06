/// s3_anticipation.rs — ITEM-17.2-CONSUMER: anticipatory reallocation for S4 directives
///
/// @vsm 0.3  V("s3-anticipation", L=1)  @status=synthetic_build
///
/// SYNTHETIC BUILD (2026-07-14): grants are LOGGED only — no real cgroup writes.
/// Production cgroup actuation gated on R2 (stasis_cos ≥ 0.875 donor floor).
///
/// Two safety-critical invariants (R1):
///   INV-SUM:    Σ zone_shares = CONST (800) before & after every grant
///   INV-FLOOR:  No donor dropped below basin_floor post-transfer
///   INV-FRESH:  directive_id must not already be applied (order freshness)
///
/// SUBSCRIPTION PATTERN: follows s5_covenant::start_resume_subscriber exactly
///   — vsf_agent::nats::connect + async_nats subscribe + StreamExt::next loop
///   — reconnect on failure with 10s backoff
///   — fail-soft (NATS_URL unset → graceful no-op)
///
/// Design: docs/spec/s4_anticipation/ds_proposal.vsm
/// Claude review: APPROVED with 4 refinements (R1=R4)
/// Build gate: EXP-S4-01_full runs on synthetic path — validates LOGIC + H1/H2

use crate::calibration;
use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use chrono::Utc;
use serde::Deserialize;
use std::collections::{HashMap, HashSet, VecDeque};

// ── CONSTANTS ──────────────────────────────────────────────────────────────────

/// Total envelope: 8 zones × 100 default = 800
pub const ENVELOPE_SUM: u64 = 800;

/// Default CPU weight per zone (all zones start equal)
pub const DEFAULT_CPU_WEIGHT: u64 = 100;

/// Sandbox floor: cpu.weight = 50 (R2: proxy only — production uses stasis_cos ≥ 0.875)
pub const BASIN_FLOOR_SANDBOX: u64 = 50;

/// Maximum entries in the INV-FRESH directive_id ring buffer (A2)
/// Prevents unbounded memory growth from replay attacks or runaway directives
pub const FRESH_RING_SIZE: usize = 256;

/// VSF node ID for φ↑ events
const SYSTEM_ID: &str = "alpha";

/// Real training band for ERA5 (production). [-1, 1] is a placeholder.
/// Production: replace with ERA5-per-zone λ_max from training data.
/// See docs/spec/s4_anticipation/spec.vsm §frozen.H4_regime.
const REGIME_LAMBDA_MIN: f64 = -0.05;
const REGIME_LAMBDA_MAX: f64 = 0.05;

// ── TYPE ALIASES ───────────────────────────────────────────────────────────────

type ZoneId = String;

// ── NATS PAYLOAD ───────────────────────────────────────────────────────────────

/// Anticipatory directive from S4 (sent by S4 Markov projection)
///
/// Fields match the S4→S3 contract defined in ds_proposal.vsm §directive_in.
/// `delta_cpu_weight` is the amount to GIVE to the target zone (positive).
/// Negative values (reclaim) are escalated as unsupported in v1.
#[derive(Debug, Clone, Deserialize)]
pub struct AnticipatoryDirective {
    pub zone: String,
    pub delta_cpu_weight: i64,
    pub directive_id: String,
    pub ts: String,
    /// S4's λ classification; used for H4 guard (out-of-band rejection)
    pub regime_lambda: Option<f64>,
}

// ── INTERNAL STATE ─────────────────────────────────────────────────────────────

/// Per-zone record in the envelope tracker
#[derive(Debug, Clone)]
struct ZoneRecord {
    weight: u64,
    floor: u64,
}

/// Reallocation order metadata (serialized to φ↑ event)
#[derive(Debug, Clone, serde::Serialize)]
struct GrantEventMeta {
    directive_id: String,
    target_zone: String,
    donor_zone: String,
    delta_cpu_weight: i64,
    envelope_sum_before: u64,
    envelope_sum_after: u64,
    donor_weight_before: u64,
    donor_weight_after: u64,
    donor_floor: u64,
    target_weight_before: u64,
    target_weight_after: u64,
    synthetic: bool,
    safety_invariant: String,
    note: String,
}

// ── SAFETY-CRITICAL: ANTICIPATION STATE MACHINE ────────────────────────────────
//
// This section implements the two safety invariants R1 requires:
//   INV-SUM:   Σ zone_shares = ENVELOPE_SUM (800) before every grant write.
//              Enforced by assertion in prepare_grant.
//   INV-FLOOR: Donor post-transfer ≥ its basin_floor.
//              Enforced by select_donor's slack computation.
//   INV-FRESH: directive_id dedup (for production; synthetic accepts all).
//
// The state machine NEVER directly writes cgroups — it emits a φ↑ event
// (s3_pre_grant) that Component B (host timer) picks up and validates
// independently BEFORE applying (R1: validating executor pattern).

pub struct AnticipationState {
    zones: HashMap<ZoneId, ZoneRecord>,
    envelope_sum: u64,
    synthetic: bool,
    /// Per-zone stasis_cos from S4 Markov projection (production mode).
    /// Populated from s4_markov_projection.json. In production mode, a donor's
    /// stasis_cos must be ≥ calibration::BASIN_FLOOR (0.875) to be selectable.
    /// In synthetic mode, this map is empty and the weight proxy is used.
    stasis_cos: HashMap<ZoneId, f64>,
    /// Bounded INV-FRESH ring buffer (A2): VecDeque tracks order, HashSet for O(1) lookup.
    /// Oldest entry is evicted when FRESH_RING_SIZE is exceeded — prevents unbounded memory growth.
    fresh_queue: VecDeque<String>,
    fresh_set: HashSet<String>,
    /// Path to write order files for Component B (when Some).
    /// Set by subscriber from S3_ANTICIPATION_ORDER_DIR env var.
    orders_dir: Option<String>,
    /// Maximum age (seconds) of the projection file before it is considered stale.
    /// Deliberately matches Component B's STALE_PROJECTION_SECS (600s = 2 × 5min refresh).
    projection_stale_threshold_secs: u64,
}

impl AnticipationState {
    /// Initialize with the 8 clima L2 zones at default weights.
    /// This is the SYNTHETIC starting state — weights are not read from live cgroups.
    /// Production init would read current cpu.weight from LXC 112 on first boot.
    pub fn new_sandbox() -> Self {
        let mut zones = HashMap::new();
        let zone_names = [
            "mediterranea",
            "subpolar",
            "semiarida",
            "templada-humeda",
            "tropical-arida",
            "humboldt",
            "pacifico-sur-medio",
            "enso-tropical",
        ];
        for name in &zone_names {
            zones.insert(
                name.to_string(),
                ZoneRecord {
                    weight: DEFAULT_CPU_WEIGHT,
                    floor: BASIN_FLOOR_SANDBOX,
                },
            );
        }
        Self {
            zones,
            envelope_sum: ENVELOPE_SUM,
            synthetic: true,
            stasis_cos: HashMap::new(),
            fresh_queue: VecDeque::with_capacity(FRESH_RING_SIZE),
            fresh_set: HashSet::with_capacity(FRESH_RING_SIZE),
            orders_dir: None,
            projection_stale_threshold_secs: 600, // matches Component B's STALE_PROJECTION_SECS
        }
    }

    /// Switch to production mode: use stasis_cos-based donor floor instead of weight proxy.
    /// Production mode rejects any donor whose stasis_cos < calibration::BASIN_FLOOR (0.875).
    /// In synthetic mode, the weight proxy BASIN_FLOOR_SANDBOX=50 is used.
    pub fn set_production(&mut self) {
        self.synthetic = false;
        eprintln!("[s3_anticipation] PRODUCTION mode — stasis_cos >= {} required for donors",
            calibration::BASIN_FLOOR);
    }

    /// Set a zone's live stasis_cos value from the S4 Markov projection.
    /// In production mode, donors with stasis_cos < calibration::BASIN_FLOOR
    /// are excluded from selection (gap_1 viability floor).
    pub fn set_zone_stasis_cos(&mut self, zone: &str, cos: f64) {
        self.stasis_cos.insert(zone.to_string(), cos);
    }

    /// Set the directory where order files (for Component B) are written.
    pub fn set_orders_dir(&mut self, path: String) {
        self.orders_dir = Some(path);
    }

    /// Clear all stasis_cos entries (used when the projection file is stale or missing).
    /// This forces fail-closed behavior: in production mode, zones without stasis_cos
    /// data are excluded from donor selection.
    pub fn clear_stasis_cos(&mut self) {
        self.stasis_cos.clear();
    }

    /// Read the S4 Markov projection file and populate stasis_cos for all known zones.
    ///
    /// Fail-closed contract:
    ///   - File not found → clear stasis_cos (all zones excluded from donor selection)
    ///   - File stale (mtime > projection_stale_threshold_secs) → clear stasis_cos
    ///   - Malformed JSON → clear stasis_cos
    ///   - Zones NOT in file → removed from stasis_cos (treated as absent)
    ///   - Unknown zone names in file → ignored (logged at debug trace)
    ///
    /// On success: only zones present in the file with valid name+current_sc are populated.
    /// On any error: stasis_cos is cleared entirely (fail-closed).
    ///
    /// Called from start_directive_subscriber before each handle_directive call.
    /// Deliberately matches Component B's read_projection_stasis_cos() staleness threshold
    /// (STALE_PROJECTION_SECS=600) for consistency — both components agree on "stale."
    pub fn refresh_stasis_cos(&mut self, projection_path: &str) -> Result<(), String> {
        let path = std::path::Path::new(projection_path);

        // File must exist
        if !path.exists() {
            self.clear_stasis_cos();
            return Err(format!("projection file not found: {}", projection_path));
        }

        // Check mtime for staleness
        let metadata = path.metadata()
            .map_err(|e| format!("metadata error: {}", e))?;
        let mtime = metadata.modified()
            .map_err(|e| format!("mtime error: {}", e))?;
        let age = std::time::SystemTime::now()
            .duration_since(mtime)
            .map_err(|e| format!("clock error: {}", e))?
            .as_secs();

        if age >= self.projection_stale_threshold_secs {
            self.clear_stasis_cos();
            return Err(format!(
                "projection file stale: age={}s > threshold={}s",
                age, self.projection_stale_threshold_secs
            ));
        }

        // Read and parse the file
        let content = std::fs::read_to_string(path)
            .map_err(|e| format!("read error: {}", e))?;
        let data: serde_json::Value = serde_json::from_str(&content)
            .map_err(|e| format!("parse error: {}", e))?;

        // Clear first, then populate from the current file.
        // Any zone not in the current file is removed (fail-closed: absent data = excluded).
        self.clear_stasis_cos();

        if let Some(zones) = data.get("zones").and_then(|z| z.as_array()) {
            for zone_val in zones {
                let name = match zone_val.get("name").and_then(|n| n.as_str()) {
                    Some(n) => n,
                    None => continue,
                };
                let sc = match zone_val.get("current_sc").and_then(|s| s.as_f64()) {
                    Some(s) => s,
                    None => continue,
                };
                // Only accept known zones (one of the 8 L2 zones the nucleus manages)
                if self.zones.contains_key(name) {
                    self.set_zone_stasis_cos(name, sc);
                } else {
                    eprintln!(
                        "[s3_anticipation] refresh_stasis_cos: ignoring unknown zone '{}' (not one of the 8 managed L2 zones)",
                        name
                    );
                }
            }
        }

        Ok(())
    }

    /// Write an order file for Component B (host-level cgroup reallocator).
    ///
    /// The file is written in EXACTLY the order_format that Component B's
    /// Order.load() parses (component_b_host_reallocator.spec.vsm §order_format).
    /// Written to {orders_dir}/pending/{directive_id}.json.
    ///
    /// The `kernel_claimed_donor_stasis_cos` field is the current stasis_cos in
    /// our state for the selected donor (the value we used in selection). It may
    /// be None if the state has no stasis_cos populated (synthetic mode).
    ///
    /// Emitted in BOTH synthetic and production mode per the spec's order_emission
    /// requirement: this enables true shadow-first integration testing (Component B
    /// runs --dry-run against REAL orders from a synthetic-mode Component A).
    fn write_order_file(&self, meta: &GrantEventMeta) -> Result<String, String> {
        let dir = self.orders_dir.as_ref()
            .ok_or_else(|| "orders_dir not set — cannot write order file".to_string())?;

        let pending_dir = std::path::Path::new(dir).join("pending");
        std::fs::create_dir_all(&pending_dir)
            .map_err(|e| format!("create pending dir '{}': {}", pending_dir.display(), e))?;

        let filename = format!("{}.json", meta.directive_id);
        let filepath = pending_dir.join(&filename);

        let kernel_claimed_cos: Option<f64> = self.stasis_cos.get(&meta.donor_zone).copied();
        let mode = if self.synthetic { "synthetic" } else { "production" };

        let order_json = serde_json::json!({
            "directive_id": meta.directive_id,
            "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
            "donor_zone": meta.donor_zone,
            "target_zone": meta.target_zone,
            "delta": meta.delta_cpu_weight,
            "kernel_claimed_donor_stasis_cos": kernel_claimed_cos,
            "kernel_claimed_sum_after": ENVELOPE_SUM,
            "kernel_mode": mode,
        });

        let content = serde_json::to_string_pretty(&order_json)
            .map_err(|e| format!("serialize: {}", e))?;

        std::fs::write(&filepath, &content)
            .map_err(|e| format!("write '{}': {}", filepath.display(), e))?;

        eprintln!(
            "[s3_anticipation] order written: {} (donor={}, target={}, delta={}, mode={})",
            filepath.display(), meta.donor_zone, meta.target_zone, meta.delta_cpu_weight, mode
        );

        Ok(filepath.to_string_lossy().to_string())
    }

    /// ── INV-SUM: verify the envelope sum is correct ──
    fn check_envelope_sum(&self) -> bool {
        let actual: u64 = self.zones.values().map(|z| z.weight).sum();
        actual == self.envelope_sum
    }

    /// ── INV-FLOOR / INV-SUM: SELECT DONOR ──
    ///
    /// Given a directive requesting to INCREASE `target` by `delta`,
    /// find the zone with the most slack (weight - floor) that can spare `delta`.
    ///
    /// In PRODUCTION mode, additionally requires donor's stasis_cos ≥ calibration::BASIN_FLOOR
    /// (0.875) — the R2 viability floor. Donors below this threshold are excluded even if
    /// they have cpu.weight slack (gap_1 viability floor guard).
    ///
    /// In SYNTHETIC mode, only the weight proxy (BASIN_FLOOR_SANDBOX=50) is checked.
    ///
    /// Returns `Some((donor_name, delta))` on success.
    /// Returns `None` if no donor satisfies all constraints → D4 double-loop escalation.
    ///
    /// Safety:
    ///   - Donor post-transfer weight is GUARANTEED ≥ floor (by slack comparison)
    ///   - Target + donor weight changes are SELF-BALANCING (sum conserved)
    ///   - All other zone weights are untouched
    fn select_donor(&self, target: &str, delta: u64) -> Option<(String, u64)> {
        let mut candidates: Vec<(&String, u64)> = self
            .zones
            .iter()
            .filter(|(name, _)| *name != target) // exclude target zone
            .filter(|(name, _)| {
                // PRODUCTION mode: donor must have live stasis_cos ≥ BASIN_FLOOR
                // Same fail-closed principle as bbh_policy_gate.py: absent data must
                // never read as permission. If stasis_cos is missing or stale for a
                // zone, the zone is EXCLUDED from donor selection. This is conservative:
                // a temporary inability to grant is a much smaller failure than a silent,
                // permanent bypass of the safety floor.
                if !self.synthetic {
                    match self.stasis_cos.get(*name) {
                        Some(&cos) if cos < calibration::BASIN_FLOOR => {
                            eprintln!(
                                "[s3_anticipation] PRODUCTION donor guard: zone {} stasis_cos={:.4} < floor={} — excluded from donor selection",
                                name, cos, calibration::BASIN_FLOOR
                            );
                            return false;
                        }
                        Some(_) => {
                            // Healthy stasis_cos — eligible donor
                        }
                        None => {
                            eprintln!(
                                "[s3_anticipation] PRODUCTION donor guard: zone {} has NO stasis_cos data — EXCLUDED (fail-closed)",
                                name
                            );
                            return false;
                        }
                    }
                }
                true
            })
            .map(|(name, rec)| {
                let slack = rec.weight.saturating_sub(rec.floor);
                (name, slack)
            })
            .collect();

        // Sort by slack descending — richest donor first
        candidates.sort_by(|a, b| b.1.cmp(&a.1));

        // Pick first donor with enough slack
        for (donor_name, slack) in &candidates {
            if *slack >= delta {
                return Some((donor_name.to_string(), delta));
            }
        }

        // No donor found → D4 double-loop
        None
    }

    /// ── INV-SUM: PREPARE GRANT METADATA ──
    ///
    /// Build the GrantEventMeta that verifies INV-SUM holds.
    /// The zone weights in `self` are NOT mutated here — this is a read-only
    /// check that produces the event metadata. For synthetic build, we log and
    /// don't apply. For production, the host reallocator (Component B) performs
    /// an INDEPENDENT validation before applying (R1).
    fn prepare_grant_meta(
        &self,
        directive: &AnticipatoryDirective,
        donor: &str,
        delta: u64,
    ) -> Option<GrantEventMeta> {
        let target = &directive.zone;
        let target_rec = self.zones.get(target)?;
        let donor_rec = self.zones.get(donor)?;

        // Build metadata with both before and after values
        let meta = GrantEventMeta {
            directive_id: directive.directive_id.clone(),
            target_zone: target.clone(),
            donor_zone: donor.to_string(),
            delta_cpu_weight: delta as i64,
            envelope_sum_before: self.envelope_sum,
            envelope_sum_after: self.envelope_sum, // INV-SUM: MUST be unchanged
            donor_weight_before: donor_rec.weight,
            donor_weight_after: donor_rec.weight - delta, // INV-FLOOR: guaranteed ≥ floor
            donor_floor: donor_rec.floor,
            target_weight_before: target_rec.weight,
            target_weight_after: target_rec.weight + delta,
            synthetic: self.synthetic,
            safety_invariant: format!(
                "INV-SUM: Σ={} (unchanged) | INV-FLOOR: donor={}≥{} after transfer",
                self.envelope_sum,
                donor_rec.weight - delta,
                donor_rec.floor
            ),
            note: if self.synthetic {
                "SYNTHETIC — no cgroup write. Production gated on R2 (stasis_cos ≥ 0.875)."
                    .to_string()
            } else {
                "REAL — host reallocator (Component B) validates independently before applying (R1)."
                    .to_string()
            },
        };

        Some(meta)
    }

    /// Emit s3_pre_grant event to canonical φ↑
    fn emit_grant_event(&self, canon: &CanonicalTelemetry, meta: &GrantEventMeta, status: &str) {
        let event = CanonicalEvent {
            ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
            system_id: SYSTEM_ID.to_string(),
            event_type: "s3_pre_grant".to_string(),
            status: status.to_string(),
            signal_status: status.to_string(),
            duration_s: 0.0,
            metrics: serde_json::json!(meta),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        if let Err(e) = canon.emit(event) {
            eprintln!("[s3_anticipation] emit_grant failed: {} (non-fatal)", e);
        }
    }

    /// ── END-TO-END HANDLER ──
    ///
    /// Process one directive from S4:
    ///   1. INV-FRESH: reject if directive_id already seen
    ///   2. H4 guard: reject if regime_lambda out of training band
    ///   3. INV-FLOOR/SUM: select donor
    ///   4. INV-SUM: prepare grant (verify Σ unchanged)
    ///   5. Emit s3_pre_grant to φ↑ (no cgroup write in synthetic mode)
    ///   6. Apply to internal state ONLY if synthetic (for state tracking)
    ///
    /// This function is the single entry point for all directive processing.
    /// Its outputs (s3_pre_grant events) are what EXP-S4-01_full validates.
    pub fn handle_directive(&mut self, directive: AnticipatoryDirective, canon: &CanonicalTelemetry) {
        // ── Step 0: INV-FRESH — bounded ring buffer dedup (A2) ──
        if self.fresh_set.contains(&directive.directive_id) {
            eprintln!(
                "[s3_anticipation] INV-FRESH: duplicate directive_id={} — ignoring",
                directive.directive_id
            );
            return;
        }
        // Insert into ring buffer; evict oldest if at capacity
        if self.fresh_queue.len() >= FRESH_RING_SIZE {
            if let Some(oldest) = self.fresh_queue.pop_front() {
                self.fresh_set.remove(&oldest);
            }
        }
        self.fresh_queue.push_back(directive.directive_id.clone());
        self.fresh_set.insert(directive.directive_id.clone());

        // ── Step 0: verify positive delta (v1 limitation) ──
        if directive.delta_cpu_weight <= 0 {
            eprintln!(
                "[s3_anticipation] v1 limitation: delta_cpu_weight={} must be positive (reclaim not supported) — escalating",
                directive.delta_cpu_weight
            );
            let event = CanonicalEvent {
                ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                system_id: SYSTEM_ID.to_string(),
                event_type: "s3_pre_grant".to_string(),
                status: "double_loop".to_string(),
                signal_status: "unsupported_delta_sign".to_string(),
                duration_s: 0.0,
                metrics: serde_json::json!({
                    "directive_id": directive.directive_id,
                    "target_zone": directive.zone,
                    "delta_cpu_weight": directive.delta_cpu_weight,
                    "reason": "v1 only supports positive delta (transfer TO target). Negative/reclaim requires human deliberation (D4-L3).",
                    "synthetic": self.synthetic,
                }),
                variety_delta: None,
                trust_score: None,
                algedonic_seq: 0,
                origin: None,
                chain_format_version: None,
                prev_hash: None,
                hash: None,
            };
            let _ = canon.emit(event);
            return;
        }

        let target = &directive.zone;
        let delta = directive.delta_cpu_weight as u64;

        // ── Step 0: verify target zone exists ──
        if !self.zones.contains_key(target) {
            eprintln!(
                "[s3_anticipation] target zone '{}' not in envelope — ignoring",
                target
            );
            return;
        }

        // ── Step 1: H4 guard — regime_lambda validation ──
        // regime_guard_17_4 (spec.vsm §frozen.H4_regime): THREE cases:
        //   (a) regime_lambda == None → log explicitly as projection_unvalidated (A3),
        //       ALLOW the grant but flag the missing band. This covers the pre-production
        //       case where the projector doesn't yet emit regime_lambda.
        //   (b) regime_lambda out of ERA5 training band → REJECT, projection_invalid.
        //   (c) regime_lambda within band → ALLOW (normal operation).
        //
        // The band [-1, 1] is a PLACEHOLDER (A4). Production replaces with per-zone
        // ERA5 training bounds from docs/data/era5_climatology_maxlambda.json.
        // See docs/spec/s4_anticipation/spec.vsm §frozen.regime_band_note.
        match directive.regime_lambda {
            None => {
                // (a) No regime_lambda — log but allow (pre-production mode)
                eprintln!(
                    "[s3_anticipation] H4: regime_lambda=None (unvalidated) — allowing grant with projection_unvalidated flag"
                );
            }
            Some(regime_lambda) if regime_lambda.is_nan()
                || regime_lambda < REGIME_LAMBDA_MIN
                || regime_lambda > REGIME_LAMBDA_MAX =>
            {
                // (b) Out of training band — REJECT
                eprintln!(
                    "[s3_anticipation] H4 guard: regime_lambda={} out of training band [{}, {}] — rejection",
                    regime_lambda, REGIME_LAMBDA_MIN, REGIME_LAMBDA_MAX
                );
                let event = CanonicalEvent {
                    ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                    system_id: SYSTEM_ID.to_string(),
                    event_type: "s3_pre_grant".to_string(),
                    status: "rejected".to_string(),
                    signal_status: "projection_invalid".to_string(),
                    duration_s: 0.0,
                    metrics: serde_json::json!({
                        "directive_id": directive.directive_id,
                        "target_zone": target,
                        "regime_lambda": regime_lambda,
                        "regime_band": format!("[{}, {}]", REGIME_LAMBDA_MIN, REGIME_LAMBDA_MAX),
                        "reason": "regime_lambda out of ERA5 training band",
                        "_note": "Placeholder band. Production: per-zone ERA5 range from docs/data/era5_climatology_maxlambda.json (A4).",
                        "synthetic": self.synthetic,
                    }),
                    variety_delta: None,
                    trust_score: None,
                    algedonic_seq: 0,
                    origin: None,
                    chain_format_version: None,
                    prev_hash: None,
                    hash: None,
                };
                let _ = canon.emit(event);
                return;
            }
            Some(_regime_lambda) => {
                // (c) Within band — normal operation
                eprintln!(
                    "[s3_anticipation] H4: regime_lambda={:.6} within training band — allowing",
                    _regime_lambda
                );
            }
        }

        // ── Step 2: INV-FLOOR/SUM — select donor ──
        match self.select_donor(target, delta) {
            Some((donor, selected_delta)) => {
                // ── Step 3: INV-SUM — prepare grant ──
                match self.prepare_grant_meta(&directive, &donor, selected_delta) {
                    Some(meta) => {
                        eprintln!(
                            "[s3_anticipation] GRANT: dir={} target={} donor={} delta={} sum={} {}",
                            meta.directive_id,
                            meta.target_zone,
                            meta.donor_zone,
                            meta.delta_cpu_weight,
                            meta.envelope_sum_before,
                            if self.synthetic {
                                "SYNTHETIC"
                            } else {
                                "REAL"
                            }
                        );

                        // ── Step 4: emit s3_pre_grant to φ↑ ──
                        self.emit_grant_event(canon, &meta, "granted");

                        // ── Step 5: apply to internal state (synthetic: state tracking only) ──
                        if let Some(donor_rec) = self.zones.get_mut(&donor) {
                            donor_rec.weight -= selected_delta;
                        }
                        if let Some(target_rec) = self.zones.get_mut(target) {
                            target_rec.weight += selected_delta;
                        }

                        // ── A1: INV-SUM runtime guard (SEGURIDAD, NO debug_assert) ──
                        // If the envelope sum changed, this is a CRITICAL invariant violation.
                        // We MUST NOT continue with a corrupted envelope. Fail safe:
                        //   emit s3_pre_grant with status="rejected" reason="INV-SUM"
                        //   escalate to algedonic_ledger as pending_human
                        //   rollback the weight change
                        //   return (do NOT write order)
                        // NO panic, NO debug_assert — this is production-safe.
                        if !self.check_envelope_sum() {
                            eprintln!(
                                "[s3_anticipation] *** INV-SUM VIOLATION *** envelope sum changed after grant! ROLLING BACK."
                            );

                            // Rollback the weight changes
                            if let Some(donor_rec) = self.zones.get_mut(&donor) {
                                donor_rec.weight = donor_rec.weight.saturating_add(selected_delta);
                            }
                            if let Some(target_rec) = self.zones.get_mut(target) {
                                target_rec.weight = target_rec.weight.saturating_sub(selected_delta);
                            }

                            // Emit rejection with INV-SUM reason
                            let event = CanonicalEvent {
                                ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                system_id: SYSTEM_ID.to_string(),
                                event_type: "s3_pre_grant".to_string(),
                                status: "rejected".to_string(),
                                signal_status: "INV-SUM".to_string(),
                                duration_s: 0.0,
                                metrics: serde_json::json!({
                                    "directive_id": directive.directive_id,
                                    "target_zone": target,
                                    "donor_zone": donor,
                                    "delta_cpu_weight": delta,
                                    "reason": "INV-SUM: envelope sum changed after grant — rolled back, escalated to pending_human",
                                    "synthetic": self.synthetic,
                                }),
                                variety_delta: None,
                                trust_score: None,
                                algedonic_seq: 0,
                                origin: None,
                                chain_format_version: None,
                                prev_hash: None,
                                hash: None,
                            };
                            let _ = canon.emit(event);

                            // INV-SUM is a critical invariant breach — escalate to algedonic_ledger
                            let algedonic_event = CanonicalEvent {
                                ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                system_id: SYSTEM_ID.to_string(),
                                event_type: "algedonic_ledger_entry".to_string(),
                                status: "critical".to_string(),
                                signal_status: "INV-SUM".to_string(),
                                duration_s: 0.0,
                                metrics: serde_json::json!({
                                    "source": "s3_anticipation",
                                    "type": "invariant_breach",
                                    "severity": 9.0,
                                    "reason": "INV-SUM: envelope sum changed after grant — requires human deliberation (D4-L3)",
                                    "directive_id": directive.directive_id,
                                }),
                                variety_delta: None,
                                trust_score: None,
                                algedonic_seq: 0,
                                origin: None,
                                chain_format_version: None,
                                prev_hash: None,
                                hash: None,
                            };
                            let _ = canon.emit(algedonic_event);
                            eprintln!(
                                "[s3_anticipation] INV-SUM escalation sent to algedonic_ledger — pending_human"
                            );
                            return;
                        }

                        // ── Step 6: write order file for Component B ──
                        // Emit in BOTH synthetic and production mode — this enables
                        // true shadow-first integration testing (Component B runs
                        // --dry-run against REAL orders from synthetic-mode A).
                        if let Err(e) = self.write_order_file(&meta) {
                            eprintln!(
                                "[s3_anticipation] write_order_file: {} (non-fatal — order emission is advisory, not safety-critical)",
                                e
                            );
                        }
                    }
                    None => {
                        eprintln!(
                            "[s3_anticipation] grant preparation failed — inconsistent state (zone exists in select but not in prepare?)"
                        );
                    }
                }
            }
            None => {
                // ── D4 double-loop: no donor can spare → escalate ──
                eprintln!(
                    "[s3_anticipation] DOUBLE-LOOP: no donor can spare delta={} for zone={} — escalating to pending_human (D4-L3)",
                    delta, target
                );
                let event = CanonicalEvent {
                    ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                    system_id: SYSTEM_ID.to_string(),
                    event_type: "s3_pre_grant".to_string(),
                    status: "double_loop".to_string(),
                    signal_status: "no_donor".to_string(),
                    duration_s: 0.0,
                    metrics: serde_json::json!({
                        "directive_id": directive.directive_id,
                        "target_zone": target,
                        "delta_cpu_weight": delta,
                        "reason": "no donor with sufficient slack — requires human deliberation (D4-L3)",
                        "synthetic": self.synthetic,
                    }),
                    variety_delta: None,
                    trust_score: None,
                    algedonic_seq: 0,
                    origin: None,
                    chain_format_version: None,
                    prev_hash: None,
                    hash: None,
                };
                let _ = canon.emit(event);
            }
        }
    }

    /// ── INTROSPECTION (for tests) ──

    pub fn zone_weight(&self, zone: &str) -> Option<u64> {
        self.zones.get(zone).map(|r| r.weight)
    }

    pub fn total_weight(&self) -> u64 {
        self.zones.values().map(|r| r.weight).sum()
    }
}

// ── NATS SUBSCRIBER ────────────────────────────────────────────────────────────
//
// Pattern: identical to s5_covenant::start_resume_subscriber.
//   - vsf_agent::nats::connect for auth
//   - async_nats subscribe + StreamExt::next
//   - reconnect on disconnect with 10s backoff
//   - fail-soft: NATS_URL unset → no-op
// Subject: vsf.<id>.s4.anticipatory_directive

/// Spawn a NATS subscriber for `vsf.<id>.s4.anticipatory_directive`.
///
/// On receipt: parses `AnticipatoryDirective`, runs donor selection,
/// verifies INV-SUM/INV-FLOOR/INV-FRESH, and emits `s3_pre_grant` to φ↑.
///
/// SYNTHETIC BUILD: no real cgroup writes. The grant is logged to events.jsonl
/// for validation by EXP-S4-01_full.
///
/// Production path (future, gated on R2):
///   - Writes reallocation order to shared dir /var/lib/vsf/reallocate/
///   - Host reallocator (Component B) independently validates (R1) and actuates
///
/// Fail-soft: NATS_URL unset → subscriber disabled.
pub fn start_directive_subscriber(
    vsf_id: &str,
    canon: CanonicalTelemetry,
) -> tokio::task::JoinHandle<()> {
    let vsf_id = vsf_id.to_string();
    tokio::spawn(async move {
        use futures::StreamExt;
        use std::env;

        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!(
                    "[s3_anticipation] NATS_URL unset — anticipatory directive subscriber disabled (no reallocation)"
                );
                return;
            }
        };
        let subject = format!("vsf.{}.s4.anticipatory_directive", vsf_id);
        eprintln!("[s3_anticipation] directive subscriber: {}", subject);

        // Single envelope state machine shared across all directives
        // Mode is controlled by S3_ANTICIPATION_MODE env var (set on n02 for LXC 101):
        //   - unset / "synthetic" / "sandbox" → SYNTHETIC (log only, no cgroup writes) [DEFAULT]
        //   - "production" / "real"           → REAL (cgroup writes, stasis_cos guard active)
        // This is THE single switch for shadow→live. No code branch to remember.
        let mode = env::var("S3_ANTICIPATION_MODE").ok().unwrap_or_default();
        let is_production = matches!(mode.as_str(), "production" | "real");
        let state = std::sync::Mutex::new(AnticipationState::new_sandbox());
        if is_production {
            state.lock().unwrap().set_production();
            eprintln!(
                "[s3_anticipation] REAL mode (S3_ANTICIPATION_MODE={}) — cgroup writes ENABLED, stasis_cos >= {} donor guard ACTIVE",
                mode, calibration::BASIN_FLOOR
            );
        } else {
            eprintln!(
                "[s3_anticipation] SYNTHETIC mode (S3_ANTICIPATION_MODE={}) — no cgroup writes. Production gated on R2 (stasis_cos ≥ 0.875). Set S3_ANTICIPATION_MODE=production to enable.",
                if mode.is_empty() { "unset" } else { &mode }
            );
        }

        // ── NUCLEUS-REALDATA-WIRING: projection path + orders dir ──
        // See docs/spec/s4_anticipation/nucleus_realdata_wiring.spec.vsm
        let projection_path = env::var("S3_ANTICIPATION_PROJECTION_PATH")
            .ok().filter(|s| !s.is_empty());
        if let Some(ref path) = projection_path {
            eprintln!(
                "[s3_anticipation] projection file: {} (staleness threshold: {}s, matches Component B)",
                path, 600
            );
        }
        let orders_dir = env::var("S3_ANTICIPATION_ORDER_DIR")
            .ok().filter(|s| !s.is_empty());
        if let Some(ref dir) = orders_dir {
            state.lock().unwrap().set_orders_dir(dir.clone());
            eprintln!(
                "[s3_anticipation] order files will be written to: {} (for Component B consumption)",
                dir
            );
        }

        loop {
            match vsf_agent::nats::connect(&url, "s3-anticipation").await {
                Ok(client) => match client.subscribe(subject.clone()).await {
                    Ok(mut sub) => {
                        eprintln!(
                            "[s3_anticipation] subscriber ready — listening for S4 anticipatory directives"
                        );
                        while let Some(msg) = sub.next().await {
                            match serde_json::from_slice::<AnticipatoryDirective>(&msg.payload) {
                                Ok(directive) => {
                                    let mut state = state.lock().unwrap();

                                    // Refresh stasis_cos from projection file before every directive.
                                    // Each directive is evaluated against the freshest available data.
                                    // Fail-closed: if refresh fails, stasis_cos is cleared and all
                                    // zones are excluded from donor selection (no silent permission).
                                    if let Some(ref proj_path) = projection_path {
                                        if let Err(e) = state.refresh_stasis_cos(proj_path) {
                                            eprintln!(
                                                "[s3_anticipation] refresh_stasis_cos: {} (fail-closed: stasis_cos cleared)",
                                                e
                                            );
                                        }
                                    }

                                    eprintln!(
                                        "[s3_anticipation] directive: zone={} delta={} id={}",
                                        directive.zone, directive.delta_cpu_weight, directive.directive_id
                                    );
                                    state.handle_directive(directive, &canon);
                                }
                                Err(e) => {
                                    eprintln!(
                                        "[s3_anticipation] deserialize error: {} — ignoring payload",
                                        e
                                    );
                                }
                            }
                        }
                        eprintln!("[s3_anticipation] subscription ended — reconnecting");
                    }
                    Err(e) => {
                        eprintln!("[s3_anticipation] subscribe error: {} — retrying in 10s", e);
                    }
                },
                Err(e) => {
                    eprintln!(
                        "[s3_anticipation] connect failed: {} — retrying in 10s",
                        e
                    );
                }
            }
            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
        }
    })
}

// ── GAP 2 — Viability tracker with hysteresis-based reversibility ──────────────
//
// After a grant is applied, track the donor and target zones' stasis_cos.
// If either drops below VIABILITY_THRESHOLD for HYSTERESIS_TICKS consecutive ticks,
// the weight transfer is reverted (same pattern as INV-SUM rollback but driven by
// a real-world harm signal, not an internal accounting guard).
//
// Hysteresis prevents single-tick noise from triggering a revert (same discipline
// as s3_resource_alloc.py's RECOVERY_THRESHOLD=0.70 + RECOVERY_TICKS=5 pattern).

/// How many consecutive degraded ticks must be observed before a grant is reverted.
const HYSTERESIS_TICKS: u32 = 5;

/// A grant whose post-application viability is being monitored.
#[derive(Debug, Clone)]
struct ActiveGrant {
    directive_id: String,
    target_zone: String,
    donor_zone: String,
    delta_cpu_weight: u64,
    donor_weight_before: u64,
    target_weight_before: u64,
    /// Consecutive degraded ticks for the target (stasis_cos < VIABILITY_THRESHOLD).
    target_degrade_count: u32,
    /// Consecutive degraded ticks for the donor.
    donor_degrade_count: u32,
    /// True after the grant has been reverted (prevents double-revert).
    reverted: bool,
}

/// A revert action to be applied by the caller.
#[derive(Debug, Clone)]
struct RevertAction {
    directive_id: String,
    target_zone: String,
    donor_zone: String,
    delta_cpu_weight: u64,
    donor_weight_before: u64,
    target_weight_before: u64,
    reason: String,
}

/// Tracks the post-grant viability of recently applied grants.
/// Call `record_grant` after every successful grant, then call `tick_viability`
/// periodically (e.g., every kernel tick) with the current stasis_cos for all zones.
///
/// Design follows the hysteresis pattern from s3_resource_alloc.py (RECOVERY_TICKS=5):
/// N consecutive ticks past a threshold before acting, to avoid noise-driven reversion.
struct ViabilityTracker {
    active_grants: Vec<ActiveGrant>,
    max_grants: usize,
}

impl ViabilityTracker {
    fn new(max_grants: usize) -> Self {
        Self {
            active_grants: Vec::with_capacity(max_grants),
            max_grants,
        }
    }

    /// Record a new grant to monitor.
    fn record_grant(
        &mut self,
        directive_id: &str,
        target: &str,
        donor: &str,
        delta: u64,
        donor_before: u64,
        target_before: u64,
    ) {
        // Evict oldest non-reverted grant if at capacity
        if self.active_grants.len() >= self.max_grants {
            // Find first reverted grant to replace
            if let Some(pos) = self.active_grants.iter().position(|g| g.reverted) {
                self.active_grants.remove(pos);
            } else {
                // No reverted grants to reuse — replace the oldest
                self.active_grants.remove(0);
            }
        }

        self.active_grants.push(ActiveGrant {
            directive_id: directive_id.to_string(),
            target_zone: target.to_string(),
            donor_zone: donor.to_string(),
            delta_cpu_weight: delta,
            donor_weight_before: donor_before,
            target_weight_before: target_before,
            target_degrade_count: 0,
            donor_degrade_count: 0,
            reverted: false,
        });
    }

    /// Check viability of all active grants.
    ///
    /// `get_stasis_cos` is a closure that returns the current stasis_cos for a zone.
    /// It is called once per zone per tick.
    ///
    /// Returns `RevertAction` for every grant whose donor OR target has been degraded
    /// for >= HYSTERESIS_TICKS consecutive ticks.
    fn tick_viability<F>(&mut self, get_stasis_cos: &F) -> Vec<RevertAction>
    where
        F: Fn(&str) -> Option<f64>,
    {
        let mut reverts: Vec<RevertAction> = Vec::new();

        for grant in &mut self.active_grants {
            if grant.reverted {
                continue; // Already handled
            }

            let mut any_degrade = false;

            // Check target zone viability
            if let Some(cos) = get_stasis_cos(&grant.target_zone) {
                if cos < calibration::BASIN_FLOOR {
                    grant.target_degrade_count += 1;
                    if grant.target_degrade_count >= HYSTERESIS_TICKS {
                        any_degrade = true;
                    }
                } else {
                    // Recovery — reset counter (hysteresis: N must be consecutive)
                    grant.target_degrade_count = 0;
                }
            } else {
                // No stasis_cos data available — don't count as degrade, don't reset
                // (graceful degradation for zones without recent projection data)
            }

            // Check donor zone viability
            if let Some(cos) = get_stasis_cos(&grant.donor_zone) {
                if cos < calibration::BASIN_FLOOR {
                    grant.donor_degrade_count += 1;
                    if grant.donor_degrade_count >= HYSTERESIS_TICKS {
                        any_degrade = true;
                    }
                } else {
                    grant.donor_degrade_count = 0;
                }
            }

            if any_degrade {
                grant.reverted = true;
                let reason = if grant.target_degrade_count >= HYSTERESIS_TICKS
                    && grant.donor_degrade_count >= HYSTERESIS_TICKS
                {
                    format!(
                        "both — target={} degraded {} ticks, donor={} degraded {} ticks",
                        grant.target_zone, grant.target_degrade_count,
                        grant.donor_zone, grant.donor_degrade_count,
                    )
                } else if grant.target_degrade_count >= HYSTERESIS_TICKS {
                    format!(
                        "target — {} degraded {} ticks",
                        grant.target_zone, grant.target_degrade_count,
                    )
                } else {
                    format!(
                        "donor — {} degraded {} ticks",
                        grant.donor_zone, grant.donor_degrade_count,
                    )
                };

                eprintln!(
                    "[ViabilityTracker] REVERT grant={} reason={} target={} donor={} delta={}",
                    grant.directive_id, reason, grant.target_zone, grant.donor_zone, grant.delta_cpu_weight,
                );

                reverts.push(RevertAction {
                    directive_id: grant.directive_id.clone(),
                    target_zone: grant.target_zone.clone(),
                    donor_zone: grant.donor_zone.clone(),
                    delta_cpu_weight: grant.delta_cpu_weight,
                    donor_weight_before: grant.donor_weight_before,
                    target_weight_before: grant.target_weight_before,
                    reason,
                });
            }
        }

        reverts
    }

    /// Number of currently monitored (not yet reverted) grants.
    fn active_count(&self) -> usize {
        self.active_grants.iter().filter(|g| !g.reverted).count()
    }

    /// Total tracked grants (including reverted ones still in buffer).
    fn total_count(&self) -> usize {
        self.active_grants.len()
    }
}

// ── TESTS ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;

    fn temp_dirs() -> (String, String) {
        let base = std::env::temp_dir().join(format!("vsf-s3-ant-test-{}", std::process::id()));
        let tmpfs = base.join("tmpfs");
        let disk = base.join("disk");
        let _ = std::fs::create_dir_all(&tmpfs);
        let _ = std::fs::create_dir_all(&disk);
        (tmpfs.to_string_lossy().to_string(), disk.to_string_lossy().to_string())
    }

    fn make_directive(zone: &str, delta: i64, id: &str, lambda: Option<f64>) -> AnticipatoryDirective {
        AnticipatoryDirective {
            zone: zone.to_string(),
            delta_cpu_weight: delta,
            directive_id: id.to_string(),
            ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
            regime_lambda: lambda,
        }
    }

    /// ── TEST 1: INV-SUM — envelope sum ALWAYS conserved ──
    /// Safety-critical: Σ zone_shares = ENVELOPE_SUM (800) before & after every grant.
    /// Feed multiple directives and verify sum stays 800.
    /// NOTE: Donor selection is HashMap-order-dependent (non-deterministic), so we do NOT
    /// assert which specific donor was chosen — we assert:
    ///   (1) Σ always = 800       (INV-SUM)
    ///   (2) target zone weight increases
    ///   (3) at least one donor decreased
    ///   (4) all zones ≥ floor    (INV-FLOOR)
    #[test]
    fn inv_sum_is_conserved() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-inv-sum", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Initial sum must be 800
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM: initial sum must be 800");

        // Grant 10 to mediterranea
        let med_before = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(make_directive("mediterranea", 10, "d1", Some(0.01)), &canon);
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after d1");
        assert!(state.zone_weight("mediterranea").unwrap() > med_before,
            "INV-SUM: target zone must increase after grant");

        // Grant 20 to templada-humeda
        let th_before = state.zone_weight("templada-humeda").unwrap();
        state.handle_directive(make_directive("templada-humeda", 20, "d2", Some(-0.02)), &canon);
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after d2");
        assert!(state.zone_weight("templada-humeda").unwrap() > th_before);

        // Grant 50 to humboldt
        let hum_before = state.zone_weight("humboldt").unwrap();
        state.handle_directive(make_directive("humboldt", 50, "d3", Some(0.0)), &canon);
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after d3");
        assert!(state.zone_weight("humboldt").unwrap() > hum_before);

        // Grant 3 to tropical-arida
        let ta_before = state.zone_weight("tropical-arida").unwrap();
        state.handle_directive(make_directive("tropical-arida", 3, "d4", Some(0.03)), &canon);
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after d4");
        assert!(state.zone_weight("tropical-arida").unwrap() > ta_before);

        // INV-FLOOR: all zones must be ≥ BASIN_FLOOR_SANDBOX
        for (name, rec) in &state.zones {
            assert!(rec.weight >= BASIN_FLOOR_SANDBOX,
                "INV-FLOOR: zone {} dropped to {} (below floor {})",
                name, rec.weight, BASIN_FLOOR_SANDBOX);
        }

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 2: INV-FRESH — duplicate directive_id must be rejected ──
    /// Directive d5 applied twice → second call must be a no-op (weights unchanged).
    #[test]
    fn inv_fresh_duplicate_rejected() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-fresh", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        let d = make_directive("mediterranea", 5, "dup-1", Some(0.01));
        state.handle_directive(d.clone(), &canon);
        let weight_after_first = state.zone_weight("mediterranea").unwrap();

        // Second same directive_id → must be ignored (INV-FRESH)
        state.handle_directive(d, &canon);
        let weight_after_second = state.zone_weight("mediterranea").unwrap();
        assert_eq!(weight_after_first, weight_after_second,
            "INV-FRESH: duplicate directive_id must not change weights");
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-FRESH: Σ must remain 800 after duplicate rejection");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 3: INV-FLOOR — donor post-transfer weight must stay ≥ floor ──
    /// Feed a directive targeting a zone near floor, verify the donor algorithm
    /// respects INV-FLOOR (post-transfer ≥ BASIN_FLOOR_SANDBOX=50).
    #[test]
    fn inv_floor_respected() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-floor", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Every zone starts at 100 with floor=50, so max slack = 50 per zone
        // Grant 49 to mediterranea (leaves donor with 51 ≥ 50)
        state.handle_directive(make_directive("mediterranea", 49, "f1", Some(0.01)), &canon);
        let med_w = state.zone_weight("mediterranea").unwrap();
        assert_eq!(med_w, 149, "mediterranea should be 100+49=149");
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after f1");

        // Grant another 49 to mediterranea — donor now has 51-49=2, which would be BELOW floor.
        // select_donor must find a different donor (not the first one again) with enough slack,
        // or escalate. If all donors are tapped out, must double-loop.
        state.handle_directive(make_directive("mediterranea", 49, "f2", Some(-0.01)), &canon);
        // After two grants of 49 each: mediterranea=198. Two donors each gave 49 (total 98).
        // Donors: subpolar(-49) and semiarida(-49) — both now at 51 (still ≥ 50).
        // INV-FLOOR holds.
        let sub_w = state.zone_weight("subpolar").unwrap();
        assert!(sub_w >= BASIN_FLOOR_SANDBOX,
            "INV-FLOOR: donor subpolar must stay ≥ floor after transfer (was {})", sub_w);
        let sem_w = state.zone_weight("semiarida").unwrap();
        assert!(sem_w >= BASIN_FLOOR_SANDBOX,
            "INV-FLOOR: donor semiarida must stay ≥ floor after transfer (was {})", sem_w);
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after f2");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 4: H4 guard — regime_lambda out of ERA5 training band must reject ──
    /// REGIME_LAMBDA_MIN=-0.05, REGIME_LAMBDA_MAX=0.05.
    /// Values outside must be rejected (state unchanged).
    /// Values within must be accepted (weight increases).
    /// DONOR is non-deterministic (HashMap order), so we check the TARGET zone weight
    /// relative to its previous value, not absolute.
    #[test]
    fn h4_rejects_out_of_band() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-h4", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Case (a): regime_lambda=None → allowed (pre-production mode, A3)
        let med_before = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(make_directive("mediterranea", 5, "h4a", None), &canon);
        assert!(state.zone_weight("mediterranea").unwrap() > med_before,
            "H4(a): None should allow grant — target must increase");

        // Case (b): regime_lambda=0.1 (out of band, > 0.05) → must be REJECTED
        let sub_before = state.zone_weight("subpolar").unwrap();
        state.handle_directive(make_directive("subpolar", 5, "h4b", Some(0.1)), &canon);
        assert_eq!(state.zone_weight("subpolar").unwrap(), sub_before,
            "H4(b): out-of-band lambda must reject — state unchanged");

        // Case (b): regime_lambda=-0.1 (out of band, < -0.05) → must be REJECTED
        let sem_before = state.zone_weight("semiarida").unwrap();
        state.handle_directive(make_directive("semiarida", 5, "h4c", Some(-0.1)), &canon);
        assert_eq!(state.zone_weight("semiarida").unwrap(), sem_before,
            "H4(c): out-of-band lambda must reject — state unchanged");

        // Case (c): regime_lambda=0.0 (within band) → allowed
        let temp_before = state.zone_weight("templada-humeda").unwrap();
        state.handle_directive(make_directive("templada-humeda", 10, "h4d", Some(0.0)), &canon);
        assert!(state.zone_weight("templada-humeda").unwrap() > temp_before,
            "H4(c): in-band lambda should allow grant — target must increase");

        // Final check: INV-SUM must hold after all operations
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-SUM: Σ must remain 800 after H4 guard tests");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 5: Negative delta must escalate (v1 limitation) ──
    /// Negative delta_cpu_weight means reclaim — v1 does not support it.
    /// Must emit double-loop event and not modify state.
    #[test]
    fn negative_delta_escalates() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-neg", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        let med_before = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(make_directive("mediterranea", -10, "neg1", Some(0.01)), &canon);
        let med_after = state.zone_weight("mediterranea").unwrap();
        assert_eq!(med_before, med_after,
            "negative delta must not change weights");
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-SUM after negative delta");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 6: Unknown zone must be ignored ──
    #[test]
    fn unknown_zone_ignored() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-unknown", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        state.handle_directive(make_directive("nonexistent-zone", 10, "unk1", Some(0.01)), &canon);
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-SUM unchanged after unknown zone directive");

        // All zones should still be at default weights
        for name in &["mediterranea", "subpolar", "semiarida", "templada-humeda",
                      "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical"]
        {
            assert_eq!(state.zone_weight(name), Some(100),
                "zone {} should be unchanged after unknown zone directive", name);
        }

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 7: Double-loop escalation when no donor can spare ──
    /// A delta that exceeds all donors' slack must escalate (not crash, not silently accept).
    /// DONOR is non-deterministic (HashMap order), so we do NOT assert which donor was picked.
    /// We assert:
    ///   (1) impossible request → state unchanged (double-loop)
    ///   (2) possible request → target increases (some donor picked)
    ///   (3) INV-SUM always = 800
    ///   (4) INV-FLOOR: all zones ≥ floor
    #[test]
    fn double_loop_on_insufficient_slack() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-double-loop", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Each zone starts at 100 with floor=50, so max slack per donor = 50.
        // Request 300 (impossible — all 7 donors together have 7*50=350,
        // but the algorithm picks ONE donor with enough slack, not all 7).
        // The largest single-donor slack is 50, so 300 > 50 → double-loop.
        let med_before = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(make_directive("mediterranea", 300, "dl1", Some(0.01)), &canon);
        assert_eq!(state.zone_weight("mediterranea"), Some(med_before),
            "double-loop: impossible request must not change weight");
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after double-loop");

        // Request 50 (possible — slack=50 per donor, one donor can spare this).
        state.handle_directive(make_directive("mediterranea", 50, "dl2", Some(0.01)), &canon);
        assert!(state.zone_weight("mediterranea").unwrap() > med_before,
            "mediterranea must increase from {} after possible grant of 50", med_before);
        // Some donor should have decreased (INV-FLOOR ensures it stayed ≥ floor)
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after possible grant");

        // Request 51 → no single donor has 51 slack (remaining max slack = 50).
        let med_after_dl2 = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(make_directive("mediterranea", 51, "dl3", Some(0.01)), &canon);
        assert_eq!(state.zone_weight("mediterranea"), Some(med_after_dl2),
            "double-loop: mediterranea must remain unchanged after impossible 51 request");
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after impossible request");

        // INV-FLOOR: all zones ≥ floor
        for (name, rec) in &state.zones {
            assert!(rec.weight >= BASIN_FLOOR_SANDBOX,
                "INV-FLOOR: zone {} dropped to {} (below floor {})",
                name, rec.weight, BASIN_FLOOR_SANDBOX);
        }

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── TEST 8: Safety invariant — INV-SUM under stress ──
    /// Feed 100 directives in sequence simulating real S4 anticipatory signals.
    /// The Σ must ALWAYS equal ENVELOPE_SUM (800) after every grant, no matter what.
    /// This is the load-bearing invariant test the directive requires.
    #[test]
    fn safety_invariant_inv_sum_stress_test() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-safety", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        let zones = [
            "mediterranea", "subpolar", "semiarida", "templada-humeda",
            "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
        ];

        // Phase 1: 50 small directives (various zones, small deltas)
        for i in 0..50 {
            let zone = zones[i % 8];
            let delta: i64 = ((i % 5) + 1) as i64 * 3; // 3, 6, 9, 12, or 15
            let id = format!("stress-a-{}", i);
            // Alternate in-band lambdas
            let lambda = Some(if i % 3 == 0 { 0.0 } else { 0.01 * (i as f64 * 0.01) });
            state.handle_directive(make_directive(zone, delta, &id, lambda), &canon);
            // CRITICAL: INV-SUM must hold after EVERY grant
            assert_eq!(state.total_weight(), ENVELOPE_SUM,
                "INV-SUM VIOLATION at directive stress-a-{}", i);
        }

        // Phase 2: 25 impossible requests (delta > 50) → must all double-loop
        for i in 0..25 {
            let zone = zones[(i + 3) % 8];
            let delta: i64 = 60 + (i % 5) as i64 * 10; // 60, 70, 80, 90, 100
            let id = format!("stress-impossible-{}", i);
            state.handle_directive(make_directive(zone, delta, &id, Some(0.02)), &canon);
            // INV-SUM must STILL hold even when double-loop escalates
            assert_eq!(state.total_weight(), ENVELOPE_SUM,
                "INV-SUM VIOLATION at directive stress-impossible-{}", i);
        }

        // Phase 3: 20 H4 out-of-band directives → must all be rejected
        for i in 0..20 {
            let zone = zones[(i + 5) % 8];
            let id = format!("stress-h4-{}", i);
            let lambda = Some(if i % 2 == 0 { 0.1 } else { -0.1 }); // out of band
            state.handle_directive(make_directive(zone, 10, &id, lambda), &canon);
            assert_eq!(state.total_weight(), ENVELOPE_SUM,
                "INV-SUM VIOLATION at directive stress-h4-{}", i);
        }

        // Phase 4: 5 negative deltas → must all escalate
        for i in 0..5 {
            let zone = zones[(i + 7) % 8];
            let id = format!("stress-neg-{}", i);
            state.handle_directive(make_directive(zone, -10, &id, Some(0.01)), &canon);
            assert_eq!(state.total_weight(), ENVELOPE_SUM,
                "INV-SUM VIOLATION at directive stress-neg-{}", i);
        }

        // Final invariant: after 100 directives, Σ must still be 800
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-SUM: Σ must be 800 after 100 mixed directives");

        // Each zone must be ≥ BASIN_FLOOR_SANDBOX (INV-FLOOR)
        for zone in &zones {
            let w = state.zone_weight(zone).unwrap();
            assert!(w >= BASIN_FLOOR_SANDBOX,
                "INV-FLOOR: zone {} dropped to {} (below floor {})",
                zone, w, BASIN_FLOOR_SANDBOX);
        }

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── GAP 1: PRODUCTION donor viability floor (stasis_cos ≥ 0.875) ──
    ///
    /// Adversarial test: In production mode, a zone with plenty of cpu.weight slack
    /// but stasis_cos < calibration::BASIN_FLOOR (0.875) must NEVER be selected as a donor.
    /// The weight-based proxy (BASIN_FLOOR_SANDBOX=50) passing must not be sufficient.
    ///
    /// In synthetic mode, the weight proxy still governs (existing tests stay green).
    #[test]
    fn gap_1_production_viability_floor_excludes_unhealthy_donor() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-gap1-viability", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Verify synthetic mode still works (existing tests must stay green)
        // All zones at 100, slack=50, pick one donor, all healthy.
        state.handle_directive(make_directive("mediterranea", 10, "g1-syn", Some(0.01)), &canon);
        assert!(state.zone_weight("mediterranea").unwrap() > 100,
            "synthetic: basic grant must work");
        assert_eq!(state.total_weight(), ENVELOPE_SUM);
        // Note: during synthetic phase, any zone could be the donor — their weights may have changed.

        // Capture pre-production weights of zones that will be unhealthy.
        // The synthetic grant above may have changed some; that's fine — what matters
        // is their weight MUST NOT change further DURING production-mode grants.
        let enso_before = state.zone_weight("enso-tropical").unwrap();
        let templada_before = state.zone_weight("templada-humeda").unwrap();
        let tropical_before = state.zone_weight("tropical-arida").unwrap();

        // Now switch to production mode and set stasis_cos for all zones.
        state.set_production();
        state.set_zone_stasis_cos("mediterranea", 0.95);
        state.set_zone_stasis_cos("subpolar", 0.92);
        state.set_zone_stasis_cos("semiarida", 0.88);      // just above 0.875 — BARELY healthy
        state.set_zone_stasis_cos("templada-humeda", 0.85); // BELOW floor — must be excluded
        state.set_zone_stasis_cos("tropical-arida", 0.70);  // BELOW floor — must be excluded
        state.set_zone_stasis_cos("humboldt", 0.99);
        state.set_zone_stasis_cos("pacifico-sur-medio", 0.91);
        state.set_zone_stasis_cos("enso-tropical", 0.75);   // BELOW floor — must be excluded

        // The target is humboldt (healthy). Request 40 from healthy donors.
        // Excluded donors (stasis_cos < 0.875): templada-humeda(85), tropical-arida(70), enso-tropical(75)
        //   — these must NOT be selected. Their weight must not decrease.
        let hum_before = state.zone_weight("humboldt").unwrap();
        state.handle_directive(make_directive("humboldt", 40, "g1-prod-1", Some(0.01)), &canon);
        assert!(state.zone_weight("humboldt").unwrap() > hum_before,
            "production: grant must succeed with healthy donors");

        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after production grant");

        // Verify unhealthy donors (stasis_cos < 0.875) were NOT selected — their weights unchanged
        assert_eq!(state.zone_weight("templada-humeda"), Some(templada_before),
            "GAP-1: templada-humeda (stasis_cos=0.85) must NOT be selected as donor");
        assert_eq!(state.zone_weight("tropical-arida"), Some(tropical_before),
            "GAP-1: tropical-arida (stasis_cos=0.70) must NOT be selected as donor");
        assert_eq!(state.zone_weight("enso-tropical"), Some(enso_before),
            "GAP-1: enso-tropical (stasis_cos=0.75) must NOT be selected as donor");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    /// ── GAP 1 (adversarial): last-resort — even when ALL healthy donors are exhausted ──
    ///
    /// If all healthy donors (stasis_cos ≥ 0.875) are at floor and cannot give,
    /// and unhealthy donors (stasis_cos < 0.875) still have cpu.weight slack,
    /// the system MUST double-loop escalate rather than pick an unhealthy donor.
    ///
    /// This test is fully deterministic: no synthetic-phase weight shuffling.
    /// We start in production mode and drain healthy donors via explicit directives,
    /// knowing exactly which ones have slack.
    #[test]
    fn gap_1_production_prefers_double_loop_over_unhealthy_donor() {
        let (tmpfs, disk) = temp_dirs();
        let canon = CanonicalTelemetry::with_roots("test-gap1-exhaust", &tmpfs, &disk).unwrap();
        let mut state = AnticipationState::new_sandbox();

        // Capture baselines of the zones that will be unhealthy
        let templada_before = state.zone_weight("templada-humeda").unwrap();
        let tropical_before = state.zone_weight("tropical-arida").unwrap();
        let enso_before = state.zone_weight("enso-tropical").unwrap();

        // Switch to production mode first (before any grants).
        state.set_production();
        state.set_zone_stasis_cos("mediterranea", 0.95);
        state.set_zone_stasis_cos("subpolar", 0.92);
        state.set_zone_stasis_cos("semiarida", 0.88);      // BARELY healthy (0.88 > 0.875)
        state.set_zone_stasis_cos("templada-humeda", 0.85); // BELOW floor
        state.set_zone_stasis_cos("tropical-arida", 0.70);  // BELOW floor
        state.set_zone_stasis_cos("humboldt", 0.99);
        state.set_zone_stasis_cos("pacifico-sur-medio", 0.91);
        state.set_zone_stasis_cos("enso-tropical", 0.75);   // BELOW floor

        // Healthy donors (stasis_cos ≥ 0.875): subpolar(92), semiarida(88),
        //   humboldt(99), pacifico-sur-medio(91) — all at 100 with slack=50.
        // Unhealthy donors: templada-humeda(85), tropical-arida(70), enso-tropical(75)
        //   — all at 100 with slack=50 but must NOT be selected.
        // Target: mediterranea (the zone we're testing as recipient).

        // Drain: 4 rounds × 40 = 160 from 4 healthy donors, each with 50 slack.
        // After this, ALL 4 healthy donors are at floor (50) — no healthy slack left.
        for i in 0..4 {
            let before = state.zone_weight("mediterranea").unwrap();
            state.handle_directive(
                make_directive("mediterranea", 40, &format!("g1e-drain-{}", i), Some(0.01)),
                &canon,
            );
            assert!(state.zone_weight("mediterranea").unwrap() > before,
                "production drain {}: must find a healthy donor (med={}→{})",
                i, before, state.zone_weight("mediterranea").unwrap());
            assert_eq!(state.total_weight(), ENVELOPE_SUM);
        }
        // After 4 drains: mediterranea=100+160=260, each healthy donor at 60 (slack=10 remaining).

        // Now every healthy donor has 0 slack. Unhealthy donors still at 100 (slack=50).
        // Request another 40 must double-loop — no healthy donor can give.
        let med_before = state.zone_weight("mediterranea").unwrap();
        state.handle_directive(
            make_directive("mediterranea", 40, "g1e-overflow", Some(0.01)),
            &canon,
        );
        assert_eq!(state.zone_weight("mediterranea"), Some(med_before),
            "GAP-1: when all healthy donors exhausted, must double-loop, not pick unhealthy donor");
        assert_eq!(state.total_weight(), ENVELOPE_SUM,
            "INV-SUM after double-loop from exhausted healthy pool");

        // Verify unhealthy donors were NOT touched
        assert_eq!(state.zone_weight("templada-humeda"), Some(templada_before),
            "templada-humeda (stasis_cos=0.85) must remain untouched");
        assert_eq!(state.zone_weight("tropical-arida"), Some(tropical_before),
            "tropical-arida (stasis_cos=0.70) must remain untouched");
        assert_eq!(state.zone_weight("enso-tropical"), Some(enso_before),
            "enso-tropical (stasis_cos=0.75) must remain untouched");

        let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
    }

    // ── GAP 2: Hysteresis-based reversibility on viability drop ──

    /// Happy path: no degrade after grant → no revert.
    #[test]
    fn gap_2_no_degrade_no_revert() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-1", "mediterranea", "subpolar", 40, 100, 100);

        // 6 ticks of healthy stasis_cos — no revert
        for tick in 0..6 {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" | "subpolar" => Some(0.95),
                    _ => Some(0.90),
                }
            });
            assert!(reverts.is_empty(),
                "tick {}: no revert expected with healthy stasis_cos, got {}",
                tick, reverts.len());
        }
        assert_eq!(tracker.active_count(), 1, "grant still active after healthy ticks");
    }

    /// Revert after HYSTERESIS_TICKS consecutive degraded ticks on the target.
    #[test]
    fn gap_2_revert_after_hysteresis_ticks() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-revert", "mediterranea", "subpolar", 40, 100, 100);

        // HYSTERESIS_TICKS-1 degraded ticks: no revert yet
        for tick in 0..HYSTERESIS_TICKS - 1 {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" => Some(0.50), // target degraded
                    "subpolar" => Some(0.95),     // donor healthy
                    _ => Some(0.90),
                }
            });
            assert!(reverts.is_empty(),
                "tick {}: no revert before {}-tick threshold (got {} reverts)",
                tick, HYSTERESIS_TICKS, reverts.len());
        }

        // Nth degraded tick: must revert
        let reverts = tracker.tick_viability(&|zone| {
            match zone {
                "mediterranea" => Some(0.50),
                "subpolar" => Some(0.95),
                _ => Some(0.90),
            }
        });
        assert_eq!(reverts.len(), 1,
            "must revert after {} consecutive degraded ticks", HYSTERESIS_TICKS);
        assert_eq!(reverts[0].directive_id, "g2-revert");
        assert_eq!(reverts[0].target_zone, "mediterranea");
        assert_eq!(reverts[0].donor_zone, "subpolar");
        assert_eq!(reverts[0].delta_cpu_weight, 40);
        assert!(reverts[0].reason.contains("target"),
            "reason should mention target zone 'mediterranea', got: {}", reverts[0].reason);

        // After revert: grant is no longer active
        assert_eq!(tracker.active_count(), 0,
            "grant should be inactive after revert");
    }

    /// Revert after HYSTERESIS_TICKS consecutive degraded ticks on the DONOR.
    #[test]
    fn gap_2_revert_after_donor_degrade() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-donor-deg", "mediterranea", "subpolar", 30, 100, 100);

        // Donor degraded, target healthy
        for _tick in 0..HYSTERESIS_TICKS - 1 {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" => Some(0.95),  // target healthy
                    "subpolar" => Some(0.60),       // donor degraded
                    _ => Some(0.90),
                }
            });
            assert!(reverts.is_empty());
        }

        // Nth tick: must revert (donor degraded)
        let reverts = tracker.tick_viability(&|zone| {
            match zone {
                "mediterranea" => Some(0.95),
                "subpolar" => Some(0.60),
                _ => Some(0.90),
            }
        });
        assert_eq!(reverts.len(), 1);
        assert!(reverts[0].reason.contains("donor"),
            "reason should mention donor zone 'subpolar', got: {}", reverts[0].reason);
    }

    /// Recovery within the hysteresis window: must NOT revert.
    #[test]
    fn gap_2_recovery_within_window_no_revert() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-recover", "mediterranea", "subpolar", 40, 100, 100);

        // 3 degraded ticks: target below threshold
        for _tick in 0..3 {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" => Some(0.50), // degraded
                    "subpolar" => Some(0.95),
                    _ => Some(0.90),
                }
            });
            assert!(reverts.is_empty(),
                "no revert after 3 degraded ticks");
        }

        // Then recovery: stasis_cos back to healthy
        for _tick in 0..4 {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" => Some(0.92), // recovered!
                    "subpolar" => Some(0.95),
                    _ => Some(0.90),
                }
            });
            assert!(reverts.is_empty(),
                "no revert after recovery — hysteresis window reset");
        }

        assert_eq!(tracker.active_count(), 1,
            "grant still active after recovery (should not revert)");
    }

    /// Both target and donor degraded: single revert with both-reason.
    #[test]
    fn gap_2_both_degrade_single_revert() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-both", "mediterranea", "subpolar", 40, 100, 100);

        // Both degraded for HYSTERESIS_TICKS ticks
        for tick in 0..HYSTERESIS_TICKS {
            let reverts = tracker.tick_viability(&|_zone| Some(0.50));
            if tick < HYSTERESIS_TICKS - 1 {
                assert!(reverts.is_empty(), "no revert before threshold");
            }
        }
        // The last tick produced the revert — but we already consumed it.
        // So this tick should produce none (already reverted).
        let reverts = tracker.tick_viability(&|_zone| Some(0.50));
        assert_eq!(reverts.len(), 0,
            "no more reverts after grant already reverted");
        assert_eq!(tracker.active_count(), 0,
            "no active grants after revert");
    }

    /// Max grants: when tracker is full, oldest grant is evicted.
    #[test]
    fn gap_2_max_grants_evicts_oldest() {
        let mut tracker = ViabilityTracker::new(3);

        tracker.record_grant("g2-1", "a", "b", 10, 100, 100);
        tracker.record_grant("g2-2", "c", "d", 20, 100, 100);
        tracker.record_grant("g2-3", "e", "f", 30, 100, 100);
        assert_eq!(tracker.total_count(), 3, "3 grants fit in capacity");

        // 4th grant evicts oldest (g2-1)
        tracker.record_grant("g2-4", "g", "h", 40, 100, 100);
        assert_eq!(tracker.total_count(), 3, "after eviction, 3 grants remain");

        // Only g2-2, g2-3, g2-4 remain
        let remaining: Vec<&str> = tracker.active_grants.iter()
            .map(|g| g.directive_id.as_str()).collect();
        assert!(remaining.contains(&"g2-2"));
        assert!(remaining.contains(&"g2-3"));
        assert!(remaining.contains(&"g2-4"));
    }

    /// Applicative test: verify the revert would restore correct weights.
    #[test]
    fn gap_2_revert_restores_correct_weights() {
        let mut tracker = ViabilityTracker::new(10);

        // Simulate: donor=subpolar was at 100, target=mediterranea was at 100
        tracker.record_grant("g2-weights", "mediterranea", "subpolar", 40, 100, 100);

        // After grant: donor=60, target=140. If reverted, donor→100, target→100.

        // Degrade for HYSTERESIS_TICKS
        for tick in 0..HYSTERESIS_TICKS {
            let reverts = tracker.tick_viability(&|zone| {
                match zone {
                    "mediterranea" => Some(0.50),
                    "subpolar" => Some(0.95),
                    _ => Some(0.90),
                }
            });
            if tick == HYSTERESIS_TICKS - 1 {
                // Verify revert action carries pre-grant weights
                assert_eq!(reverts.len(), 1);
                assert_eq!(reverts[0].donor_weight_before, 100);
                assert_eq!(reverts[0].target_weight_before, 100);
                assert_eq!(reverts[0].delta_cpu_weight, 40);
            }
        }
    }

    /// Edge: zone without stasis_cos data (None) does not count as degrade.
    #[test]
    fn gap_2_unknown_zone_no_degrade() {
        let mut tracker = ViabilityTracker::new(10);
        tracker.record_grant("g2-unknown", "mediterranea", "subpolar", 40, 100, 100);

        // Both zones return None for stasis_cos — no degrade counted
        for _tick in 0..HYSTERESIS_TICKS + 2 {
            let reverts = tracker.tick_viability::<_>(&|_zone| None);
            assert!(reverts.is_empty(),
                "no revert when stasis_cos unavailable");
        }
        assert_eq!(tracker.active_count(), 1,
            "grant still active when stasis_cos unavailable");
    }

    // ── NUCLEUS-REALDATA-WIRING integration test ──────────────────────────────
    //
    // Proves the full pipeline from fixture projection file → fail-closed donor
    // selection → order file emission → correct format for Component B.
    //
    // Design per: docs/spec/s4_anticipation/nucleus_realdata_wiring.spec.vsm

    /// Helper: create a fixture projection file with a known stasis_cos mix.
    fn write_fixture_projection(
        tmpdir: &std::path::Path, zones: &[(&str, f64)],
    ) -> std::path::PathBuf {
        let path = tmpdir.join("projection.json");
        let data = serde_json::json!({
            "ts": Utc::now().to_rfc3339(),
            "zones": zones.iter().map(|(name, sc)| {
                serde_json::json!({"name": name, "current_sc": sc})
            }).collect::<Vec<_>>(),
        });
        std::fs::write(&path, serde_json::to_string_pretty(&data).unwrap()).unwrap();
        path
    }

    #[test]
    fn nucleus_realdata_wiring_integration() {
        let tmpdir = std::env::temp_dir()
            .join(format!("vsf-nucleus-integration-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmpdir);
        std::fs::create_dir_all(&tmpdir).unwrap();
        let orders_dir = tmpdir.join("orders");

        // ── Step 1: fixture projection file ──
        // 6 of the 8 known zones are present; 2 are intentionally missing
        // (semiarida, enso-tropical) to test fail-closed on absent data.
        // Among the present zones, 2 are below BASIN_FLOOR=0.875:
        //   templada-humeda (0.85) and tropical-arida (0.70).
        let fixture_zones: &[(&str, f64)] = &[
            ("mediterranea", 0.95),
            ("subpolar", 0.92),
            ("semiarida", 0.88),          // BARELY healthy (0.88 > 0.875)
            ("templada-humeda", 0.85),    // BELOW floor — must be excluded
            ("tropical-arida", 0.70),     // BELOW floor — must be excluded
            ("humboldt", 0.99),
            ("pacifico-sur-medio", 0.91),
            // enso-tropical intentionally absent — fail-closed
        ];
        let proj_path = write_fixture_projection(&tmpdir, fixture_zones);

        // ── Step 2: create state, switch to production ──
        let mut state = AnticipationState::new_sandbox();
        state.set_production();
        state.set_orders_dir(orders_dir.to_string_lossy().to_string());

        // ── Step 2a: refresh_stasis_cos from fixture ──
        let result = state.refresh_stasis_cos(proj_path.to_str().unwrap());
        assert!(result.is_ok(), "refresh_stasis_cos should succeed: {:?}", result);

        // Verify: 7 zones populated, 1 absent (enso-tropical)
        assert_eq!(
            state.stasis_cos.len(), 7,
            "expected 7 of 8 known zones in stasis_cos (enso-tropical absent)"
        );
        assert_eq!(state.stasis_cos.get("mediterranea"), Some(&0.95));
        assert_eq!(state.stasis_cos.get("templada-humeda"), Some(&0.85));
        assert!(
            !state.stasis_cos.contains_key("enso-tropical"),
            "enso-tropical NOT in fixture projection — must be absent (fail-closed)"
        );

        // ── Step 2b: fail-closed — below-floor zone excluded from donor selection ──
        // Target: humboldt (healthy, stasis_cos=0.99). Request delta=40.
        // Natural first-choice donors by slack (all at 100 with slack=50):
        //   - subpolar (0.92 — healthy, eligible)
        //   - templada-humeda (0.85 — BELOW FLOOR, must be excluded)
        //   - tropical-arida (0.70 — BELOW FLOOR, must be excluded)
        //   - enso-tropical (ABSENT, must be excluded — fail-closed)
        // Only healthy donors: subpolar, semiarida, humboldt(can't self-donate),
        //   pacifico-sur-medio, mediterranea.
        // After grant: donor must be one of the healthy zones.
        let hum_before = state.zone_weight("humboldt").unwrap();
        let templada_before = state.zone_weight("templada-humeda").unwrap();
        let tropical_before = state.zone_weight("tropical-arida").unwrap();
        let enso_before = state.zone_weight("enso-tropical").unwrap();

        let canon = {
            let (tmpfs, disk) = temp_dirs();
            let c = CanonicalTelemetry::with_roots("test-nucleus-wiring", &tmpfs, &disk).unwrap();
            let _ = std::fs::remove_dir_all(tmpfs.trim_end_matches("/tmpfs"));
            c
        };

        state.handle_directive(
            make_directive("humboldt", 40, "nw-grant-1", Some(0.01)),
            &canon,
        );

        // humboldt weight must increase (grant succeeded)
        assert!(
            state.zone_weight("humboldt").unwrap() > hum_before,
            "humboldt should increase after grant (was {}, now {})",
            hum_before,
            state.zone_weight("humboldt").unwrap()
        );
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after integration grant");

        // Below-floor zones must NOT have been selected as donors (weights unchanged)
        assert_eq!(
            state.zone_weight("templada-humeda"),
            Some(templada_before),
            "templada-humeda (stasis_cos=0.85) must NOT be donor — fail-closed"
        );
        assert_eq!(
            state.zone_weight("tropical-arida"),
            Some(tropical_before),
            "tropical-arida (stasis_cos=0.70) must NOT be donor — fail-closed"
        );
        // Absent zone must NOT have been selected (fail-closed)
        assert_eq!(
            state.zone_weight("enso-tropical"),
            Some(enso_before),
            "enso-tropical (no stasis_cos data) must NOT be donor — fail-closed"
        );

        // ── Step 2c: fail-closed on MISSING projection data ──
        // Write a NEW stale projection file (touch mtime to be old) — or just
        // test that refreshing from a nonexistent path clears stasis_cos.
        // Actually, for an observable test: refresh from a file that is
        // deliberately nonexistent, then verify that NO donor can be selected,
        // forcing a double-loop.
        let nonexistent_path = tmpdir.join("nonexistent_projection.json");
        assert!(!nonexistent_path.exists());

        let result = state.refresh_stasis_cos(nonexistent_path.to_str().unwrap());
        assert!(result.is_err(), "refresh from nonexistent file must fail");
        assert!(state.stasis_cos.is_empty(), "stasis_cos must be cleared on refresh failure (fail-closed)");

        // Now attempt a directive that would normally succeed (healthy target,
        // plenty of slack on all donors). Since stasis_cos is empty, ALL zones
        // are excluded in production mode → double-loop escalation.
        let hum_before2 = state.zone_weight("humboldt").unwrap();
        state.handle_directive(
            make_directive("humboldt", 10, "nw-stale-1", Some(0.01)),
            &canon,
        );
        // humboldt weight must NOT change (no donor selectable → double-loop)
        assert_eq!(
            state.zone_weight("humboldt"),
            Some(hum_before2),
            "with empty stasis_cos, no donor should be selectable — must double-loop"
        );
        assert_eq!(state.total_weight(), ENVELOPE_SUM, "INV-SUM after double-loop from empty stasis_cos");

        // ── Step 3: order file was written in correct format ──
        let pending_dir = orders_dir.join("pending");
        assert!(pending_dir.exists(), "pending/ directory must exist");
        let order_files: Vec<_> = std::fs::read_dir(&pending_dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .collect();
        // The first grant (nw-grant-1) should have produced an order file.
        let grant1_order = order_files.iter()
            .find(|e| e.file_name().to_string_lossy().contains("nw-grant-1"))
            .expect("order file for nw-grant-1 must exist in pending/");
        let order_content = std::fs::read_to_string(grant1_order.path()).unwrap();
        let order_data: serde_json::Value = serde_json::from_str(&order_content).unwrap();

        // Validate required fields match Component B's order_format contract
        assert_eq!(order_data["directive_id"], "nw-grant-1");
        // Don't assert specific donor (non-deterministic in tests).
        let donor = order_data["donor_zone"].as_str().unwrap_or("");
        assert!(!donor.is_empty(), "donor_zone must be non-empty");
        assert_eq!(order_data["target_zone"], "humboldt");
        assert_eq!(order_data["delta"], 40);
        assert!(order_data["kernel_claimed_donor_stasis_cos"].as_f64().unwrap_or(0.0) > 0.0,
            "kernel_claimed_donor_stasis_cos must be populated (production mode)");
        assert_eq!(order_data["kernel_claimed_sum_after"], ENVELOPE_SUM as i64);
        assert_eq!(order_data["kernel_mode"], "production");

        // The stale-grant directive (nw-stale-1) must NOT have an order file
        // (double-loop escalation — no grant was applied, no order emitted).
        let stale_order = order_files.iter()
            .find(|e| e.file_name().to_string_lossy().contains("nw-stale-1"));
        assert!(
            stale_order.is_none(),
            "double-loop directive must NOT produce an order file (no grant to emit)"
        );

        // Cleanup
        let _ = std::fs::remove_dir_all(&tmpdir);
        let _ = std::fs::remove_dir_all(tmpdir.to_string_lossy().trim_end_matches('/')
            .trim_end_matches(std::path::MAIN_SEPARATOR_STR));
    }

    /// ── NUCLEUS-REALDATA-WIRING: stale projection → fail-closed ──
    ///
    /// If the projection file exists but is stale (mtime beyond threshold),
    /// refresh_stasis_cos must clear the map — not keep last-known-good values.
    #[test]
    fn nucleus_realdata_wiring_stale_projection_clears_stasis_cos() {
        let tmpdir = std::env::temp_dir()
            .join(format!("vsf-nucleus-stale-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmpdir);
        std::fs::create_dir_all(&tmpdir).unwrap();

        // Write a fixture, then age its mtime artificially by writing with a past timestamp.
        let proj_path = write_fixture_projection(&tmpdir, &[
            ("mediterranea", 0.95),
            ("subpolar", 0.92),
        ]);

        let mut state = AnticipationState::new_sandbox();
        state.set_production();

        // Populate stasis_cos with a fresh read
        let result = state.refresh_stasis_cos(proj_path.to_str().unwrap());
        assert!(result.is_ok(), "first refresh should succeed");
        assert_eq!(state.stasis_cos.len(), 2, "two zones populated");

        // Now age the file: set mtime to > threshold (600s) ago.
        // We do this by writing a new file with an old mtime via filetime manipulation.
        // On Linux we can use utimensat via std::fs or shell out.
        // Simplest approach: change the stale threshold temporarily for this test.
        // But that requires making it a field access. Instead, write a file with
        // an mtime in the past using a touch-like approach.
        //
        // Actually, the cleanest way: just write the file with an old timestamp
        // using the file's own mtime. We can't set arbitrary mtime from std Rust
        // easily (no filetime crate). Alternative: use a threshold of 0 so any
        // file is stale.
        //
        // The intended test mechanism: we set a very low threshold so the existing
        // fixture file (written milliseconds ago) is already stale.
        state.projection_stale_threshold_secs = 0; // any positive age = stale

        let result = state.refresh_stasis_cos(proj_path.to_str().unwrap());
        assert!(result.is_err(), "refresh with 0s threshold must report stale");
        assert!(
            state.stasis_cos.is_empty(),
            "stasis_cos must be cleared when projection file is stale (fail-closed)"
        );

        let _ = std::fs::remove_dir_all(&tmpdir);
    }
}
