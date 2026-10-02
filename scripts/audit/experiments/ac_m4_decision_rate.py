#!/usr/bin/env python3
"""AC-M4-REDO: d|D|/dt — DECISION RATE over time from canon events.jsonl.

Decision types (signed decisions from S3/S5 that propagate to the system):
  - phi_down          S3→S1 parameter emissions
  - grant             resource allocation grants
  - algedonic_action  algedonic signal consequences (auto-escalations, auto-dismissals)
  - s3_alloc          S3 resource allocator decisions
  - param_change      S5 policy parameter changes

Non-decisions (excluded): kernel_tick (homeostatic heartbeat), env_sensor,
thermal_update, etc.

Output: hourly counts, baseline (homeostasis mean), peak (excursion max),
        and ratio peak/baseline.
"""

import argparse
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

DECISION_TYPES = {"phi_down", "grant", "algedonic_action", "s3_alloc", "param_change"}

def classify_decision(ev: dict) -> bool:
    """Return True if event is a system decision (not a tick or sensor reading)."""
    et = ev.get("event_type", "")
    return et in DECISION_TYPES

def main():
    parser = argparse.ArgumentParser(description="AC-M4-REDO: decision rate analysis")
    parser.add_argument("--file", required=True, help="Path to events.jsonl")
    parser.add_argument("--min-days", type=int, default=7,
                        help="Minimum days of data required (default: 7)")
    args = parser.parse_args()

    # Read and parse events
    hourly = Counter()  # hour_key -> decision count
    total = 0
    malformed = 0
    decisions = 0
    first_ts = None
    last_ts = None

    with open(args.file, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue

            ts_str = ev.get("ts")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

            if classify_decision(ev):
                decisions += 1
                hour_key = ts.strftime("%Y-%m-%dT%H:00:00Z")
                hourly[hour_key] += 1

    if first_ts is None or last_ts is None:
        print("ERROR: no events with valid timestamps found")
        sys.exit(1)

    span_days = (last_ts - first_ts).total_seconds() / 86400.0
    print(f"=== AC-M4-REDO: Decision Rate Analysis ===")
    print(f"Data window: {first_ts.isoformat()} to {last_ts.isoformat()} ({span_days:.1f} days)")
    print(f"Total events: {total} (malformed: {malformed})")
    print(f"Total decisions: {decisions}")
    print(f"Decision types counted: {', '.join(sorted(DECISION_TYPES))}")
    print()

    if span_days < args.min_days:
        print(f"WARNING: only {span_days:.1f} days of data (< {args.min_days} minimum)")
    else:
        print(f"✓ ≥{args.min_days} days of data available")

    # Hourly statistics
    hours_sorted = sorted(hourly.keys())
    if len(hours_sorted) < 2:
        print("ERROR: fewer than 2 hours of data")
        sys.exit(1)

    hourly_values = [hourly[h] for h in hours_sorted]

    # Find baseline (homeostasis): median of the middle 50% (25th-75th percentile)
    # This filters out excursion peaks
    sorted_vals = sorted(hourly_values)
    n = len(sorted_vals)
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    baseline_vals = sorted_vals[q1_idx:q3_idx]
    baseline = sum(baseline_vals) / len(baseline_vals) if baseline_vals else 0

    # Peak = maximum hourly rate
    peak = max(hourly_values)
    peak_hour = hours_sorted[hourly_values.index(peak)]

    # Ratio
    ratio = peak / baseline if baseline > 0 else float('inf')

    print(f"\n--- HOURLY DECISION RATE ---")
    print(f"Total hours in window: {len(hours_sorted)}")
    print(f"Hourly rates: min={min(hourly_values)}, max={peak}, mean={sum(hourly_values)/len(hourly_values):.1f}")
    print(f"Baseline (homeostasis, 25-75%ile mean): {baseline:.1f} decisions/hour")
    print(f"Peak (max hourly rate): {peak} decisions/hour at {peak_hour}")
    print(f"Peak/Baseline ratio: {ratio:.2f}x")
    print(f"Median hourly rate: {sorted_vals[n//2]}")
    print()

    # Top 5 peak hours
    print("--- Top 5 peak hours ---")
    top5 = sorted(zip(hourly_values, hours_sorted), reverse=True)[:5]
    for rate, hour in top5:
        print(f"  {rate:5d} dec/h  {hour}")

    # Decision type breakdown
    print(f"\n--- Decision type breakdown (sample last 20K decisions) ---")
    type_counts = Counter()
    sample_count = 0
    with open(args.file, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if classify_decision(ev):
                type_counts[ev.get("event_type", "?")] += 1
                sample_count += 1
                if sample_count >= 20000:
                    break

    for et, cnt in type_counts.most_common():
        print(f"  {et:25s}: {cnt}")

    # Summary for AC paper
    print(f"\n=== SUMMARY (for AC Open Questions Q6) ===")
    print(f"IMPORTANT: events.jsonl ONLY records param_change decisions.")
    print(f"  φ↓ emissions, grants, s3_alloc, and algedonic_actions are")
    print(f"  NATS-only signals — NOT persisted to the chain.")
    print(f"  These rates are LOWER BOUNDS (param_change only).")
    print(f"")
    print(f"Decisions emitted per year (extrapolated): {decisions / span_days * 365.25:.0f}")
    print(f"Baseline d|D|/dt = {baseline:.1f} dec/h (homeostasis, param_change only)")
    print(f"Peak d|D|/dt    = {peak} dec/h at {peak_hour} ({ratio:.1f}x baseline)")
    print(f"Window: {span_days:.1f} days, {len(hours_sorted)} hours with activity")
    print(f"")
    print(f"Constraint: total NATS decision throughput is higher but unmeasured.")
    print(f"  To measure full d|D|/dt, instrument NATS publish byte counts in the")
    print(f"  phi_down path (future task — out of scope for AC-M4-REDO).")

if __name__ == "__main__":
    main()
