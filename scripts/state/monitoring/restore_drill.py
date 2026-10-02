#!/usr/bin/env python3
"""restore_drill.py — G-07 restoration drill (RTO measurement, never destructive).

Rehearses restoring RSI state from a daily snapshot WITHOUT touching the
live sources (state/rsi/faults, state/rsi/rollback are read-only here;
copies go to a drill destination only).

Flow:
  1. pick snapshot date (default: latest) from state/rsi/snapshots/
  2. copy snapshot/<date>/*.json into <dest>/{faults,rollback}/ per the
     index.jsonl 'from' field (layout of the live tree)
  3. verify: sha256-16 of every restored file == the sha recorded in
     index.jsonl at snapshot time (integrity through time)
  4. verify: every restored file parses as JSON (usable, not just byte-equal)
  5. report RTO: wall seconds for the whole restore

Negative control: --corrupt NAME alters one restored copy before
verification; the drill MUST then exit 1 (an accepting corrupted restore
would make the drill a proxy, not a rehearsal).

Exit codes: 0 = restored + verified, 1 = verification failed,
2 = snapshot/date missing, 3 = usage.

Deterministic (R10): reads snapshot tree + index, writes drill dest only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # scripts/state/monitoring/ -> repo
SNAP_ROOT = REPO / "state" / "rsi" / "snapshots"
INDEX = SNAP_ROOT / "index.jsonl"


def sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_index() -> dict[str, list[dict]]:
    """date -> [{name, from, sha, bytes}]"""
    by_date: dict[str, list[dict]] = {}
    for line in INDEX.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_date.setdefault(row["date"], []).extend(row.get("changed", []))
    return by_date


def pick_date(requested: str | None) -> str:
    by_date = load_index()
    if requested:
        if requested not in by_date:
            sys.exit(2)
        return requested
    return max(by_date)


def drill(snapshot_date: str, dest: Path, corrupt: str | None = None) -> int:
    t0 = time.monotonic()
    by_date = load_index()
    entries = by_date.get(snapshot_date)
    if not entries:
        print(f"FAIL: no index entries for {snapshot_date}", file=sys.stderr)
        return 2
    src_dir = SNAP_ROOT / snapshot_date
    if not src_dir.is_dir():
        print(f"FAIL: snapshot dir missing {src_dir}", file=sys.stderr)
        return 2

    # 1. restore (copy only — never writes inside state/rsi live tree)
    restored: list[tuple[Path, dict]] = []
    for e in entries:
        src = src_dir / e["name"]
        if not src.is_file():
            print(f"FAIL: snapshot file missing {src}", file=sys.stderr)
            return 2
        target_dir = dest / e["from"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / e["name"]
        shutil.copyfile(src, target)
        restored.append((target, e))
    elapsed = time.monotonic() - t0

    # 2. optional negative control: corrupt one restored copy
    if corrupt:
        victim = None
        for target, e in restored:
            if e["name"] == corrupt:
                victim = target
        if victim is None:
            print(f"FAIL: --corrupt {corrupt} does not match a snapshot file",
                  file=sys.stderr)
            return 3
        victim.write_bytes(victim.read_bytes() + b"CORRUPTED")

    # 3. verify integrity against the index (sha recorded at snapshot time)
    bad = 0
    for target, e in restored:
        got = sha16(target)
        ok = got == e["sha"]
        if not ok:
            bad += 1
        print(f"  [{'ok  ' if ok else 'FAIL'}] {e['from']}/{e['name']} "
              f"sha={got} expected={e['sha']}")

    # 4. verify usability: every restored file parses as JSON
    parse_bad = 0
    for target, _ in restored:
        try:
            json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            parse_bad += 1
            print(f"  [FAIL] json parse {target.name}: {exc}")

    rto = f"{elapsed:.3f}s"
    if bad or parse_bad:
        print(f"DRILL FAILED — sha mismatches={bad} json_errors={parse_bad} "
              f"rto={rto}")
        return 1
    print(f"DRILL PASSED — {len(restored)} file(s) restored+verified from "
          f"{snapshot_date} — RTO {rto}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", help="snapshot date YYYY-MM-DD (default: latest)")
    ap.add_argument("--dest", required=True, help="drill destination directory")
    ap.add_argument("--corrupt", help="negative control: corrupt this file after copy")
    args = ap.parse_args()

    date = pick_date(args.snapshot)
    dest = Path(args.dest)
    if SNAP_ROOT.resolve() in dest.resolve().parents:
        print("FAIL: drill dest must not be inside the snapshot tree",
              file=sys.stderr)
        return 3
    return drill(date, dest, args.corrupt)


if __name__ == "__main__":
    sys.exit(main())
