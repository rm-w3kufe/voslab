#!/usr/bin/env python3
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
    acknowledged: bool = False


# ─── Alert Monitor ────────────────────────────────────────────────────────────

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

    def _emit(self, level: str, alert_type: str, source: str, detail: str, evidence: Optional[Dict] = None) -> Alert:
        """Create and persist an alert."""
        alert = Alert(
            alert_id=f"alert-{int(time.time() * 1000)}-{hash(alert_type) % 10000:04d}",
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            level=level,
            alert_type=alert_type,
            source=source,
            detail=detail,
            evidence=evidence or {},
        )
        self._alerts_file.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self._alerts_file), "a") as f:
            f.write(json.dumps(asdict(alert), default=str) + "\n")
        return alert

    def check(self) -> List[Alert]:
        """Run all checks and return new alerts."""
        alerts = []
        alerts.extend(self._check_latency_spike())
        alerts.extend(self._check_failure_burst())
        alerts.extend(self._check_attestation_failures())
        alerts.extend(self._check_health_degradation())
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
                ))
        return alerts

    def _check_failure_burst(self) -> List[Alert]:
        """Check for burst of failures in recent window."""
        alerts = []
        window = self._thresholds["failure_burst_window"]
        threshold = self._thresholds["failure_burst_count"]
        traces = self._read_traces(n=window * 2)

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

        # Compare first 3 entries avg pass_rate vs last 3 entries avg
        def _pass_rate(entry):
            traces = entry.get("traces", {})
            truths = traces.get("truths", {})
            total = traces.get("total", sum(truths.values()))
            if total == 0:
                return 1.0
            return truths.get("Truth.TRUE", 0) / total

        first_3_avg = sum(_pass_rate(e) for e in entries[:3]) / 3
        last_3_avg = sum(_pass_rate(e) for e in entries[-3:]) / 3
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
        traces_file = Path(tmp) / "tree_traces.jsonl"
        traces_file.parent.mkdir(parents=True, exist_ok=True)
        trace = {
            "trace_id": "t1", "ts": "2026-01-01T00:00:00Z", "session_id": "s1",
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
        monitor2._health_file = clean_tmp / "nonexistent_health.jsonl"  # no health data
        alerts3 = monitor2.check()
        check("clean data → no alerts", len(alerts3) == 0, str([a.alert_type for a in alerts3]))

        # 4. Alert persistence
        alerts_file = Path(tmp) / "alerts.jsonl"
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
                "ts": f"2026-01-0{i}T00:00:00Z", "session_id": f"s{i}",
                "traces": {"total": 10, "truths": {"Truth.TRUE": 9}},
                "attestations": {}, "patterns": [],
            }))
        # Last 3: low pass rate
        for i in range(3):
            health_entries.append(json.dumps({
                "ts": f"2026-01-0{i+3}T00:00:00Z", "session_id": f"s{i+3}",
                "traces": {"total": 10, "truths": {"Truth.TRUE": 4}},
                "attestations": {}, "patterns": [],
            }))
        health_file.write_text("\n".join(health_entries) + "\n")
        monitor4 = AlertMonitor({"health_degradation_threshold": 0.05})
        monitor4._state_dir = Path(tmp)
        alerts4 = monitor4._check_health_degradation()
        check("health_degradation detected", len(alerts4) == 1 and alerts4[0].alert_type == "health_degradation")

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
