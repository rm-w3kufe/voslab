#!/usr/bin/env python3
"""test_alerting.py — Tests for Capa 4: Alerting."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerting import AlertMonitor, Alert, DEFAULT_THRESHOLDS


def _make_trace(**overrides):
    """Create a minimal trace dict."""
    base = {
        "trace_id": "t1", "ts": "2026-01-01T00:00:00Z", "session_id": "s1",
        "tree_shape": "p", "final_truth": "Truth.TRUE", "final_certified": True,
        "final_source": "pred", "total_nodes": 1, "predicates_evaluated": 1,
        "operators_evaluated": 0, "total_latency_ms": 50, "context_keys": [],
        "attestation": None, "nodes": [],
    }
    base.update(overrides)
    return base


def test_latency_spike():
    """Detects single evaluation > threshold."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"latency_spike_ms": 1000})
        monitor._state_dir = Path(tmp)
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # no leak to production
        traces = [_make_trace(total_latency_ms=50), _make_trace(trace_id="t2", total_latency_ms=2000)]
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor._check_latency_spike()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "latency_spike"
        assert "2000ms" in alerts[0].detail
        print("PASS: test_latency_spike")
    return True


def test_no_latency_spike_below_threshold():
    """No alert when all latencies below threshold."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"latency_spike_ms": 1000})
        monitor._state_dir = Path(tmp)
        traces = [_make_trace(total_latency_ms=100), _make_trace(trace_id="t2", total_latency_ms=500)]
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor._check_latency_spike()
        assert len(alerts) == 0
        print("PASS: test_no_latency_spike_below_threshold")
    return True


def test_failure_burst():
    """Detects ≥N failures in window."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"failure_burst_count": 5, "failure_burst_window": 10})
        monitor._state_dir = Path(tmp)
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # no leak to production
        traces = [_make_trace(trace_id=f"t{i}", final_truth="Truth.FALSE", final_source=f"fail_{i}")
                  for i in range(7)]
        traces += [_make_trace(trace_id=f"t_ok{i}", final_truth="Truth.TRUE") for i in range(3)]
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor._check_failure_burst()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "failure_burst"
        assert "7/10" in alerts[0].detail
        print("PASS: test_failure_burst")
    return True


def test_no_failure_burst_below_threshold():
    """No alert when failures below threshold."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"failure_burst_count": 5, "failure_burst_window": 10})
        monitor._state_dir = Path(tmp)
        traces = [_make_trace(trace_id=f"t{i}", final_truth="Truth.FALSE" if i < 3 else "Truth.TRUE")
                  for i in range(10)]
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor._check_failure_burst()
        assert len(alerts) == 0
        print("PASS: test_no_failure_burst_below_threshold")
    return True


def test_failure_burst_ignores_benign_false():
    """Designed-benign FALSEs must not fire a failure burst (1b, 2026-10-05)."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"failure_burst_count": 5, "failure_burst_window": 10})
        monitor._state_dir = Path(tmp)
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # no leak to production
        # 12 FALSE traces, all benign sources: classification misses + gate verdicts
        traces = [_make_trace(trace_id=f"t{i}", final_truth="Truth.FALSE",
                              final_source="type_prefix" if i % 2 else "action_forbidden")
                  for i in range(12)]
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor._check_failure_burst()
        assert len(alerts) == 0, f"benign FALSEs must not burst: {[a.detail for a in alerts]}"
        print("PASS: test_failure_burst_ignores_benign_false")
    return True


def test_alert_persistence():
    """Alerts append to alerts.jsonl."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor()
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"
        a1 = monitor._emit("warning", "test", "src", "detail1")
        a2 = monitor._emit("critical", "test2", "src2", "detail2")
        assert monitor._alerts_file.exists()
        lines = monitor._alerts_file.read_text().strip().split("\n")
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        assert e1["alert_id"] == a1.alert_id
        assert e1["level"] == "warning"
        e2 = json.loads(lines[1])
        assert e2["level"] == "critical"
        print("PASS: test_alert_persistence")
    return True


def test_acknowledge():
    """Acknowledge marks alert as read."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor()
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"
        alert = monitor._emit("info", "test", "src", "detail")
        assert not alert.acknowledged
        ok = monitor.acknowledge(alert.alert_id)
        assert ok
        loaded = json.loads(monitor._alerts_file.read_text().strip())
        assert loaded["acknowledged"] is True
        # Non-existent ID returns False
        assert not monitor.acknowledge("nonexistent-id")
        print("PASS: test_acknowledge")
    return True


def test_recent_alerts():
    """Recent returns last N alerts."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor()
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"
        for i in range(5):
            monitor._emit("info", f"t{i}", "src", f"detail{i}")
        recent = monitor.recent(3)
        assert len(recent) == 3
        assert recent[0]["alert_type"] == "t2"
        print("PASS: test_recent_alerts")
    return True


def test_health_degradation():
    """Detects pass rate degradation over time."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor({"health_degradation_threshold": 0.05})
        monitor._health_file = Path(tmp) / "health.jsonl"
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # no leak to production
        entries = []
        for i in range(3):
            entries.append(json.dumps({
                "ts": f"2026-01-0{i}T00:00:00Z", "session_id": f"s{i}",
                "traces": {"total": 10, "truths": {"Truth.TRUE": 9}},
                "attestations": {}, "patterns": [],
            }))
        for i in range(3):
            entries.append(json.dumps({
                "ts": f"2026-01-0{i+3}T00:00:00Z", "session_id": f"s{i+3}",
                "traces": {"total": 10, "truths": {"Truth.TRUE": 4}},
                "attestations": {}, "patterns": [],
            }))
        monitor._health_file.write_text("\n".join(entries) + "\n")
        alerts = monitor._check_health_degradation()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "health_degradation"
        print("PASS: test_health_degradation")
    return True


def test_clean_system_no_alerts():
    """Clean system produces no alerts."""
    with tempfile.TemporaryDirectory() as tmp:
        monitor = AlertMonitor()
        monitor._state_dir = Path(tmp)
        monitor._alerts_file = Path(tmp) / "alerts.jsonl"  # no leak to production
        monitor._health_file = Path(tmp) / "nonexistent.jsonl"
        # Mostly TRUE (1 FALSE out of 10 = 10% failure, below burst threshold of 5)
        traces = [_make_trace(trace_id=f"t{i}", final_truth="Truth.TRUE",
                              total_latency_ms=50) for i in range(9)]
        traces.append(_make_trace(trace_id="t_fail", final_truth="Truth.FALSE", total_latency_ms=50))
        (Path(tmp) / "tree_traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces))
        alerts = monitor.check()
        assert len(alerts) == 0, f"Unexpected alerts: {[a.alert_type for a in alerts]}"
        print("PASS: test_clean_system_no_alerts")
    return True


if __name__ == "__main__":
    tests = [
        test_latency_spike,
        test_no_latency_spike_below_threshold,
        test_failure_burst,
        test_no_failure_burst_below_threshold,
        test_failure_burst_ignores_benign_false,
        test_alert_persistence,
        test_acknowledge,
        test_recent_alerts,
        test_health_degradation,
        test_clean_system_no_alerts,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                failed += 1
                print(f"FAIL: {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"ERROR: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
