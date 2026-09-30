"""test_router — EP-2 of EPISTEMIC-CERT-001: claim-gate routing, F16,
decide (H2) and trace persistence.

Negative control of the plan: a conformance claim at risk=delivery with
monocanal evidence must land on route R1 with status=FAIL (exit 1).
All stores and traces are sandboxed (tmp EpicStore root + VOSLAB_PATH).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import vos_kernel.router as router
from vos_kernel.epistemic import EpicStore
from vos_kernel.router import decide, route_all, route_claim


# ------------------------------------------------------------------ helpers


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_claim(**over) -> dict:
    base = {
        "id": "CL-TEST-001",
        "text": "sample claim text",
        "type": "theorem",
        "subject": "unit",
        "risk": "internal",
        "status": "DECLARED",
        "provenance": "test",
        "certs": [],
    }
    base["text_hash"] = _hash(base["text"])
    base.update(over)
    if "text" in over and "text_hash" not in over:
        base["text_hash"] = _hash(over["text"])
    return base


@pytest.fixture()
def store(tmp_path):
    return EpicStore(root=tmp_path)


@pytest.fixture()
def traces(tmp_path, monkeypatch):
    """Redirect the tree_trace store into tmp and return the file."""
    monkeypatch.setenv("VOSLAB_PATH", str(tmp_path))
    return tmp_path / "state" / "rsi" / "tree_traces.jsonl"


def _shapes(trace_file: Path) -> list[str]:
    if not trace_file.exists():
        return []
    return [json.loads(ln)["tree_shape"]
            for ln in trace_file.read_text().splitlines() if ln.strip()]


# ------------------------------------------------------------------- routes


def test_route_r1_machine(traces, store):
    claim = make_claim()
    res = route_claim(claim, store=store)
    assert res["route"] == "R1"
    assert res["verdict"] == "PASS"
    assert res["status"] == "DECLARED"
    assert res["required_certs"] == ["FORMAL", "PREDICATE"]
    assert res["f16"] == "not-subject"
    assert res["tree_shape"].startswith("claim_gate(")
    assert any(s.startswith("claim_gate(") for s in _shapes(traces))


def test_route_r0_recycles_hash_matched_cert(traces, store):
    claim = make_claim(status="CERTIFIED", certs=["CRT-T-001"])
    cert = {
        "id": "CRT-T-001",
        "claim_id": claim["id"],
        "class": "FORMAL",
        "executor_ref": "test-exec",
        "inputs_digest": claim["text_hash"],
        "verdict": "pass",
        "observed_at": "2026-09-28T00:10:10Z",
        "independent": False,
    }
    store.append("certs", cert)
    res = route_claim(claim, store=store)
    assert res["route"] == "R0"
    assert res["status"] == "CERTIFIED"
    assert res["required_certs"] == []
    assert res["verdict"] == "PASS"


def test_route_r0_f16_ceiling(traces, store):
    """A passing FORMAL cert without an independent channel cannot lift a
    conformance@delivery claim past OBSERVED (F16 holds at R0 too)."""
    claim = make_claim(type="conformance", risk="delivery",
                       status="CERTIFIED", certs=["CRT-T-002"])
    cert = {
        "id": "CRT-T-002",
        "claim_id": claim["id"],
        "class": "FORMAL",
        "executor_ref": "test-exec",
        "inputs_digest": claim["text_hash"],
        "verdict": "pass",
        "observed_at": "2026-09-28T00:11:11Z",
        "independent": False,
    }
    store.append("certs", cert)
    res = route_claim(claim, store=store)
    assert res["route"] == "R0"
    assert res["status"] == "OBSERVED"
    assert res["f16"] == "violated"
    assert res["verdict"] == "PASS"  # the link works; the ceiling applies


def test_route_r2_observed(traces, store):
    claim = make_claim(type="empirical")
    res = route_claim(claim, store=store)
    assert res["route"] == "R2"
    assert res["status"] == "OBSERVED"
    assert res["required_certs"] == ["PREDICATE", "IDENTITY"]


def test_route_r3_interpretation_ceiling_before_machine(traces, store):
    """Even machine-checkable interpretations take R3: the semantic never
    ascends via FORMAL/PREDICATE."""
    claim = make_claim(type="interpretation", checkable="machine")
    res = route_claim(claim, store=store)
    assert res["route"] == "R3"
    assert res["status"] == "INTERPRETIVE"
    assert res["required_certs"] == ["AUDIT"]


def test_trace_records_home_and_context(traces, store):
    """F1/F2: the persisted trace carries the winning home + full ctx
    values — the decision explanation the root truth alone cannot give
    (AND short-circuits before the discriminating predicates)."""
    claim = make_claim(type="interpretation")
    res = route_claim(claim, store=store)
    rows = [json.loads(ln) for ln in
            traces.read_text().splitlines() if ln.strip()]
    row = rows[-1]
    assert row["trace_id"] == res["trace_id"]
    assert row["home"] == "R3"
    assert row["context"]["claim_type"] == "interpretation"
    assert row["context"]["cert_present"] == "false"


def test_trace_home_raw_for_fail_route(traces, store):
    """R1-FAIL collapses to route=R1 in the result, but the trace keeps
    the raw home (auditable distinction)."""
    claim = make_claim(type="conformance", risk="delivery",
                       checkable="machine")
    res = route_claim(claim, store=store)
    assert res["route"] == "R1"
    assert res["status"] == "FAIL"
    row = json.loads(traces.read_text().splitlines()[-1])
    assert row["home"] == "R1-FAIL"


def test_trace_textual_predicates(traces, store):
    """F3: nodes carry the predicates as written — including the branches
    the AND short-circuit never evaluated."""
    claim = make_claim(type="interpretation")
    route_claim(claim, store=store)
    row = json.loads(traces.read_text().splitlines()[-1])
    by_type = {}
    for n in row["nodes"]:
        by_type.setdefault(n["type"], []).append(n)
    # evaluated root predicate, literal + home marker
    p0 = by_type["predicate"][0]
    assert p0["text"] == "ctx_equals($ctx, cert_present, true) -> R0"
    assert p0["args"] == ["$ctx", "cert_present", "true"]
    # F4: each node carries the literal question it asks
    assert "certificado con hash" in p0["question"]
    # untouched branches still readable (short-circuit placeholders)
    sc_texts = [n["text"] for n in by_type.get("short_circuit", [])]
    assert any("ctx_equals($ctx, claim_type, interpretation) -> R3" in t
               for t in sc_texts)
    assert any("falsifier" in t for t in sc_texts)
    sc_q = [n["question"] for n in by_type.get("short_circuit", [])]
    assert any("interpretación" in (q or "") for q in sc_q)
    assert any("falsificador" in (q or "") for q in sc_q)


def test_route_r4_decision_blocked(traces, store):
    claim = make_claim(type="decision")
    res = route_claim(claim, store=store)
    assert res["route"] == "R4"
    assert res["verdict"] == "FAIL"
    assert res["status"] == "FAIL"
    assert res["decide"]["outcome"] == "blocked"
    shapes = _shapes(traces)
    assert any(s.startswith("decide(") for s in shapes)
    assert any(s.startswith("claim_gate(") for s in shapes)


def test_route_r4_decision_approved(traces, store):
    claim = make_claim(type="decision", alternatives=["a", "b"],
                       impact="session flow", reversible=True)
    res = route_claim(claim, store=store)
    assert res["route"] == "R4"
    assert res["verdict"] == "PASS"
    assert res["decide"]["outcome"] == "approved"


def test_route_r5_unknown(traces, store):
    claim = make_claim(type="procedure")
    res = route_claim(claim, store=store)
    assert res["route"] == "R5"
    assert res["status"] == "UNKNOWN"
    assert res["verdict"] == "PASS"  # declared UNKNOWN is legitimate (F10)


# ------------------------------------------------- F16 negative control


def test_f16_monocanal_control_negative(traces, store, tmp_path):
    """Plan EP-2 control: conformance@delivery monocanal => route R1,
    status FAIL, CLI exit 1."""
    claim = make_claim(id="CL-F16-NEG", type="conformance", risk="delivery",
                       status="DECLARED", certs=[])
    res = route_claim(claim, store=store)
    assert res["route"] == "R1"
    assert res["status"] == "FAIL"
    assert res["verdict"] == "FAIL"
    assert res["f16"] == "violated"
    assert res["required_certs"] == ["FORMAL", "PREDICATE", "INDEPENDENT"]

    # CLI exit code path (sandbox the store; the file claim routes FAIL)
    claim_file = tmp_path / "f16.json"
    claim_file.write_text(json.dumps(claim))
    orig = router.EpicStore
    router.EpicStore = lambda *a, **k: orig(root=tmp_path)
    try:
        rc = router.main(["route", str(claim_file)])
    finally:
        router.EpicStore = orig
    assert rc == 1


def test_f16_independent_channel_passes(traces, store):
    claim = make_claim(id="CL-F16-POS", type="conformance", risk="delivery",
                       status="DECLARED", certs=[], independent_source=True)
    res = route_claim(claim, store=store)
    assert res["route"] == "R1"
    assert res["status"] == "DECLARED"
    assert res["verdict"] == "PASS"
    assert res["f16"] == "satisfied"


# ------------------------------------------------------- decide (H2) + DEC


def test_decide_records_dec_with_trace(traces, store):
    res = decide("ship the router now",
                 alternatives=["ship", "defer"],
                 impact="EP-2 exit",
                 store=store,
                 logger=router._trace_logger())
    assert res["outcome"] == "approved"
    decs = store.load("decisions")
    assert len(decs) == 1
    assert decs[0]["tree_trace_id"] == res["trace_id"]
    assert decs[0]["outcome"] == "approved"
    assert any(s.startswith("decide(") for s in _shapes(traces))


def test_decide_irreversible_needs_approval(traces, store):
    res = decide("drop the old ledger",
                 alternatives=["keep", "drop"],
                 impact="history loss",
                 reversible=False,
                 approved=False,
                 store=store,
                 logger=router._trace_logger())
    assert res["outcome"] == "blocked"


# ------------------------------------------------------- determinism, all


def test_route_deterministic(traces, store):
    claim = make_claim(type="empirical")
    a = route_claim(dict(claim), store=store)
    b = route_claim(dict(claim), store=store)
    keep = ("claim_id", "route", "status", "verdict", "required_certs",
            "f16")
    assert {k: a[k] for k in keep} == {k: b[k] for k in keep}


def test_route_all_store(traces, store):
    for i in range(3):
        store.append("claims", make_claim(id=f"CL-ALL-{i}"))
    rep = route_all(store=store, logger=router._trace_logger())
    assert rep["routed"] == 3
    assert rep["routes"] == {"R1": 3}
    assert rep["failed"] == []
    assert len(_shapes(traces)) == 3


def test_invalid_claim_rejected(traces, store):
    with pytest.raises(ValueError):
        route_claim({"id": "x"}, store=store)
