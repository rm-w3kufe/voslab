#!/usr/bin/env python3
# design: docs/design/sources/r16-spec-v1/LEARNING-CYCLE-INSTRUMENTS-DESIGN.vsm
"""learning_stats.py — S4 statistical mechanism for the learning cycle.

learning_cycle.vsm §1 trace: "S4 intelligence records novel patterns and
aggregates statistically (N in window → decide investment in new structure)".
This instrument POPULATES the window (aggregates learning records by
family/class/organ over time) and is READ under a condition (N novel in
window → decision trigger).

SCENARIO-MEMORY-FASE-1 (2026-08-27): procedure metrics.
Aggregates procedure records from learning_records/procedures/ for
procedural memory analysis (success rate, duration, instrument usage).

Deterministic (R10): parses records, aggregates counts, prints the window.
It does NOT decide — it surfaces the aggregate so S4/S5 can decide.

Usage:
  learning_stats.py              # populate + print window (all records)
  learning_stats.py --check      # read under condition: novel family count >= N
                                 # in window W days → exit 1 (trigger)
  learning_stats.py --json       # machine-readable aggregate (for hooks/plugins)
  learning_stats.py --procedures # include procedure metrics (Scenario Memory)

Config (env or flags):
  N  = --min-n (default 3)      # novel records in window to trigger
  W  = --window-days (default 30)  # window size in days
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/../../.."
RECORDS = os.path.join(ROOT, "state/learning_records")
PROCEDURES = os.path.join(RECORDS, "procedures")

# Header: ⟦ AAAAMMDD_name | TYPE | vsm-1.0 | date ⟧ — date in field 4
RE_HEADER = re.compile(r"^⟦\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*⟧")
# Body fields per standard §6
RE_FAMILY = re.compile(r"family:\s*([a-z_]+)")
RE_CLASS = re.compile(r"class:\s*([a-z_]+)")
RE_ORGAN = re.compile(r"organ:\s*([A-Za-z0-9_\-]+)")
RE_STATUS = re.compile(r"@status\(V\)\s+([a-z_]+)")
RE_UUID = re.compile(r'uuid:\s*"([^"]+)"')


def parse_record(path):
    """Return dict of fields from a learning record, or None if not one."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    m = RE_HEADER.match(text)
    if not m:
        return None
    # date field 4: "2026-08-16" or "2026-08-16T06:32:29Z"
    raw_date = m.group(4).strip()
    try:
        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {
        "name": m.group(1).strip(),
        "type": m.group(2).strip(),
        "version": m.group(3).strip(),
        "date": dt.isoformat() if dt else raw_date,
        "ts": dt,
        "family": (RE_FAMILY.search(text) or [None, "unknown"])[1],
        "class": (RE_CLASS.search(text) or [None, "unknown"])[1],
        "organ": (RE_ORGAN.search(text) or [None, "unknown"])[1],
        "status": (RE_STATUS.search(text) or [None, "unknown"])[1],
        "uuid": (RE_UUID.search(text) or [None, ""])[1],
    }


def collect():
    records = []
    if os.path.isdir(RECORDS):
        for fn in sorted(os.listdir(RECORDS)):
            if fn.endswith(".vsm") and not fn.startswith("."):
                r = parse_record(os.path.join(RECORDS, fn))
                if r:
                    records.append(r)
    return records


def parse_procedure(path):
    """Return dict of fields from a procedure record, or None if not one."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("type") != "procedure":
        return None
    # Parse timestamp
    ts_str = data.get("metadata", {}).get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {
        "id": data.get("id", ""),
        "instrument": data.get("source", {}).get("instrument", "unknown"),
        "hook": data.get("source", {}).get("hook", "unknown"),
        "action": data.get("action", ""),
        "result": data.get("decision", {}).get("result", "unknown"),
        "success": data.get("outcome", {}).get("success", False),
        "duration_ms": data.get("outcome", {}).get("durationMs", 0),
        "ts": dt,
        "context": data.get("context", {}),
    }


def collect_procedures():
    """Collect all procedure records from procedures/ directory."""
    procedures = []
    if os.path.isdir(PROCEDURES):
        for fn in sorted(os.listdir(PROCEDURES)):
            if fn.endswith(".json"):
                p = parse_procedure(os.path.join(PROCEDURES, fn))
                if p:
                    procedures.append(p)
    return procedures


def aggregate_procedures(procedures):
    """Aggregate procedure metrics for Scenario Memory."""
    if not procedures:
        return {
            "total": 0,
            "success_rate": 0.0,
            "avg_duration_ms": 0,
            "by_instrument": {},
            "by_hook": {},
            "matching": {
                "total_matches": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
            },
            "autonomy": {
                "score": 0.0,
                "total_decisions": 0,
                "autonomous_decisions": 0,
                "reused_decisions": 0,
                "adapted_decisions": 0,
                "new_decisions": 0,
            },
        }
    total = len(procedures)
    successes = sum(1 for p in procedures if p["success"])
    success_rate = successes / total if total > 0 else 0.0
    durations = [p["duration_ms"] for p in procedures if p["duration_ms"] is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0
    by_instrument = Counter(p["instrument"] for p in procedures)
    by_hook = Counter(p["hook"] for p in procedures)
    
    # Matching metrics: analyze procedure patterns
    matching = analyze_matching_patterns(procedures)
    
    # Autonomy metrics: calculate autonomy score
    autonomy = calculate_autonomy_score(procedures)
    
    return {
        "total": total,
        "success_rate": round(success_rate, 3),
        "avg_duration_ms": round(avg_duration, 1),
        "by_instrument": dict(by_instrument),
        "by_hook": dict(by_hook),
        "matching": matching,
        "autonomy": autonomy,
    }


def analyze_matching_patterns(procedures):
    """Analyze patterns in procedures for matching metrics."""
    if not procedures:
        return {
            "total_matches": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
        }
    
    # Group by instrument
    by_instrument = defaultdict(list)
    for proc in procedures:
        by_instrument[proc["instrument"]].append(proc)
    
    # Calculate matching potential
    total_matches = 0
    high_confidence = 0
    medium_confidence = 0
    low_confidence = 0
    
    for instrument, procs in by_instrument.items():
        if len(procs) < 2:
            continue
        
        # Count successful procedures (reusable)
        successes = sum(1 for p in procs if p["success"])
        if successes >= 2:
            high_confidence += successes
            total_matches += successes
        elif successes == 1:
            medium_confidence += 1
            total_matches += 1
        else:
            # Even failures can be matched (to avoid)
            low_confidence += 1
            total_matches += 1
    
    return {
        "total_matches": total_matches,
        "high_confidence": high_confidence,
        "medium_confidence": medium_confidence,
        "low_confidence": low_confidence,
    }


def calculate_autonomy_score(procedures):
    """Calculate autonomy score based on procedure outcomes.
    
    Autonomy score = (successful autonomous decisions) / (total decisions)
    
    A decision is considered "autonomous" if:
    - It was generated by scenario-memory (has parent_id in metadata)
    - OR it was adapted (has adaptations_used > 0)
    - OR it was reused successfully (high confidence match)
    
    Target: >30% autonomy (Phase 3 objective)
    """
    if not procedures:
        return {
            "score": 0.0,
            "total_decisions": 0,
            "autonomous_decisions": 0,
            "reused_decisions": 0,
            "adapted_decisions": 0,
            "new_decisions": 0,
        }
    
    total = len(procedures)
    autonomous = 0
    reused = 0
    adapted = 0
    new = 0
    
    for proc in procedures:
        metadata = proc.get("context", {}).get("metadata", {})
        parent_id = metadata.get("parent_id")
        adaptations_used = metadata.get("adaptations_used", 0)
        
        if parent_id:
            # Adapted procedure
            adapted += 1
            autonomous += 1
        elif adaptations_used > 0:
            # Has adaptations
            adapted += 1
            autonomous += 1
        elif proc.get("success"):
            # Successful procedure (reusable)
            reused += 1
            autonomous += 1
        else:
            # New or failed procedure
            new += 1
    
    score = autonomous / total if total > 0 else 0.0
    
    return {
        "score": round(score, 3),
        "total_decisions": total,
        "autonomous_decisions": autonomous,
        "reused_decisions": reused,
        "adapted_decisions": adapted,
        "new_decisions": new,
    }


def window_records(records, window_days, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    return [r for r in records if r["ts"] and r["ts"] >= cutoff]


def aggregate(records):
    by_family = Counter(r["family"] for r in records)
    by_class = Counter(r["class"] for r in records)
    by_organ = Counter(r["organ"] for r in records)
    by_status = Counter(r["status"] for r in records)
    by_date = Counter((r["ts"].date().isoformat() if r["ts"] else "?") for r in records)
    novel = [r for r in records if r["family"] == "novel"]
    return {
        "total": len(records),
        "by_family": dict(by_family),
        "by_class": dict(by_class),
        "by_organ": dict(by_organ),
        "by_status": dict(by_status),
        "by_date": dict(sorted(by_date.items())),
        "novel": [{"name": r["name"], "date": r["date"], "organ": r["organ"],
                   "class": r["class"], "uuid": r["uuid"]} for r in novel],
    }


def main():
    ap = argparse.ArgumentParser(description="S4 learning-cycle statistics")
    ap.add_argument("--check", action="store_true", help="read under condition")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--procedures", action="store_true", help="include procedure metrics")
    ap.add_argument("--min-n", type=int, default=int(os.environ.get("LEARNING_MIN_N", 3)))
    ap.add_argument("--window-days", type=int,
                    default=int(os.environ.get("LEARNING_WINDOW_DAYS", 30)))
    args = ap.parse_args()

    records = collect()
    w = window_records(records, args.window_days)
    agg = aggregate(w)

    # Scenario Memory: collect procedure metrics if requested
    procedures = collect_procedures() if args.procedures else []
    proc_agg = aggregate_procedures(procedures) if args.procedures else None

    if args.json:
        output = agg
        if proc_agg:
            output["procedures"] = proc_agg
        print(json.dumps(output, indent=2))
        return 0

    if args.check:
        n_novel = len(agg["novel"])
        print(f"S4 learning stats: {agg['total']} records in {args.window_days}d window; "
              f"novel={n_novel} (threshold N={args.min_n})")
        if n_novel >= args.min_n:
            print(f"TRIGGER: {n_novel} novel patterns ≥ N={args.min_n} in "
                  f"{args.window_days}d — S4/S5 should decide investment in new structure",
                  file=sys.stderr)
            return 1
        return 0

    # populate mode: print the window
    print(f"S4 learning stats — window {args.window_days}d ({agg['total']} records)")
    print(f"  family:  {agg['by_family']}")
    print(f"  class:   {agg['by_class']}")
    print(f"  organ:   {agg['by_organ']}")
    print(f"  status:  {agg['by_status']}")
    print(f"  by_date: {agg['by_date']}")
    if agg["novel"]:
        print(f"  novel (trigger candidates): {len(agg['novel'])}")
        for n in agg["novel"]:
            print(f"    {n['date']}  {n['name']}  organ={n['organ']} class={n['class']}")

    # Scenario Memory: print procedure metrics if requested
    if proc_agg:
        print(f"\nScenario Memory — procedures ({proc_agg['total']} records)")
        print(f"  success_rate: {proc_agg['success_rate']:.1%}")
        print(f"  avg_duration: {proc_agg['avg_duration_ms']:.0f}ms")
        print(f"  by_instrument: {proc_agg['by_instrument']}")
        print(f"  by_hook: {proc_agg['by_hook']}")
        if proc_agg.get("matching"):
            m = proc_agg["matching"]
            print(f"\n  Matching Potential:")
            print(f"    total_matches: {m['total_matches']}")
            print(f"    high_confidence (>=0.8): {m['high_confidence']}")
            print(f"    medium_confidence (0.6-0.8): {m['medium_confidence']}")
            print(f"    low_confidence (<0.6): {m['low_confidence']}")
        if proc_agg.get("autonomy"):
            a = proc_agg["autonomy"]
            print(f"\n  Autonomy Score: {a['score']:.1%} (target: >30%)")
            print(f"    total_decisions: {a['total_decisions']}")
            print(f"    autonomous_decisions: {a['autonomous_decisions']}")
            print(f"    reused_decisions: {a['reused_decisions']}")
            print(f"    adapted_decisions: {a['adapted_decisions']}")
            print(f"    new_decisions: {a['new_decisions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())