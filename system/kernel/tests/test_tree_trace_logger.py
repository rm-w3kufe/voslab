#!/usr/bin/env python3
"""test_tree_trace_logger.py — Tests for Tree Trace Logger (Capa 1)"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Add system/kernel to path (where tree_trace_logger lives)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tree_trace_logger import TreeTraceLogger, TreeTrace, NodeTrace


def test_basic_capture():
    """Logger captures a simple evaluation trace."""
    from socratic_engine import SocraticEngine, PredicateResult, Truth

    engine = SocraticEngine()

    @engine.register("is_positive")
    def is_positive(**kw):
        v = int(kw.get("value", 0))
        return PredicateResult(
            truth=Truth.TRUE if v > 0 else Truth.FALSE,
            certified=True,
            evidence={"value": v},
            source="is_positive",
        )

    @engine.register("is_even")
    def is_even(**kw):
        v = int(kw.get("value", 0))
        return PredicateResult(
            truth=Truth.TRUE if v % 2 == 0 else Truth.FALSE,
            certified=True,
            evidence={"value": v},
            source="is_even",
        )

    tree = {"op": "AND", "children": [
        {"predicate": "is_positive", "kwargs": {"value": 5}},
        {"predicate": "is_even", "kwargs": {"value": 4}},
    ]}

    result = engine.evaluate(tree, {}, enforce_limits=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "traces.jsonl"
        logger = TreeTraceLogger(log_file=log_file, session_id="test-session")

        trace = logger.capture(result, tree, {"key": "value"}, latency_ms=1.5)

        # Verify trace structure
        assert trace.session_id == "test-session"
        assert trace.tree_hash  # non-empty
        assert trace.tree_shape == "AND(is_positive, is_even)"
        assert trace.final_truth == "Truth.TRUE"
        assert trace.final_certified is True
        assert trace.total_nodes == 3  # AND + is_positive + is_even
        assert trace.predicates_evaluated == 2
        assert trace.operators_evaluated == 1
        assert trace.total_latency_ms == 1.5
        assert trace.context_keys == ["key"]

        # Verify nodes
        assert len(trace.nodes) == 3
        root = trace.nodes[0]
        assert root.node_type == "operator"
        assert root.name == "AND"
        assert root.truth == "Truth.TRUE"
        assert len(root.children_ids) == 2

        pred1 = trace.nodes[1]
        assert pred1.node_type == "predicate"
        assert pred1.name == "is_positive"
        assert pred1.evidence == {"value": 5}

        pred2 = trace.nodes[2]
        assert pred2.node_type == "predicate"
        assert pred2.name == "is_even"
        assert pred2.evidence == {"value": 4}

        print("PASS: test_basic_capture")
    return True


def test_persist_and_read():
    """Traces are persisted to JSONL and readable."""
    from socratic_engine import SocraticEngine, PredicateResult, Truth

    engine = SocraticEngine()

    @engine.register("always_true")
    def always_true(**kw):
        return PredicateResult(truth=Truth.TRUE, certified=True, source="always_true")

    tree = {"predicate": "always_true", "kwargs": {}}
    result = engine.evaluate(tree, {}, enforce_limits=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "traces.jsonl"
        logger = TreeTraceLogger(log_file=log_file)

        trace = logger.capture(result, tree)
        logger.persist(trace)

        # Read back
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["trace_id"] == trace.trace_id
        assert entry["final_truth"] == "Truth.TRUE"
        assert len(entry["nodes"]) == 1
        assert entry["nodes"][0]["name"] == "always_true"

        print("PASS: test_persist_and_read")
    return True


def test_nested_tree():
    """Nested trees produce correct trace with children."""
    from socratic_engine import SocraticEngine, PredicateResult, Truth

    engine = SocraticEngine()

    @engine.register("check_a")
    def check_a(**kw):
        return PredicateResult(truth=Truth.TRUE, certified=True, evidence={"a": 1}, source="check_a")

    @engine.register("check_b")
    def check_b(**kw):
        return PredicateResult(truth=Truth.FALSE, certified=True, evidence={"b": 2}, source="check_b")

    @engine.register("check_c")
    def check_c(**kw):
        return PredicateResult(truth=Truth.TRUE, certified=True, evidence={"c": 3}, source="check_c")

    tree = {"op": "OR", "children": [
        {"op": "AND", "children": [
            {"predicate": "check_a", "kwargs": {}},
            {"predicate": "check_b", "kwargs": {}},
        ]},
        {"predicate": "check_c", "kwargs": {}},
    ]}

    result = engine.evaluate(tree, {}, enforce_limits=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "traces.jsonl"
        logger = TreeTraceLogger(log_file=log_file)

        trace = logger.capture(result, tree)

        # OR -> AND(check_a, check_b) + check_c
        # AND fails (check_b is FALSE), so OR tries check_c (TRUE) -> TRUE
        assert trace.total_nodes >= 4  # OR + AND + check_a + check_b + check_c
        assert trace.tree_shape.startswith("OR(AND(")

        # Verify the trace tree structure
        root = trace.nodes[0]
        assert root.name == "OR"

        print("PASS: test_nested_tree")
    return True


def test_session_summary():
    """Session summary aggregates multiple traces."""
    from socratic_engine import SocraticEngine, PredicateResult, Truth

    engine = SocraticEngine()

    @engine.register("pred_a")
    def pred_a(**kw):
        return PredicateResult(truth=Truth.TRUE, certified=True, source="pred_a")

    @engine.register("pred_b")
    def pred_b(**kw):
        return PredicateResult(truth=Truth.FALSE, certified=True, source="pred_b")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "traces.jsonl"
        logger = TreeTraceLogger(log_file=log_file, session_id="summary-test")

        # Evaluate 3 traces
        for _ in range(2):
            tree = {"predicate": "pred_a", "kwargs": {}}
            result = engine.evaluate(tree, {}, enforce_limits=False)
            trace = logger.capture(result, tree)
            logger.persist(trace)

        tree = {"predicate": "pred_b", "kwargs": {}}
        result = engine.evaluate(tree, {}, enforce_limits=False)
        trace = logger.capture(result, tree)
        logger.persist(trace)

        summary = logger.session_summary()
        assert summary["traces"] == 3
        assert summary["truths"].get("Truth.TRUE") == 2
        assert summary["truths"].get("Truth.FALSE") == 1
        assert summary["session_id"] == "summary-test"
        assert summary["total_nodes"] >= 3

        print("PASS: test_session_summary")
    return True


def test_rsi_cycle_integration():
    """RSI Cycle produces tree traces on evaluate().

    Sampling contract (H3): failures always traced. Uses a
    deterministic certified-FALSE tree (not state-dependent
    task_has_work) so the trace is guaranteed, not sampled out.
    """
    os.environ["VOSLAB_PATH"] = str(Path(__file__).resolve().parent.parent.parent.parent)

    from rsi_cycle import RSICycle

    cycle = RSICycle()

    trace_file = Path(os.environ["VOSLAB_PATH"]) / "state" / "rsi" / "tree_traces.jsonl"
    before_count = 0
    if trace_file.exists():
        content = trace_file.read_text().strip()
        before_count = len(content.split("\n")) if content else 0

    tree = {"predicate": "type_prefix", "args": ["$type", "VSL-"]}
    result = cycle.evaluate(tree, {"type": "OTHER"})
    assert result["truth"] == "FALSE" and result["certified"] is True

    assert trace_file.exists(), f"Trace file not found at {trace_file}"

    lines = trace_file.read_text().strip().split("\n")
    assert len(lines) > before_count, "No new traces written after evaluate()"

    our_trace = None
    for line in lines[before_count:]:
        try:
            entry = json.loads(line)
            if entry.get("final_source") == "type_prefix":
                our_trace = entry
                break
        except Exception:
            continue

    if our_trace is None:
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("final_source") == "type_prefix":
                    our_trace = entry
                    break
            except Exception:
                continue

    assert our_trace is not None, "No trace found for RSI cycle evaluation"
    assert our_trace["final_source"] == "type_prefix"
    assert our_trace["total_nodes"] >= 1

    from vsf_rsi.rsi_socratic_bridge import list_queue
    for item in list_queue("pending"):
        queue_file = Path(os.environ.get("RSI_QUEUE_DIR", "/tmp")) / f"{item['name']}.json"
        if queue_file.exists():
            queue_file.unlink()

    from vsf_rsi.rsi_fault_detector import FAULT_FILE
    if FAULT_FILE.exists():
        FAULT_FILE.unlink()

    print("PASS: test_rsi_cycle_integration")
    return True


if __name__ == "__main__":
    tests = [
        test_basic_capture,
        test_persist_and_read,
        test_nested_tree,
        test_session_summary,
        test_rsi_cycle_integration,
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
