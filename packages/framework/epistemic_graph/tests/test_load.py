"""Loader tests: tolerance + denominators (never silent)."""
import json

import pytest

from epistemic_graph import load as L
from .fixtures import write_workspace


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = write_workspace(tmp_path)
    monkeypatch.setenv("VOSLAB_PATH", str(root))
    return root


def test_traces_malformed_counted(ws):
    traces, skipped = L.load_traces()
    assert len(traces) == 4
    assert skipped == 1  # trailing "{bad json"


def test_claims_and_routes(ws):
    out = L.load_claims()
    assert out["files"] == 1
    assert len(out["claims"]) == 6  # fase-2 fixture: 4 main + 2 orphan
    assert out["routes"]["SRC-MAIN-aaaa-C001"]["verdict"] == "PASS"
    assert out["skipped"] == 0
    assert out["ts_by_stem"]["main"] == "2026-10-01T10:11:12Z"


def test_claims_missing_file_zero(ws):
    (ws / "state/epistemic/sidecars/main.claims.vsm").unlink()
    out = L.load_claims()
    assert out["claims"] == [] and out["files"] == 0


def test_depth_fields(ws):
    out = L.load_depth()
    rec = out["docs"]["main"]
    assert rec["levels"] == ["L1", "L2"]
    assert rec["span"] == "L1-L2"
    assert rec["status"] == "active"
    assert rec["ts"] == "2026-10-01T10:10:10Z"
    assert out["skipped"] == 0


def test_rules_first_occurrence_wins(ws):
    out = L.load_rules()
    keys = [r["key"] for r in out["rules"]]
    assert keys == ["R1_locality", "R5_canon_over_recall"]
    assert out["status"] == "ratified"


def test_experiments_token_grammar(ws):
    out = L.load_experiments()
    # EXP-AB-01 + EXP-LY-01; brace-expansion EXP-NC-0{1,2} style excluded
    assert out["ids"] == ["EXP-AB-01", "EXP-LY-01"]


def test_decisions_focus_and_registry(ws):
    out = L.load_decisions()
    ids = [d["id"] for d in out["decisions"]]
    assert "decision:F-TEST-1" in ids
    assert "decision:PLAN-TEST-2" in ids
    plan2 = next(d for d in out["decisions"] if d["ref"] == "PLAN-TEST-2")
    assert plan2["status"] == "active"  # block-scoped status, not template


def test_gaps(ws):
    out = L.load_gaps()
    assert [g["id"] for g in out["gaps"]] == ["sample-gap"]


def test_fingerprint_content_not_mtime(ws):
    paths = L.source_files()
    fp1 = L.fingerprint(paths)
    import os
    st = (ws / "current_focus.json").stat()
    os.utime(ws / "current_focus.json", (st.st_atime, st.st_mtime + 999))
    assert L.fingerprint(paths) == fp1  # touch alone must NOT change fp
    (ws / "current_focus.json").write_text("[]")  # byte change must
    assert L.fingerprint(paths) != fp1
