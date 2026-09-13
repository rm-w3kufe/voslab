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
