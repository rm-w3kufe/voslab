#!/usr/bin/env python3
"""test_audit_pipeline.py — F4.3: AuditPipeline integration test.

Tests the unified pipeline as a black box: evaluate → trace → attest → alert.
"""
import os
import sys
from pathlib import Path

# Ensure kernel is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Workspace root (2026-10-20 fix): tests/ needs parents[3] — the old
# parent.parent.parent resolved to <repo>/system, and this module-level
# setdefault poisoned VOSLAB_PATH for the whole pytest session whenever
# the env var was missing (systemd weekly runs) → root/TASKS.vsm not
# found → bridge live=0 + tasks-reconcile-enforced red (3 failures).
os.environ.setdefault("VOSLAB_PATH", str(Path(__file__).resolve().parents[3]))


def test_pipeline_run_returns_trace_id():
    """Pipeline.run() returns a trace_id on success."""
    from audit_pipeline import AuditPipeline
    import rsi_cycle

    cycle = rsi_cycle.RSICycle()
    pipeline = AuditPipeline(session_id="test-pipeline")

    ev = cycle.engine.evaluate(
        {"predicate": "task_has_work", "kwargs": {}}, {}, enforce_limits=True
    )
    result = pipeline.run(
        ev,
        {"predicate": "task_has_work", "kwargs": {}},
        {},
        latency_ms=42.0,
    )

    assert result["trace_id"] is not None
    assert isinstance(result["trace_id"], str)
    assert len(result["trace_id"]) > 0
    print("PASS: test_pipeline_run_returns_trace_id")


def test_pipeline_metrics_update():
    """Pipeline metrics update after each run."""
    from audit_pipeline import AuditPipeline
    import rsi_cycle

    cycle = rsi_cycle.RSICycle()
    pipeline = AuditPipeline(session_id="test-metrics")

    ev = cycle.engine.evaluate(
        {"predicate": "task_has_work", "kwargs": {}}, {}, enforce_limits=True
    )
    pipeline.run(ev, {"predicate": "task_has_work", "kwargs": {}}, {}, 10.0)
    pipeline.run(ev, {"predicate": "task_has_work", "kwargs": {}}, {}, 10.0)

    m = pipeline.metrics
    assert m["evals_total"] == 2
    assert m["traces_captured"] == 2
    assert m["traces_lost"] == 0
    print("PASS: test_pipeline_metrics_update")


def test_pipeline_attestation_created():
    """Pipeline creates attestation for each trace."""
    from audit_pipeline import AuditPipeline
    import rsi_cycle

    cycle = rsi_cycle.RSICycle()
    pipeline = AuditPipeline(session_id="test-attest")

    ev = cycle.engine.evaluate(
        {"predicate": "task_has_work", "kwargs": {}}, {}, enforce_limits=True
    )
    result = pipeline.run(ev, {"predicate": "task_has_work", "kwargs": {}}, {}, 10.0)

    assert result["attestation"] is not None
    att = result["attestation"]
    assert hasattr(att, "trace_id")
    assert hasattr(att, "signature_b64")
    assert pipeline.metrics["attestations_signed"] >= 1
    print("PASS: test_pipeline_attestation_created")


def test_pipeline_null_event():
    """Pipeline handles None event gracefully (trace_lost +1)."""
    from audit_pipeline import AuditPipeline

    pipeline = AuditPipeline(session_id="test-null")
    result = pipeline.run(None, {}, {}, 0.0)

    assert result["trace_id"] is None
    assert result["metrics"]["traces_lost"] == 1
    print("PASS: test_pipeline_null_event")


def test_pipeline_check_alerts(monkeypatch, tmp_path):
    """Pipeline.check_alerts() returns a list.

    VOSLAB_PATH must point at tmp: AlertMonitor resolves its state dir at
    __init__ from VOSLAB_PATH, and check() emits alerts — without this the
    test leaked real-looking alerts into production state/rsi/alerts.jsonl
    on every pytest run (leak proven 2026-10-05).
    """
    from audit_pipeline import AuditPipeline

    monkeypatch.setenv("VOSLAB_PATH", str(tmp_path))
    pipeline = AuditPipeline(session_id="test-alerts")
    alerts = pipeline.check_alerts()
    assert isinstance(alerts, list)
    print("PASS: test_pipeline_check_alerts")


if __name__ == "__main__":
    test_pipeline_run_returns_trace_id()
    test_pipeline_metrics_update()
    test_pipeline_attestation_created()
    test_pipeline_null_event()
    test_pipeline_check_alerts()
    print("\nAll AuditPipeline tests passed!")
