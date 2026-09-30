"""Synthetic traces covering old/new row shapes (no runtime file dependency)."""
import json
from pathlib import Path


def make_traces() -> list[dict]:
    # A: claim_gate, home R1, branch 'a' evaluated with a child
    a = {
        "trace_id": "t-a", "ts": "2026-09-30T10:00:00+00:00",
        "session_id": "s1", "tree_shape": "claim_gate(AND(a, b))",
        "home": "R1", "final_truth": "Truth.TRUE", "final_certified": True,
        "total_latency_ms": 1.5, "context": {"command": "x"},
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.TRUE", "certified": True,
             "text": "AND(a, b)", "question": None, "children": [1, 2],
             "evidence": None, "args": None, "error": None},
            {"node_id": 1, "type": "operator", "name": "a",
             "truth": "Truth.TRUE", "certified": True,
             "text": "a($x)", "question": "evalua a", "children": [3],
             "evidence": None, "args": None, "error": None},
            {"node_id": 2, "type": "predicate", "name": "b",
             "truth": "Truth.TRUE", "certified": True,
             "text": "b($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
            {"node_id": 3, "type": "predicate", "name": "inner",
             "truth": "Truth.TRUE", "certified": True,
             "text": "inner($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
        ],
    }
    # B: same family, branch 'a' short-circuited (placeholder, same text),
    # no home recorded (old-ish row that still has text)
    b = {
        "trace_id": "t-b", "ts": "2026-09-30T10:01:00+00:00",
        "session_id": "s1", "tree_shape": "claim_gate(AND(a, b))",
        "final_truth": "Truth.FALSE", "final_certified": False,
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.FALSE", "certified": True,
             "text": "AND(a, b)", "question": None, "children": [1, 2],
             "evidence": None, "args": None, "error": None},
            {"node_id": 1, "type": "short_circuit", "name": "short_circuit",
             "truth": "Truth.UNKNOWN", "certified": False,
             "text": "a($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
            {"node_id": 2, "type": "predicate", "name": "b",
             "truth": "Truth.FALSE", "certified": True,
             "text": "b($x)", "question": None, "children": [],
             "evidence": None, "args": None, "error": None},
        ],
    }
    # C: OLD row — no text/question/home/context (pre-F1/F3)
    c = {
        "trace_id": "t-c", "ts": "2026-09-20T00:00:00+00:00",
        "tree_shape": "claim_gate(AND(...))",
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.FALSE", "certified": True, "children": [1]},
            {"node_id": 1, "type": "predicate", "name": "ctx_equals",
             "truth": "Truth.UNKNOWN", "certified": False, "children": []},
        ],
    }
    # D: claim_gate row without nodes at all
    d = {"trace_id": "t-d", "ts": "2026-09-21T00:00:00+00:00",
         "tree_shape": "claim_gate(AND(...))"}
    # E: other family (filter must exclude it)
    e = {"trace_id": "t-e", "ts": "2026-09-22T00:00:00+00:00",
         "tree_shape": "type_prefix(foo)", "nodes": [
             {"node_id": 0, "type": "operator", "name": "prefix",
              "truth": "Truth.TRUE", "certified": True,
              "text": "prefix($v)", "children": []}]}
    return [a, b, c, d, e]


def write_file(path: Path, traces: list[dict],
               extra_lines: tuple[str, ...] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(t) for t in traces] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n")
    return path
