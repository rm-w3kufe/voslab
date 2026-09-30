#!/usr/bin/env python3
"""snapshot_runtime_state.py — point-in-time history for churn-prone state.

state/rsi/faults/ and state/rsi/rollback/ are rewritten on every RSI cycle
(demoted to runtime in cf7f8bc: live git tracking = pure diff noise). But
their HISTORY matters — L4 trial forensics needs "when did faults appear /
what did rollback_state hold before the incident" (CC-8 prerequisite:
S5 decides on presented evolution, and evolution without history is not
presentable).

Solution: daily cron copies changed files into a TRACKED snapshot tree:

    state/rsi/snapshots/<YYYY-MM-DD>/<name>.json
    state/rsi/snapshots/index.jsonl   (append-only: ts, date, per-file sha)

Dedup: a file is only copied when its sha differs from the previous
snapshot (idle days cost one 200-byte index line). NEVER deletes (R17 —
retention is an S5 policy decision, not this script's).

Run: python3 scripts/state/monitoring/snapshot_runtime_state.py
Cron (agent host): daily 04:23, flock-guarded, logged to logs/.
Exit: 0 = snapshot taken/indexed, 1 = nothing to do (all unchanged),
      2 = source unreadable.
Deterministic (R10): reads sources, writes snapshot dirs only.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    ROOT / "state/rsi/faults",
    ROOT / "state/rsi/rollback",
]
SNAP_ROOT = ROOT / "state/rsi/snapshots"
INDEX = SNAP_ROOT / "index.jsonl"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _prev_shas() -> dict[str, str]:
    """sha per filename from the most recent snapshot dir (or index)."""
    prev: dict[str, str] = {}
    if not SNAP_ROOT.is_dir():
        return prev
    for d in sorted(x for x in SNAP_ROOT.iterdir() if x.is_dir()):
        for f in d.glob("*.json"):
            prev[f.name] = _sha(f)
    return prev


def main() -> int:
    now = datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    files: list[tuple[str, Path, str]] = []
    for src in SOURCES:
        if not src.is_dir():
            print(f"snapshot: source missing {src}", file=sys.stderr)
            return 2
        for f in sorted(src.glob("*.json")):
            files.append((src.name, f, _sha(f)))

    prev = _prev_shas()
    changed = [(sub, f, sha) for sub, f, sha in files
               if prev.get(f.name) != sha]
    unchanged = len(files) - len(changed)

    if not changed:
        print(f"[{ts}] snapshot: no change ({unchanged} files identical "
              f"to previous)")
        return 1

    dest = SNAP_ROOT / date
    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for sub, f, sha in changed:
        target = dest / f.name
        target.write_bytes(f.read_bytes())
        entries.append({"name": f.name, "from": sub, "sha": sha,
                        "bytes": f.stat().st_size})

    SNAP_ROOT.mkdir(parents=True, exist_ok=True)
    with INDEX.open("a") as fh:
        fh.write(json.dumps({"ts": ts, "date": date,
                             "changed": entries,
                             "unchanged": unchanged}) + "\n")

    print(f"[{ts}] snapshot: {len(entries)} changed -> {dest} "
          f"({unchanged} unchanged deduped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
