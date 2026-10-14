"""F5 E2E — one candidate climbs the root ladder S1→S4→S5→S3→S1→S3*→S1.

Deterministic (R10). Candidate journey runs in a tmp root (stub dep-graph +
discovery); aggregate acceptance predicates read the LIVE repo read-only.
"""
from __future__ import annotations

import json
from pathlib import Path

from vos_kernel import handoff
from vos_kernel import instrument_manifest as im

_ROOT = Path(__file__).resolve().parents[4]


def _mk_journey_root(tmp: Path) -> Path:
    """tmp root with 1 dep-graph cycle (stub) + 1 discovery candidate — the
    two S4.S1 instrument sources that feed the handoff."""
    stub = tmp / "scripts" / "vsl" / "tools"
    stub.mkdir(parents=True, exist_ok=True)
    (stub / "dep_graph.py").write_text(
        "import json\n"
        "print(json.dumps({'cycles': [['a.vsm', 'b.vsm', 'a.vsm']], 'count': 1}))\n")
    disc = tmp / "state" / "epistemic" / "discovery_queue.jsonl"
    disc.parent.mkdir(parents=True, exist_ok=True)
    disc.write_text(json.dumps({
        "fingerprint": "fp1", "type": "triad_closure",
        "candidates": [{"kind": "edge", "u": "u", "v": "v", "method": "m", "score": 1.0}],
    }) + "\n")
    return tmp


# ── the climb ───────────────────────────────────────────────────────────────
def test_one_candidate_climbs_ladder(tmp_path: Path):
    root = _mk_journey_root(tmp_path)
    # S1 opera → OBSERVED → S4: both S4.S1 instruments observe candidates
    cands = handoff.collect_candidates(root)
    assert {c["source"] for c in cands} == {"discovery", "dep-graph-cycles"}
    # S4 proyecta → PROPOSED → S5; S5 ratifica by consent rail:
    s = handoff.run_handoff(root)
    assert s["routed_by_rail"]["advisory"] == 1   # discovery → rastro (auto)
    assert s["routed_by_rail"]["needs-nod"] == 1  # dep-graph → waits S5 (R17)
    # S5 ratify artifacts: advisory surfaced as rastro; needs-nod as alert
    assert "advisory-surfaced" in (root / "state/epistemic/decisions.jsonl").read_text()
    assert "depgraph:" in (root / "state/rsi/alerts.jsonl").read_text()
    # S3* atestigua: ledger is the audit trail of every processed candidate
    ledger = (root / "state/epistemic/handoff_ledger.jsonl").read_text()
    assert "disc:" in ledger and "depgraph:" in ledger
    # realimenta / idempotency: a re-run skips both (already attested)
    s2 = handoff.run_handoff(root)
    assert s2["processed"] == 0 and s2["skipped"] == 2


def test_autonomy_rails_by_source():
    # acceptance: read-only → auto; advisory → rastro; needs-nod → wait (R17)
    assert handoff.classify_consent("read-only") == "read-only"
    assert handoff.classify_consent("discovery") == "advisory"
    assert handoff.classify_consent("dep-graph-cycles") == "needs-nod"
    assert handoff.classify_consent("rsi-predicate") == "needs-nod"
    assert handoff.classify_consent("mystery") == "needs-nod"  # unknown safest


# ── aggregate acceptance on the LIVE repo (read-only) ───────────────────────
def test_no_mute_queues_every_source_feeds_handoff():
    # acceptance "colas mudas = 0": every S4.S1 source is wired into
    # collect_candidates (discovery + rsi + dep-graph; F3 closed the gap).
    cands = handoff.collect_candidates(_ROOT)
    sources = {c["source"] for c in cands}
    assert "discovery" in sources       # epistemic discovery queue
    assert "dep-graph-cycles" in sources  # dep_graph cycles (F3)
    # rsi source is wired even when 0 pending (queue empty is not "mute")
    assert handoff._rsi_candidates(_ROOT) == [] or "rsi-predicate" in sources


def test_canonical_feedback_is_one():
    # acceptance "feedback canónico = 1": canonical_feedback.vsm designates
    # rsi_cycle @ S5.S3* as THE loop; the other 3 delegate as sub-loops.
    doc = (_ROOT / "docs/spec_revision/design-sources/second-order-loop-v1"
           / "canonical_feedback.vsm").read_text()
    assert "rsi_cycle" in doc and "S5.S3*" in doc
    for delegate in ("rsi_feedback_loop", "feedback_loop", "pleasure_emitter"):
        assert delegate in doc  # all three are the designated sub-loop set


def test_instrument_onboard_is_one_manifest():
    # acceptance "instrumento nuevo onboard = 1 manifest": the F2 seed seats
    # at (S5, S3*) and the loader is the single onboarding surface.
    idx = im.index_by_seat(im.load_manifests(_ROOT / "system" / "instruments"))
    assert ("S5", "S3*") in idx and "rsi-cycle-feedback" in idx[("S5", "S3*")]


def test_gates_green():
    # acceptance "gates green" (POST CHILD-ARCHIVE-LEGACY, 2026-10-14): the
    # former known-red (child-boot-state-archive-gates) was RETIRED with the
    # child/ archive, so the suite is fully green. Suite size is 82 (84 − 2
    # retired child-* checks). Assert the PASS summary + an empty red set.
    import re
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(_ROOT / "packages/framework/run_gates.py")],
                       capture_output=True, text=True, cwd=_ROOT, timeout=300)
    assert "LIVE CHECKS PASS" in r.stdout, r.stdout[-400:]
    assert "82 checks green" in r.stdout, r.stdout[-400:]
    reds = re.findall(r"rc=\s+1\s+(\S+)", r.stdout)
    assert reds == [], reds
