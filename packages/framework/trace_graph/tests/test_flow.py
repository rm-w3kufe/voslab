import json

import pytest

from trace_graph.cli import main
from trace_graph.export import to_dot, to_json, to_networkx
from trace_graph.graph import flow

from .fixtures import write_file


def _traces():
    ctx_id = {"claim_id": "CLM-1", "claim_type": "theorem"}
    return [
        {"trace_id": "t1", "ts": "2026-09-30T10:00:00+00:00",
         "session_id": "s1", "tree_shape": "claim_gate(x)",
         "home": "R1", "final_truth": "Truth.TRUE",
         "total_latency_ms": 1.0, "context": ctx_id},
        {"trace_id": "t2", "ts": "2026-09-30T10:05:00+00:00",
         "session_id": "s1", "tree_shape": "claim_gate(x)",
         "home": "R2", "final_truth": "Truth.FALSE",
         "total_latency_ms": 2.0, "context": ctx_id},
        {"trace_id": "t3", "ts": "2026-09-30T11:00:00+00:00",
         "tree_shape": "claim_gate(x)", "home": None,
         "final_truth": "Truth.UNKNOWN",
         "context": {"claim_type": "theorem", "falsifier": "true"}},
        {"trace_id": "t4", "ts": "2026-09-30T12:00:00+00:00",
         "tree_shape": "claim_gate(x)", "context": None},
        {"trace_id": "t5", "ts": "2026-09-30T13:00:00+00:00",
         "session_id": "s1", "tree_shape": "type_prefix(x)",
         "home": "R1", "context": {"claim_id": "CLM-9"}},
    ]


def test_flow_parts_and_counts():
    g = flow(_traces(), tree="claim_gate")
    assert g["kind"] == "flow"
    m = g["meta"]
    assert m["traces"] == 4                      # t5 filtered by family
    assert m["claims"] == {"by_claim_id": 2,      # t1 + t2 (CLM-1)
                           "by_context_fingerprint": 1,  # t3
                           "missing_context": 1}  # t4
    assert m["homes"] == {"R1": 1, "R2": 1}
    kinds = {n["kind"] for n in g["nodes"]}
    assert kinds == {"claim", "trace", "home"}
    assert any(n["id"] == "claim:CLM-1" and n["keyed_by"] == "claim_id"
               for n in g["nodes"])


def test_flow_edge_kinds():
    g = flow(_traces(), tree="claim_gate")
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert ("claim:CLM-1", "t1", "link") in edges      # claim -> trace
    assert ("t1", "home:R1", "route") in edges          # trace -> home
    assert ("t1", "t2", "temporal") in edges            # same session chain
    # no temporal across session groups (t1->t3 must NOT exist)
    assert not any(a == "t1" and b == "t3" for a, b, _ in edges)


def test_flow_session_filter():
    g = flow(_traces(), session="s1")
    ids = {n["id"] for n in g["nodes"]}
    assert {"t1", "t2", "t5"} <= ids and "t3" not in ids
    assert g["meta"]["sessions"] == 1


def test_flow_deterministic():
    t = _traces()
    assert flow(t, tree="claim_gate") == flow(t, tree="claim_gate")


def test_flow_dot_styles():
    dot = to_dot(flow(_traces(), tree="claim_gate"), name="claim_gate")
    assert dot.startswith("digraph claim_gate {")
    assert "shape=diamond" in dot and "shape=oval" in dot
    assert "claims(id=2, ctx=1, missing=1)" in dot
    assert 'color="#0d6efd"' in dot and 'color="#dc3545"' in dot
    assert dot.rstrip().endswith("}")


def test_flow_json_and_networkx():
    env = to_json(flow(_traces(), tree="claim_gate"))
    assert env["graph"] == "claim_gate" and env["meta"]["kind"] == "flow"
    assert all("kind" in e for e in env["links"])
    json.dumps(env)
    nx = pytest.importorskip("networkx")
    g = to_networkx(flow(_traces(), tree="claim_gate"))
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == len(env["nodes"])
    assert g.number_of_edges() == len(env["links"])


def test_cli_flow(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", _traces())
    rc = main(["flow", "--tree", "claim_gate", "--format", "json",
               "--traces", str(p)])
    out = capsys.readouterr().out
    assert rc == 0 and '"kind": "flow"' in out
    rc = main(["flow", "--session", "nope", "--traces", str(p)])
    assert rc == 2
