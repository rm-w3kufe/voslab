"""handoff.py — S4→S5 consent-rail (second-order-loop F0).

design: docs/spec_revision/design-sources/second-order-loop-v1/second_order_loop.vsm

Closes the discovery→instruction gap: the candidate queues (epistemic
`discovery_queue.jsonl` + RSI predicate `state/rsi/queue/`) previously had
NO consumer — they sat mute forever. This module is the handoff: it collects
candidates, classifies consent DETERMINISTICALLY (R10), and routes each to
its rail:

    read-only  → auto-cable to destination (no human nod)
    advisory   → process + rastro (decision record) for later S5 review
    needs-nod  → route to S5 via alert; NEVER auto-execute (R17)

Consent classification is pure/deterministic — the same candidate always
yields the same rail (R10: no randomness). F0 ships the ROUTING (closes the
mute-queue gap); the bulk mutations (add-edge / approve-predicate) are F3/F5
and deliberately NOT auto-run here on the 71 raw candidates.

Design: docs/spec_revision/design-sources/second-order-loop-v1/second_order_loop.vsm
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "handoff-v1"

# Consent rails (deterministic mapping — R10). Source → rail.
# discovery = advisory by design (discovery.py docstring: "semi-automatica,
# advisory"). rsi predicate = needs-nod: activating it MUTATES the Socratic
# engine's behavior (R17 — a behavior change deserves an explicit nod, not a
# silent auto-approve). An explicit read-only flag wins (highest precedence).
_RAIL_BY_SOURCE = {
    "discovery": "advisory",
    "rsi-predicate": "needs-nod",
    "read-only": "read-only",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root() -> Path:
    # handoff.py lives at <root>/packages/framework/vos_kernel/handoff.py
    return Path(__file__).resolve().parents[3]


def classify_consent(source: str, explicit: str | None = None) -> str:
    """Deterministic consent rail (R10). An explicit flag overrides the
    source default; otherwise the source maps via _RAIL_BY_SOURCE."""
    if explicit in ("read-only", "advisory", "needs-nod"):
        return explicit
    return _RAIL_BY_SOURCE.get(source, "needs-nod")  # unknown → safest rail


def _discovery_candidates(root: Path) -> list[dict]:
    """Flatten pending batches from discovery_queue.jsonl into candidates."""
    out: list[dict] = []
    q = root / "state" / "epistemic" / "discovery_queue.jsonl"
    if not q.is_file():
        return out
    for line in q.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            batch = json.loads(line)
        except json.JSONDecodeError:
            continue
        fp = batch.get("fingerprint") or "nofp"
        for i, c in enumerate(batch.get("candidates") or []):
            out.append({
                "id": f"disc:{fp}:{i}",
                "source": "discovery",
                "kind": c.get("kind", "edge"),
                "payload": {"u": c.get("u"), "v": c.get("v"),
                            "method": c.get("method"), "score": c.get("score")},
            })
    return out


def _rsi_candidates(root: Path) -> list[dict]:
    """Pending predicates from state/rsi/queue/*.json (rsi_socratic_bridge)."""
    out: list[dict] = []
    q = root / "state" / "rsi" / "queue"
    if not q.is_dir():
        return out
    for f in sorted(q.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        name = d.get("name") or f.stem
        out.append({
            "id": f"rsi:{name}",
            "source": "rsi-predicate",
            "kind": "predicate",
            "payload": {"name": name, "source": d.get("source"),
                        "description": d.get("description")},
        })
    return out


def collect_candidates(root: Path) -> list[dict]:
    """All pending candidates from both queues, normalized to a common shape."""
    return _discovery_candidates(root) + _rsi_candidates(root)


def _ledger_path(root: Path) -> Path:
    return root / "state" / "epistemic" / "handoff_ledger.jsonl"


def _load_processed(root: Path) -> set[str]:
    """Ids already routed (idempotency). A re-run skips these."""
    p = _ledger_path(root)
    if not p.is_file():
        return set()
    done: set[str] = set()
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line).get("id", ""))
        except json.JSONDecodeError:
            continue
    return done


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _route_needs_nod(root: Path, cand: dict, consent: str) -> dict:
    """Route to S5 via the algedonic alert channel (R17: never auto-execute).
    Mirrors system/kernel/alerting.py's alert schema so rsi_cycle consumes it."""
    alert = {
        "alert_id": f"alert-{int(time.time() * 1000)}-{abs(hash(cand['id'])) % 10000:04d}",
        "ts": _now(),
        "level": "warning",
        "alert_type": "handoff_needs_nod",
        "source": f"handoff({cand['source']})",
        "detail": f"candidate awaiting S5 nod: {cand['id']} ({cand['kind']})",
        "evidence": {"candidate_id": cand["id"], "consent": consent,
                     "payload": cand["payload"]},
        "acknowledged": False,
    }
    _append(root / "state" / "rsi" / "alerts.jsonl", alert)
    return {"action": "routed-s5", "alert_id": alert["alert_id"]}


def _record_rastro(root: Path, cand: dict, consent: str, action: str) -> dict:
    """Advisory/read-only rastro — a decision record for later S5 review.
    F0 surfaces the candidate (closes the mute-queue gap) without bulk-mutating
    the graph/engine; the real cable is F3/F5."""
    rec = {
        "ts": _now(),
        "schema": SCHEMA,
        "kind": "handoff_decision",
        "candidate_id": cand["id"],
        "source": cand["source"],
        "consent": consent,
        "action": action,
        "payload": cand["payload"],
    }
    _append(root / "state" / "epistemic" / "decisions.jsonl", rec)
    return {"action": action}


def run_handoff(root: Path | None = None, dry_run: bool = False) -> dict:
    """Main entry: collect → classify → route. Idempotent via the ledger.

    Returns a summary {collected, routed_by_rail, processed, skipped, dry_run}.
    """
    root = root or _repo_root()
    processed = _load_processed(root)
    cands = collect_candidates(root)
    summary = {"collected": len(cands), "processed": 0, "skipped": 0,
               "routed_by_rail": {"read-only": 0, "advisory": 0, "needs-nod": 0},
               "dry_run": dry_run, "schema": SCHEMA}

    ledger = _ledger_path(root)
    for cand in cands:
        if cand["id"] in processed:
            summary["skipped"] += 1
            continue
        consent = classify_consent(cand["source"], cand.get("explicit"))
        summary["routed_by_rail"][consent] += 1
        summary["processed"] += 1
        if dry_run:
            continue
        if consent == "needs-nod":
            _route_needs_nod(root, cand, consent)
        else:
            # read-only → auto-cable marker; advisory → rastro. Both record a
            # decision; the bulk mutation is F3/F5 (not F0).
            _record_rastro(root, cand, consent,
                           "auto-cabled" if consent == "read-only" else "advisory-surfaced")
        _append(ledger, {"ts": _now(), "id": cand["id"], "consent": consent,
                         "schema": SCHEMA})
    return summary


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="S4→S5 consent-rail handoff (F0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="collect+classify only; no writes")
    ap.add_argument("--root", default=None, help="repo root (default: auto)")
    args = ap.parse_args()
    root = Path(args.root) if args.root else _repo_root()
    s = run_handoff(root, dry_run=args.dry_run)
    print(json.dumps(s, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
