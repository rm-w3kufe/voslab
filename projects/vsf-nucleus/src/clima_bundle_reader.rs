/// clima_bundle_reader.rs — reads s4_clima_bundle.json for nucleus kernel_tick metrics
///
/// Maps the REAL bundle schema (verified live on LXC 101, 2026-07-02) to structured fields.
/// Never panics: all extraction is Option-based, returns None on any error.
///
/// Live bundle schema (2026-07-02):
///   top-level: domain, ts, events[], algedonic_status, baseline{...}, _received_at, _recv_count
///   baseline:  global_regime, oni_value, enso_state, n_systems, omega_modulation{},
///              global_stasis_cos, global_stasis_min, global_viability
///
/// @vsm 0.3
/// V(clima-bundle-reader, L=1) = {
///   role:    "deterministic s4_clima_bundle.json → ClimaBundleFields extractor",
///   parent:  V(vsf-nucleus, L=2),
///   status:  production,
///   coupling: phi_up,
/// }

use chrono::{DateTime, Utc};
use serde_json::Value;
use std::path::Path;

/// Structured fields extracted from a fresh s4_clima_bundle.json
#[derive(Debug, Clone, serde::Serialize)]
pub struct ClimaBundleFields {
    pub available: bool,
    pub stasis_cos: Option<f64>,
    pub viability: Option<f64>,
    pub regime: Option<String>,
    pub algedonic: Option<String>,
    pub refreshed_at: Option<String>,
    pub systems: Option<u64>,
}

impl ClimaBundleFields {
    /// Sentinel for "bundle absent/unreadable/stale"
    pub fn unavailable() -> Self {
        Self {
            available: false,
            stasis_cos: None,
            viability: None,
            regime: None,
            algedonic: None,
            refreshed_at: None,
            systems: None,
        }
    }
}

/// Read and parse s4_clima_bundle.json, returning structured fields.
///
/// Returns `None` if:
///   - file absent
///   - file unreadable or not valid JSON
///   - bundle `_received_at` (or `ts`) is older than `max_age_secs`
///
/// This is a pure function — no mutable state, no side effects beyond file I/O.
pub fn read_clima_bundle(path: &Path, max_age_secs: i64) -> Option<ClimaBundleFields> {
    if !path.exists() {
        return None;
    }
    let content = std::fs::read_to_string(path).ok()?;
    let bundle: Value = serde_json::from_str(&content).ok()?;

    // Staleness check: prefer _received_at (bridge-wallclock), fall back to ts
    let bundle_ts = bundle
        .get("_received_at")
        .or_else(|| bundle.get("ts"))
        .and_then(|v| v.as_str())
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&Utc));

    if let Some(ts) = bundle_ts {
        let age = (Utc::now() - ts).num_seconds();
        if age > max_age_secs {
            eprintln!(
                "[clima_bundle_reader] bundle stale ({}s old, max {}s) — skipping",
                age, max_age_secs
            );
            return None;
        }
    }

    let baseline = bundle.get("baseline");

    Some(ClimaBundleFields {
        available: true,
        // baseline.global_stasis_cos — f64, e.g. 0.293
        stasis_cos: baseline
            .and_then(|b| b.get("global_stasis_cos"))
            .and_then(|v| v.as_f64()),
        // baseline.global_viability — f64, e.g. 0.55 (added per C1 — cheap, useful)
        viability: baseline
            .and_then(|b| b.get("global_viability"))
            .and_then(|v| v.as_f64()),
        // baseline.global_regime — str, e.g. "active"
        regime: baseline
            .and_then(|b| b.get("global_regime"))
            .and_then(|v| v.as_str().map(String::from)),
        // top-level algedonic_status — letter code e.g. "B" (NOT green/amber/red)
        algedonic: bundle
            .get("algedonic_status")
            .and_then(|v| v.as_str().map(String::from)),
        // _received_at fallback ts
        refreshed_at: bundle
            .get("_received_at")
            .and_then(|v| v.as_str().map(String::from))
            .or_else(|| bundle.get("ts").and_then(|v| v.as_str().map(String::from))),
        // baseline.n_systems — u64, number of L1 systems
        systems: baseline
            .and_then(|b| b.get("n_systems"))
            .and_then(|v| v.as_u64()),
    })
}

// ─── Tests ─────────────────────────────────────────────────────────────────
// C4: VERBATIM production bundle sample — if the schema drifts, the test breaks.

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;

    /// Helper: write content to a temp file, return the path.
    fn write_temp(content: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("clima_test_{}", std::process::id()));
        let mut f = fs::File::create(&path).expect("create temp file");
        f.write_all(content.as_bytes()).expect("write temp file");
        path
    }

    /// Verbatim production s4_clima_bundle.json captured from LXC 101
    /// (vsf-s4-clima-bridge.service, 2026-07-02T05:17Z).
    /// This is a PINNED fixture: any schema change MUST update this string.
    const PROD_BUNDLE_SAMPLE: &str = r#"{
  "domain": "s1-clima",
  "ts": "2026-07-02T05:17:02.784453Z",
  "events": [
    {
      "system_id": "continental",
      "regime": "frontal",
      "confidence": 1.0,
      "n_excursion_zones": 2,
      "n_zones": 5,
      "system_coherence": 0.9401,
      "mean_min_stasis": 0.1247,
      "stasis_cos_sys": 0.3128,
      "stasis_cos_min": -0.4758,
      "viability_ratio": 0.6
    }
  ],
  "algedonic_status": "B",
  "baseline": {
    "global_regime": "active",
    "oni_value": 0.48,
    "enso_state": "neutral",
    "n_systems": 3,
    "omega_modulation": {},
    "global_stasis_cos": 0.293,
    "global_stasis_min": -0.5501,
    "global_viability": 0.55
  },
  "_received_at": "2026-07-02T05:17:02.817124Z",
  "_recv_count": 1
}"#;

    fn cleanup(path: &std::path::Path) {
        let _ = fs::remove_file(path);
    }

    #[test]
    fn test_read_valid_bundle() {
        let path = write_temp(PROD_BUNDLE_SAMPLE);

        let result = read_clima_bundle(&path, 7200);
        assert!(result.is_some(), "should parse valid bundle");
        let f = result.unwrap();

        assert!(f.available, "available must be true");
        assert_eq!(
            f.stasis_cos,
            Some(0.293),
            "global_stasis_cos mismatch"
        );
        assert_eq!(
            f.viability,
            Some(0.55),
            "global_viability mismatch"
        );
        assert_eq!(
            f.regime.as_deref(),
            Some("active"),
            "global_regime mismatch"
        );
        assert_eq!(
            f.algedonic.as_deref(),
            Some("B"),
            "algedonic_status mismatch"
        );
        assert_eq!(f.systems, Some(3), "n_systems mismatch");
        assert_eq!(
            f.refreshed_at.as_deref(),
            Some("2026-07-02T05:17:02.817124Z"),
            "_received_at mismatch"
        );

        cleanup(&path);
    }

    #[test]
    fn test_missing_file_returns_none() {
        let result = read_clima_bundle(Path::new("/nonexistent/bundle.json"), 7200);
        assert!(result.is_none(), "missing file should return None");
    }

    #[test]
    fn test_corrupted_json_returns_none() {
        let path = write_temp("not valid json");

        let result = read_clima_bundle(&path, 7200);
        assert!(result.is_none(), "corrupted JSON should return None");

        cleanup(&path);
    }

    #[test]
    fn test_stale_bundle_returns_none() {
        let stale = PROD_BUNDLE_SAMPLE.replace(
            "\"_received_at\": \"2026-07-02T05:17:02.817124Z\"",
            "\"_received_at\": \"2020-01-01T00:00:00Z\"",
        );
        let path = write_temp(&stale);

        let result = read_clima_bundle(&path, 7200);
        assert!(
            result.is_none(),
            "bundle with _received_at=2020 should be stale → None"
        );

        cleanup(&path);
    }

    #[test]
    fn test_no_received_at_falls_back_to_ts() {
        // Remove _received_at from JSON using serde_json Value manipulation
        let mut v: serde_json::Value =
            serde_json::from_str(PROD_BUNDLE_SAMPLE).expect("valid JSON fixture");
        v.as_object_mut().unwrap().remove("_received_at");
        let no_recv = serde_json::to_string(&v).expect("serialize");
        let path = write_temp(&no_recv);

        let result = read_clima_bundle(&path, 7200);
        assert!(
            result.is_some(),
            "should still parse when _received_at absent (fallback to ts)"
        );
        let f = result.unwrap();
        assert!(f.available);
        assert_eq!(
            f.refreshed_at.as_deref(),
            Some("2026-07-02T05:17:02.784453Z")
        );

        cleanup(&path);
    }

    #[test]
    fn test_unavailable_sentinel() {
        let u = ClimaBundleFields::unavailable();
        assert!(!u.available);
        assert!(u.stasis_cos.is_none());
        assert!(u.viability.is_none());
        assert!(u.regime.is_none());
        assert!(u.algedonic.is_none());
        assert!(u.refreshed_at.is_none());
        assert!(u.systems.is_none());
    }
}
