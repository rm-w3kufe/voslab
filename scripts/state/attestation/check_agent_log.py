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

Census memoization (F3a warm-run floor; v2 incremental 2026-10-15):
archives are immutable once written, so the archive census (json.loads
over ~250k historical lines ≈ 40s cold) is cached PER ARCHIVE in
<log>.census_cache, each entry keyed by that archive's size+mtime (R10:
pure function of inputs, no TTL). A rotation ADDS one file → every
unchanged archive is reused by stat and only the new one is parsed
(<100ms); a prune drops its entry. The v1 whole-set signature flipped on
every rotation and re-parsed the full retained history, blowing the
harness 60s budget under suite contention (rc=124 flake). The LIVE log
is always parsed fresh by the strict pass — its sources join the cached
archive census. Cache write is best-effort; a failed write never changes
the verdict.

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


def _census_archives(path: str) -> set:
    """Sources observed in rotated .gz archives (incrementally memoized).

    Cache v2 (2026-10-15, flake agent-plugin-log-valid rc=124): the v1
    whole-set signature [basename, size, mtime] flipped on EVERY rotation
    → full re-parse of the retained history (~250MB / ~240 archives,
    ~40s cold) → >60s under suite parallel contention → harness
    TimeoutExpired. Rotations only ADD one file, so v2 memoizes PER
    ARCHIVE (size+mtime identity): unchanged archives are reused by stat,
    only the new archive is parsed (<100ms), deleted ones are pruned.
    Full json parsing (no regex shortcuts) on compute — correctness over
    speed where it only runs on rotation. Best-effort cache: any I/O or
    parse failure retries next run and never changes the verdict (R10:
    the source set is a pure function of archive contents either way).
    """
    d = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    archives = sorted(glob.glob(os.path.join(d, name + ".*.jsonl.gz")))
    cache_path = os.path.join(d, name + ".census_cache")
    old: dict = {}
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        # v2 shape {"version": 2, "archives": {...}}; v1 (whole-set
        # signature) is intentionally ignored → one full re-parse, then v2.
        if isinstance(cached, dict) and isinstance(cached.get("archives"), dict):
            old = cached["archives"]
    except (OSError, ValueError, TypeError):
        pass  # missing/corrupt cache → recompute
    new_cache: dict = {}
    seen: set = set()
    for f in archives:
        try:
            st = os.stat(f)
        except OSError:
            continue
        base = os.path.basename(f)
        key = [st.st_size, int(st.st_mtime)]
        entry = old.get(base)
        if (isinstance(entry, dict) and entry.get("key") == key
                and isinstance(entry.get("sources"), list)):
            new_cache[base] = entry
            seen.update(s for s in entry["sources"] if isinstance(s, str))
            continue
        sources: set = set()
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
                        sources.add(s)
        except OSError:
            continue  # unreadable → not cached, retried next run
        new_cache[base] = {"key": key, "sources": sorted(sources)}
        seen.update(sources)
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "archives": new_cache}, fh)
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
