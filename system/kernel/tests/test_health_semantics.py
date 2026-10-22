#!/usr/bin/env python3
# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: system/kernel/health_semantics.py)
"""test_health_semantics — R10 classification of operational vs benign traces."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health_semantics import (  # noqa: E402
    BENIGN_SOURCES,
    NON_OPERATIONAL,
    OPERATIONAL_FAILURE,
    OPERATIONAL_SUCCESS,
    classify_trace,
    operational_counts,
    operational_truths,
)


def _trace(truth, source, nodes=None):
    return {
        "trace_id": "t1", "final_truth": truth, "final_source": source,
        "nodes": nodes or [],
    }


def _pred(name, truth):
    return {"type": "predicate", "name": name, "truth": truth}


def test_benign_singles_are_non_operational():
    """Designed-benign sources never count against health."""
    cases = [
        ("Truth.FALSE", "test_always_false"),
        ("Truth.FALSE", "type_prefix"),
        ("Truth.FALSE", "task_active"),
        ("Truth.FALSE", "task_has_work"),
        ("Truth.FALSE", "action_forbidden"),
        ("Truth.FALSE", "ctx_contains"),  # branch not taken (gap/classify trees)
        ("Truth.FALSE", "ctx_equals"),    # branch not taken (covenant trees)
        ("Truth.TRUE", "type_prefix"),   # classification hit: also not health
        ("Truth.TRUE", "task_has_work"),  # observation: not health
    ]
    for truth, src in cases:
        assert classify_trace(_trace(truth, src)) == NON_OPERATIONAL, (truth, src)
    print("PASS: test_benign_singles_are_non_operational")
    return True


def test_operational_failures_count():
    """Real check failures are operational failures."""
    for src in ("state_consistent", "scripts_migrated_ok", "not_redundant",
                "write_scope_ok", "read_size_ok"):
        assert classify_trace(_trace("Truth.FALSE", src)) == OPERATIONAL_FAILURE, src
    assert classify_trace(_trace("Truth.FALSE", "pred")) == OPERATIONAL_FAILURE
    assert classify_trace(_trace("Truth.ERROR", "pred")) == OPERATIONAL_FAILURE
    assert classify_trace(_trace("Truth.TRUE", "state_consistent")) == OPERATIONAL_SUCCESS
    print("PASS: test_operational_failures_count")
    return True


def test_composite_with_benign_only_false_is_non_operational():
    """op:AND false ONLY because a gate fired = not a health failure."""
    t = _trace("Truth.FALSE", "op:AND", nodes=[
        {"type": "operator", "name": "AND", "truth": "Truth.FALSE", "children": [1, 2]},
        _pred("action_forbidden", "Truth.FALSE"),
        {"type": "short_circuit", "name": "short_circuit", "truth": "Truth.UNKNOWN"},
    ])
    assert classify_trace(t) == NON_OPERATIONAL

    t2 = _trace("Truth.FALSE", "op:OR", nodes=[
        {"type": "operator", "name": "OR", "truth": "Truth.FALSE"},
        _pred("type_prefix", "Truth.FALSE"),
    ])
    assert classify_trace(t2) == NON_OPERATIONAL
    print("PASS: test_composite_with_benign_only_false_is_non_operational")
    return True


def test_composite_with_operational_false_is_failure():
    """op:AND false because a real child failed = operational failure."""
    t = _trace("Truth.FALSE", "op:AND", nodes=[
        {"type": "operator", "name": "AND", "truth": "Truth.FALSE"},
        _pred("action_forbidden", "Truth.FALSE"),
        _pred("state_consistent", "Truth.FALSE"),
    ])
    assert classify_trace(t) == OPERATIONAL_FAILURE

    t2 = _trace("Truth.FALSE", "op:AND", nodes=[
        {"type": "operator", "name": "AND", "truth": "Truth.FALSE"},
        _pred("not_redundant", "Truth.FALSE"),
    ])
    assert classify_trace(t2) == OPERATIONAL_FAILURE
    print("PASS: test_composite_with_operational_false_is_failure")
    return True


def test_composite_without_nodes_is_conservative():
    """Legacy composite FALSE with no node detail counts (never hide)."""
    t = _trace("Truth.FALSE", "op:AND", nodes=[])
    assert classify_trace(t) == OPERATIONAL_FAILURE
    print("PASS: test_composite_without_nodes_is_conservative")
    return True


def test_counts_and_truths():
    traces = [
        _trace("Truth.FALSE", "test_always_false"),   # excluded
        _trace("Truth.FALSE", "type_prefix"),         # excluded
        _trace("Truth.FALSE", "state_consistent"),    # failure
        _trace("Truth.TRUE", "state_consistent"),     # success
        _trace("Truth.TRUE", "task_has_work"),        # excluded
        _trace("Truth.FALSE", "op:AND", nodes=[_pred("action_forbidden", "Truth.FALSE")]),  # excluded
    ]
    total, failures, successes = operational_counts(traces)
    assert (total, failures, successes) == (2, 1, 1)
    assert operational_truths(traces) == {"Truth.TRUE": 1, "Truth.FALSE": 1}
    print("PASS: test_counts_and_truths")
    return True


def test_deterministic_r10():
    """Same input -> same classification (no clock, no randomness)."""
    t = _trace("Truth.FALSE", "op:AND", nodes=[_pred("path_forbidden", "Truth.FALSE")])
    results = {classify_trace(t) for _ in range(100)}
    assert results == {NON_OPERATIONAL}
    assert isinstance(BENIGN_SOURCES, frozenset)
    print("PASS: test_deterministic_r10")
    return True


if __name__ == "__main__":
    tests = [
        test_benign_singles_are_non_operational,
        test_operational_failures_count,
        test_composite_with_benign_only_false_is_non_operational,
        test_composite_with_operational_false_is_failure,
        test_composite_without_nodes_is_conservative,
        test_counts_and_truths,
        test_deterministic_r10,
    ]
    passed = failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
