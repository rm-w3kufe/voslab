/// invariant_checker.rs — γ.6 — Runtime checker for formal VSL invariants
///
/// @vsm 0.3
/// canonical: matches connection_schema.json v0.2.1 §upward_channel event_types:
///   - invariant_check
///   - drift_alert
///
/// Implements the 3 formal invariants added in Qwen consensus ronda 3:
///   VAR-1   : ΔV_in ≥ ΔV_out per regulating step (Ashby variety law applied)
///   TRUST-1 : trust_chain(path) = Π trust_i  (multiplicative trust composition)
///   ALG-1   : algedonic_decay(L, t) ≤ exp(-λ·t)  (cascade prevention)
///
/// Plus runtime mechanics required by per_system_requirements_method.md §6:
///   - Rolling window stats (N=100 samples) per invariant
///   - Drift detection: |current - baseline| > k·stddev_baseline (k=3 default)
///   - Circuit breaker: M=3 consecutive failures → emit signal_escalated
///
/// Design principle: "núcleo primero" — no external dependencies beyond what
/// γ.1+γ.2 already brought in (telemetry_canonical, serde_json).
///
/// This module also exposes `baseline_stasis_cos()` for γ.4 (algedonic_gate
/// needs a healthy-system reference to set its hysteresis).

use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use serde_json::json;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

/// Default rolling window size per invariant.
pub const WINDOW_SIZE: usize = 100;
/// Sigmas from baseline before emitting drift_alert.
pub const DRIFT_K: f64 = 3.0;
/// Consecutive failures before emitting signal_escalated (circuit breaker).
pub const CB_M: usize = 3;
/// Algedonic decay rate λ — per VSL ALG-1, the upper-bound exponent in exp(-λt).
/// Tuned conservatively; revisit after empirical observation in γ.0 dry-run.
pub const ALG_LAMBDA: f64 = 0.1; // 1/sec ≈ half-life ~6.9 sec

#[derive(Debug, Clone, PartialEq)]
pub enum InvariantId {
    Var1,    // ΔV_in ≥ ΔV_out
    Trust1,  // trust_chain = Π trust_i
    Alg1,    // algedonic_decay ≤ exp(-λt)
}

impl InvariantId {
    pub fn as_str(&self) -> &'static str {
        match self {
            InvariantId::Var1 => "VAR-1",
            InvariantId::Trust1 => "TRUST-1",
            InvariantId::Alg1 => "ALG-1",
        }
    }
}

#[derive(Debug, Clone)]
pub struct InvariantResult {
    pub id: InvariantId,
    pub value: f64,
    pub threshold: f64,
    pub pass: bool,
}

/// Rolling window of f64 samples + simple stats.
struct Window {
    samples: VecDeque<f64>,
    capacity: usize,
}

impl Window {
    fn new(cap: usize) -> Self {
        Self { samples: VecDeque::with_capacity(cap), capacity: cap }
    }
    fn push(&mut self, v: f64) {
        if self.samples.len() == self.capacity {
            self.samples.pop_front();
        }
        self.samples.push_back(v);
    }
    fn mean(&self) -> f64 {
        if self.samples.is_empty() { return 0.0; }
        let s: f64 = self.samples.iter().sum();
        s / (self.samples.len() as f64)
    }
    fn stddev(&self) -> f64 {
        let n = self.samples.len();
        if n < 2 { return 0.0; }
        let m = self.mean();
        let var = self.samples.iter().map(|v| (v - m).powi(2)).sum::<f64>() / (n as f64 - 1.0);
        var.sqrt()
    }
    fn len(&self) -> usize { self.samples.len() }
    fn last(&self) -> Option<f64> { self.samples.back().copied() }
}

/// VAR-1 tracker: variety in vs out.
struct VarietyState {
    window: Window,
    consecutive_fail: usize,
    baseline_mean: Option<f64>,
}

/// TRUST-1 tracker: multiplicative chain product.
struct TrustState {
    window: Window,        // composed trust over time
    consecutive_fail: usize,
    threshold: f64,        // chain product threshold (e.g. 0.5)
}

/// ALG-1 tracker: algedonic intensity per recursive level over time.
struct AlgedonicState {
    /// per-level: Some((last_seq, last_ts_ns)) once observed, None otherwise.
    /// Using Option distinguishes "never seen" from "seen at t=0".
    last_seen: Vec<Option<(u64, u128)>>,
    consecutive_fail: usize,
}

/// Public runtime checker. Holds state for all 3 invariants and emits events
/// via the CanonicalTelemetry writer.
pub struct InvariantChecker {
    canonical: CanonicalTelemetry,
    system_id: String,
    inner: Mutex<CheckerInner>,
}

struct CheckerInner {
    var: VarietyState,
    trust: TrustState,
    alg: AlgedonicState,
    /// Window over stasis_cos samples — used to derive baseline for γ.4 algedonic_gate.
    stasis_cos: Window,
}

impl InvariantChecker {
    pub fn new(canonical: CanonicalTelemetry, system_id: String) -> Self {
        Self {
            canonical,
            system_id,
            inner: Mutex::new(CheckerInner {
                var: VarietyState {
                    window: Window::new(WINDOW_SIZE),
                    consecutive_fail: 0,
                    baseline_mean: None,
                },
                trust: TrustState {
                    window: Window::new(WINDOW_SIZE),
                    consecutive_fail: 0,
                    threshold: 0.5,
                },
                alg: AlgedonicState {
                    last_seen: Vec::new(),
                    consecutive_fail: 0,
                },
                stasis_cos: Window::new(WINDOW_SIZE),
            }),
        }
    }

    /// Record an observed variety_delta (ΔV_in - ΔV_out for a regulator step).
    /// VAR-1 passes if value ≥ 0 (variety absorbed ≥ variety emitted).
    pub fn record_variety(&self, delta: f64) -> InvariantResult {
        let mut st = self.inner.lock().expect("invariant lock");
        st.var.window.push(delta);
        let pass = delta >= 0.0;
        let result = InvariantResult {
            id: InvariantId::Var1,
            value: delta,
            threshold: 0.0,
            pass,
        };
        Self::update_fail_counter(&mut st.var.consecutive_fail, pass);
        let mean = st.var.window.mean();
        if st.var.window.len() >= WINDOW_SIZE && st.var.baseline_mean.is_none() {
            st.var.baseline_mean = Some(mean);
        }
        let drift = Self::drift_signal(&st.var.window, st.var.baseline_mean);
        drop(st);
        self.emit_invariant_check(&result);
        if let Some(d) = drift {
            self.emit_drift_alert("VAR-1", &d);
        }
        if !pass && self.check_circuit_breaker(InvariantId::Var1) {
            self.emit_signal_escalated("VAR-1");
        }
        result
    }

    /// Record current composed trust score (trust_chain = Π trust_i over path).
    /// TRUST-1 passes if chain ≥ threshold.
    pub fn record_trust(&self, chain_value: f64) -> InvariantResult {
        let mut st = self.inner.lock().expect("invariant lock");
        st.trust.window.push(chain_value);
        let threshold = st.trust.threshold;
        let pass = chain_value >= threshold;
        let result = InvariantResult {
            id: InvariantId::Trust1,
            value: chain_value,
            threshold,
            pass,
        };
        Self::update_fail_counter(&mut st.trust.consecutive_fail, pass);
        drop(st);
        self.emit_invariant_check(&result);
        if !pass && self.check_circuit_breaker(InvariantId::Trust1) {
            self.emit_signal_escalated("TRUST-1");
        }
        result
    }

    /// Record an algedonic emission for ALG-1 cascade-decay check.
    /// Level is the recursion level of the emitter (0 = innermost, larger = outer).
    /// Returns whether the emission satisfies the decay bound.
    pub fn record_algedonic(&self, level: usize, seq: u64, ts_ns: u128) -> InvariantResult {
        let mut st = self.inner.lock().expect("invariant lock");
        // Ensure last_seen vector covers the level.
        while st.alg.last_seen.len() <= level {
            st.alg.last_seen.push(None);
        }
        let prev = st.alg.last_seen[level];
        let (observed_intensity, bound, dt_sec_for_log) = match prev {
            None => {
                // First emission at this level — passes trivially (no decay constraint yet)
                (0.0, f64::INFINITY, f64::INFINITY)
            }
            Some((prev_seq, prev_ts)) => {
                let dt_sec = (ts_ns.saturating_sub(prev_ts) as f64) / 1e9;
                if dt_sec <= 0.0 {
                    // Same-instant duplicate emission → maximal intensity, fails decay
                    (f64::INFINITY, 0.0, dt_sec)
                } else {
                    let intensity = (seq.saturating_sub(prev_seq) as f64) / dt_sec;
                    let bound_val = (-ALG_LAMBDA * dt_sec).exp();
                    (intensity, bound_val, dt_sec)
                }
            }
        };
        let pass = observed_intensity <= bound;
        let _ = dt_sec_for_log; // available for future log enrichment
        st.alg.last_seen[level] = Some((seq, ts_ns));
        let result = InvariantResult {
            id: InvariantId::Alg1,
            value: observed_intensity,
            threshold: bound,
            pass,
        };
        Self::update_fail_counter(&mut st.alg.consecutive_fail, pass);
        drop(st);
        self.emit_invariant_check(&result);
        if !pass && self.check_circuit_breaker(InvariantId::Alg1) {
            self.emit_signal_escalated("ALG-1");
        }
        result
    }

    /// Record a stasis_cos measurement (used by γ.4 for algedonic_gate baseline).
    pub fn record_stasis_cos(&self, value: f64) {
        let mut st = self.inner.lock().expect("invariant lock");
        st.stasis_cos.push(value);
    }

    /// Return the baseline stasis_cos (rolling mean) for γ.4 algedonic_gate.
    /// None if the window has insufficient data.
    pub fn baseline_stasis_cos(&self) -> Option<f64> {
        let st = self.inner.lock().expect("invariant lock");
        if st.stasis_cos.len() >= WINDOW_SIZE / 2 {
            Some(st.stasis_cos.mean())
        } else {
            None
        }
    }

    /// P.2 — Periodic snapshot of all three invariants emitted as a canonical
    /// `invariant_check` event. Called by the sampler task; never propagates
    /// errors so the cycle continues on transient I/O issues.
    pub fn snapshot_and_emit(&self) -> std::io::Result<String> {
        let st = self.inner.lock().expect("invariant lock");
        let var_n = st.var.window.len();
        let var_mean = st.var.window.mean();
        let var_last = st.var.window.last().unwrap_or(0.0);
        let trust_n = st.trust.window.len();
        let trust_mean = st.trust.window.mean();
        let trust_last = st.trust.window.last().unwrap_or(0.0);
        let stasis_n = st.stasis_cos.len();
        let stasis_mean = st.stasis_cos.mean();
        let stasis_last = st.stasis_cos.last().unwrap_or(0.0);
        drop(st);

        let event = crate::telemetry_canonical::CanonicalEvent {
            ts: String::new(), // emit() fills
            system_id: self.system_id.clone(),
            event_type: "invariant_check".to_string(),
            status: "ok".to_string(),
            signal_status: "resolved".to_string(),
            duration_s: 0.0,
            metrics: serde_json::json!({
                "_note": "P.2 periodic invariant snapshot — VAR-1, TRUST-1 windows + stasis baseline. deep-wiring W4: samples are REAL — VAR-1 = Ashby ΔV_in−ΔV_out over live ingest (Block B) + kernel; TRUST-1 = live kernel trust; stasis = live stasis_cos. (BBH/S1 external variety still pending, but the internal regulator path is no longer synthetic.)",
                "synthetic_load": false,
                "var1_samples": var_n,
                "var1_mean": var_mean,
                "var1_last": var_last,
                "trust1_samples": trust_n,
                "trust1_mean": trust_mean,
                "trust1_last": trust_last,
                "stasis_samples": stasis_n,
                "stasis_mean": stasis_mean,
                "stasis_last": stasis_last,
            }),
            variety_delta: if var_n > 0 { Some(var_last) } else { None },
            trust_score: if trust_n > 0 { Some(trust_last) } else { None },
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        self.canonical.emit(event)
    }

    /// P.2 — Spawn a tokio task that calls snapshot_and_emit every `interval_secs`.
    pub fn start_sampler_task(
        self: std::sync::Arc<Self>,
        interval_secs: u64,
    ) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(interval_secs));
            interval.tick().await; // consume the immediate tick
            loop {
                interval.tick().await;
                if let Err(e) = self.snapshot_and_emit() {
                    eprintln!("[invariants] periodic emit failed: {} (cycle continues)", e);
                }
            }
        })
    }

    fn update_fail_counter(c: &mut usize, pass: bool) {
        if pass { *c = 0 } else { *c += 1 }
    }

    fn check_circuit_breaker(&self, id: InvariantId) -> bool {
        let st = self.inner.lock().expect("invariant lock");
        let c = match id {
            InvariantId::Var1 => st.var.consecutive_fail,
            InvariantId::Trust1 => st.trust.consecutive_fail,
            InvariantId::Alg1 => st.alg.consecutive_fail,
        };
        c >= CB_M
    }

    fn drift_signal(window: &Window, baseline: Option<f64>) -> Option<f64> {
        let baseline = baseline?;
        let stddev = window.stddev();
        let current = window.last()?;
        if stddev == 0.0 { return None; }
        let sigmas = (current - baseline).abs() / stddev;
        if sigmas > DRIFT_K { Some(sigmas) } else { None }
    }

    fn emit_invariant_check(&self, r: &InvariantResult) {
        let event = CanonicalEvent {
            ts: String::new(),
            system_id: self.system_id.clone(),
            event_type: "invariant_check".to_string(),
            status: if r.pass { "ok" } else { "warn" }.to_string(),
            signal_status: "resolved".to_string(),
            duration_s: 0.0,
            metrics: json!({
                "invariant_id": r.id.as_str(),
                "value": r.value,
                "threshold": r.threshold,
                "pass": r.pass,
            }),
            variety_delta: if r.id == InvariantId::Var1 { Some(r.value) } else { None },
            trust_score: if r.id == InvariantId::Trust1 { Some(r.value) } else { None },
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        let _ = self.canonical.emit(event);
    }

    fn emit_drift_alert(&self, invariant_id: &str, delta_sigmas: &f64) {
        let event = CanonicalEvent {
            ts: String::new(),
            system_id: self.system_id.clone(),
            event_type: "drift_alert".to_string(),
            status: "warn".to_string(),
            signal_status: "pending".to_string(),
            duration_s: 0.0,
            metrics: json!({
                "invariant_id": invariant_id,
                "delta_sigmas": delta_sigmas,
                "window_size": WINDOW_SIZE,
            }),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        let _ = self.canonical.emit(event);
    }

    fn emit_signal_escalated(&self, invariant_id: &str) {
        let event = CanonicalEvent {
            ts: String::new(),
            system_id: self.system_id.clone(),
            event_type: "signal_escalated".to_string(),
            status: "error".to_string(),
            signal_status: "escalated".to_string(),
            duration_s: 0.0,
            metrics: json!({
                "signal_id": format!("invariant-{}", invariant_id),
                "urgency": "HIGH",
                "resolve_attempted": false,
                "reason": format!("Circuit breaker tripped: {} consecutive failures of {}", CB_M, invariant_id),
            }),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        let _ = self.canonical.emit(event);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::telemetry_canonical::CanonicalTelemetry;
    use std::fs;

    fn make_checker(test_name: &str) -> InvariantChecker {
        let base = std::env::temp_dir().join(format!("vsf-invar-{}-{}", test_name, std::process::id()));
        let tmpfs = base.join("tmpfs");
        let disk = base.join("disk");
        let _ = fs::create_dir_all(&tmpfs);
        let _ = fs::create_dir_all(&disk);
        let canon = CanonicalTelemetry::with_roots(
            test_name,
            tmpfs.to_str().unwrap(),
            disk.to_str().unwrap(),
        ).unwrap();
        InvariantChecker::new(canon, test_name.to_string())
    }

    #[test]
    fn var1_passes_when_input_geq_output() {
        let c = make_checker("var1_pass");
        let r = c.record_variety(0.5);
        assert!(r.pass);
    }

    #[test]
    fn var1_fails_when_output_exceeds_input() {
        let c = make_checker("var1_fail");
        let r = c.record_variety(-0.2);
        assert!(!r.pass);
    }

    #[test]
    fn trust1_passes_above_threshold() {
        let c = make_checker("trust1_pass");
        let r = c.record_trust(0.8);
        assert!(r.pass);
        assert_eq!(r.threshold, 0.5);
    }

    #[test]
    fn trust1_fails_below_threshold() {
        let c = make_checker("trust1_fail");
        let r = c.record_trust(0.2);
        assert!(!r.pass);
    }

    #[test]
    fn alg1_first_emission_passes() {
        let c = make_checker("alg1_first");
        let r = c.record_algedonic(0, 1, 1_000_000_000);
        assert!(r.pass); // dt=∞ → always passes initial
    }

    #[test]
    fn alg1_burst_violates_decay() {
        let c = make_checker("alg1_burst");
        // First emission at t=0
        let _ = c.record_algedonic(0, 1, 0);
        // Second emission 1µs later with seq +10 → very high intensity
        let r2 = c.record_algedonic(0, 11, 1_000); // 1µs = 1000ns
        assert!(!r2.pass); // intensity (10 per µs) >> exp(-0.1 * 1e-6) ≈ 1
    }

    #[test]
    fn circuit_breaker_after_M_failures() {
        let c = make_checker("cb_trip");
        for _ in 0..CB_M {
            c.record_variety(-1.0);
        }
        // Next failure → should trip
        let tripped = c.check_circuit_breaker(InvariantId::Var1);
        assert!(tripped);
    }

    #[test]
    fn baseline_stasis_cos_requires_window() {
        let c = make_checker("baseline");
        // Below half window: returns None
        for i in 0..(WINDOW_SIZE / 2 - 1) {
            c.record_stasis_cos(0.9 + (i as f64) * 0.0001);
        }
        assert!(c.baseline_stasis_cos().is_none());
        // Push more
        for i in 0..(WINDOW_SIZE / 2 + 5) {
            c.record_stasis_cos(0.9 + (i as f64) * 0.0001);
        }
        let b = c.baseline_stasis_cos();
        assert!(b.is_some());
        assert!(b.unwrap() > 0.85 && b.unwrap() < 1.0);
    }
}
