"""Build tests: 9 kinds, 6 edges, R10 determinism, D3 identity,
NO-NEW-TRUTH, cache reconstruction, views, CLI."""
import json
import os
from pathlib import Path

import pytest

from epistemic_graph import build, by_dim, by_kind, to_dot, to_json
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

def test_nine_kinds_and_six_edge_kinds(ws):
    g = build(use_cache=False)
    present_kinds = {n["kind"] for n in g["nodes"]}
    assert present_kinds == set(KINDS), present_kinds
    present_edges = {e["kind"] for e in g["edges"]}
    assert present_edges == set(EDGE_KINDS), present_edges


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
    assert m["skipped"].get("claims_without_document") == 1  # orphan subject


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
    assert main(["export", "--format", "json", "--kind", "rule",
                 "--no-cache"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["nodes"][0]["kind"] == "rule"
    assert main(["show", "--kind", "gap", "--no-cache"]) == 0
    assert "gap:" in capsys.readouterr().out
