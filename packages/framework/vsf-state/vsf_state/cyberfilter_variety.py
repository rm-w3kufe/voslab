#!/usr/bin/env python3
"""
F3.d — Cyberfilter variety accounting.
Measures the Ashby attenuation ratio (events_in / alerts_out) per day
and stores it in state.db — closing the Cyberfilter conformity gap.

Beer's Cyberfilter (S3) absorbs the bulk of operational variety so only
significant deviations escalate as algedonic signals:
  events_in  = invariant_check events emitted by vsf-nucleus (raw S1 variety)
  alerts_out = algedonic_signal events in events.jsonl (A/B alerts that escaped)
  attenuation = events_in / max(1, alerts_out)   [higher = better filtering]

Runs on the n02 HOST via systemd daily timer.
Pushes a counting script to LXC 101 via pct push, runs via pct exec.
Writes to /var/lib/vsf-state/state.db.

Usage:
    python3 cyberfilter_variety.py [--date YYYY-MM-DD] [--verbose] [--dry-run]
"""

import argparse, datetime, json, os, sqlite3, subprocess, sys, tempfile

# Resolve LXC ID from topology.json (clone-portable)
sys.path.insert(0, str(os.environ.get("VOSLAB_PATH", os.path.dirname(__file__))))
from topology_resolve import resolve_lxc

STATE_DB     = os.environ.get("VSF_STATE_DB", "/var/lib/vsf-state/state.db")
LXC_ID       = resolve_lxc("nucleus")
EVENTS_JSONL = "/var/lib/vsf/vsf_nucleus/events.jsonl"

WARN_RATIO = 10.0   # ratio < 10 → Cyberfilter leaking variety


def _count_events(date_str: str) -> dict:
    """Push a counting script to LXC 101 and run it. Returns {event_type: count}."""
    # Build script with date and path as literals (avoids -c quoting hazards)
    script_lines = [
        "import json, sys, collections",
        f"TARGET = '{date_str}'",
        f"PATH   = '{EVENTS_JSONL}'",
        "c = collections.defaultdict(int)",
        "try:",
        "    fh = open(PATH, errors='replace')",
        "except OSError as e:",
        "    print(json.dumps({'error': str(e)}))",
        "    sys.exit(1)",
        "for line in fh:",
        "    line = line.strip()",
        "    if not line: continue",
        "    try:",
        "        ev = json.loads(line)",
        "        if ev.get('ts', '')[:10] == TARGET:",
        "            c[ev.get('event_type', 'unknown')] += 1",
        "    except Exception:",
        "        pass",
        "print(json.dumps(dict(c)))",
    ]
    script = "\n".join(script_lines)

    host_path = f"/tmp/_vsf_cf_{date_str}.py"
    lxc_path  = f"/tmp/_vsf_cf_{date_str}.py"

    with open(host_path, "w") as fh:
        fh.write(script)

    subprocess.run(
        ["pct", "push", LXC_ID, host_path, lxc_path],
        check=True, timeout=15, capture_output=True
    )

    result = subprocess.run(
        ["pct", "exec", LXC_ID, "--", "python3", lxc_path],
        capture_output=True, text=True, timeout=180
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"pct exec {LXC_ID} failed (rc={result.returncode}): {result.stderr.strip()!r}"
        )
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(
            f"pct exec {LXC_ID} returned no output — rc={result.returncode!r} "
            f"stderr={result.stderr.strip()!r}"
        )
    data = json.loads(raw)
    if "error" in data:
        raise RuntimeError(f"LXC {LXC_ID} read error: {data['error']}")
    return data


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS cyberfilter_health (
            date        TEXT PRIMARY KEY,
            events_in   INTEGER NOT NULL DEFAULT 0,
            alerts_out  INTEGER NOT NULL DEFAULT 0,
            attenuation REAL    NOT NULL DEFAULT 0.0,
            computed_ts TEXT    NOT NULL
        )
    """)
    db.commit()


def run(date_str: str, dry_run: bool = False, verbose: bool = False) -> int:
    print(f"F3.d cyberfilter_variety: date={date_str}")

    counts = _count_events(date_str)
    if verbose:
        print("  event type distribution:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {v:5}  {k}")

    events_in  = counts.get("invariant_check", 0)
    alerts_out = counts.get("algedonic_signal", 0)
    attenuation = round(events_in / max(1, alerts_out), 2)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"  events_in={events_in}  alerts_out={alerts_out}  attenuation={attenuation:.1f}x")

    if alerts_out > 0 and attenuation < WARN_RATIO:
        print(f"  WARN: low attenuation ({attenuation:.1f}x < {WARN_RATIO}x) — Cyberfilter leaking variety")

    if dry_run:
        print("  [dry-run] not writing to state.db")
        return 0

    with sqlite3.connect(STATE_DB) as db:
        _ensure_table(db)
        db.execute(
            "INSERT OR REPLACE INTO cyberfilter_health"
            " (date, events_in, alerts_out, attenuation, computed_ts)"
            " VALUES (?,?,?,?,?)",
            (date_str, events_in, alerts_out, attenuation, now)
        )
        db.commit()
    print(f"  written → state.db:cyberfilter_health")

    with sqlite3.connect(STATE_DB) as db:
        rows = db.execute(
            "SELECT date, events_in, alerts_out, attenuation"
            " FROM cyberfilter_health ORDER BY date DESC LIMIT 7"
        ).fetchall()
    print(f"\n  Cyberfilter health — last {len(rows)} day(s):")
    print(f"  {'date':12}  {'events_in':>9}  {'alerts_out':>10}  {'attenuation':>12}")
    print(f"  {'-'*12}  {'-'*9}  {'-'*10}  {'-'*12}")
    for r in rows:
        print(f"  {r[0]:12}  {r[1]:>9}  {r[2]:>10}  {r[3]:>11.1f}x")
    return 0


def main(argv: list) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", default=None,
                   help="Date YYYY-MM-DD (default: yesterday)")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute but do not write to state.db")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print all event type counts")
    args = p.parse_args(argv)

    date_str = args.date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    try:
        return run(date_str, dry_run=args.dry_run, verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
