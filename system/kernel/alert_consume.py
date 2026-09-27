#!/usr/bin/env python3
"""alert_consume — EP-0/F3: boot-time consumer for state/rsi/alerts.jsonl.

Why: the alerting layer produced alerts nobody ever read (1144 unacked as
of 2026-09-27, including the health_degradation alert of 2026-09-26).
This script is the missing consumer: it surfaces unacknowledged alerts on
boot and records acknowledgment through AlertMonitor (official storage).

Modes:
  --list   read-only: summary + last N alert details, then
           "alerts_unacked=<n>" (for tests / negative control)
  --boot   same surface, then acknowledges ALL unacked via
           AlertMonitor.acknowledge_many() and prints
           "alerts_consumed=<n>" (default mode)

Contract: last output line is machine-readable; exit code is always 0 —
alert consumption is best-effort and must never block boot.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alerting import AlertMonitor  # noqa: E402  (same-dir kernel module)

SHOW_N = 10


def main(argv) -> int:
    mode = "--list" if "--list" in argv else "--boot"
    monitor = AlertMonitor()
    try:
        alerts = monitor._read_alerts()
    except FileNotFoundError:
        print("alerts_consumed=0 reason=no_alerts_file")
        return 0
    except (json.JSONDecodeError, OSError) as e:
        print(f"alerts_consumed=0 reason=unreadable:{e}")
        return 0

    unacked = [a for a in alerts if not a.get("acknowledged")]
    if not unacked:
        print("alerts_unacked=0" if mode == "--list" else "alerts_consumed=0")
        return 0

    by_level = Counter(str(a.get("level", "?")) for a in unacked)
    by_type = Counter(str(a.get("alert_type", "?")) for a in unacked)
    span = f"{unacked[0].get('ts', '?')}..{unacked[-1].get('ts', '?')}"
    print(
        f"UNACKED ALERTS: {len(unacked)} "
        f"| levels={dict(by_level)} | types={dict(by_type)} | span={span}"
    )
    for a in unacked[-SHOW_N:]:
        print(
            f"  [{a.get('level')}] {a.get('ts')} {a.get('alert_type')}: "
            f"{str(a.get('detail', ''))[:100]}"
        )

    if mode == "--list":
        print(f"alerts_unacked={len(unacked)}")
        return 0

    try:
        acked = monitor.acknowledge_many(a.get("alert_id") for a in unacked)
    except OSError as e:
        print(f"alerts_consumed=0 reason=ack_write_failed:{e}")
        return 0
    print(f"alerts_consumed={acked}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
