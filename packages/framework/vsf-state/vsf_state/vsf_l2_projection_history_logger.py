#!/usr/bin/env python3
"""vsf_l2_projection_history_logger — append-only history for L2 zone stasis_cos.

Independent of vsf_l3_l2_aggregator.py (doesn't modify it) — just reads the
snapshot file it writes every 5 min and appends one line to a JSONL history,
so a future recalibration has real accumulated data instead of a single
point-in-time snapshot. Read-only w.r.t. the snapshot; append-only w.r.t. the
history file. No effect on the anticipation pipeline itself.

Added 2026-07-30 -- the recalibration of BASIN_FLOOR (currently 0.875,
unvalidated against real L2 data) needs a real window to be meaningful, and
this session's window would otherwise start right as a storm + El Nino
intensification hits (rmw3, 2026-07-30) -- exactly the wrong time to treat as
"typical" data. Logging starts now regardless (cheap, no downside); the
regime field lets a future analysis separate storm-time from normal-time
distributions instead of conflating them.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT = Path("/var/lib/vsf/vsf_nucleus/s4_markov_l2_projection.json")
HISTORY = Path("/var/lib/vsf/vsf_nucleus/s4_l2_projection_history.jsonl")


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"[l2-history] snapshot missing: {SNAPSHOT}", file=sys.stderr)
        return 1
    try:
        snap = json.loads(SNAPSHOT.read_text())
    except json.JSONDecodeError as e:
        print(f"[l2-history] snapshot unparseable: {e}", file=sys.stderr)
        return 1

    record = {
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_ts": snap.get("ts"),
        "zones": snap.get("zones", []),
    }

    with open(HISTORY, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"[l2-history] appended {len(record['zones'])} zones (snapshot_ts={record['snapshot_ts']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
