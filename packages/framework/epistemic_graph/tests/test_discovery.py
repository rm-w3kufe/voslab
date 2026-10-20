# design: docs/plans/graph_phase3_plan.vsm (SUT: packages/framework/epistemic_graph/discovery.py)
"""discovery tests: R10 determinism, closed scores, negative control,
NO-NEW-TRUTH, denominators (plan ratificado 3b)."""
import json

import pytest

from epistemic_graph import build, discover
from epistemic_graph.discovery import (
    MIN_SCORE_PROVISIONAL, MOTIF_DIRECTED_KINDS, SCHEMA,
    label_propagation_deterministic, write_queue,
)
from .fixtures import write_workspace


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = write_workspace(tmp_path)
    monkeypatch.setenv("VOSLAB_PATH", str(root))
    return root


# ---------------------------------------------------------------- structure

def test_schema_and_fingerprint(ws):
    g = build(use_cache=False)
    q = discover(g)
    assert q["schema"] == SCHEMA
    assert q["fingerprint"] == g["meta"]["fingerprint"]
    assert q["min_score"] == MIN_SCORE_PROVISIONAL
    assert set(q["denominators"]) == {
        "link_prediction", "motif_closure", "time_respecting",
        "communities_consenso"}
    assert q["meta"]["total_candidates"] == len(q["candidates"])


def test_candidates_have_kind_score_method(ws):
    g = build(use_cache=False)
    q = discover(g)
    for c in q["candidates"]:
        assert "kind" in c and "u" in c and "v" in c
        assert "score" in c and "method" in c
        assert c["u"] != c["v"], "no self-loops"
        assert 0.0 <= c["score"] <= 1.0, c


def test_candidates_sorted_deterministic(ws):
    g = build(use_cache=False)
    q = discover(g)
    keys = [(-c["score"], c["kind"], c["u"], c["v"]) for c in q["candidates"]]
    assert keys == sorted(keys)


# ---------------------------------------------------------------- R10

def test_r10_same_graph_same_candidates(ws):
    g = build(use_cache=False)
    q1 = discover(g)
    q2 = discover(g)
    assert json.dumps(q1, sort_keys=True) == json.dumps(q2, sort_keys=True)


def test_r10_rebuild_same_candidates(ws):
    g1 = build(use_cache=False)
    g2 = build(use_cache=False)
    q1 = discover(g1)
    q2 = discover(g2)
    assert json.dumps(q1, sort_keys=True) == json.dumps(q2, sort_keys=True)


def test_r10_min_score_filter_deterministic(ws):
    g = build(use_cache=False)
    qa = discover(g, min_score=0.3)
    qb = discover(g, min_score=0.3)
    assert json.dumps(qa, sort_keys=True) == json.dumps(qb, sort_keys=True)
    # lower threshold -> superset of candidates
    q05 = discover(g, min_score=MIN_SCORE_PROVISIONAL)
    assert len(qa["candidates"]) >= len(q05["candidates"])


# ---------------------------------------------------------------- negative control

def test_negative_control_empty_graph():
    """Synthetic graph with no missing edges -> empty queue."""
    graph = {
        "meta": {"fingerprint": "neg", "nodes_total": 2, "edges_total": 1,
                 "edges_by_kind": {}},
        "nodes": [
            {"id": "claim:A", "kind": "claim", "dims": {}},
            {"id": "claim:B", "kind": "claim", "dims": {}},
        ],
        "edges": [
            {"source": "claim:A", "target": "claim:B",
             "kind": "correlates_with"},
        ],
    }
    q = discover(graph)
    # only 2 claims, fully connected -> no link-pred candidates
    # no directed edges -> no motifs
    # no claim dims with ts -> no temporal
    assert q["candidates"] == []
    assert q["meta"]["total_candidates"] == 0


def test_negative_control_complete_graph_small():
    """Triangle of claims fully connected -> no link-pred non-edges."""
    ids = ["claim:A", "claim:B", "claim:C"]
    nodes = [{"id": i, "kind": "claim", "dims": {}} for i in ids]
    edges = [
        {"source": "claim:A", "target": "claim:B", "kind": "correlates_with"},
        {"source": "claim:B", "target": "claim:C", "kind": "correlates_with"},
        {"source": "claim:A", "target": "claim:C", "kind": "correlates_with"},
    ]
    graph = {"meta": {"fingerprint": "tri", "nodes_total": 3,
                      "edges_total": 3, "edges_by_kind": {}},
             "nodes": nodes, "edges": edges}
    q = discover(graph)
    assert q["meta"]["total_candidates"] == 0


# ---------------------------------------------------------------- label propagation

def test_label_propagation_deterministic():
    g = __import__("networkx").Graph()
    g.add_edges_from([("a", "b"), ("b", "c"), ("x", "y")])
    l1 = label_propagation_deterministic(g)
    l2 = label_propagation_deterministic(g)
    assert l1 == l2
    # connected component {a,b,c} shares a label; {x,y} another
    assert l1["a"] == l1["b"] == l1["c"]
    assert l1["x"] == l1["y"]
    assert l1["a"] != l1["x"]


def test_label_propagation_empty():
    import networkx as nx
    assert label_propagation_deterministic(nx.Graph()) == {}


# ---------------------------------------------------------------- NO-NEW-TRUTH

def test_discover_no_new_truth(ws):
    """discover() is pure: never mutates the graph dict."""
    g = build(use_cache=False)
    before = json.dumps(g, sort_keys=True)
    discover(g)
    after = json.dumps(g, sort_keys=True)
    assert before == after


# ---------------------------------------------------------------- queue IO

def test_write_queue_roundtrip(ws, tmp_path):
    g = build(use_cache=False)
    q = discover(g)
    out = tmp_path / "dq.jsonl"
    write_queue(q, path=out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1 + len(q["candidates"])  # snapshot + candidates
    snap = json.loads(lines[0])
    assert snap["type"] == "snapshot"
    first = json.loads(lines[1]) if len(lines) > 1 else None
    if first:
        assert first["type"] == "candidate"
        assert first["status"] == "pending"


# ---------------------------------------------------------------- motifs

def test_motif_closure_detects_missing_edge():
    """A->B->C (same kind), A->C missing -> one candidate."""
    graph = {
        "meta": {"fingerprint": "m", "nodes_total": 3, "edges_total": 2,
                 "edges_by_kind": {"child_of": 2}},
        "nodes": [],
        "edges": [
            {"source": "p:A", "target": "p:B", "kind": "child_of"},
            {"source": "p:B", "target": "p:C", "kind": "child_of"},
        ],
    }
    q = discover(graph)
    motifs = [c for c in q["candidates"] if c["method"] == "triad_closure"]
    assert len(motifs) == 1
    m = motifs[0]
    assert m["u"] == "p:A" and m["v"] == "p:C" and m["via"] == "p:B"
    assert m["kind"] == "child_of"


def test_motif_excludes_contradicts():
    """contradicts is symmetric by design — no triad closure on it."""
    graph = {
        "meta": {"fingerprint": "m2", "nodes_total": 3, "edges_total": 4,
                 "edges_by_kind": {"contradicts": 4}},
        "nodes": [],
        "edges": [
            {"source": "c:A", "target": "c:B", "kind": "contradicts"},
            {"source": "c:B", "target": "c:A", "kind": "contradicts"},
            {"source": "c:B", "target": "c:C", "kind": "contradicts"},
            {"source": "c:C", "target": "c:B", "kind": "contradicts"},
        ],
    }
    q = discover(graph)
    motifs = [c for c in q["candidates"] if c["method"] == "triad_closure"]
    assert motifs == [], "contradicts must not produce triad candidates"
