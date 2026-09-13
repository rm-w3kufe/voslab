#!/usr/bin/env python3
"""test_audit_e2e.py — F1.2: End-to-end audit trail verification.

Tests the complete chain: evaluate() → trace capture → attestation sign → verify.
This is the definitive test that proves the audit trail works.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_e2e_evaluate_trace_attest_verify():
    """Full chain: evaluate → trace → sign → verify. Zero losses."""
    _vlab = str(Path(__file__).resolve().parent.parent.parent.parent)
    os.environ["VOSLAB_PATH"] = _vlab
    import rsi_cycle as _rc
    _rc.VOSLAB_PATH = Path(_vlab)  # Reset module-level constant
    from rsi_cycle import RSICycle
    from tree_trace_attest import AttestationVerifier

    cycle = RSICycle()
    verifier = AttestationVerifier()

    # Run 5 evaluations with different trees
    trees = [
        {"predicate": "task_has_work", "kwargs": {}},
        {"predicate": "state_consistent", "kwargs": {}},
        {"op": "AND", "children": [
            {"predicate": "state_consistent", "kwargs": {}},
            {"predicate": "naming_conforms", "kwargs": {}},
        ]},
        {"predicate": "action_forbidden", "kwargs": {"action": "write", "path": "/etc/passwd"}},
        {"predicate": "task_has_work", "kwargs": {}},
    ]

    for tree in trees:
        result = cycle.evaluate(tree, {})
        assert result["certified"] is not None

    # Check metrics: zero losses
    metrics = cycle._audit_metrics
    assert metrics["evals_total"] == 5, f"Expected 5 evals, got {metrics['evals_total']}"
    assert metrics["traces_captured"] == 5, f"Expected 5 traces, got {metrics['traces_captured']}"
    assert metrics["traces_lost"] == 0, f"Expected 0 lost traces, got {metrics['traces_lost']}"
    assert metrics["attestations_signed"] == 5, f"Expected 5 attestations, got {metrics['attestations_signed']}"
    assert metrics["attestations_lost"] == 0, f"Expected 0 lost attestations, got {metrics['attestations_lost']}"

    # Verify trace file has new entries
    trace_file = Path(os.environ["VOSLAB_PATH"]) / "state" / "rsi" / "tree_traces.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text().strip().split("\n")
    # Find our traces (last 5 should be from this test)
    our_traces = []
    for line in lines[-10:]:  # check last 10
        try:
            entry = json.loads(line)
            if entry.get("session_id") == cycle.session_id:
                our_traces.append(entry)
        except Exception:
            continue
    assert len(our_traces) >= 5, f"Expected ≥5 traces in file, found {len(our_traces)}"

    # Verify each trace has correct structure
    for trace in our_traces:
        assert "trace_id" in trace
        assert "tree_shape" in trace
        assert "final_truth" in trace
        assert "nodes" in trace
        assert len(trace["nodes"]) >= 1

    # Verify attestation files exist and verify
    att_dir = Path(os.environ["VOSLAB_PATH"]) / "state" / "rsi" / "attestations"
    assert att_dir.exists()
    att_files = sorted(att_dir.glob("*.attest.json"))
    assert len(att_files) >= 5

    # Verify last 5 attestations
    for att_file in att_files[-5:]:
        att = json.load(open(att_file))
        r = verifier.verify_trace(att)
        assert r["ok"], f"Attestation {att_file.name} failed verification: {r['reason']}"

    print("PASS: test_e2e_evaluate_trace_attest_verify")
    return True


def test_e2e_metrics_visible_in_stats():
    """Audit metrics are accessible via get_stats()."""
    _vlab = str(Path(__file__).resolve().parent.parent.parent.parent)
    os.environ["VOSLAB_PATH"] = _vlab
    import rsi_cycle as _rc
    _rc.VOSLAB_PATH = Path(_vlab)
    from rsi_cycle import RSICycle

    cycle = RSICycle()
    cycle.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})

    stats = cycle.get_stats()
    assert "audit_metrics" in stats
    m = stats["audit_metrics"]
    assert m["evals_total"] >= 1
    assert m["traces_captured"] >= 1
    assert m["traces_lost"] == 0

    print("PASS: test_e2e_metrics_visible_in_stats")
    return True


def test_e2e_trace_count_matches_eval_count():
    """Every evaluate() produces exactly one trace (no duplicates, no skips)."""
    _vlab = str(Path(__file__).resolve().parent.parent.parent.parent)
    os.environ["VOSLAB_PATH"] = _vlab
    import rsi_cycle as _rc
    _rc.VOSLAB_PATH = Path(_vlab)
    from rsi_cycle import RSICycle

    cycle = RSICycle()
    initial = cycle._audit_metrics["traces_captured"]

    for i in range(10):
        cycle.evaluate({"predicate": "task_has_work", "kwargs": {}}, {})

    m = cycle._audit_metrics
    assert m["evals_total"] == 10
    assert m["traces_captured"] - initial == 10
    assert m["traces_lost"] == 0

    print("PASS: test_e2e_trace_count_matches_eval_count")
    return True


if __name__ == "__main__":
    tests = [
        test_e2e_evaluate_trace_attest_verify,
        test_e2e_metrics_visible_in_stats,
        test_e2e_trace_count_matches_eval_count,
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
