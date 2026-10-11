"""Build tests: 9 kinds, 10 edge kinds (6 MVP + 4 fase-2), R10 determinism,
D3 identity, NO-NEW-TRUTH, cache reconstruction, views, CLI."""
import json
import os
from pathlib import Path

import pytest

from epistemic_graph import build, by_dim, by_edge, by_kind, to_dot, to_json
from epistemic_graph.graph import KINDS, EDGE_KINDS
from epistemic_graph import load as L
from .fixtures import write_workspace


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = write_workspace(tmp_path)
    monkeypatch.setenv("VOSLAB_PATH", str(root))
    return root


def _digest_sources(root: Path) -> dict:
    out = {}
    for p in sorted(L.source_files()):
        if p.is_file():
            out[str(p)] = p.read_bytes()
    return out


# ---------------------------------------------------------------- structure

def test_exact_kinds_and_edge_kinds(ws):
    g = build(use_cache=False)
    present_kinds = {n["kind"] for n in g["nodes"]}
    assert present_kinds == set(KINDS), present_kinds
    present_edges = {e["kind"] for e in g["edges"]}
    assert present_edges == set(EDGE_KINDS), present_edges  # fixture: all 10


def test_base_dims_on_every_node(ws):
    g = build(use_cache=False)
    for n in g["nodes"]:
        d = n["dims"]
        assert set(("kind", "status", "source", "ts")) <= set(d), n["id"]
        assert d["kind"] == n["kind"]


def test_denominators_sum(ws):
    g = build(use_cache=False)
    m = g["meta"]
    assert m["nodes_total"] == len(g["nodes"]) == sum(
        m["nodes_by_kind"].values())
    assert m["edges_total"] == len(g["edges"]) == sum(
        m["edges_by_kind"].values())
    # fixture reports its skips explicitly
    assert m["skipped"].get("traces_malformed") == 1
    assert m["skipped"].get("claim_duplicate_content") == 1  # C002 dup
    assert m["skipped"].get("claims_without_document") == 2  # 2 orphan claims


def test_certificates_and_claim_edges(ws):
    g = build(use_cache=False)
    cert = next(n for n in g["nodes"] if n["kind"] == "certificate")
    assert cert["id"].startswith("certificate:SRC-MAIN-aaaa-C001#")
    kinds = {(e["source"].split(":")[0], e["target"].split(":")[0],
              e["kind"]) for e in g["edges"]}
    assert ("certificate", "claim", "derived_from") in kinds
    assert ("claim", "certificate", "certified_by") in kinds
    assert ("claim", "document", "extracted_from") in kinds
    assert ("answer", "predicate", "answers") in kinds
    assert ("predicate", "predicate", "child_of") in kinds
    assert ("experiment", "claim", "correlates_with") in kinds
    assert ("claim", "experiment", "correlates_with") in kinds  # '<->' ratified


# ---------------------------------------------------------------- fase-2

def test_fase2_certified_by_cruzado(ws):
    """trace.context.claim_id -> claim certified by the trace's root."""
    g = build(use_cache=False)
    claim = next(n["id"] for n in g["nodes"]
                 if n["id"].startswith("claim:SRC-MAIN-aaaa|"))
    pred = {e["target"] for e in g["edges"]
            if e["source"] == claim and e["kind"] == "certified_by"
            and e["target"].startswith("predicate:")}
    assert pred, "cruzado edge missing"
    f2 = g["meta"]["sources"]["fase2"]["certified_by_cruzado"]
    assert f2 == {"traces_with_claim_ref": 1, "matched_claim_nodes": 1,
                  "unmatched_claim_refs": 0}


def test_fase2_contradicts_refutes_supersedes(ws):
    g = build(use_cache=False)
    pairs = {(e["source"], e["target"]) for e in g["edges"]
             if e["kind"] == "contradicts"}
    # symmetric: 4 comparable pairs x 2 arcs
    assert len(pairs) == 8, pairs
    c1 = next(n["id"] for n in g["nodes"]
              if n["id"].startswith("claim:SRC-ORPH-eeee|999000"))
    c2 = next(n["id"] for n in g["nodes"]
              if n["id"].startswith("claim:SRC-ORPH-eeee|fffee3"))
    # counter-claim refutes the REFUTED one (exactly one arc)
    assert (c2, c1) in {(e["source"], e["target"]) for e in g["edges"]
                        if e["kind"] == "refutes"}
    assert not any(e["kind"] == "refutes" and e["source"] == c1
                   for e in g["edges"])
    # supersedes: C004 (highest ordinal, different text) -> older restatements
    sup = [(e["source"], e["target"]) for e in g["edges"]
           if e["kind"] == "supersedes"]
    assert len(sup) == 2 and all("C004" not in t for _, t in sup)
    assert all("|ccc444" in s for s, _ in sup)


def test_fase2_resolves_requires_resolved_status(ws):
    g = build(use_cache=False)
    res = [e for e in g["edges"] if e["kind"] == "resolves"]
    assert [(e["source"], e["target"]) for e in res] == \
        [("decision:F-TEST-1", "gap:sample-gap")]
    f2 = g["meta"]["sources"]["fase2"]["resolves"]
    assert f2 == {"gaps_resolved_status": 1, "decisions_naming": 1, "edges": 1}


def test_fase2_denominators_reported(ws):
    g = build(use_cache=False)
    f2 = g["meta"]["sources"]["fase2"]
    assert f2["contradicts"]["claims_quantity_comparable"] == 6
    assert f2["contradicts"]["pairs_different_value"] == 4
    assert f2["supersedes"]["groups_same_value"] == 1
    assert f2["supersedes"]["edges_different_text"] == 2
    assert g["meta"]["edge_kinds_fase2"] == ["contradicts", "refutes",
                                             "supersedes", "resolves"]


def test_experiments_exclude_brace_expansion(ws):
    g = build(use_cache=False)
    exp_ids = {n["id"] for n in g["nodes"] if n["kind"] == "experiment"}
    assert exp_ids == {"experiment:EXP-AB-01", "experiment:EXP-LY-01"}


# ---------------------------------------------------------------- R10 / D3

def test_determinism_same_input_same_graph(ws):
    a = build(use_cache=False)
    b = build(use_cache=False)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_identity_survives_touch(ws):
    a = build(use_cache=False)
    st = (ws / "state/epistemic/sidecars/main.claims.vsm").stat()
    os.utime(ws / "state/epistemic/sidecars/main.claims.vsm",
             (st.st_atime, st.st_mtime + 999))
    b = build(use_cache=False)
    assert [n["id"] for n in a["nodes"]] == [n["id"] for n in b["nodes"]]


def test_identity_changes_when_artifact_bytes_change(ws):
    a = build(use_cache=False)
    doc_ids_a = {n["id"] for n in a["nodes"] if n["kind"] == "document"}
    (ws / "docs/x/main.tex").write_text("changed content\n")
    b = build(use_cache=False)
    doc_ids_b = {n["id"] for n in b["nodes"] if n["kind"] == "document"}
    assert doc_ids_a != doc_ids_b  # content-keyed: fingerprint in identity


# ---------------------------------------------------------------- NO-NEW-TRUTH

def test_build_never_writes_sources(ws):
    before = _digest_sources(ws)
    build(use_cache=False)
    build(use_cache=True)  # cache write allowed, but ONLY at cache path
    after = _digest_sources(ws)
    assert before == after


def test_cache_is_disposable_rebuild_identical(ws):
    a = build(use_cache=True)
    cache = ws / "state/epistemic/graph_cache.json"
    assert cache.is_file()
    cached = build(use_cache=True)
    assert cached["meta"]["cache_hit"] is True
    assert [n["id"] for n in a["nodes"]] == [n["id"] for n in cached["nodes"]]
    cache.unlink()  # delete the cache: full reconstruction from source
    rebuilt = build(use_cache=True)
    assert rebuilt["meta"]["cache_hit"] is False
    assert json.dumps(a, sort_keys=True) == json.dumps(rebuilt, sort_keys=True)


def test_byte_change_invalidates_cache(ws):
    a = build(use_cache=True)
    assert a["meta"]["cache_hit"] is False
    (ws / "current_focus.json").write_text(
        json.dumps([{"ref": "F-NEW", "status": "active",
                     "updated_at": "2026-10-03T10:00:00Z"}]))
    b = build(use_cache=True)
    assert b["meta"]["cache_hit"] is False  # fingerprint changed -> rebuild
    assert any(n["id"] == "decision:F-NEW" for n in b["nodes"])


# ---------------------------------------------------------------- views

def test_view_by_kind(ws):
    g = build(use_cache=False)
    v = by_kind(g, "claim")
    assert v["nodes"] and all(n["kind"] == "claim" for n in v["nodes"])
    assert v["meta"]["nodes_total"] == len(v["nodes"])


def test_view_by_dim(ws):
    g = build(use_cache=False)
    v = by_dim(g, "status", "DECLARED")
    assert v["nodes"] and all(
        n["dims"].get("status") == "DECLARED" for n in v["nodes"])
    v2 = by_dim(g, "truth", "Truth.TRUE")
    assert all(n["dims"].get("truth") == "Truth.TRUE" for n in v2["nodes"])


def test_view_by_edge(ws):
    """FASE-2 vista: endpoints of one edge kind (cross views)."""
    g = build(use_cache=False)
    v = by_edge(g, "certified_by")
    assert v["edges"] and all(e["kind"] == "certified_by"
                              for e in v["edges"])
    ids = {e["source"] for e in v["edges"]} | {e["target"] for e in v["edges"]}
    assert {n["id"] for n in v["nodes"]} == ids
    assert v["meta"]["view"] == "edge:certified_by"
    v2 = by_edge(g, "resolves")
    assert [e["target"] for e in v2["edges"]] == ["gap:sample-gap"]


# ---------------------------------------------------------------- export/CLI

def test_exports_deterministic(ws):
    g = build(use_cache=False)
    assert to_dot(g) == to_dot(g)
    env = to_json(g)
    assert env["graph"] == "epistemic"
    assert len(env["nodes"]) == g["meta"]["nodes_total"]
    assert len(env["links"]) == g["meta"]["edges_total"]


def test_cli_stats_and_export(ws, capsys):
    from epistemic_graph.cli import main
    assert main(["stats", "--no-cache"]) == 0
    out = capsys.readouterr().out
    assert "node answer:" in out and "edge answers:" in out
    assert "fase2" in out  # fase-2 denominators surfaced in stats
    assert main(["export", "--format", "json", "--kind", "rule",
                 "--no-cache"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["nodes"][0]["kind"] == "rule"
    assert main(["show", "--kind", "gap", "--no-cache"]) == 0
    assert "gap:" in capsys.readouterr().out
    assert main(["export", "--format", "json", "--edge", "resolves",
                 "--no-cache"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["meta"]["view"] == "edge:resolves"
    assert env["links"][0]["kind"] == "resolves"
