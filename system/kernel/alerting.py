#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/capa4-alerting-feedback-v1/capa4_alerting_feedback.vsm
# route: backbone (librería Capa-4: feedback_loop/audit_pipeline/learn_budget/vosi)
"""alerting — Capa 4: local alerting for anomaly detection.

Monitors tree traces, attestations, and health history for anomalies.
Produces alerts to state/rsi/alerts.jsonl (append-only).

Alert levels:
  - info: informational, no action needed
  - warning: anomaly detected, investigate
  - critical: system health at risk, immediate attention

Alert types:
  - latency_spike: evaluation latency >threshold
  - failure_burst: N failures in short window
  - attestation_fail: signature verification failed
  - pattern_shift: new pattern emerged or pattern frequency changed
  - health_degradation: pass_rate dropping over time
  - abstention_collapse: sustained zero-abstention window (§6.3 F4.2 —
    compliance-bias signature: no UNKNOWN/uncertified verdicts for long)

Usage:
    # As module:
    from alerting import AlertMonitor
    monitor = AlertMonitor()
    alerts = monitor.check()

    # CLI:
    python3 alerting.py --check
    python3 alerting.py --recent 10
    python3 alerting.py --selftest
"""
import json
import logging
import os
import sys
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

_logger = logging.getLogger("alerting")


def _voslab_path() -> Path:
    return Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))


# ─── Thresholds ───────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "latency_spike_ms": 1200,        # 3x p99 (F2.1 baseline: p99≈400ms)
    "latency_sustained_ms": 500,     # Avg over 10 evals >500ms
    "failure_burst_count": 5,        # ≥5 failures in 10 evals
    "failure_burst_window": 10,      # Window size for burst detection
    "attestation_fail_count": 3,     # ≥3 attestation failures
    "pattern_shift_min_occurrences": 5,  # Pattern must appear ≥5 times
    "health_degradation_threshold": 0.1, # Pass rate drop >10%
    "abstention_window": 200,     # Traces per rolling abstention window
    "abstention_sustain_h": 24.0, # Window must span ≥ this to be "sustained"
}


# ─── Alert Data ───────────────────────────────────────────────────────────────

@dataclass
class Alert:
    """A single alert."""
    alert_id: str
    ts: str
    level: str          # "info", "warning", "critical"
    alert_type: str     # "latency_spike", "failure_burst", etc.
    source: str         # What triggered it (predicate name, session, etc.)
    detail: str         # Human-readable description
    evidence: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None   # Correlation: which trace triggered this
    session_id: Optional[str] = None  # Correlation: which session
    acknowledged: bool = False


# ─── Alert Monitor ────────────────────────────────────────────────────────────

from health_semantics import (  # noqa: E402  (trace health semantics, R10)
    NON_OPERATIONAL,
    classify_trace,
)


def _parse_ts(value: Any) -> Optional[datetime]:
    """ISO-8601 ('Z' or offset) → aware datetime; None if unparsable."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def abstention_window_stats(traces: List[dict], window: int,
                            sustain_h: float) -> Dict[str, Any]:
    """Rolling-window abstention census + fire verdict (§6.3, F4.2).

    Abstention = the evaluation declined a definitive certified verdict:
    final_truth UNKNOWN or final_certified False. A SUSTAINED zero rate
    (window full, spanning >= sustain_h, zero abstentions) is the
    compliance-bias signature — the system stopped being able to say
    "I don't know" (gates captured). Pure (R10): counts + wall-clock
    span from trace timestamps; shared by _check_abstention_collapse
    and scripts/state/monitoring/abstention_audit.py (single source).
    """
    w = list(traces[-window:]) if len(traces) > window else list(traces)
    truths: Counter = Counter()
    abstentions = 0
    certified_true = 0
    for t in w:
        truth = str(t.get("final_truth", ""))
        truths[truth] += 1
        if "UNKNOWN" in truth or t.get("final_certified") is False:
            abstentions += 1
        if t.get("final_certified") is True:
            certified_true += 1

    # Window time span (first → last ts); any unparsable ts → 0 (no fire).
    span_h = 0.0
    if len(w) >= 2:
        first = _parse_ts(w[0].get("ts"))
        last = _parse_ts(w[-1].get("ts"))
        if first is not None and last is not None and last >= first:
            span_h = (last - first).total_seconds() / 3600.0

    # Most recent abstention across everything read (evidence context).
    last_abstention_ts = None
    for t in reversed(traces):
        truth = str(t.get("final_truth", ""))
        if "UNKNOWN" in truth or t.get("final_certified") is False:
            last_abstention_ts = t.get("ts")
            break

    enough = len(w) >= window
    would_fire = bool(enough and span_h >= sustain_h and abstentions == 0)
    return {
        "window": window,
        "samples": len(w),
        "span_h": round(span_h, 2),
        "sustain_h": sustain_h,
        "abstentions": abstentions,
        "certified_true": certified_true,
        "truths": dict(truths),
        "enough_samples": enough,
        "would_fire": would_fire,
        "last_abstention_ts": last_abstention_ts,
    }


class AlertMonitor:
    """Monitors system health and produces alerts."""

    def __init__(self, thresholds: Optional[Dict] = None):
        self._state_dir = _voslab_path() / "state" / "rsi"
        self._alerts_file = self._state_dir / "alerts.jsonl"
        self._health_file = _voslab_path() / "state" / "health_history.jsonl"
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def _read_traces(self, n: Optional[int] = None) -> List[dict]:
        """Read last N traces from JSONL log."""
        trace_file = self._state_dir / "tree_traces.jsonl"
        if not trace_file.exists():
            return []
        lines = trace_file.read_text().strip().split("\n")
        traces = []
        for line in lines[-n:] if n else lines:
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                _logger.debug("trace entry skipped: %s", e)
                continue
        return traces

    def _read_alerts(self) -> List[dict]:
        """Read existing alerts."""
        if not self._alerts_file.exists():
            return []
        alerts = []
        for line in self._alerts_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                _logger.debug("alert entry skipped: %s", e)
                continue
        return alerts

    def _emit(self, level: str, alert_type: str, source: str, detail: str,
              evidence: Optional[Dict] = None, trace_id: Optional[str] = None,
              session_id: Optional[str] = None) -> Alert:
        """Create and persist an alert."""
        alert = Alert(
            alert_id=f"alert-{int(time.time() * 1000)}-{hash(alert_type) % 10000:04d}",
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            level=level,
            alert_type=alert_type,
            source=source,
            detail=detail,
            evidence=evidence or {},
            trace_id=trace_id,
            session_id=session_id,
        )
        self._alerts_file.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self._alerts_file), "a") as f:
            f.write(json.dumps(asdict(alert), default=str) + "\n")
        # Rotate if too large (keep last 5000)
        try:
            lines = self._alerts_file.read_text().strip().split("\n")
            if len(lines) > 10000:
                self._alerts_file.write_text("\n".join(lines[-5000:]) + "\n")
        except OSError as e:
            _logger.debug("alert rotation failed: %s", e)
        return alert

    def check(self) -> List[Alert]:
        """Run all checks and return new alerts."""
        alerts = []
        alerts.extend(self._check_latency_spike())
        alerts.extend(self._check_failure_burst())
        alerts.extend(self._check_attestation_failures())
        alerts.extend(self._check_health_degradation())
        alerts.extend(self._check_abstention_collapse())
        return alerts

    def _check_latency_spike(self) -> List[Alert]:
        """Check for single evaluation latency spikes."""
        alerts = []
        traces = self._read_traces(n=50)
        threshold = self._thresholds["latency_spike_ms"]

        for trace in traces:
            latency = trace.get("total_latency_ms", 0)
            if latency > threshold:
                alerts.append(self._emit(
                    level="warning",
                    alert_type="latency_spike",
                    source=trace.get("final_source", "unknown"),
                    detail=f"Latency {latency:.0f}ms > {threshold}ms threshold",
                    evidence={
                        "trace_id": trace.get("trace_id"),
                        "latency_ms": latency,
                        "threshold_ms": threshold,
                        "tree_shape": trace.get("tree_shape", ""),
                    },
                    trace_id=trace.get("trace_id"),
                    session_id=trace.get("session_id"),
                ))
        return alerts

    def _check_failure_burst(self) -> List[Alert]:
        """Check for burst of failures in recent window.

        Window counts OPERATIONAL evaluations only (health_semantics):
        designed-benign FALSEs (type_prefix misses, task_* observations,
        gate verdicts) are not failures and must not fire bursts.
        """
        alerts = []
        window = self._thresholds["failure_burst_window"]
        threshold = self._thresholds["failure_burst_count"]
        traces = [t for t in self._read_traces(n=window * 5)
                  if classify_trace(t) != NON_OPERATIONAL]

        if len(traces) < window:
            return alerts

        # Check the last `window` traces
        recent = traces[-window:]
        failures = [t for t in recent if "FALSE" in t.get("final_truth", "") or "ERROR" in t.get("final_truth", "")]

        if len(failures) >= threshold:
            sources = Counter(t.get("final_source", "unknown") for t in failures)
            top_source = sources.most_common(1)[0] if sources else ("unknown", 0)
            alerts.append(self._emit(
                level="warning",
                alert_type="failure_burst",
                source=top_source[0],
                detail=f"{len(failures)}/{window} recent evaluations failed (threshold: {threshold})",
                evidence={
                    "failure_count": len(failures),
                    "window_size": window,
                    "threshold": threshold,
                    "top_sources": dict(sources.most_common(5)),
                },
            ))
        return alerts

    def _check_attestation_failures(self) -> List[Alert]:
        """Check for attestation verification failures."""
        alerts = []
        threshold = self._thresholds["attestation_fail_count"]

        try:
            from tree_trace_attest import AttestationVerifier
            verifier = AttestationVerifier()
        except Exception as e:
            _logger.debug("attestation verifier unavailable: %s", e)
            return alerts

        att_dir = self._state_dir / "attestations"
        if not att_dir.exists():
            return alerts

        failures = 0
        failure_details = []
        for f in sorted(att_dir.glob("*.attest.json"))[-20:]:  # Last 20
            try:
                att = json.load(open(f))
                if "trace_id" in att:
                    r = verifier.verify_trace(att)
                    if not r["ok"]:
                        failures += 1
                        failure_details.append({"file": f.name, "reason": r["reason"]})
            except (json.JSONDecodeError, OSError) as e:
                _logger.debug("attestation parse failed for %s: %s", f.name, e)
                failures += 1
                failure_details.append({"file": f.name, "reason": "parse error"})

        if failures >= threshold:
            alerts.append(self._emit(
                level="critical",
                alert_type="attestation_fail",
                source="attestations",
                detail=f"{failures} attestation verification failures (threshold: {threshold})",
                evidence={
                    "failure_count": failures,
                    "threshold": threshold,
                    "details": failure_details[:5],
                },
            ))
        return alerts

    def _check_health_degradation(self) -> List[Alert]:
        """Check for health pass_rate degradation over time."""
        alerts = []
        if not self._health_file.exists():
            return alerts

        entries = []
        for line in self._health_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                _logger.debug("health entry skipped: %s", e)
                continue

        if len(entries) < 3:
            return alerts

        # P-EV-R4 (FND-HEALTH-H1-SCOPE): solo comparar entradas del MISMO
        # scope — promediar "session" con "all_time" (o legacy sin scope)
        # produce falsos degradados. Sin >=3 entradas session-scoped no hay
        # señal (silencio honesto, R9: sin concesión ni alerta inventada).
        session_entries = [e for e in entries if e.get("scope") == "session"]
        if len(session_entries) < 3:
            return alerts

        # Compare first 3 session-scope entries avg pass_rate vs last 3
        def _pass_rate(entry):
            traces = entry.get("traces", {})
            # New entries carry operational_truths (benign designed FALSEs
            # excluded); legacy entries fall back to raw truths + total.
            truths = traces.get("operational_truths")
            if truths:
                total = sum(truths.values())
            else:
                truths = traces.get("truths", {})
                total = traces.get("total", sum(truths.values()))
            if total == 0:
                return 1.0
            return truths.get("Truth.TRUE", 0) / total

        first_3_avg = sum(_pass_rate(e) for e in session_entries[:3]) / 3
        last_3_avg = sum(_pass_rate(e) for e in session_entries[-3:]) / 3
        degradation = first_3_avg - last_3_avg

        threshold = self._thresholds["health_degradation_threshold"]
        if degradation > threshold:
            alerts.append(self._emit(
                level="warning",
                alert_type="health_degradation",
                source="health_history",
                detail=f"Pass rate dropped {degradation:.1%} (from {first_3_avg:.1%} to {last_3_avg:.1%})",
                evidence={
                    "first_3_avg": round(first_3_avg, 3),
                    "last_3_avg": round(last_3_avg, 3),
                    "degradation": round(degradation, 3),
                    "threshold": threshold,
                },
            ))
        return alerts

    def _check_abstention_collapse(self) -> List[Alert]:
        """Sustained zero-abstention window (§6.3, F4.2 — regulation alarm).

        Fires when the rolling window of evaluations contains ZERO
        abstentions (no UNKNOWN roots, no uncertified verdicts) across a
        span >= abstention_sustain_h: the compliance-bias / gates-captured
        signature — the system answers everything definitively and can no
        longer say "I don't know". Emits ONE algedonic signal per episode:
        dedup suppresses while a same-type alert is unacked or younger
        than 24h (algedonic-queue contract — unacked >48h fails a gate;
        don't pile duplicates). Once acked and older than 24h, a still-
        sustained window may signal again (fresh observation).
        """
        alerts = []
        window = self._thresholds["abstention_window"]
        sustain_h = self._thresholds["abstention_sustain_h"]
        traces = self._read_traces(n=window * 5)
        stats = abstention_window_stats(traces, window, sustain_h)
        if not stats["would_fire"]:
            return alerts

        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                               time.gmtime(time.time() - 24 * 3600))
        for existing in self._read_alerts():
            if existing.get("alert_type") != "abstention_collapse":
                continue
            if (not existing.get("acknowledged")
                    or str(existing.get("ts", "")) >= cutoff):
                return alerts  # episode already signalled

        alerts.append(self._emit(
            level="warning",
            alert_type="abstention_collapse",
            source="abstention-audit",
            detail=(f"0 abstentions in last {stats['samples']} evaluations "
                    f"over {stats['span_h']}h (sustain {sustain_h}h) — "
                    f"compliance-bias signature"),
            evidence=stats,
        ))
        return alerts

    def recent(self, n: int = 10) -> List[dict]:
        """Get last N alerts."""
        return self._read_alerts()[-n:]

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert by ID."""
        alerts = self._read_alerts()
        updated = False
        for alert in alerts:
            if alert.get("alert_id") == alert_id:
                alert["acknowledged"] = True
                updated = True
        if updated:
            self._alerts_file.write_text(
                "\n".join(json.dumps(a, default=str) for a in alerts) + "\n"
            )
        return updated

    def acknowledge_many(self, alert_ids) -> int:
        """Acknowledge N alerts in a single read+write (EP-0/F3).

        acknowledge() rewrites the whole file per call — fine for one
        alert, O(n^2) for a legacy backlog (1144 unacked on 2026-09-27).
        Same storage, same JSON contract, one pass. Returns acked count.
        """
        wanted = set(alert_ids)
        if not wanted:
            return 0
        alerts = self._read_alerts()
        acked = 0
        for alert in alerts:
            if alert.get("alert_id") in wanted and not alert.get("acknowledged"):
                alert["acknowledged"] = True
                acked += 1
        if acked:
            self._alerts_file.write_text(
                "\n".join(json.dumps(a, default=str) for a in alerts) + "\n"
            )
        return acked


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if "--selftest" in sys.argv:
        return _selftest()

    if "--check" in sys.argv:
        monitor = AlertMonitor()
        alerts = monitor.check()
        if not alerts:
            print("No new alerts")
        else:
            print(f"{len(alerts)} new alert(s):")
            for a in alerts:
                icon = {"info": "ℹ", "warning": "⚠", "critical": "🚨"}.get(a.level, "?")
                print(f"  {icon} [{a.level}] {a.alert_type}: {a.detail}")
        return 0

    if "--recent" in sys.argv:
        idx = sys.argv.index("--recent")
        n = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 10
        monitor = AlertMonitor()
        alerts = monitor.recent(n)
        if not alerts:
            print("No alerts")
        else:
            print(f"Last {len(alerts)} alert(s):")
            for a in alerts:
                icon = {"info": "ℹ", "warning": "⚠", "critical": "🚨"}.get(a.level, "?")
                ack = " [ack]" if a.get("acknowledged") else ""
                print(f"  {icon} [{a.level}] {a.alert_type}: {a.detail}{ack}")
        return 0

    print("usage: alerting.py [--check | --recent N | --selftest]")
    return 2


def _selftest():
    """Test alert monitoring with synthetic data."""
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp(prefix="alert-test-")
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    try:
        # 1. Latency spike detection
        monitor = AlertMonitor({"latency_spike_ms": 1000})
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # never emit to production
        traces_file = Path(tmp) / "tree_traces.jsonl"
        traces_file.parent.mkdir(parents=True, exist_ok=True)
        trace = {
            "trace_id": "t1", "ts": "2026-01-01T00:00:00Z", "session_id": "s1",  # hardcoded-allow: synthetic selftest fixture
            "tree_shape": "p", "final_truth": "Truth.TRUE", "final_certified": True,
            "final_source": "fast_pred", "total_nodes": 1, "predicates_evaluated": 1,
            "operators_evaluated": 0, "total_latency_ms": 50, "context_keys": [],
            "attestation": None, "nodes": [],
        }
        slow_trace = dict(trace, trace_id="t2", total_latency_ms=2000, final_source="slow_pred")
        traces_file.write_text(json.dumps(trace) + "\n" + json.dumps(slow_trace) + "\n")
        monitor._state_dir = Path(tmp)
        alerts = monitor._check_latency_spike()
        check("latency_spike detected", len(alerts) == 1 and alerts[0].alert_type == "latency_spike")

        # 2. Failure burst detection
        burst_traces = []
        for i in range(8):
            burst_traces.append(json.dumps(dict(trace, trace_id=f"t{i}", final_truth="Truth.FALSE", final_source=f"fail_{i}", total_latency_ms=10)))
        for i in range(2):
            burst_traces.append(json.dumps(dict(trace, trace_id=f"t_ok{i}", final_truth="Truth.TRUE", final_source="ok", total_latency_ms=10)))
        traces_file.write_text("\n".join(burst_traces) + "\n")
        alerts2 = monitor._check_failure_burst()
        check("failure_burst detected", len(alerts2) == 1 and alerts2[0].alert_type == "failure_burst")

        # 3. No alert on clean data (use isolated temp dir)
        clean_tmp = Path(tmp) / "clean"
        clean_tmp.mkdir()
        clean_traces = []
        for i in range(10):
            clean_traces.append(json.dumps(dict(trace, trace_id=f"t_clean{i}", final_truth="Truth.TRUE", final_source=f"p{i}", total_latency_ms=50)))
        (clean_tmp / "tree_traces.jsonl").write_text("\n".join(clean_traces) + "\n")
        monitor2 = AlertMonitor()
        monitor2._state_dir = clean_tmp
        monitor2._alerts_file = clean_tmp / "alerts.jsonl"  # never emit to production
        monitor2._health_file = clean_tmp / "nonexistent_health.jsonl"  # no health data
        alerts3 = monitor2.check()
        check("clean data → no alerts", len(alerts3) == 0, str([a.alert_type for a in alerts3]))

        # 4. Alert persistence (isolated file: cases 1-2 wrote to
        # tmp/alerts.jsonl — sharing it made json.loads see 2+ lines)
        persist_dir = Path(tmp) / "persist"
        persist_dir.mkdir()
        alerts_file = persist_dir / "alerts.jsonl"
        monitor3 = AlertMonitor()
        monitor3._alerts_file = alerts_file
        alert = monitor3._emit("warning", "test_type", "test_source", "test detail", {"key": "val"})
        check("alert persisted", alerts_file.exists())
        loaded = json.loads(alerts_file.read_text().strip())
        check("alert readable", loaded["alert_type"] == "test_type")
        check("alert has evidence", loaded["evidence"]["key"] == "val")

        # 5. Acknowledge
        ok = monitor3.acknowledge(alert.alert_id)
        check("acknowledge returns True", ok)
        loaded2 = json.loads(alerts_file.read_text().strip())
        check("alert acknowledged", loaded2["acknowledged"] is True)

        # 6. Recent alerts
        recent = monitor3.recent(5)
        check("recent alerts", len(recent) == 1)

        # 7. Health degradation detection
        health_file = Path(tmp) / "health_history.jsonl"
        health_entries = []
        # First 3: high pass rate
        for i in range(3):
            health_entries.append(json.dumps({
                "ts": f"2026-01-0{i}T00:00:00Z", "session_id": f"s{i}",  # hardcoded-allow: synthetic selftest fixture
                "traces": {"total": 10, "truths": {"Truth.TRUE": 9}},
                "attestations": {}, "patterns": [],
            }))
        # Last 3: low pass rate
        for i in range(3):
            health_entries.append(json.dumps({
                "ts": f"2026-01-0{i+3}T00:00:00Z", "session_id": f"s{i+3}",  # hardcoded-allow: synthetic selftest fixture
                "traces": {"total": 10, "truths": {"Truth.TRUE": 4}},
                "attestations": {}, "patterns": [],
            }))
        health_file.write_text("\n".join(health_entries) + "\n")
        monitor4 = AlertMonitor({"health_degradation_threshold": 0.05})
        monitor4._state_dir = Path(tmp)
        alerts4 = monitor4._check_health_degradation()
        check("health_degradation detected", len(alerts4) == 1 and alerts4[0].alert_type == "health_degradation")

        # 8. Abstention collapse: full certified window spanning >24h
        # fires once (dedup on rerun); an uncertified verdict keeps quiet.
        abs_dir = Path(tmp) / "abs"
        abs_dir.mkdir()
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)  # hardcoded-allow: synthetic selftest fixture
        coll = []
        for i in range(200):
            ts = (epoch + timedelta(hours=i * 2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            coll.append(json.dumps(dict(trace, trace_id=f"ab{i}", ts=ts,
                                        final_truth="Truth.TRUE",
                                        final_certified=True,
                                        total_latency_ms=5)))
        (abs_dir / "tree_traces.jsonl").write_text("\n".join(coll) + "\n")
        m5 = AlertMonitor()
        m5._state_dir = abs_dir
        m5._alerts_file = abs_dir / "alerts.jsonl"  # never emit to production
        a5 = m5._check_abstention_collapse()
        check("abstention_collapse detected",
              len(a5) == 1 and a5[0].alert_type == "abstention_collapse")
        a5b = m5._check_abstention_collapse()
        check("abstention_collapse deduped", len(a5b) == 0)
        coll2 = list(coll)
        last = json.loads(coll2[199])
        last["final_certified"] = False
        coll2[199] = json.dumps(last)
        (abs_dir / "tree_traces.jsonl").write_text("\n".join(coll2) + "\n")
        m6 = AlertMonitor()
        m6._state_dir = abs_dir
        m6._alerts_file = abs_dir / "alerts2.jsonl"  # never emit to production
        a6 = m6._check_abstention_collapse()
        check("abstention quiet with uncertified verdict", len(a6) == 0)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    print("alerting --selftest")
    for n, ok, d in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else ""))
    print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
