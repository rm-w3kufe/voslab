import json

import pytest

from trace_graph.export import to_dot, to_json, to_networkx
from trace_graph.graph import aggregate, per_trace

from .fixtures import make_traces


def _agg():
    return aggregate(make_traces(), tree="claim_gate")


def test_to_dot_aggregate():
    dot = to_dot(_agg(), name="claim_gate")
    assert dot.startswith("digraph claim_gate {")
    assert "homes: R1=1" in dot
    assert "keyed_by_text=4" in dot
    assert dot.count("->") == len(_agg()["edges"])
    assert dot.rstrip().endswith("}")


def test_to_dot_deterministic():
    assert to_dot(_agg()) == to_dot(_agg())


def test_to_dot_newline_separator_single_escaped():
    """Regression: separators must be ONE backslash ('\\n' in file), never
    double-escaped ('\\\\n' → graphviz would render a literal \\n)."""
    dot = to_dot(_agg())
    assert "\\n" in dot          # single backslash+n present
    assert "\\\\n" not in dot    # never two backslashes


def test_to_dot_label_truncated_tooltip_full():
    long_text = "x" * 200
    traces = [{"trace_id": "L", "tree_shape": "claim_gate(L)",
               "nodes": [{"node_id": 0, "type": "predicate", "name": "p",
                          "truth": "Truth.TRUE", "certified": True,
                          "text": long_text, "children": []}]}]
    dot = to_dot(aggregate(traces, tree="claim_gate"))
    label_section = dot.split("tooltip")[0]
    assert "x" * 71 in label_section      # limit 72 = 71 chars + ellipsis
    assert "x" * 72 not in label_section
    assert long_text in dot               # full text survives in tooltip


def test_to_dot_escapes_quotes_and_newlines():
    traces = [{"trace_id": "q", "tree_shape": "claim_gate(q)",
               "nodes": [{"node_id": 0, "type": "predicate", "name": "p",
                          "truth": "Truth.TRUE", "certified": True,
                          'text': 'p("x")\nsecond', "children": []}]}]
    dot = to_dot(aggregate(traces, tree="claim_gate"))
    assert '\\"x\\"' in dot and "\\nsecond" in dot


def test_to_dot_per_trace_local_ids():
    dot = to_dot(per_trace(make_traces()[0]))
    assert "n0 -> n1" in dot and "n1 -> n3" in dot
    assert "evalua a" in dot  # question surfaces as tooltip


def test_to_json_shape():
    env = to_json(_agg())
    assert env["graph"] == "claim_gate"
    assert all({"id", "label", "type", "truths"} <= set(n) for n in env["nodes"])
    assert all({"source", "target", "weight"} <= set(e) for e in env["links"])
    assert env["meta"]["traces_without_nodes"] == 1
    json.dumps(env)  # serializable


def test_to_networkx():
    nx = pytest.importorskip("networkx")
    g = to_networkx(_agg())
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == len(_agg()["nodes"])
    assert g.number_of_edges() == len(_agg()["edges"])
    assert g.nodes["a($x)"]["evals"] == 2
