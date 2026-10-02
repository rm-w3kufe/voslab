#!/usr/bin/env python3
"""AC-ETA-REDO: η₁ and η₂ efficiency ratios from canon events.jsonl.

η₁ = decision bits / variety bits  (dimensionless)
η₂ = decision bits / joules         (bits/J)

Decision types (same as AC-M4-REDO): param_change (only type persisted in canon).
Variety bits = total byte count of ALL events in the file.
Decision bits = total byte count of decision-type events only.

η₂ requires RAPL energy data (joules) from n02 host, which can only be measured
on the host (containers can't read /sys/class/powercap/). This script computes
η₁ directly from events.jsonl and provides bit counts for η₂ computation.
"""

import argparse
import json
import sys
import os
from collections import defaultdict

DECISION_TYPES = {"phi_down", "grant", "algedonic_action", "s3_alloc", "param_change"}

def classify_decision(ev: dict) -> bool:
    et = ev.get("event_type", "")
    return et in DECISION_TYPES

def main():
    parser = argparse.ArgumentParser(description="AC-ETA-REDO: efficiency ratios")
    parser.add_argument("--file", required=True, help="Path to events.jsonl")
    parser.add_argument("--rapl-joules", type=float, default=None,
                        help="Total joules from RAPL over the measurement window (for η₂)")
    parser.add_argument("--cpu-share-101", type=float, default=None,
                        help="CPU time share of LXC 101 (fraction of total, for η₂ attribution)")
    parser.add_argument("--cpu-share-110", type=float, default=None,
                        help="CPU time share of LXC 110 (fraction of total, for η₂ attribution)")
    args = parser.parse_args()

    total_bytes = 0
    decision_bytes = 0
    decision_count = 0
    total_events = 0
    first_ts = None
    last_ts = None

    with open(args.file, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_events += 1
            line_bytes = len(line.encode("utf-8"))
            total_bytes += line_bytes

            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = ev.get("ts")
            if ts_str:
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except (ValueError, AttributeError):
                    pass

            if classify_decision(ev):
                decision_count += 1
                decision_bytes += line_bytes

    window_seconds = (last_ts - first_ts).total_seconds() if first_ts and last_ts else 0
    window_hours = window_seconds / 3600 if window_seconds > 0 else 0

    print("=== AC-ETA-REDO: Efficiency Ratios ===")
    print(f"Data window: {first_ts} to {last_ts}" if first_ts else "No timestamps")
    print(f"Window: {window_hours:.1f} hours ({window_seconds:.0f}s)")
    print(f"Total events: {total_events}")
    print(f"Total bytes: {total_bytes:,} ({total_bytes/1024:.1f} KB, {total_bytes/1048576:.1f} MB)")
    print(f"Decision events: {decision_count}")
    print(f"Decision bytes: {decision_bytes:,} ({decision_bytes/1024:.1f} KB)")
    print()

    # η₁ = decision bits / variety bits (dimensionless)
    if total_bytes > 0:
        eta1 = decision_bytes / total_bytes
        print(f"η₁ (dimensionless) = decision_bytes / total_bytes")
        print(f"  = {decision_bytes:,} / {total_bytes:,}")
        print(f"  = {eta1:.6f}")
        print(f"  = {eta1*100:.4f}% of total bytes are decision content")
        print()
    else:
        print("η₁: cannot compute (total_bytes = 0)")

    # Decision bits (bytes * 8)
    decision_bits = decision_bytes * 8
    print(f"Decision bits: {decision_bytes:,} bytes × 8 = {decision_bits:,} bits")
    print()

    # η₂ = decision bits / joules (bits/J)
    if args.rapl_joules is not None:
        # Total joules from RAPL for the window
        total_joules = args.rapl_joules

        # Attribution to LXC 101+110 by CPU share
        share_101 = args.cpu_share_101 or 0.5  # default 50%
        share_110 = args.cpu_share_110 or 0.1  # default 10%
        attributed_joules = total_joules * (share_101 + share_110)

        eta2 = decision_bits / attributed_joules if attributed_joules > 0 else float('inf')
        print(f"η₂ (bits/J) = decision_bits / attributed_joules")
        print(f"  RAPL total: {total_joules:.1f} J over window")
        print(f"  LXC 101 share: {share_101:.1%}")
        print(f"  LXC 110 share: {share_110:.1%}")
        print(f"  Attributed joules: {attributed_joules:.1f} J")
        print(f"  Decision bits: {decision_bits:,} bits")
        print(f"  η₂ = {eta2:.4f} bits/J")
        print(f"  η₂ = {eta2*8:.4f} bytes/J (alternative: decision_bytes / J)")
    else:
        print("η₂: RAPL data required. Provide --rapl-joules and --cpu-share-* flags.")

    print()
    print("=== NOTE ===")
    print("These are LOWER BOUNDS — only param_change decisions are persisted")
    print("in events.jsonl. φ↓, grant, s3_alloc, and algedonic_action decisions")
    print("are NATS-only signals not recorded in the chain. True η₁ and η₂")
    print("would include NATS byte counts (total vs decision-specific), which")
    print("requires NATS monitoring instrumentation.")
    print()

if __name__ == "__main__":
    main()
