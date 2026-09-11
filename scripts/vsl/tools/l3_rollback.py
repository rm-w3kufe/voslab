#!/usr/bin/env python3
"""l3_rollback.py — One-line rollback for L3 activations (s4 hardening).

Reverses recent activations: queue entries -> rejected, pred_dir files ->
quarantine (never deleted), pins dropped so a re-approval re-verifies.
Running engines keep them until restart (documented, not hidden).

Usage:
  l3_rollback.py --list                 # what WOULD be revoked (default window 24h)
  l3_rollback.py --apply [--hours N]    # revoke recent activations
  l3_rollback.py --apply --name X       # revoke one predicate

Exit codes: 0 ok (nothing to do is ok), 1 usage/IO error.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOSLAB / "system" / "kernel"))


def _activated() -> dict:
    for cand in (VOSLAB / "state" / "rsi" / "activated.json",
                 Path.home() / "packages" / "public" / "state" / "activated.json"):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _recent(names=None, hours: int = 24) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for name, meta in _activated().items():
        if names is not None and name not in names:
            continue
        try:
            seen = datetime.fromisoformat(str(meta.get("first_seen", "")))
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if seen >= cutoff or names is not None:
            out.append(name)
    return sorted(out)


def _revoke(name: str, reason: str) -> dict:
    """Mark queue rejected + quarantine pred_dir file. Returns report."""
    rep = {"name": name, "queue": None, "pred_dir": None}
    qdir = VOSLAB / "state" / "rsi" / "queue"
    for qf in ([qdir / f"{name}.json"] if qdir.is_dir() else []):
        if qf.is_file():
            try:
                entry = json.loads(qf.read_text())
                entry["status"] = "rejected"
                entry["rejected_at"] = datetime.now(timezone.utc).isoformat()
                entry["rejection_reason"] = reason
                qf.write_text(json.dumps(entry, indent=2))
                rep["queue"] = "rejected"
            except Exception as e:
                rep["queue"] = f"error: {e}"
    # pred_dir files live under agent state or package fallback
    candidates = []
    try:
        from vos_agent_state import get_agent_state_dir
        candidates.append(Path(str(get_agent_state_dir("vsf-rsi", "predicates"))))
    except Exception:
        pass
    candidates.append(VOSLAB / "packages" / "public" / "vsf-rsi" / "state" / "predicates")
    for d in candidates:
        p = d / f"{name}.json"
        if p.is_file():
            try:
                q = VOSLAB / "state" / "quarantine"
                q.mkdir(parents=True, exist_ok=True)
                dest = q / f"{name}.revoked.json"
                shutil.move(str(p), str(dest))
                rep["pred_dir"] = f"quarantined -> {dest.name}"
            except Exception as e:
                rep["pred_dir"] = f"error: {e}"
            break
    else:
        if rep["pred_dir"] is None:
            rep["pred_dir"] = "no pred_dir file"
    # drop the pin so a future re-approval re-verifies from scratch
    for cand in (VOSLAB / "state" / "rsi" / "activated.json",
                 Path.home() / "packages" / "public" / "state" / "activated.json"):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            if name in data:
                del data[name]
                cand.write_text(json.dumps(data, indent=2))
        except Exception:
            continue
    return rep


def main(argv: list[str]) -> int:
    if "--list" in argv or len(argv) == 0:
        names = _recent()
        print(json.dumps({"recent_activations": names, "count": len(names)},
                         indent=2))
        return 0
    if argv[0] != "--apply":
        print(__doc__.split("Usage:")[1].strip(), file=sys.stderr)
        return 1
    hours = 24
    names = None
    if "--name" in argv:
        names = [argv[argv.index("--name") + 1]]
    if "--hours" in argv:
        try:
            hours = int(argv[argv.index("--hours") + 1])
        except (ValueError, IndexError):
            print("bad --hours value", file=sys.stderr)
            return 1
    targets = _recent(names, hours)
    reports = [_revoke(n, "l3_rollback --apply") for n in targets]
    print(json.dumps({"revoked": reports, "count": len(reports)}, indent=2,
                     default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
