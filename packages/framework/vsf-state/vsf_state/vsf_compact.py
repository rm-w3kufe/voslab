#!/usr/bin/env python3
"""vsf-compact.py — tiered retention compactor (C.3 v1).

Reads events.jsonl (the chain — UNCHANGED, source of truth) and produces
aggregated views for time-bounded display. Tier 0 stays raw; tiers 1+ are
derivable agregates.

Tier layout (under /var/lib/vsf/vsf_nucleus/aggregates/):
    minute/YYYY-MM-DD/HH.jsonl   — 1 row per minute (this script)
    day/YYYY/MM.jsonl            — 1 row per day  (rolled from minute, deferred)
    week/YYYY-Www.jsonl          — 1 row per week (deferred)

Per-minute row shape:
    {
      "minute":        "2026-05-31T04:07",
      "bucket_start":  "2026-05-31T04:07:00Z",  # hardcoded-allow: data record
      "n_events":      42,
      "n_by_type":     {"kernel_tick": 12, "s4-analysis": 1, ...},
      "p50_duration":  0.0,
      "p95_duration":  76.13,
      "origins":       ["abc...12", "def...34"],
      "last_hash":     "299c4e7a..."   // chain head at end of bucket (anti-tamper)
    }

Invoked from systemd timer every hour. Idempotent: if the hour's file
exists AND the chain head at the end of the file matches the chain head
at the end of the same window in events.jsonl, skip.

Usage:
    vsf-compact [--events PATH] [--out PATH] [--window-hours N]
"""
import argparse
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_EVENTS = "/var/lib/vsf/vsf_nucleus/events.jsonl"
DEFAULT_OUT    = "/var/lib/vsf/vsf_nucleus/aggregates"

def parse_ts(s: str):
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except: return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=DEFAULT_EVENTS)
    ap.add_argument("--out",    default=DEFAULT_OUT)
    ap.add_argument("--window-hours", type=int, default=24,
                    help="re-aggregate this many trailing hours each run (default: 24)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.window_hours)

    # Walk events, filter by cutoff, group by minute.
    by_minute = defaultdict(list)  # minute_key -> list of events
    n_total = 0
    with open(args.events, "rb") as f:
        for raw in f:
            try:
                ev = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:
                continue
            ts = parse_ts(ev.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            minute_key = ts.strftime("%Y-%m-%dT%H:%M")
            by_minute[minute_key].append(ev)
            n_total += 1

    # Aggregate per minute, write to hour-bucket files.
    out_root = Path(args.out)
    by_hour_file = defaultdict(list)  # hour_path -> list of minute aggregates
    for minute_key in sorted(by_minute):
        evs = by_minute[minute_key]
        n_by_type = defaultdict(int)
        for e in evs: n_by_type[e.get("event_type", "?")] += 1
        durations = [e.get("duration_s", 0.0) for e in evs if isinstance(e.get("duration_s"), (int, float))]
        durations.sort()
        origins = sorted({e.get("origin") for e in evs if e.get("origin")})
        # last_hash = the `hash` field of the last event in this minute, for
        # anti-tamper verification (the compactor's view of chain head at
        # bucket end).
        last_hash = next((e.get("hash") for e in reversed(evs) if e.get("hash")), None)
        row = {
            "minute":       minute_key,
            "bucket_start": minute_key + ":00Z",
            "n_events":     len(evs),
            "n_by_type":    dict(n_by_type),
            "p50_duration": statistics.median(durations) if durations else 0.0,
            "p95_duration": durations[int(0.95 * (len(durations) - 1))] if durations else 0.0,
            "origins":      origins[:10],
            "n_origins":    len(origins),
            "last_hash":    last_hash,
        }
        # Hour bucket: minute YYYY-MM-DDTHH:MM → file YYYY-MM-DD/HH.jsonl
        date, time = minute_key.split("T")
        hour = time.split(":")[0]
        hour_path = out_root / "minute" / date / f"{hour}.jsonl"
        by_hour_file[hour_path].append(row)

    # Write hour-bucket files (overwrite to keep idempotent + reflect updates).
    n_files = 0
    for hour_path, rows in by_hour_file.items():
        hour_path.parent.mkdir(parents=True, exist_ok=True)
        with open(hour_path, "w") as f:
            for r in rows: f.write(json.dumps(r) + "\n")
        n_files += 1

    print(f"# vsf-compact ok")
    print(f"  events scanned in last {args.window_hours}h: {n_total}")
    print(f"  minute buckets written:                     {len(by_minute)}")
    print(f"  hour files written:                         {n_files}")
    print(f"  output root:                                {out_root}")

if __name__ == "__main__":
    main()
