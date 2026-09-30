"""End-to-end pipeline: extract -> validate -> route -> ledger (isolated)."""
from __future__ import annotations

from pathlib import Path

import pytest

from vos_kernel.epistemic import EpicStore, load_sidecar
from vos_kernel.utils.vsm_kernel import validate_vsm_content

from claim_ingest import ingest_text

_ABSTRACT = "The mechanism reaches n = 10 at scale."
_BODY = (
    "Convergence reaches n = 10 after the update. "
    "The panel reports 24/24 checks passed. "
    "All prices remain non-negative under every scheduled update."
)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Redirect traces + registry + ledger root to tmp (VOSLAB_PATH is
    re-read at runtime; write_ledger guards on repo_root)."""
    (tmp_path / "state" / "rsi").mkdir(parents=True)
    monkeypatch.setenv("VOSLAB_PATH", str(tmp_path))
    import claim_ingest.ledger.ledger as L
    monkeypatch.setattr(L, "repo_root", lambda: tmp_path)
    return tmp_path


def test_ingest_end_to_end(isolated):
    store = EpicStore(isolated)
    out = ingest_text(
        "", name="demo_artifact.vsm",
        sections={"abstract": _ABSTRACT, "body": _BODY},
        store=store, route=True,
        ledger_path=isolated / "out" / "demo.claims.vsm",
    )
    # claims extracted + agent none
    assert len(out["claims"]) == 4
    assert out["source_id"].startswith("SRC-DEMO-ARTIFACT-")
    # every claim registry-valid and routed
    assert len(out["routes"]) == len(out["claims"])
    assert all(r.get("trace_id") for r in out["routes"])
    # coverage: all DECLARED -> untested, denominators present
    cov = out["coverage"]
    assert cov["untested"] == 4 and cov["total"] == 4
    assert cov["untested"] + cov["verified"] + cov["refuted"] \
        + cov["out_of_scope"] == cov["total"]
    assert sum(cov["routes"].values()) == 4
    # internal: abstract n=10 corroborated by body n=10
    assert out["internal"]["abstract"]["unmatched"] == []
    assert out["internal"]["contradictions"] == []
    assert out["internal"]["pairs_checked"] <= out["internal"] \
        ["pairs_comparable"] <= out["internal"]["pairs_total"]
    # ledger on disk: valid VSM + loadable claims
    lp = Path(out["ledger_path"])
    assert lp.exists()
    assert validate_vsm_content(lp.read_text())["valid"]
    loaded = load_sidecar(lp)
    assert {c["id"] for c in loaded} == {c["id"] for c in out["claims"]}
    assert "coverage = " in lp.read_text()
    # traces landed under redirected VOSLAB_PATH (rmw3 watches these)
    traces = isolated / "state" / "rsi" / "tree_traces.jsonl"
    assert traces.exists() and traces.stat().st_size > 0


def test_agent_claims_labeled_and_sequenced(isolated):
    store = EpicStore(isolated)
    out = ingest_text(
        "K0 = 5 at start.", name="doc.vsm", store=store, route=False,
        agent_claims=[
            {"text": "the compiler rejects malformed trees",
             "type": "conformance", "section": "agent"},
            {"text": "internal reading of the design", "type": "interpretation",
             "scope": "out_of_scope"},
        ],
    )
    methods = [c["method"] for c in out["claims"]]
    assert methods == ["deterministic", "agent", "agent"]
    ids = [c["id"] for c in out["claims"]]
    assert ids == [f"{out['source_id']}-C001",
                   f"{out['source_id']}-C002",
                   f"{out['source_id']}-C003"]
    # explicit out_of_scope never folds into untested
    assert out["coverage"]["out_of_scope"] == 1
    assert out["coverage"]["untested"] == 2


def test_ingest_determinism(isolated):
    store = EpicStore(isolated)
    kw = dict(name="doc.vsm", sections={"abstract": _ABSTRACT,
                                        "body": _BODY},
              store=store, route=False)
    a = ingest_text("", **kw)
    b = ingest_text("", **kw)
    assert [c["id"] for c in a["claims"]] == [c["id"] for c in b["claims"]]
    assert a["coverage"] == b["coverage"]
    assert a["internal"] == b["internal"]
    assert a["fingerprint"] == b["fingerprint"]


def test_contradiction_blocks_certified(isolated):
    from claim_ingest.internal import (
        ContradictionBlocked,
        ensure_certifiable,
        internal_check,
    )

    store = EpicStore(isolated)
    # contradictory pair is INGESTED fine (visible, DECLARED)
    out = ingest_text("", name="conflict.vsm",
                      sections={"body": "mu = 5. mu = 6."},
                      store=store, route=False)
    assert out["internal"]["contradictions"], "conflict must be visible"
    assert out["coverage"]["untested"] == 2  # visible, not certified
    # ...but certification of either side is refused (block rule)
    claims = [dict(c, status="CERTIFIED") for c in out["claims"]]
    chk = internal_check(claims)
    with pytest.raises(ContradictionBlocked):
        ensure_certifiable(claims[0], chk)


def test_register_is_idempotent(isolated):
    store = EpicStore(isolated)
    kw = dict(name="doc.vsm", store=store, route=False, register=True)
    a = ingest_text("K0 = 5 at start.", **kw)
    n = len(store.load("claims"))
    assert n == len(a["claims"]) > 0
    b = ingest_text("K0 = 5 at start.", **kw)  # same content re-ingest
    assert len(store.load("claims")) == n  # upsert, no duplicates
    assert [c["id"] for c in b["claims"]] == [c["id"] for c in a["claims"]]


def test_r10_no_randomness_in_sources():
    import claim_ingest as pkg
    root = Path(pkg.__file__).parent
    for py in root.rglob("*.py"):
        if "tests" in py.parts:
            continue
        src = py.read_text()
        assert "import random" not in src, py
        assert "from random" not in src, py
        assert "time.time(" not in src, py
