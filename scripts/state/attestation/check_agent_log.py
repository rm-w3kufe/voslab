#!/usr/bin/env python3
# design: system/s5-policy/agent-policy/agent-instruments-v1/agent_instruments.vsm
"""check_agent_log.py — validate the agent activation log (JSONL).

S5 decision 2026-09-30 (FND-AGENT-LOG-SCHEMA-DRIFT-01): the LIVE schema is
canonical. Required fields: ts, source, event_type, action, result (the old
instrument/hook names were the pre-rename taxonomy; the ~12 writers have been
stable on source/event_type since). Instruments are declared as plugin
SOURCES — the organ→source mapping lives in agent_instruments.vsm
(gate→GATE, write-gates→gate-suite sources, relocate→CLASSIFY;
state-canon/state/manifest never write this log and are attested elsewhere).

Reads the current log PLUS rotated .jsonl.<epoch>.jsonl.gz archives (size
rotation at ~5M — the FND-CYCLE-HEALTH-ROTATION-BLIND lesson) so idle-only
sources count from retained history: a validator that only sees the file
since the last restart goes red on every restart (a noisy certifier is a
dead certifier).

ts must be ISO 8601 UTC with an explicit offset: 'Z' (TypeScript writers) or
'+00:00' (python writers) — both are UTC, naive timestamps are rejected.

Exit: 0 valid, 1 invalid (first violation reported), 2 usage.
Deterministic (R10) — reads, never writes.
"""
import glob
import gzip
import json
import os
import sys
from datetime import datetime, timezone


def _iter_rows(path: str):
    """Yield parsed rows across rotated archives (oldest first) + current log."""
    d = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    files = sorted(glob.glob(os.path.join(d, name + ".*.jsonl.gz")))
    if os.path.exists(path):
        files.append(path)
    for f in files:
        try:
            opener = gzip.open if f.endswith(".gz") else open
            with opener(f, "rt", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue  # handled strictly by the caller below
        except OSError:
            continue


def _ts_ok(ts: str) -> bool:
    if not isinstance(ts, str) or len(ts) < 20:
        return False
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    elif "+00:00" not in ts and "+0000" not in ts:
        return False  # must declare UTC offset explicitly
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(None)


def validate(path: str, declared: str) -> int:
    seen = set()
    n = 0
    # Strict pass over COMPLETE lines (concurrent append: a final line
    # without '\n' is a write in progress, not corruption).
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError as e:
        print(f"  ✗ cannot read {path}: {e}", file=sys.stderr)
        return 1
    complete = lines[:-1] if lines and not lines[-1].endswith("\n") else lines
    for i, line in enumerate(complete):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  ✗ line {i}: invalid JSON — {e}", file=sys.stderr)
            return 1
        for field in ("ts", "source", "event_type", "action", "result"):
            if field not in r:
                print(f"  ✗ line {i}: missing field '{field}'", file=sys.stderr)
                return 1
        if not _ts_ok(r["ts"]):
            print(f"  ✗ line {i}: ts not ISO 8601 UTC with offset ({r['ts']})",
                  file=sys.stderr)
            return 1
    # Census pass over everything retained (current + rotations): which
    # declared sources have EVER fired.
    for r in _iter_rows(path):
        s = r.get("source")
        if isinstance(s, str):
            seen.add(s)

    missing = [src for src in declared.split() if src not in seen]
    if missing:
        for src in missing:
            print(f"  ✗ source '{src}' NEVER fired — dead plugin?",
                  file=sys.stderr)
        return 1
    print(f"  ✓ {n} records validated, {len(seen)} sources observed, "
          f"all {len(declared.split())} declared present", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: check_agent_log.py <log.jsonl> <'declared sources'>",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(sys.argv[1], sys.argv[2]))
