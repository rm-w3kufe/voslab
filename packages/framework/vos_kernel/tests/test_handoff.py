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
