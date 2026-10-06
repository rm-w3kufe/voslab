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

Census memoization (F3a warm-run floor): archives are immutable once
written, so the archive census (json.loads over ~250k historical lines ≈
10s) is cached in <log>.census_cache keyed by the archive SIGNATURE
(basename+size+mtime of every .gz). Same signature → same sources (R10:
pure function of inputs, no TTL); rotation/prune changes the signature →
automatic recompute. The LIVE log is always parsed fresh by the strict
pass — its sources join the cached archive census. Cache write is
best-effort; a failed write never changes the verdict.

Exit: 0 valid, 1 invalid (first violation reported), 2 usage.
Deterministic (R10): reads the log; writes only the derived census cache.
"""
import glob
import gzip
import json
import os
import sys
from datetime import datetime, timezone


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


def _archive_signature(files) -> list:
    """Identity of the archive set: [basename, size, mtime] per file.

    Rotations add a file, prunes remove one, corruption changes size —
    every history change flips the signature and invalidates the cache.
    """
    sig = []
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        sig.append([os.path.basename(f), st.st_size, int(st.st_mtime)])
    return sig


def _census_archives(path: str) -> set:
    """Sources observed in rotated .gz archives (memoized by signature).

    json.loads over the full retained history (~250k lines) costs ~10s and
    dominates the warm-run floor; the archives never change between
    rotations, so the parsed source set is a pure function of the archive
    signature and is cached beside the log. Full json parsing (no regex
    shortcuts) on compute — correctness over speed where it only runs on
    rotation.
    """
    d = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    archives = sorted(glob.glob(os.path.join(d, name + ".*.jsonl.gz")))
    sig = _archive_signature(archives)
    cache_path = os.path.join(d, name + ".census_cache")
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("signature") == sig:
            return {s for s in cached.get("sources", []) if isinstance(s, str)}
    except (OSError, ValueError, TypeError):
        pass  # missing/corrupt cache → recompute
    seen = set()
    for f in archives:
        try:
            with gzip.open(f, "rt", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # archive scrubbed on write; tolerate
                    s = r.get("source")
                    if isinstance(s, str):
                        seen.add(s)
        except OSError:
            continue
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"signature": sig, "sources": sorted(seen)}, fh)
        os.replace(tmp, cache_path)
    except OSError:
        pass  # best-effort — verdict never depends on the cache write
    return seen


def validate(path: str, declared: str) -> int:
    seen = set()
    n = 0
    # Strict pass over COMPLETE lines (concurrent append: a final line
    # without '\n' is a write in progress, not corruption). Sources are
    # collected here for free — every line is already json-parsed.
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
        s = r.get("source")
        if isinstance(s, str):
            seen.add(s)
    # Census over retained history: live sources (strict pass, above) ∪
    # archive sources (memoized — archives are immutable between rotations).
    seen |= _census_archives(path)

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
