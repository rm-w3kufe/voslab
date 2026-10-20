# design: docs/plans/graph_phase3_plan.vsm (SUT: packages/framework/epistemic_graph/graph_health.py)
"""graph_health tests: R10 determinism, per-layer denominators, acyclic
check, fiedler honest denominators, fixture reconstruction (NO-NEW-TRUTH)."""
import json

import pytest

from epistemic_graph import build, health
from epistemic_graph.graph_health import (
    ACYCLIC_KINDS, BETWEENNESS_TOP_N, LAYERS, SCHEMA,
    write_snapshot,
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
    h = health(g)
    assert h["schema"] == SCHEMA
    assert h["fingerprint"] == g["meta"]["fingerprint"]
    assert h["nodes_total"] == len(g["nodes"])
    assert h["edges_total"] == len(g["edges"])
    assert set(h["layers"]) == {name for name, _, _ in LAYERS}
    assert set(h["acyclic_check"]) == set(ACYCLIC_KINDS)


def test_layer_denominators_and_kinds(ws):
    """Every layer reports its own nodes/edges and edge_kinds match.

    Undirected layers (correlacion): bidirectional source pairs (A->B and
    B->A, ratified '<->') collapse to ONE undirected edge — count unique
    unordered pairs, not directed rows.
    """
    g = build(use_cache=False)
    h = health(g)
    edge_kind_total = 0
    for name, kinds, directed in LAYERS:
        entry = h["layers"][name]
        assert entry["edge_kinds"] == list(kinds)
        kind_edges = [e for e in g["edges"] if e["kind"] in kinds]
        if directed:
            want_edges = len(kind_edges)
        else:
            pairs = {(e["source"], e["target"]) for e in kind_edges}
            want_edges = len({tuple(sorted(p)) for p in pairs})
        assert entry["edges"] == want_edges, name
        if directed:
            assert "is_dag" in entry and "cyclic_sccs" in entry
        else:
            assert "is_dag" not in entry and "cyclic_sccs" not in entry
        edge_kind_total += want_edges
    # fixture covers all 10 edge kinds across the 4 layers (undirected
    # correlacion collapses pairs, so total directed rows >= layer sum)
    assert edge_kind_total <= len(g["edges"])


def test_density_range(ws):
    g = build(use_cache=False)
    h = health(g)
    for name, entry in h["layers"].items():
        assert 0.0 <= entry["density"] <= 1.0, name


def test_degree_p_k_sorted_and_sums(ws):
    g = build(use_cache=False)
    h = health(g)
    for name, entry in h["layers"].items():
        pk = entry["degree_p_k"]
        ks = [k for k, _ in pk]
        assert ks == sorted(ks), name
        assert sum(c for _, c in pk) == entry["nodes"], name


# ---------------------------------------------------------------- R10

def test_r10_same_graph_same_health(ws):
    g = build(use_cache=False)
    h1 = health(g)
    h2 = health(g)
    assert json.dumps(h1, sort_keys=True) == json.dumps(h2, sort_keys=True)


def test_r10_rebuild_same_health(ws):
    """Two independent builds (no cache) -> identical health (R10)."""
    g1 = build(use_cache=False)
    g2 = build(use_cache=False)
    h1 = health(g1)
    h2 = health(g2)
    assert json.dumps(h1, sort_keys=True) == json.dumps(h2, sort_keys=True)


# ---------------------------------------------------------------- acyclic

def test_acyclic_check_dag_kinds(ws):
    """child_of/derived_from/supersedes must be acyclic (fixture is clean)."""
    g = build(use_cache=False)
    h = health(g)
    for kind, entry in h["acyclic_check"].items():
        assert entry["is_dag"] is True, kind
        assert entry["cyclic_sccs"] == 0, kind


def test_acyclic_check_detects_cycle():
    """Synthetic cycle in supersedes -> flagged (gate candidate 3c)."""
    graph = {
        "meta": {"fingerprint": "x", "nodes_total": 3, "edges_total": 3,
                 "edges_by_kind": {"supersedes": 3}},
        "nodes": [],
        "edges": [
            {"source": "A", "target": "B", "kind": "supersedes"},
            {"source": "B", "target": "C", "kind": "supersedes"},
            {"source": "C", "target": "A", "kind": "supersedes"},
        ],
    }
    h = health(graph)
    sup = h["acyclic_check"]["supersedes"]
    assert sup["is_dag"] is False
    assert sup["cyclic_sccs"] == 1


# ---------------------------------------------------------------- fiedler

def test_fiedler_null_when_lt2_nodes():
    graph = {"meta": {}, "nodes": [],
             "edges": [{"source": "only", "target": "only2",
                        "kind": "correlates_with"}]}
    # 2 nodes undirected layer -> fiedler present
    h = health(graph)
    assert h["layers"]["correlacion"]["nodes"] == 2
    assert h["layers"]["correlacion"]["fiedler"] is not None
    # empty directed layers -> null (honest denominator)
    assert h["layers"]["estructura"]["fiedler"] is None


def test_fiedler_connected_vs_disconnected():
    # connected path A-B-C on correlates_with
    conn = {"meta": {}, "nodes": [],
            "edges": [
                {"source": "A", "target": "B", "kind": "correlates_with"},
                {"source": "B", "target": "C", "kind": "correlates_with"},
            ]}
    # disconnected: A-B and C-D
    disc = {"meta": {}, "nodes": [],
            "edges": [
                {"source": "A", "target": "B", "kind": "correlates_with"},
                {"source": "C", "target": "D", "kind": "correlates_with"},
            ]}
    f_conn = health(conn)["layers"]["correlacion"]["fiedler"]
    f_disc = health(disc)["layers"]["correlacion"]["fiedler"]
    assert f_conn is not None and f_conn > 0
    assert f_disc is not None and f_disc == 0.0  # disconnected -> 0


# ---------------------------------------------------------------- betweenness

def test_betweenness_top_bounded(ws):
    g = build(use_cache=False)
    h = health(g)
    for name, entry in h["layers"].items():
        bk = entry["betweenness_top"]
        assert len(bk) <= BETWEENNESS_TOP_N, name
        # ordered by (-value, id) — non-increasing values
        vals = [v for _, v in bk]
        assert vals == sorted(vals, reverse=True), name


# ---------------------------------------------------------------- snapshot IO

def test_write_snapshot_roundtrip(ws, tmp_path):
    g = build(use_cache=False)
    h = health(g)
    out = tmp_path / "gh.json"
    write_snapshot(h, path=out)
    loaded = json.loads(out.read_text())
    assert loaded == h


def test_health_no_new_truth(ws):
    """health is pure view: never mutates the graph dict."""
    g = build(use_cache=False)
    before = json.dumps(g, sort_keys=True)
    health(g)
    after = json.dumps(g, sort_keys=True)
    assert before == after
