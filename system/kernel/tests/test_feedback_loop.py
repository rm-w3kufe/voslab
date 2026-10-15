#!/usr/bin/env python3
"""test_feedback_loop.py — Tests for Capa 3: Feedback Loop."""
import json
import os
import sys
import tempfile
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback_loop import FeedbackLoop, PatternDetector, SessionReport, HealthEntry


def test_high_failure_rate():
    """Detector flags sessions with >50% failure rate."""
    detector = PatternDetector()
    traces = [{"final_truth": "Truth.FALSE", "final_source": f"p{i}", "total_nodes": 1,
                "total_latency_ms": 10, "nodes": []} for i in range(8)]
    traces += [{"final_truth": "Truth.TRUE", "final_source": "ok", "total_nodes": 1,
                 "total_latency_ms": 10, "nodes": []} for _ in range(2)]
    patterns = detector.detect(traces)
    assert any(p["type"] == "high_failure_rate" for p in patterns)
    print("PASS: test_high_failure_rate")
    return True


def test_latency_spike():
    """Detector flags latency spikes (>3x avg, >500ms)."""
    detector = PatternDetector()
    traces = [{"final_truth": "Truth.TRUE", "final_source": "ok", "total_nodes": 1,
                "total_latency_ms": 10, "nodes": []} for _ in range(9)]
    traces.append({"final_truth": "Truth.TRUE", "final_source": "slow", "total_nodes": 1,
                    "total_latency_ms": 5000, "nodes": []})
    patterns = detector.detect(traces)
    assert any(p["type"] == "latency_spike" for p in patterns)
    print("PASS: test_latency_spike")
    return True


def test_repeated_failure():
    """Detector flags repeated failures on same source (≥3)."""
    detector = PatternDetector()
    traces = [{"final_truth": "Truth.FALSE", "final_source": "broken",
                "total_nodes": 1, "total_latency_ms": 10, "nodes": []} for _ in range(5)]
    patterns = detector.detect(traces)
    assert any(p["type"] == "repeated_failure" for p in patterns)
    print("PASS: test_repeated_failure")
    return True


def test_monotonic_truth():
    """Detector flags when all traces return same truth (≥5)."""
    detector = PatternDetector()
    traces = [{"final_truth": "Truth.TRUE", "final_source": f"p{i}",
                "total_nodes": 1, "total_latency_ms": 10, "nodes": []} for i in range(6)]
    patterns = detector.detect(traces)
    assert any(p["type"] == "monotonic_truth" for p in patterns)
    print("PASS: test_monotonic_truth")
    return True


def test_clean_data_no_patterns():
    """Clean data with varied truths produces no patterns."""
    detector = PatternDetector()
    traces = [{"final_truth": "Truth.TRUE" if i % 2 == 0 else "Truth.FALSE",
                "final_source": f"p{i}", "total_nodes": 1,
                "total_latency_ms": 50, "nodes": []} for i in range(5)]
    patterns = detector.detect(traces)
    assert len(patterns) == 0
    print("PASS: test_clean_data_no_patterns")
    return True


def test_empty_traces():
    """Empty traces produce no patterns."""
    detector = PatternDetector()
    assert len(detector.detect([])) == 0
    print("PASS: test_empty_traces")
    return True


def test_health_history_write():
    """Health entries append to health_history.jsonl."""
    with tempfile.TemporaryDirectory() as tmp:
        loop = FeedbackLoop()
        loop._health_file = Path(tmp) / "health.jsonl"
        report = SessionReport(
            session_id="test", ts="2026-01-01T00:00:00Z", duration_seconds=60,
            total_traces=10, truth_distribution={"TRUE": 7, "FALSE": 3},
            avg_latency_ms=50.0, max_latency_ms=200.0, total_nodes_evaluated=30,
            total_attestations=10, attestations_valid=10,
            patterns=[], health_entry={
                "ts": "2026-01-01T00:00:00Z", "session_id": "test",
                "traces": {"total": 10, "truths": {"TRUE": 7}},
                "attestations": {"total": 10, "valid": 10},
                "patterns": [],
            },
        )
        loop.update_health_history(report)
        assert loop._health_file.exists()
        lines = loop._health_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["session_id"] == "test"
        assert entry["traces"]["total"] == 10
        print("PASS: test_health_history_write")
    return True


def test_health_report():
    """Health report aggregates entries correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        loop = FeedbackLoop()
        loop._health_file = Path(tmp) / "health.jsonl"

        # Write two entries
        for i in range(2):
            entry = {
                "ts": f"2026-01-01T0{i}:00:00Z", "session_id": f"s{i}",
                "traces": {"total": 5 + i, "truths": {"TRUE": 3}},
                "attestations": {"total": 5 + i, "valid": 5 + i},
                "patterns": [{"type": "test_pattern", "severity": "info", "detail": "x"}],
            }
            with open(loop._health_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

        report = loop.health_report()
        assert report["entries"] == 2
        assert report["total_traces"] == 11  # 5 + 6
        assert report["total_attestations"] == 11
        assert "test_pattern" in report["pattern_frequency"]
        print("PASS: test_health_report")
    return True


def test_session_report_structure():
    """SessionReport has all required fields."""
    report = SessionReport(
        session_id="test", ts="2026-01-01T00:00:00Z", duration_seconds=60,
        total_traces=10, truth_distribution={"TRUE": 7, "FALSE": 3},
        avg_latency_ms=50.0, max_latency_ms=200.0, total_nodes_evaluated=30,
        total_attestations=10, attestations_valid=10,
        patterns=[], health_entry={},
    )
    assert report.total_traces == 10
    assert report.session_id == "test"
    assert report.total_nodes_evaluated == 30
    print("PASS: test_session_report_structure")
    return True


def test_health_report_session_scope():
    """P-EV-R4 (FND-HEALTH-H1-SCOPE): scoped report = SOLO las traces de
    esta sesión; unscoped = all_time honesto. El bug viejo contaba el
    ledger acumulado entero como si fuera de la sesión (totales idénticos
    entre sesiones = reporte que miente)."""
    with tempfile.TemporaryDirectory() as tmp:
        tfile = Path(tmp) / "tree_traces.jsonl"
        lines = []
        for i in range(3):
            lines.append(json.dumps({
                "trace_id": f"trace-a-{i}", "ts": f"2026-10-15T10:00:0{i}Z",
                "session_id": "sess-A", "final_truth": "Truth.TRUE",
                "final_source": "p", "total_nodes": 1, "total_latency_ms": 5,
            }))
        for i in range(2):
            lines.append(json.dumps({
                "trace_id": f"trace-b-{i}", "ts": f"2026-10-15T11:00:0{i}Z",
                "session_id": "sess-B", "final_truth": "Truth.FALSE",
                "final_source": "q", "total_nodes": 1, "total_latency_ms": 5,
            }))
        lines.append(json.dumps({
            "trace_id": "trace-none", "ts": "2026-10-15T12:00:00Z",
            "session_id": None, "final_truth": "Truth.TRUE",
            "final_source": "r", "total_nodes": 1, "total_latency_ms": 5,
        }))
        tfile.write_text("\n".join(lines) + "\n")

        old_trace = os.environ.get("VOS_TREE_TRACE_FILE")
        old_health = os.environ.get("VOS_HEALTH_FILE")
        os.environ["VOS_TREE_TRACE_FILE"] = str(tfile)
        try:
            loop = FeedbackLoop()
            loop._health_file = Path(tmp) / "health.jsonl"

            # Session-scoped: solo A (3 traces), NO el ledger completo (6)
            rep_a = loop.generate_report("sess-A")
            assert rep_a.total_traces == 3, f"expected 3, got {rep_a.total_traces}"
            assert rep_a.health_entry["scope"] == "session"
            assert rep_a.health_entry["traces"]["truths"] == {"Truth.TRUE": 3}
            # B no contamina el reporte de A
            assert "Truth.FALSE" not in rep_a.health_entry["traces"]["truths"]

            # Unscoped: all_time honesto con las 6; scope marca el alcance
            rep_all = loop.generate_report()
            assert rep_all.total_traces == 6, f"expected 6, got {rep_all.total_traces}"
            assert rep_all.health_entry["scope"] == "all_time"
            # session_id derive: primer non-None (no "unknown")
            assert rep_all.session_id == "sess-A"

            # Sesión sin traces = cero honesto (no cuenta el ledger ajeno)
            rep_z = loop.generate_report("sess-ZZ")
            assert rep_z.total_traces == 0
            assert rep_z.health_entry["scope"] == "session"
        finally:
            if old_trace is None:
                os.environ.pop("VOS_TREE_TRACE_FILE", None)
            else:
                os.environ["VOS_TREE_TRACE_FILE"] = old_trace
            if old_health is not None:
                os.environ["VOS_HEALTH_FILE"] = old_health
        print("PASS: test_health_report_session_scope")
    return True


def test_health_report_attest_join():
    """P-EV-R4: session scope junta attestations por trace_id (lookup
    directo {trace_id}.attest.json); no carga los ~11k archivos ajenos."""
    with tempfile.TemporaryDirectory() as tmp:
        tfile = Path(tmp) / "tree_traces.jsonl"
        tfile.write_text(json.dumps({
            "trace_id": "trace-sess-1", "ts": "2026-10-15T10:00:00Z",
            "session_id": "sess-C", "final_truth": "Truth.TRUE",
            "final_source": "p", "total_nodes": 1, "total_latency_ms": 5,
        }) + "\n")

        loop = FeedbackLoop()
        # Redirigir el store de attests al tmp (mismo override de entorno
        # que el de traces no existe para attestations — se parcha _state_dir)
        att_dir = Path(tmp) / "attestations"
        att_dir.mkdir()
        (att_dir / "trace-sess-1.attest.json").write_text(json.dumps({
            "trace_id": "trace-sess-1", "final_truth": "Truth.TRUE",
            "key_id": "k", "signature_b64": "x", "total_nodes": 1,
            "trace_hash": "h", "tree_shape": "p", "ts": "2026-10-15T10:00:01Z",
        }))
        (att_dir / "trace-ajeno-9.attest.json").write_text(json.dumps({
            "trace_id": "trace-ajeno-9", "final_truth": "Truth.TRUE",
            "key_id": "k", "signature_b64": "x", "total_nodes": 1,
            "trace_hash": "h", "tree_shape": "p", "ts": "2026-10-15T09:00:00Z",
        }))
        loop._state_dir = Path(tmp)  # atts = _state_dir/attestations

        old_trace = os.environ.get("VOS_TREE_TRACE_FILE")
        os.environ["VOS_TREE_TRACE_FILE"] = str(tfile)
        try:
            rep = loop.generate_report("sess-C")
            assert rep.total_attestations == 1, (
                f"join by trace_id: expected 1, got {rep.total_attestations}")
        finally:
            if old_trace is None:
                os.environ.pop("VOS_TREE_TRACE_FILE", None)
            else:
                os.environ["VOS_TREE_TRACE_FILE"] = old_trace
        print("PASS: test_health_report_attest_join")
    return True


def test_trace_logger_session_env():
    """P-EV-R4 (FND-TRACE-SESSION-ENV-DRIFT): el writer stampa
    VOS_SESSION_ID (canónico, session-lifecycle.ts) antes que SESSION_ID
    (legacy, nunca seteada en opencode → 78% de traces con None)."""
    from tree_trace_logger import TreeTraceLogger
    keys = ("VOS_SESSION_ID", "SESSION_ID")
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        os.environ["VOS_SESSION_ID"] = "ses_canonical"
        os.environ["SESSION_ID"] = "legacy-id"
        assert TreeTraceLogger(session_id=None).session_id == "ses_canonical"

        # Arg explícito gana sobre env
        assert TreeTraceLogger(session_id="explicit").session_id == "explicit"

        # Sin canónica → fallback legacy
        del os.environ["VOS_SESSION_ID"]
        assert TreeTraceLogger(session_id=None).session_id == "legacy-id"

        # Sin ninguna → None (jamás un id inventado)
        del os.environ["SESSION_ID"]
        assert TreeTraceLogger(session_id=None).session_id is None
    finally:
        for k in keys:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
    print("PASS: test_trace_logger_session_env")
    return True


if __name__ == "__main__":
    tests = [
        test_high_failure_rate,
        test_latency_spike,
        test_repeated_failure,
        test_monotonic_truth,
        test_clean_data_no_patterns,
        test_empty_traces,
        test_health_history_write,
        test_health_report,
        test_session_report_structure,
        test_health_report_session_scope,
        test_health_report_attest_join,
        test_trace_logger_session_env,
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
