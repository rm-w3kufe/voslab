"""Tests for handoff.py — S4→S5 consent-rail (second-order-loop F0).

Deterministic (R10): no randomness; same input → same rail. Verifies the
consent mapping, the routing (needs-nod→alert, advisory→rastro), idempotency,
and that dry_run performs no writes.
"""
from __future__ import annotations

import json
from pathlib import Path

from vos_kernel import handoff


# ── consent classification (R10: pure + deterministic) ──────────────────────
def test_classify_consent_mapping():
    assert handoff.classify_consent("discovery") == "advisory"
    assert handoff.classify_consent("rsi-predicate") == "needs-nod"
    assert handoff.classify_consent("read-only") == "read-only"


def test_classify_consent_deterministic():
    # Same input always yields the same rail (R10) — 50 repeats, no drift.
    for _ in range(50):
        assert handoff.classify_consent("discovery") == "advisory"
        assert handoff.classify_consent("rsi-predicate") == "needs-nod"


def test_classify_consent_explicit_overrides_source():
    assert handoff.classify_consent("discovery", explicit="needs-nod") == "needs-nod"
    assert handoff.classify_consent("rsi-predicate", explicit="read-only") == "read-only"


def test_classify_consent_unknown_source_is_safest():
    # Unknown source → needs-nod (safest rail), never silent auto-approve.
    assert handoff.classify_consent("mystery-source") == "needs-nod"


# ── fixture root with one discovery candidate + one rsi predicate ──────────
def _mk_root(tmp: Path) -> Path:
    disc = tmp / "state" / "epistemic" / "discovery_queue.jsonl"
    disc.parent.mkdir(parents=True, exist_ok=True)
    disc.write_text(json.dumps({
        "fingerprint": "fpA", "type": "triad_closure",
        "candidates": [{"kind": "child_of", "method": "triad_closure",
                        "score": 1.0, "u": "nodeU", "v": "nodeV"}],
    }) + "\n")
    rq = tmp / "state" / "rsi" / "queue"
    rq.mkdir(parents=True, exist_ok=True)
    (rq / "fix_x.json").write_text(json.dumps({
        "name": "fix_x", "source": "rsi_cycle", "description": "auto fix",
    }))
    return tmp


def test_run_handoff_routes_needs_nod_to_alert(tmp_path: Path):
    root = _mk_root(tmp_path)
    s = handoff.run_handoff(root)
    assert s["collected"] == 2
    assert s["routed_by_rail"]["advisory"] == 1   # discovery
    assert s["routed_by_rail"]["needs-nod"] == 1  # rsi predicate
    # needs-nod produced an alert in the algedonic channel
    alerts = (root / "state" / "rsi" / "alerts.jsonl").read_text().splitlines()
    rec = json.loads(alerts[-1])
    assert rec["alert_type"] == "handoff_needs_nod"
    assert rec["evidence"]["candidate_id"] == "rsi:fix_x"
    # advisory produced a rastro decision, not an alert
    decisions = (root / "state" / "epistemic" / "decisions.jsonl").read_text().splitlines()
    d = json.loads(decisions[-1])
    assert d["consent"] == "advisory"
    assert d["candidate_id"] == "disc:fpA:0"


def test_run_handoff_idempotent(tmp_path: Path):
    root = _mk_root(tmp_path)
    s1 = handoff.run_handoff(root)
    assert s1["processed"] == 2
    s2 = handoff.run_handoff(root)  # re-run: both already in ledger
    assert s2["processed"] == 0
    assert s2["skipped"] == 2


def test_dry_run_writes_nothing(tmp_path: Path):
    root = _mk_root(tmp_path)
    s = handoff.run_handoff(root, dry_run=True)
    assert s["collected"] == 2
    assert s["dry_run"] is True
    assert not (root / "state" / "rsi" / "alerts.jsonl").exists()
    assert not (root / "state" / "epistemic" / "decisions.jsonl").exists()
    assert not (root / "state" / "epistemic" / "handoff_ledger.jsonl").exists()


def test_needs_nod_never_autocables(tmp_path: Path):
    # R17: a needs-nod candidate must NOT appear as a cabled/rastro decision —
    # it only surfaces via an alert awaiting S5.
    root = _mk_root(tmp_path)
    handoff.run_handoff(root)
    decisions = (root / "state" / "epistemic" / "decisions.jsonl").read_text()
    assert "rsi:fix_x" not in decisions  # needs-nod not silently processed
    alerts = (root / "state" / "rsi" / "alerts.jsonl").read_text()
    assert "rsi:fix_x" in alerts


def test_rejected_predicate_not_collected(tmp_path: Path):
    # 2026-10-13 bug: fix_op_AND (status=rejected) was collected because the
    # filter ignored status. A rejected predicate must NOT re-enter the handoff;
    # a pending one (or one with no explicit status) still does.
    rq = tmp_path / "state" / "rsi" / "queue"
    rq.mkdir(parents=True, exist_ok=True)
    (rq / "rejected_one.json").write_text(json.dumps({
        "name": "rejected_one", "status": "rejected",
        "rejection_reason": "placeholder sin valor (S5 2026-10-07)",
    }))
    (rq / "pending_one.json").write_text(json.dumps({
        "name": "pending_one", "status": "pending",
    }))
    s = handoff.run_handoff(tmp_path)
    # only the pending predicate is a candidate (needs-nod → 1)
    assert s["routed_by_rail"]["needs-nod"] == 1
    alerts = (tmp_path / "state" / "rsi" / "alerts.jsonl").read_text()
    assert "rsi:pending_one" in alerts
    assert "rsi:rejected_one" not in alerts


# ── F3: dep-graph cycles → handoff candidates ──────────────────────────────
def _mk_depgraph_root(tmp: Path, cycles) -> Path:
    """tmp root with a stub scripts/vsl/tools/dep_graph.py that emits `cycles`
    as --cycles-json stdout (deterministic, corpus-independent)."""
    stub_dir = tmp / "scripts" / "vsl" / "tools"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "dep_graph.py").write_text(
        "import json\n"
        "print(json.dumps(%r))\n" % {"cycles": cycles, "count": len(cycles)}
    )
    return tmp


def test_depgraph_candidates_from_cycles(tmp_path: Path):
    cycles = [["a.vsm", "b.vsm", "a.vsm"], ["x.vsm", "y.vsm", "z.vsm", "x.vsm"]]
    root = _mk_depgraph_root(tmp_path, cycles)
    cands = handoff._depgraph_candidates(root)
    assert len(cands) == 2
    assert all(c["source"] == "dep-graph-cycles" for c in cands)
    assert all(c["kind"] == "cycle" for c in cands)
    assert handoff.classify_consent("dep-graph-cycles") == "needs-nod"
    # payload carries the ordered cycle path
    assert cands[0]["payload"]["cycle"] == ["a.vsm", "b.vsm", "a.vsm"]
    assert cands[0]["payload"]["size"] == 2


def test_depgraph_ids_deterministic(tmp_path: Path):
    cycles = [["a.vsm", "b.vsm", "a.vsm"]]
    root = _mk_depgraph_root(tmp_path, cycles)
    ids1 = [c["id"] for c in handoff._depgraph_candidates(root)]
    ids2 = [c["id"] for c in handoff._depgraph_candidates(root)]
    assert ids1 == ids2  # R10: same input → same ids


def test_depgraph_degrades_when_no_script(tmp_path: Path):
    # no dep_graph.py in root → [] (degradation, not crash)
    assert handoff._depgraph_candidates(tmp_path) == []


def test_depgraph_needs_nod_never_cabled(tmp_path: Path):
    # R17: a dep-graph cycle edits boot canon if fixed → needs-nod → alert
    # only, never auto-cabled as a decision.
    root = _mk_depgraph_root(tmp_path, [["a.vsm", "b.vsm", "a.vsm"]])
    s = handoff.run_handoff(root)
    assert s["routed_by_rail"]["needs-nod"] == 1
    alerts = (root / "state" / "rsi" / "alerts.jsonl").read_text()
    assert "depgraph:" in alerts
    assert not (root / "state" / "epistemic" / "decisions.jsonl").exists()
