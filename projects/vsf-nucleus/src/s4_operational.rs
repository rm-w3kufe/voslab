/// s4_operational.rs — S4 Orchestrator (operational mode)
///
/// Replaces Python s4_qwen_orchestrator.py
/// Reads system state → calls Ollama Qwen → publishes decisions to BBS

use crate::bbs_embedded::{BbsEmbeddedClient, Decision, SystemState};
use crate::config::NucleusConfig;
use crate::reframe::{RecertConfig, ReframeProposal, ReframeScope};
use crate::s5_approval_nats::{enqueue_proposal, PendingApprovalQueue, PendingProposal};
use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry, DISK_ROOT, EVENTS_FILENAME};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::error::Error;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::sync::{Arc, RwLock};
use std::thread;
use std::time::{Duration, Instant};

/// ITEM_5.5 — stasis_cos below this threshold triggers a ParameterDrift reframe proposal.
/// 0.50 = significant homeostatic deviation; normal healthy range is 0.95-1.00.
const REFRAME_STASIS_THRESHOLD: f64 = 0.50;
/// Minimum consecutive falling ticks before proposing (avoids transient spikes).
const REFRAME_MIN_FALLING_TICKS: usize = 2;

// S4-MULTI-S1 (wave_1): cross-domain synthesis
const S4_SYNTH_PERIOD_CYCLES: u32 = 10;         // run SYNTH every 10 S4 cycles (~50min at 5min interval)
pub(crate) const S4_CLIMA_BUNDLE_MAX_AGE_SECS: i64 = 7200; // climate context stale if > 2h

/// Phase 3 (BRECHA-2) — read N most-recent canonical events from events.jsonl,
/// filter out s4-analysis (echo prevention), aggregate by event_type, format as
/// compact text for Qwen prompt context.
///
/// Safety:
///   - Never panics: I/O errors return "(no recent events context available)"
///   - Bounded read: only last 200 lines scanned (cheap on any file size)
///   - Stale filter: events older than 5 minutes excluded
///
/// Format example:
///   - kernel_tick: 5 in last 5min, last at 14:23:00Z
///   - invariant_check: 5 in last 5min, last var1_mean=0.0
///   - algedonic_emit: 1 in last 5min, last category=covenant_drift sev=10.0
const CONTEXT_MAX_AGE_SECS: i64 = 300;
const CONTEXT_TAIL_LINES: usize = 15; // CPU inference: 200 lines → prompt too large. 15 = last 15min events, deduped.
const CONTEXT_EXCLUDE: &str = "s4-analysis";
// ITEM_13.1 — dual time series window: last N kernel_ticks (~N minutes at 60s cadence)
const TWIN_SERIES_N: usize = 4; // CPU inference: 12 ticks → too large prompt. 4 = last 4min, enough for trend.

fn events_jsonl_path() -> PathBuf {
    PathBuf::from(DISK_ROOT).join("vsf_nucleus").join(EVENTS_FILENAME)
}

pub(crate) fn clima_bundle_path() -> PathBuf {
    PathBuf::from(DISK_ROOT).join("vsf_nucleus").join("s4_clima_bundle.json")
}

fn markov_projection_path() -> PathBuf {
    PathBuf::from(DISK_ROOT).join("vsf_nucleus").join("s4_markov_projection.json")
}

// ITEM_17.1 — Markov projection context reader
//
// Reads s4_markov_projection.json written by s4_markov_bridge.py.
// Returns formatted context string when file is fresh (< 7200s).
// Returns None if absent, unreadable, or stale.
const S4_MARKOV_MAX_AGE_SECS: i64 = 7200; // 2h — same cadence as climate_kernel

fn gather_markov_context_safe() -> Option<String> {
    let path = markov_projection_path();
    if !path.exists() {
        return None;
    }
    let content = std::fs::read_to_string(&path).ok()?;
    let proj: serde_json::Value = serde_json::from_str(&content).ok()?;

    let ts = proj.get("ts")
        .and_then(|v| v.as_str())
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&Utc));

    if let Some(t) = ts {
        let age = (Utc::now() - t).num_seconds();
        if age > S4_MARKOV_MAX_AGE_SECS {
            return None;
        }
    }

    let alert_zones = proj.get("alert_zones")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|z| z.as_str()).collect::<Vec<_>>())
        .unwrap_or_default();
    let multi = proj.get("multi_zone_alert").and_then(|v| v.as_bool()).unwrap_or(false);
    let projs = proj.get("projections").and_then(|v| v.as_object())?;

    let mut lines: Vec<String> = Vec::new();
    lines.push(format!(
        "MARKOV PROJECTION: {} zones  at_risk={}  multi_zone_alert={}",
        projs.len(), alert_zones.len(), multi
    ));

    // Show at-risk zones first, then a compact summary of stable ones
    let mut at_risk_lines: Vec<String> = Vec::new();
    let mut stable_count = 0usize;

    for (zone, zp) in projs {
        let regime = zp.get("regime").and_then(|v| v.as_str()).unwrap_or("?");
        let p7     = zp.get("p_excursion_7d").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let p30    = zp.get("p_excursion_30d").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let sc     = zp.get("current_sc").and_then(|v| v.as_f64());
        let state  = zp.get("current_state").and_then(|v| v.as_str()).unwrap_or("?");

        if regime == "at_risk" || regime == "critical" || regime == "drifting" {
            at_risk_lines.push(format!(
                "  ⚠ {}: sc={:.3} [{}] P(exc_7d)={:.0}% P(exc_30d)={:.0}% regime={}",
                zone,
                sc.unwrap_or(f64::NAN),
                state,
                p7 * 100.0,
                p30 * 100.0,
                regime,
            ));
        } else {
            stable_count += 1;
        }
    }

    lines.extend(at_risk_lines);
    if stable_count > 0 {
        lines.push(format!("  ✓ {} zones stable (P(exc_7d) < 20%)", stable_count));
    }

    Some(lines.join("\n"))
}

// ── S4-MULTI-S1: climate domain context reader ────────────────────────────────

/// Read the latest s1-clima domain bundle written by s4_clima_bridge.py.
/// Returns formatted context string if bundle is fresh (< S4_CLIMA_BUNDLE_MAX_AGE_SECS).
/// Returns None if file absent, unreadable, or stale (bridge not running).
fn gather_climate_context_safe() -> Option<String> {
    let path = clima_bundle_path();
    if !path.exists() {
        return None;
    }
    let content = std::fs::read_to_string(&path).ok()?;
    let bundle: serde_json::Value = serde_json::from_str(&content).ok()?;

    // Staleness check: compare bundle ts to now
    let bundle_ts = bundle.get("_received_at")
        .or_else(|| bundle.get("ts"))
        .and_then(|v| v.as_str())
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&Utc));

    if let Some(ts) = bundle_ts {
        let age = (Utc::now() - ts).num_seconds();
        if age > S4_CLIMA_BUNDLE_MAX_AGE_SECS {
            eprintln!("[S4-SYNTH] clima bundle stale ({}s old) — skipping", age);
            return None;
        }
    }

    // Format the bundle into a readable prompt section
    let domain = bundle.get("domain").and_then(|v| v.as_str()).unwrap_or("s1-clima");
    let alg_status = bundle.get("algedonic_status").and_then(|v| v.as_str()).unwrap_or("?");
    let baseline = bundle.get("baseline").cloned().unwrap_or(serde_json::Value::Null);
    let oni = baseline.get("oni_value").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let enso = baseline.get("enso_state").and_then(|v| v.as_str()).unwrap_or("neutral");
    let global_regime = baseline.get("global_regime").and_then(|v| v.as_str()).unwrap_or("quiescent");

    let mut out = format!(
        "EXTERNAL DOMAIN: {} | algedonic={} | global_regime={} | ONI={:+.2} ({})\n",
        domain, alg_status, global_regime, oni, enso
    );

    if let Some(events) = bundle.get("events").and_then(|v| v.as_array()) {
        out.push_str("  L1 system summaries:\n");
        for ev in events {
            let sid = ev.get("system_id").and_then(|v| v.as_str()).unwrap_or("?");
            let reg = ev.get("regime").and_then(|v| v.as_str()).unwrap_or("?");
            let exc = ev.get("n_excursion_zones").and_then(|v| v.as_u64()).unwrap_or(0);
            let n   = ev.get("n_zones").and_then(|v| v.as_u64()).unwrap_or(0);
            let coh = ev.get("system_coherence").and_then(|v| v.as_f64()).unwrap_or(1.0);
            out.push_str(&format!(
                "    {}: regime={} excursions={}/{} coherence={:.3}\n",
                sid, reg, exc, n, coh
            ));
        }
    }

    Some(out.trim_end().to_string())
}

// ── ITEM_13.1 — Dual time series ─────────────────────────────────────────────

#[derive(Debug, Clone)]
struct TwinSeriesTick {
    tick: u64,
    ts: String,
    // Internal channel (von Foerster — system observing itself)
    stasis_cos: Option<f64>,
    h_t: Option<f64>,
    l_x: Option<f64>,
    trust: Option<f64>,
    regime: String,
    // External channel (Shannon — environment, independent of observer)
    cpu_pressure: Option<f64>,
    mem_pressure: Option<f64>,
    cpu_temp_c: Option<f64>,
    loadavg_1m: Option<f64>,
}

fn gather_twin_series_impl(path: &PathBuf) -> Result<Vec<TwinSeriesTick>, Box<dyn std::error::Error>> {
    let f = std::fs::File::open(path)?;
    let reader = std::io::BufReader::new(f);
    let mut tail: Vec<String> = Vec::with_capacity(CONTEXT_TAIL_LINES * 4);
    for line in std::io::BufRead::lines(reader) {
        let l = match line {
            Ok(l) if !l.trim().is_empty() => l,
            _ => continue,
        };
        tail.push(l);
        if tail.len() > CONTEXT_TAIL_LINES * 4 {
            let drop = tail.len() - CONTEXT_TAIL_LINES * 4;
            tail.drain(..drop);
        }
    }
    let start = tail.len().saturating_sub(CONTEXT_TAIL_LINES * 4);
    let tail = &tail[start..];

    let mut ticks: Vec<TwinSeriesTick> = Vec::new();
    for line in tail {
        let ev: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if ev.get("event_type").and_then(|v| v.as_str()) != Some("kernel_tick") {
            continue;
        }
        let m = match ev.get("metrics") {
            Some(v) => v,
            None => continue,
        };
        let k = m.get("kernel").cloned().unwrap_or(serde_json::Value::Null);
        let lyap = m.get("lyapunov").cloned().unwrap_or(serde_json::Value::Null);

        // External channel: find env_sample in l2_events
        let env = m.get("l2_events")
            .and_then(|v| v.as_array())
            .and_then(|arr| arr.iter().find(|e| e.get("kind").and_then(|x| x.as_str()) == Some("env_sample")))
            .cloned()
            .unwrap_or(serde_json::Value::Null);

        ticks.push(TwinSeriesTick {
            tick:         m.get("tick").and_then(|v| v.as_u64()).unwrap_or(0),
            ts:           ev.get("ts").and_then(|v| v.as_str()).unwrap_or("?").to_string(),
            stasis_cos:   k.get("stasis_cos").and_then(|v| v.as_f64()),
            h_t:          k.get("h_t").and_then(|v| v.as_f64()),
            l_x:          k.get("l_x").and_then(|v| v.as_f64()),
            trust:        k.get("trust").and_then(|v| v.as_f64()),
            regime:       lyap.get("regime").and_then(|v| v.as_str()).unwrap_or("?").to_string(),
            cpu_pressure: env.get("cpu_pressure").and_then(|v| v.as_f64()),
            mem_pressure: env.get("mem_pressure").and_then(|v| v.as_f64()),
            cpu_temp_c:   env.get("cpu_temp_c").and_then(|v| v.as_f64()),
            loadavg_1m:   env.get("loadavg_1m").and_then(|v| v.as_f64()),
        });
    }

    // Keep only the last N
    if ticks.len() > TWIN_SERIES_N {
        ticks.drain(..ticks.len() - TWIN_SERIES_N);
    }
    Ok(ticks)
}

fn fmt_opt(v: Option<f64>, decimals: usize) -> String {
    match v {
        Some(x) => format!("{:.prec$}", x, prec = decimals),
        None => "—".to_string(),
    }
}

// ── ITEM_13.4 — Projection context reader + Qwen interpreter ─────────────────

/// Holds the latest projection_tick snapshot from events.jsonl.
/// Fields mirror what operational.rs emits in the L2 event.
#[derive(Debug, Clone)]
struct ProjectionContext {
    regime: String,                    // "stable" | "degrading" | "recovering" | "insufficient"
    projected_stasis_cos: Option<f64>, // NaN-cleaned: None if insufficient/NaN
    horizon_ticks: u64,
    trend_slope: f64,
    load_correlation: f64,
    r_squared: f64,
    confidence: f64,
    n_points: usize,
}

/// Reads the latest `projection_tick` L2 event from events.jsonl.
/// Returns None when file unreadable, empty, or no projection yet.
fn gather_projection_impl(path: &PathBuf) -> Result<Option<ProjectionContext>, Box<dyn std::error::Error>> {
    let f = std::fs::File::open(path)?;
    let reader = std::io::BufReader::new(f);
    let mut tail: Vec<String> = Vec::with_capacity(CONTEXT_TAIL_LINES * 4);
    for line in std::io::BufRead::lines(reader) {
        let l = match line {
            Ok(l) if !l.trim().is_empty() => l,
            _ => continue,
        };
        tail.push(l);
        if tail.len() > CONTEXT_TAIL_LINES * 4 {
            let drop = tail.len() - CONTEXT_TAIL_LINES * 4;
            tail.drain(..drop);
        }
    }

    // Walk backwards: find the most recent kernel_tick that has a projection_tick L2 event
    for line in tail.iter().rev() {
        let ev: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if ev.get("event_type").and_then(|v| v.as_str()) != Some("kernel_tick") {
            continue;
        }
        let l2 = match ev.get("metrics")
            .and_then(|m| m.get("l2_events"))
            .and_then(|v| v.as_array()) {
            Some(a) => a,
            None => continue,
        };
        for e in l2 {
            if e.get("kind").and_then(|v| v.as_str()) != Some("projection_tick") {
                continue;
            }
            let regime = e.get("regime").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
            let projected_stasis_cos = e.get("projected_stasis_cos").and_then(|v| v.as_f64())
                .filter(|x| !x.is_nan());
            let horizon_ticks = e.get("horizon_ticks").and_then(|v| v.as_u64()).unwrap_or(0);
            let trend_slope = e.get("trend_slope").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let load_correlation = e.get("load_correlation").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let r_squared = e.get("r_squared").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let confidence = e.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let n_points = e.get("n_points").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            return Ok(Some(ProjectionContext {
                regime, projected_stasis_cos, horizon_ticks,
                trend_slope, load_correlation, r_squared, confidence, n_points,
            }));
        }
    }
    Ok(None)
}

/// Projection context as a formatted string for the Qwen prompt.
/// Returns None if no projection available (Insufficient / not yet started).
fn gather_projection_safe() -> Option<(ProjectionContext, String)> {
    let ctx = match gather_projection_impl(&events_jsonl_path()) {
        Ok(Some(c)) => c,
        Ok(None) | Err(_) => return None,
    };
    if ctx.regime == "insufficient" {
        return None; // Not enough data — skip interpretation cycle
    }
    let proj_sc_str = match ctx.projected_stasis_cos {
        Some(v) => format!("{:.4}", v),
        None => "N/A".to_string(),
    };
    let text = format!(
        "OLS Projection (mathematical — DO NOT recompute, read as given):\n\
        - regime:               {} (Stable/Degrading/Recovering)\n\
        - trend_slope:          {:.6}  (stasis_cos / tick)\n\
        - projected_stasis_cos: {} in {} ticks\n\
        - load_correlation:     {:.4}  (Pearson: stasis_cos vs loadavg_1m)\n\
        - r_squared:            {:.4}\n\
        - confidence:           {:.4}  (0=none, 1=high)\n\
        - n_points:             {}",
        ctx.regime, ctx.trend_slope, proj_sc_str, ctx.horizon_ticks,
        ctx.load_correlation, ctx.r_squared, ctx.confidence, ctx.n_points,
    );
    Some((ctx, text))
}

/// Qwen S4 interpretation result.
#[derive(Debug, Clone)]
pub struct InterpretationResult {
    pub regime: String,
    pub text: String,        // plain-language interpretation
    pub vsl_proposal: String, // VSL intervention proposal (may be "none" if stable)
}

/// ITEM_13.4 — Second, smaller Qwen call: interpret the projection + propose VSL action.
///
/// Qwen reads the mathematical projection as data — it does NOT recompute anything.
/// Output: { "interpretation": "...", "vsl_proposal": "..." }
fn call_qwen_interpreter(
    cfg: &NucleusConfig,
    projection_text: &str,
    ctx: &ProjectionContext,
) -> Result<InterpretationResult, Box<dyn Error>> {
    let prompt = format!(
        "You are the S4 Intelligence layer of a Viable System Model (VSM) controller.\n\
        The mathematical projector has already computed the following OLS projection.\n\
        Your task: READ these results and (1) interpret them in plain language, \
        (2) propose ONE VSL directive if action is needed.\n\
        \n\
        {}\n\
        \n\
        Rules:\n\
        - The regime field is ground truth — do NOT reinterpret or override it.\n\
        - A 'stable' regime with confidence < 0.3 means projection is tentative — note this.\n\
        - A 'degrading' regime means stasis_cos is falling; propose a VSL φ↓ directive.\n\
        - A 'recovering' regime means the system is self-correcting; recommend observation.\n\
        - VSL proposal format: S4→S3: <directive> (e.g. 'S4→S3: reduce s4_cycle_interval_secs to 30')\n\
        - If no action needed, vsl_proposal = 'none'\n\
        \n\
        Respond with ONLY valid JSON: {{\"interpretation\": \"...\", \"vsl_proposal\": \"...\"}}\n\
        No markdown, no explanation outside the JSON.",
        projection_text,
    );

    let request = OllamaRequest {
        model: cfg.ollama_model.clone(),
        prompt,
        stream: false,
        options: OllamaOptions {
            temperature: 0.3,
            num_predict: 80, // {"interpretation":"...","vsl_proposal":"..."} — short JSON, 80 tok ceiling
            num_ctx: 256,
        },
    };

    let url = format!("{}/api/generate", cfg.ollama_url);
    let response = ureq::post(&url)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_secs(cfg.ollama_timeout_secs as u64))
        .send_json(&request)
        .map_err(|e| {
            eprintln!("[S4-interp] Ollama request failed: {}", e);
            Box::new(e) as Box<dyn Error>
        })?;

    let ollama_resp: OllamaResponse = response.into_json()?;
    let raw = ollama_resp.response;

    // Strip markdown fences if present
    let json_str = if raw.contains("```") {
        raw.split("```").nth(1).unwrap_or(&raw)
            .trim_start_matches("json")
            .trim()
            .to_string()
    } else {
        raw.trim().to_string()
    };

    // Parse — lenient: if Qwen wraps in array, take first element
    let v: serde_json::Value = serde_json::from_str(&json_str)?;
    let obj = if v.is_array() {
        v.as_array().and_then(|a| a.first()).cloned().unwrap_or(serde_json::Value::Null)
    } else {
        v
    };

    let interpretation = obj.get("interpretation")
        .and_then(|x| x.as_str())
        .unwrap_or("(no interpretation)")
        .to_string();
    let vsl_proposal = obj.get("vsl_proposal")
        .and_then(|x| x.as_str())
        .unwrap_or("none")
        .to_string();

    Ok(InterpretationResult {
        regime: ctx.regime.clone(),
        text: interpretation,
        vsl_proposal,
    })
}

fn gather_twin_series_safe() -> String {
    match gather_twin_series_impl(&events_jsonl_path()) {
        Err(_) => "  (twin series unavailable)".to_string(),
        Ok(ticks) if ticks.is_empty() => "  (no kernel_tick events in window)".to_string(),
        Ok(ticks) => {
            let has_external = ticks.iter().any(|t| t.cpu_pressure.is_some());
            let mut out = String::new();

            out.push_str("INTERNAL (von Foerster — self-observation):\n");
            out.push_str("  tick    stasis_cos  h_t    l_x     trust  regime\n");
            for t in &ticks {
                out.push_str(&format!(
                    "  {:>6}  {}  {}  {}  {}  {}\n",
                    t.tick,
                    fmt_opt(t.stasis_cos, 4),
                    fmt_opt(t.h_t, 3),
                    fmt_opt(t.l_x, 4),
                    fmt_opt(t.trust, 3),
                    t.regime,
                ));
            }

            if has_external {
                out.push_str("\nEXTERNAL (Shannon — environment, independent):\n");
                out.push_str("  tick    cpu_p   mem_p  temp_c  load1m\n");
                for t in &ticks {
                    out.push_str(&format!(
                        "  {:>6}  {}  {}  {}  {}\n",
                        t.tick,
                        fmt_opt(t.cpu_pressure, 4),
                        fmt_opt(t.mem_pressure, 4),
                        fmt_opt(t.cpu_temp_c, 1),
                        fmt_opt(t.loadavg_1m, 2),
                    ));
                }
            } else {
                out.push_str("\nEXTERNAL: no env_sample events yet (ITEM_13.0 just deployed)\n");
            }

            out.trim_end().to_string()
        }
    }
}

fn gather_recent_context_safe() -> String {
    match gather_recent_context_impl(&events_jsonl_path()) {
        Ok(s) if !s.is_empty() => s,
        Ok(_) => "  (no recent events)".to_string(),
        Err(_) => "  (no recent events context available)".to_string(),
    }
}

fn gather_recent_context_impl(path: &PathBuf) -> Result<String, Box<dyn Error>> {
    let f = File::open(path)?;
    let reader = BufReader::new(f);
    // Read all lines, take last N (events.jsonl bounded by daily rollover policy)
    let mut tail: Vec<String> = Vec::with_capacity(CONTEXT_TAIL_LINES);
    for line in reader.lines() {
        let line = match line {
            Ok(l) if !l.trim().is_empty() => l,
            _ => continue,
        };
        tail.push(line);
        if tail.len() > CONTEXT_TAIL_LINES * 4 {
            // bound memory if file is huge
            let drop = tail.len() - CONTEXT_TAIL_LINES * 4;
            tail.drain(..drop);
        }
    }
    let start = tail.len().saturating_sub(CONTEXT_TAIL_LINES);
    let tail = &tail[start..];

    let now = Utc::now();
    let mut by_type: BTreeMap<String, (u32, String, String)> = BTreeMap::new();
    // (count, last_ts, last_key_metric_summary)

    for line in tail {
        let ev: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let et = match ev.get("event_type").and_then(|v| v.as_str()) {
            Some(s) if s != CONTEXT_EXCLUDE => s.to_string(),
            _ => continue,
        };
        let ts_str = match ev.get("ts").and_then(|v| v.as_str()) {
            Some(s) => s,
            None => continue,
        };
        let ts: DateTime<Utc> = match DateTime::parse_from_rfc3339(ts_str) {
            Ok(t) => t.with_timezone(&Utc),
            Err(_) => continue,
        };
        let age = (now - ts).num_seconds();
        if age < 0 || age > CONTEXT_MAX_AGE_SECS {
            continue;
        }
        // Extract a useful key metric per event type
        let summary = summarize_event(&et, &ev);
        let entry = by_type.entry(et).or_insert_with(|| (0, String::new(), String::new()));
        entry.0 += 1;
        entry.1 = ts_str.to_string();
        entry.2 = summary;
    }

    if by_type.is_empty() {
        return Ok(String::new());
    }
    let mut out = String::new();
    for (et, (count, last_ts, summary)) in by_type.iter() {
        out.push_str(&format!(
            "  - {}: {} in last {}s, last @ {} ({})\n",
            et,
            count,
            CONTEXT_MAX_AGE_SECS,
            last_ts,
            summary
        ));
    }
    Ok(out.trim_end().to_string())
}

fn summarize_event(event_type: &str, ev: &serde_json::Value) -> String {
    let m = ev.get("metrics").cloned().unwrap_or(serde_json::Value::Null);
    match event_type {
        "kernel_tick" => {
            let tick = m.get("tick").and_then(|v| v.as_u64()).unwrap_or(0);
            let sc = m.get("kernel").and_then(|k| k.get("stasis_cos"))
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
            let trust = m.get("kernel").and_then(|k| k.get("trust"))
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
            let regime = m.get("lyapunov").and_then(|l| l.get("regime"))
                .and_then(|v| v.as_str()).unwrap_or("?");
            format!("tick={} stasis_cos={:.4} trust={:.3} regime={}", tick, sc, trust, regime)
        }
        "invariant_check" => {
            let v = m.get("var1_mean").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let t = m.get("trust1_mean").and_then(|x| x.as_f64()).unwrap_or(0.0);
            format!("var1_mean={:.2} trust1_mean={:.2}", v, t)
        }
        "algedonic_emit" => {
            let cat = m.get("reason").and_then(|x| x.as_str()).unwrap_or("?");
            format!("reason={}", cat)
        }
        "param_change" => {
            let keys = m.get("changed_keys").and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|x| x.as_str()).collect::<Vec<_>>().join(","))
                .unwrap_or_default();
            format!("changed={}", keys)
        }
        _ => "—".to_string(),
    }
}

/// Ollama generate API: model params must be nested under "options", not top-level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaOptions {
    pub temperature: f64,
    /// Hard cap on generated tokens — critical for CPU inference.
    /// At ~4-8 tok/s CPU, 200 tok ≈ 25-50s; without limit → >120s timeout.
    pub num_predict: u32,
    /// Context window size — smaller = faster prefill on CPU.
    pub num_ctx: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaRequest {
    pub model: String,
    pub prompt: String,
    pub stream: bool,
    pub options: OllamaOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaResponse {
    pub response: String,
}

pub struct S4Orchestrator {
    /// P.3.1 (A1) — Shared live config. Read at start of each cycle so phi_down
    /// override semantics are honored. phi_down_subscriber holds a clone of this
    /// Arc<RwLock> and writes to it on policy-override messages.
    ///
    /// Read lock is held briefly (one read per cycle). No long-held locks.
    live_config: Arc<RwLock<NucleusConfig>>,
    bbs: BbsEmbeddedClient,
    /// P.1 — Optional canonical writer to dual-write s4-analysis events.
    /// When Some, every successful BBS publish also emits a canonical event
    /// to events.jsonl. Enables K_φ↓ numerator measurement (GATE_3).
    canon: Option<CanonicalTelemetry>,
    /// Phase 4.4 (γ.11) — Optional S3* audit findings buffer. When Some, S4
    /// includes recent audit findings in its Qwen prompt context, so S4
    /// adapts planning to anti-capture audit signals (Beer-faithful).
    audit_buffer: Option<crate::s3_star_audit::AuditBuffer>,
    /// ITEM_5.5 — Shared queue for L3 proposals awaiting S5 human approval.
    /// When Some, S4 enqueues ParameterDrift proposals on sustained drift.
    /// Subscriber (started in operational.rs) delivers signed tokens back.
    pending_queue: Option<PendingApprovalQueue>,
    /// S4-MULTI-S1: cycle counter for periodic cross-domain synthesis.
    synth_cycle_counter: std::sync::atomic::AtomicU32,
}

impl S4Orchestrator {
    pub fn new(live_config: Arc<RwLock<NucleusConfig>>) -> Self {
        let nucleus_source_id = live_config
            .read()
            .expect("config RwLock poisoned at startup")
            .nucleus_source_id
            .clone();
        let bbs = BbsEmbeddedClient::new("/root/bbs.db", nucleus_source_id)
            .expect("Failed to initialize embedded BBS");
        S4Orchestrator {
            live_config,
            bbs,
            canon: None,
            audit_buffer: None,
            pending_queue: None,
            synth_cycle_counter: std::sync::atomic::AtomicU32::new(0),
        }
    }

    /// P.1 — Attach the canonical writer so this orchestrator emits
    /// `s4-analysis` events to events.jsonl in addition to BBS.
    pub fn with_canonical(mut self, canon: CanonicalTelemetry) -> Self {
        self.canon = Some(canon);
        self
    }

    /// Phase 4.4 — Attach the S3* audit buffer so S4 prompt includes recent
    /// audit findings as planning context.
    pub fn with_audit_buffer(mut self, buf: crate::s3_star_audit::AuditBuffer) -> Self {
        self.audit_buffer = Some(buf);
        self
    }

    /// ITEM_5.5 — Attach the S5 approval queue so S4 can enqueue ParameterDrift
    /// proposals when sustained drift is detected. Queue is shared with the
    /// approval_subscriber thread (started in operational.rs).
    pub fn with_approval_queue(mut self, q: PendingApprovalQueue) -> Self {
        self.pending_queue = Some(q);
        self
    }

    /// Snapshot current live config. Called at start of each cycle.
    /// Returns owned clone to release the read lock as quickly as possible.
    fn snapshot_config(&self) -> NucleusConfig {
        self.live_config
            .read()
            .expect("config RwLock poisoned")
            .clone()
    }

    /// Expose the cycle interval (used by spawn loop sleep).
    /// Reads the LATEST value each call.
    pub fn current_cycle_interval_secs(&self) -> u32 {
        self.live_config
            .read()
            .expect("config RwLock poisoned")
            .s4_cycle_interval_secs
    }

    /// ITEM_5.5 — Check twin series for sustained homeostatic drift.
    /// If stasis_cos has been below REFRAME_STASIS_THRESHOLD for at least
    /// REFRAME_MIN_FALLING_TICKS consecutive ticks, enqueue a ParameterDrift
    /// proposal in the pending_approval_queue for S5 review via NATS.
    ///
    /// Fail-soft: any I/O or queue error is logged but never propagates.
    /// Dedup: if a parameter_drift proposal is already pending, skips quietly.
    fn check_and_propose_reframe(&self) {
        let queue = match &self.pending_queue {
            Some(q) => q,
            None => return,
        };

        // Read twin series — same path as the governance prompt context.
        let ticks = match gather_twin_series_impl(&events_jsonl_path()) {
            Ok(t) if t.len() >= REFRAME_MIN_FALLING_TICKS => t,
            _ => return,
        };

        // Count trailing ticks with stasis_cos below threshold.
        let low_count = ticks
            .iter()
            .rev()
            .take_while(|t| t.stasis_cos.map_or(false, |c| c < REFRAME_STASIS_THRESHOLD))
            .count();

        if low_count < REFRAME_MIN_FALLING_TICKS {
            return;
        }

        // Dedup: skip if a parameter_drift proposal is already queued.
        {
            let q = queue.lock().expect("pending_queue poisoned");
            if q.values().any(|p| p.kind == "parameter_drift") {
                return;
            }
        }

        let last_cos = ticks.last().and_then(|t| t.stasis_cos).unwrap_or(0.0);
        let description = format!(
            "stasis_cos={:.3} below threshold={} for {} consecutive ticks — parameter adjustment needed",
            last_cos, REFRAME_STASIS_THRESHOLD, low_count
        );

        let proposal = ReframeProposal::propose(
            format!("pd-{}", Utc::now().timestamp()),
            ReframeScope::ParameterDrift,
            &description,
            RecertConfig::default(),
        );

        let pending = PendingProposal {
            proposal_id:  proposal.id.clone(),
            content_hash: proposal.content_hash.clone(),
            kind:         "parameter_drift".to_string(),
            rationale:    description,
            staged_at:    Utc::now().to_rfc3339(),
            ttl_s:        600,
        };

        enqueue_proposal(queue, pending);
        // NATS notification is handled by start_approval_emitter (tokio task, 60s poll).
        println!("[S4-reframe] ParameterDrift proposal enqueued (id={}, cos={:.3}) — NATS emit in ≤60s",
                 proposal.id, last_cos);
    }

    /// S4-MULTI-S1 (wave_1): Cross-domain synthesis cycle.
    /// Called every S4_SYNTH_PERIOD_CYCLES S4 cycles.
    /// Reads clima context + nucleus twin series → Qwen cross-domain brief →
    /// emits s4_cross_domain_synthesis canonical event. D6'-compliant: advisory only.
    fn run_synth_cycle(&self, cfg: &NucleusConfig) -> Result<(), Box<dyn Error>> {
        let clima_ctx = match gather_climate_context_safe() {
            Some(ctx) => ctx,
            None => {
                eprintln!("[S4-SYNTH] no fresh clima context — skipping this cycle");
                return Ok(());
            }
        };

        let nucleus_ctx  = gather_twin_series_safe();
        let markov_ctx   = gather_markov_context_safe();

        let markov_section = match &markov_ctx {
            Some(m) => format!("\n\nMARKOV PROJECTIONS (τ(t+n) — Perron-Frobenius, trained ERA5 1991-2020):\n{}", m),
            None    => String::new(),
        };

        let prompt = format!(
            "You are the S4 cross-domain intelligence synthesiser of a VSM (Viable System Model) controller.\n\
            Two S1 domains are active. Review their context and identify cross-domain patterns.\n\
            \n\
            NUCLEUS DOMAIN (internal — compute kernel):\n{}\n\
            \n\
            CLIMA DOMAIN (external — South American climate network):\n{}{}\n\
            \n\
            Tasks:\n\
            1. Identify correlated anomalies (same pattern in both domains simultaneously)\n\
            2. Identify resource conflicts (shared resources: Ollama/NATS/LXC-101 CPU)\n\
            3. Identify cascading risks (anomaly in one domain predicting stress in other)\n\
            4. Name the dominant concern (which domain needs S3 attention most urgently)\n\
            \n\
            Rules:\n\
            - Do NOT recommend L0/L1 actions directly — advisory to S3 only (D6')\n\
            - If both domains quiescent: output 'routing: none'\n\
            - routing urgency: LOW | MEDIUM | HIGH | CRITICAL\n\
            \n\
            Respond with ONLY valid JSON:\n\
            {{\"correlated_anomalies\":[],\"resource_conflicts\":[],\"cascading_risks\":[],\
            \"routing\":{{\"domain\":\"...\",\"urgency\":\"LOW\",\"reason\":\"...\"}},\
            \"synthesis\":\"one sentence summary\"}}\n\
            No markdown.",
            nucleus_ctx,
            clima_ctx,
            markov_section,
        );

        let request = OllamaRequest {
            model: cfg.ollama_model.clone(),
            prompt,
            stream: false,
            options: OllamaOptions {
                temperature: 0.3,
                num_predict: 200,
                num_ctx: 512,
            },
        };

        let url = format!("{}/api/generate", cfg.ollama_url);
        let response = ureq::post(&url)
            .set("Content-Type", "application/json")
            .timeout(Duration::from_secs(cfg.ollama_timeout_secs as u64))
            .send_json(&request)
            .map_err(|e| format!("Ollama SYNTH request failed: {}", e))?;

        let ollama_resp: OllamaResponse = response.into_json()?;
        let raw = ollama_resp.response;

        // Strip markdown fences
        let json_str = if raw.contains("```") {
            raw.split("```").nth(1).unwrap_or(&raw)
                .trim_start_matches("json").trim().to_string()
        } else {
            raw.trim().to_string()
        };

        let parsed: serde_json::Value = serde_json::from_str(&json_str)
            .unwrap_or_else(|_| serde_json::json!({"synthesis": raw.trim(), "parse_error": true}));

        let synthesis = parsed.get("synthesis").and_then(|v| v.as_str()).unwrap_or("(no synthesis)");
        let urgency = parsed.get("routing")
            .and_then(|r| r.get("urgency"))
            .and_then(|v| v.as_str())
            .unwrap_or("LOW");

        println!("[S4-SYNTH] synthesis: {} | urgency={}", synthesis, urgency);

        // Emit canonical s4_cross_domain_synthesis event
        if let Some(canon) = &self.canon {
            let event = CanonicalEvent {
                ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                system_id: cfg.nucleus_source_id.clone(),
                event_type: "s4_cross_domain_synthesis".to_string(),
                status: "ok".to_string(),
                signal_status: "resolved".to_string(),
                duration_s: 0.0,
                metrics: serde_json::json!({
                    "domains_analysed": ["vsf-nucleus", "s1-clima"],
                    "synthesis": synthesis,
                    "urgency": urgency,
                    "raw_output": parsed,
                    "_note": "S4-MULTI-S1 cross-domain synthesis — advisory only (D6')"
                }),
                variety_delta: None,
                trust_score: None,
                algedonic_seq: 0,
                origin: None,
                chain_format_version: None,
                prev_hash: None,
                hash: None,
            };
            if let Err(e) = canon.emit(event) {
                eprintln!("[S4-SYNTH] canonical emit failed: {} (non-fatal)", e);
            }
        }

        // s4_routing_signal for HIGH/CRITICAL urgency (D6': AC classifies, no auto-action)
        if matches!(urgency, "HIGH" | "CRITICAL") {
            let routing_domain = parsed.get("routing")
                .and_then(|r| r.get("domain"))
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            let reason = parsed.get("routing")
                .and_then(|r| r.get("reason"))
                .and_then(|v| v.as_str())
                .unwrap_or("cross-domain synthesis");
            println!("[S4-SYNTH] routing_signal → domain={} urgency={} reason={}",
                     routing_domain, urgency, reason);
            if let Some(canon) = &self.canon {
                let routing_event = CanonicalEvent {
                    ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                    system_id: cfg.nucleus_source_id.clone(),
                    event_type: "s4_routing_signal".to_string(),
                    status: "ok".to_string(),
                    signal_status: "active".to_string(),
                    duration_s: 0.0,
                    metrics: serde_json::json!({
                        "target":  routing_domain,
                        "urgency": urgency,
                        "reason":  reason,
                        "_note":   "advisory to S3; no auto-action (D6'/A5)"
                    }),
                    variety_delta: None,
                    trust_score: None,
                    algedonic_seq: 0,
                    origin: None,
                    chain_format_version: None,
                    prev_hash: None,
                    hash: None,
                };
                if let Err(e) = canon.emit(routing_event) {
                    eprintln!("[S4-SYNTH] routing_signal emit failed: {} (non-fatal)", e);
                }
            }
        }

        Ok(())
    }

    /// Main operational cycle
    pub fn run_cycle(&self) -> Result<(), Box<dyn Error>> {
        // P.3.1 (A1) — read live config ONCE per cycle. Any phi_down patch that
        // arrived since previous cycle is now in effect.
        let cfg = self.snapshot_config();
        println!(
            "\n=== S4 ORCHESTRATION CYCLE (interval={}s, model={}) ===",
            cfg.s4_cycle_interval_secs, cfg.ollama_model
        );
        let cycle_start = Instant::now();

        // ITEM_13.4 — read projection context BEFORE Qwen calls (single read, shared)
        let proj_opt = gather_projection_safe();
        if let Some((_, ref txt)) = proj_opt {
            println!("[S4] projection context: {}", txt.lines().next().unwrap_or(""));
        }

        // ITEM_5.5 — Reframe live queue: check for sustained homeostatic drift.
        // Fail-soft: errors logged inside; never breaks the governance path.
        self.check_and_propose_reframe();

        // 1. Read system state from BBS
        match self.bbs.read_system_state() {
            Ok(state) => {
                println!(
                    "✓ System state read: node={}, ram_alloc={}GB",
                    state.node, state.ram_gb
                );

                // 2. Analyze with Qwen — governance decisions (pass snapshot)
                match self.analyze_state_with_qwen(&cfg, &state) {
                    Ok(mut decisions) => {
                        if !decisions.is_empty() {
                            // q19.B — emit-time veto: filter out empty-action decisions.
                            // MANDATORY: emit an s4-null-decision sentinel when veto fires,
                            // so the defect remains visible (bare veto masks truncation).
                            let empty_count = decisions.iter().filter(|d| d.action.trim().is_empty()).count();
                            if empty_count > 0 {
                                decisions.retain(|d| !d.action.trim().is_empty());
                                eprintln!(
                                    "[q19.B] VETO: filtered {} empty-action decision(s) ({}/{} remaining)",
                                    empty_count, decisions.len(), empty_count + decisions.len()
                                );
                                // Emit sentinel marker to canonical chain
                                if let Some(canon) = &self.canon {
                                    let sentinel = CanonicalEvent {
                                        ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                        system_id: cfg.nucleus_source_id.clone(),
                                        event_type: "s4-null-decision".to_string(),
                                        status: "vetoed".to_string(),
                                        signal_status: "active".to_string(),
                                        duration_s: 0.0,
                                        metrics: serde_json::json!({
                                            "vetoed_count": empty_count,
                                            "remaining_count": decisions.len(),
                                            "_note": "q19.B sentinel — empty-action veto fired. Not a correction: the defect is visible by design.",
                                        }),
                                        variety_delta: None,
                                        trust_score: None,
                                        algedonic_seq: 0,
                                        origin: None,
                                        chain_format_version: None,
                                        prev_hash: None,
                                        hash: None,
                                    };
                                    if let Err(e) = canon.emit(sentinel) {
                                        eprintln!("[q19.B] sentinel emit failed: {} (cycle continues)", e);
                                    }
                                }
                            }
                            println!("✓ Qwen generated {} decisions", decisions.len());

                            // ITEM_13.4 — second Qwen call: projection interpreter.
                            // Only when projection is available (regime != insufficient).
                            // Fail-soft: errors log but never break the governance path.
                            let interp_opt: Option<InterpretationResult> = proj_opt
                                .as_ref()
                                .and_then(|(ctx, txt)| {
                                    match call_qwen_interpreter(&cfg, txt, ctx) {
                                        Ok(r) => {
                                            println!(
                                                "[S4-interp] regime={} vsl_proposal={}",
                                                r.regime,
                                                if r.vsl_proposal == "none" { "none" } else { &r.vsl_proposal }
                                            );
                                            Some(r)
                                        }
                                        Err(e) => {
                                            eprintln!("[S4-interp] interpreter error: {} (non-fatal)", e);
                                            None
                                        }
                                    }
                                });

                            // 3. Log decision (embedded)
                            match self.bbs.publish_s4_analysis(decisions.clone()) {
                                Ok(msg_id) => {
                                    println!("✓ Decision logged (embedded, msg_id={})", msg_id);

                                    // P.1 — Dual-write to events.jsonl for K_φ↓ measurement
                                    self.emit_s4_analysis_event(
                                        &cfg,
                                        &decisions,
                                        &msg_id,
                                        &state,
                                        cycle_start.elapsed().as_secs_f64(),
                                        interp_opt.as_ref(),
                                    );
                                }
                                Err(e) => {
                                    eprintln!("✗ Failed to publish decisions: {}", e);
                                }
                            }
                        } else {
                            println!("! No decisions generated");
                        }
                    }
                    Err(e) => {
                        eprintln!("✗ Analysis failed: {}", e);
                    }
                }
            }
            Err(e) => {
                eprintln!("✗ Failed to read system state: {}", e);
            }
        }

        // S4-MULTI-S1: cross-domain synthesis every S4_SYNTH_PERIOD_CYCLES
        let cycle = self.synth_cycle_counter.load(std::sync::atomic::Ordering::Relaxed).wrapping_add(1);
        self.synth_cycle_counter.store(cycle, std::sync::atomic::Ordering::Relaxed);
        if cycle % S4_SYNTH_PERIOD_CYCLES == 0 {
            println!("[S4-SYNTH] cycle {} — running cross-domain synthesis", cycle);
            if let Err(e) = self.run_synth_cycle(&cfg) {
                eprintln!("[S4-SYNTH] error: {} (non-fatal)", e);
            }
        }

        println!("Cycle complete\n");
        Ok(())
    }

    /// P.1 — Emit canonical `s4-analysis` event after successful BBS publish.
    /// ITEM_13.4: includes optional `s4_interpretation` L2 block when Qwen
    /// produced a projection interpretation this cycle.
    /// No-op if canonical writer not attached. Errors logged, never propagated.
    fn emit_s4_analysis_event(
        &self,
        cfg: &NucleusConfig,
        decisions: &[Decision],
        msg_id: &str,
        state: &SystemState,
        duration_s: f64,
        interp: Option<&InterpretationResult>, // ITEM_13.4
    ) {
        let canon = match &self.canon {
            Some(c) => c,
            None => return,
        };
        let first_action = decisions
            .first()
            .map(|d| d.action.clone())
            .unwrap_or_default();

        // ITEM_13.4 — embed interpretation as l2_event if available
        let l2_events: serde_json::Value = match interp {
            Some(r) => serde_json::json!([{
                "kind": "s4_interpretation",
                "regime": r.regime,
                "text": r.text,
                "vsl_proposal": r.vsl_proposal,
            }]),
            None => serde_json::json!([]),
        };

        let event = CanonicalEvent {
            ts: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
            system_id: cfg.nucleus_source_id.clone(),
            event_type: "s4-analysis".to_string(),
            status: "ok".to_string(),
            signal_status: "resolved".to_string(),
            duration_s,
            metrics: serde_json::json!({
                "decisions_count": decisions.len(),
                "bbs_msg_id": msg_id.to_string(),
                "first_action": first_action,
                "state_ram_gb": state.ram_gb,
                "state_containers": state.containers,
                "model": cfg.ollama_model,
                "l2_events": l2_events,
                "_note": "P.1 dual-write — S5 decision marker for K_φ↓ measurement",
            }),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            // G-K.2: causal identifier — bbs_msg_id of the published decision.
            origin: Some(msg_id.to_string()),
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        if let Err(e) = canon.emit(event) {
            eprintln!("[S4] canonical emit failed: {} (cycle continues)", e);
        }
    }

    /// Call Ollama Qwen to analyze system state.
    /// Takes a config snapshot so the request uses values consistent with this cycle.
    fn analyze_state_with_qwen(
        &self,
        cfg: &NucleusConfig,
        state: &SystemState,
    ) -> Result<Vec<Decision>, Box<dyn Error>> {
        // P.4 (Phase 3) — closes BRECHA-2: S4 reads its own canonical events
        // for historical context instead of being blind to events.jsonl.
        // Filter rule: exclude s4-analysis to avoid echo-chamber feedback loop.
        let context = gather_recent_context_safe();

        // ITEM_13.1 — dual time series: last N kernel_ticks, both channels.
        // Internal (von Foerster): stasis_cos/h_t/l_x/trust — system observing itself.
        // External (Shannon): cpu_pressure/cpu_temp_c/loadavg — independent of observer.
        let twin_series = gather_twin_series_safe();

        // Phase 4.4 (γ.11) — S4 sees recent S3* audit findings so planning
        // adapts to anti-capture signals (Beer: intelligence factors audit).
        let audit_context = self
            .audit_buffer
            .as_ref()
            .map(|b| b.summarize(5))
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "  (no recent S3* audit findings)".to_string());

        // S4-MULTI-S1: include climate domain context if fresh bundle available
        let clima_ctx_opt = gather_climate_context_safe();
        let clima_section = match &clima_ctx_opt {
            Some(ctx) => format!("External domain context (s1-clima):\n{}", ctx),
            None => "(s1-clima context: not yet available)".to_string(),
        };

        // Build concise prompt with event + audit context + dual time series + clima
        let prompt = format!(
            "System Health Check: RAM {:.1}GB allocated, {} containers running.\n\
            Recent system events (last 5min, excluding own decisions):\n{}\n\
            Dual time series — last {} kernel_ticks (internal + external channels):\n{}\n\
            Recent S3* anti-capture audit findings:\n{}\n\
            {}\n\
            Return a JSON array with exactly 1 element: [{{\"decision_type\":\"...\",\"action\":\"...\",\"target\":\"...\",\"reason\":\"...\"}}]. \
            Each field: under 8 words. No markdown.",
            state.ram_gb, state.containers, context, TWIN_SERIES_N, twin_series,
            audit_context, clima_section
        );

        // q20: log prompt length for measurement (~10 cycles needed)
        let prompt_chars = prompt.chars().count();
        let prompt_est_tokens = prompt.len() / 4; // rough estimate: ~4 chars/token for English
        eprintln!("[q20] PROMPT_LEN: chars={} bytes={} est_tokens={} num_ctx=256",
            prompt_chars, prompt.len(), prompt_est_tokens);

        // Call Ollama
        let request = OllamaRequest {
            model: cfg.ollama_model.clone(),
            prompt,
            stream: false,
            options: OllamaOptions {
                temperature: 0.5,
                num_predict: 80, // per L4 tuning — reduces S4 cycle ~200s→~110s on 1 core; { ethical-elab, tradespace, confidence } fit JSON in ~60 tok with 20 tok margin
                num_ctx: 256,
            },
        };

        let url = format!("{}/api/generate", cfg.ollama_url);
        let response = ureq::post(&url)
            .set("Content-Type", "application/json")
            .timeout(Duration::from_secs(cfg.ollama_timeout_secs as u64))
            .send_json(&request)
            .map_err(|e| {
                eprintln!("Ollama request failed: {}", e);
                Box::new(e) as Box<dyn Error>
            })?;

        let ollama_resp: OllamaResponse = response.into_json()?;
        let response_text = ollama_resp.response;

        // Parse JSON (strip markdown code fences if present)
        let json_text = self.extract_json(&response_text)?;
        let decisions: Vec<Decision> = serde_json::from_str(&json_text)?;

        // q20: log the resulting action alongside prompt size for relevance check
        let first_action = decisions.first()
            .map(|d| d.action.as_str())
            .unwrap_or("(no decisions)");
        eprintln!("[q20] DECISION: action=\"{}\" decisions_count={} response_len={}",
            first_action, decisions.len(), response_text.len());

        Ok(decisions)
    }

    /// Extract JSON from response (handles markdown wrapping)
    fn extract_json(&self, text: &str) -> Result<String, Box<dyn Error>> {
        let mut result = text.to_string();

        // Remove markdown code fences if present
        if result.starts_with("```") {
            result = result.split("```").nth(1).unwrap_or("").to_string();
            if result.starts_with("json\n") {
                result = result[5..].to_string();
            }
        }

        Ok(result.trim().to_string())
    }

    /// Run continuous orchestration loop. Reads sleep interval from LIVE config
    /// each iteration so phi_down overrides take effect on the very next sleep.
    pub fn run_forever(&self) -> Result<(), Box<dyn Error>> {
        let initial = self.snapshot_config();
        println!(
            "Starting S4 Orchestrator (interval={}s, model={}) — live-config aware",
            initial.s4_cycle_interval_secs, initial.ollama_model
        );

        loop {
            if let Err(e) = self.run_cycle() {
                eprintln!("Cycle error: {}", e);
            }
            // Re-read interval each iteration — phi_down may have changed it
            let sleep_secs = self.current_cycle_interval_secs() as u64;
            thread::sleep(Duration::from_secs(sleep_secs));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_json_with_markdown() {
        let live_config = Arc::new(RwLock::new(NucleusConfig::default()));
        let orchestrator = S4Orchestrator::new(live_config);

        let input = r#"```json
[{"decision_type": "test", "action": "verify", "target": "nucleus", "reason": "test"}]
```"#;

        let result = orchestrator.extract_json(input).unwrap();
        assert!(result.contains("decision_type"));
        assert!(!result.starts_with("```"));
    }
}
