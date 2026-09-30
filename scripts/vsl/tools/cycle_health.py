#!/usr/bin/env python3
"""cycle_health.py — CC-7 closed-cycle observability (anti-pantomima).

One command that reports the REAL state of the learning cycle, per cable:

  idle    — session.* hook present in router, last firing, 24h window count
  last    — last idle burst: summary metrics + per-handler results
  queue   — approval-queue depth by status (pending/approved/activated/rejected)
  ceiling — L4_AUTO flag + activated-registry entries (activation-by-approval)
  guards  — declared guard_status of the cycle guards (state/epistemic)

Exit code (deterministic, R10):
  0 — cable healthy: hook present AND >=1 idle summary in the last 24h
  1 — cable starved (dead hook or no firing in 24h)

Usage:
  python3 scripts/vsl/tools/cycle_health.py          # human-readable
  python3 scripts/vsl/tools/cycle_health.py --json   # machine-readable
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
ROUTER = VOSLAB / ".opencode" / "plugins" / "operational" / "vsf-event-router.ts"
HANDLER_STATES = (
    VOSLAB / ".opencode" / "plugins" / "operational" / "handler_states.json"
)
LOG = VOSLAB / "logs" / "agent_plugin.jsonl"
QUEUE_DIR = VOSLAB / "state" / "rsi" / "queue"
ACTIVATED = VOSLAB / "state" / "rsi" / "activated.json"
RSI_CYCLE = VOSLAB / "system" / "kernel" / "rsi_cycle.py"
GUARDS = VOSLAB / "state" / "epistemic" / "guards.jsonl"
FINDINGS = VOSLAB / "state" / "epistemic" / "findings.jsonl"

CYCLE_GUARDS = ("G-IDLE-LIVE", "G-IDLE-TRIGGERS", "G-BOOTOOLS-PATH", "G-AGENT-LOG-SCHEMA")


def _parse_ts(value: str) -> datetime | None:
    """Parse mixed log timestamps (python '+00:00' and TS 'Z' formats)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _log_rows():
    """Yield parsed rows across rotated archives (oldest first) + current log.

    The log rotates on every session restart (e.g. 53 idle summaries of
    2026-09-30 ended up in the .gz when rmw3 restarted at 07:28Z) — reading
    only the current file made cycle_health report a false STARVED
    (total=0, last=never).
    """
    files = sorted(LOG.parent.glob(LOG.name + ".*.jsonl.gz"))
    if LOG.exists():
        files.append(LOG)
    for f in files:
        try:
            opener = gzip.open if f.suffix == ".gz" else open
            with opener(f, "rt", errors="ignore") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    yield row
        except OSError:
            continue


def _idle_cable(now: datetime) -> dict:
    hook = 0
    if ROUTER.exists():
        hook = ROUTER.read_text().count('startsWith("session.")')
    total = 0
    w24 = 0
    last_ts = None
    last_row = None
    for row in _log_rows():
        if row.get("action") != "summary:session.idle":
            continue
        total += 1
        ts = _parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        if last_ts is None or ts > last_ts:
            last_ts = ts
            last_row = row
        if now - ts <= timedelta(hours=24):
            w24 += 1
    return {
        "hook_present": hook > 0,
        "last_fired": last_ts.isoformat() if last_ts else None,
        "idles_24h": w24,
        "idles_total": total,
        "healthy": hook > 0 and w24 >= 1,
        "_last_row": last_row,
    }


def _last_burst(last_row: dict | None) -> dict:
    """Per-handler results of the last idle dispatch (same event_id)."""
    if not last_row:
        return {}
    eid = last_row.get("event_id")
    handlers: dict[str, str] = {}
    if eid:
        for row in _log_rows():
            if row.get("event_id") != eid:
                continue
            action = row.get("action") or ""
            if action.startswith("session.idle:") and row.get("source"):
                handlers[row["source"]] = row.get("result") or "?"
    metrics = last_row.get("metrics") or {}
    return {
        "ts": last_row.get("ts"),
        "result": last_row.get("result"),
        "duration_ms": metrics.get("duration_ms"),
        "handlers_total": metrics.get("items_processed", len(handlers)),
        "handlers": handlers,
    }


def _queue() -> dict:
    stats = {"pending": 0, "approved": 0, "activated": 0, "rejected": 0}
    names: dict[str, list[str]] = {k: [] for k in stats}
    if QUEUE_DIR.is_dir():
        for f in sorted(QUEUE_DIR.glob("*.json")):
            try:
                entry = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            status = entry.get("status", "pending")
            if status not in stats:
                stats[status] = stats.get(status, 0) + 1
            else:
                stats[status] += 1
            names.setdefault(status, []).append(entry.get("name", f.stem))
    return {"stats": stats, "names": names}


def _ceiling() -> dict:
    l4 = "unknown"
    if RSI_CYCLE.exists():
        m = re.search(r"^L4_AUTO\s*=\s*(\S+)", RSI_CYCLE.read_text(), re.M)
        if m:
            l4 = m.group(1)
    reg = {"exists": ACTIVATED.exists(), "entries": {}}
    if ACTIVATED.exists():
        try:
            reg["entries"] = json.loads(ACTIVATED.read_text())
        except (json.JSONDecodeError, OSError):
            reg["entries"] = {"error": "unreadable"}
    return {"L4_AUTO": l4, "activated_registry": reg}


def _guard_statuses() -> dict:
    declared: dict[str, str] = {}
    if FINDINGS.exists():
        with FINDINGS.open(errors="ignore") as fh:
            for line in fh:
                try:
                    f = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                gid = f.get("guard")
                if gid in CYCLE_GUARDS:
                    declared[gid] = f.get("guard_status", "?")
    registered = set()
    if GUARDS.exists():
        with GUARDS.open(errors="ignore") as fh:
            for line in fh:
                try:
                    registered.add(json.loads(line).get("id"))
                except (json.JSONDecodeError, ValueError):
                    continue
    return {
        gid: {
            "registered": gid in registered,
            "declared": declared.get(gid, "unreferenced"),
        }
        for gid in CYCLE_GUARDS
    }


def _handlers_state() -> dict:
    if not HANDLER_STATES.exists():
        return {"exists": False}
    try:
        data = json.loads(HANDLER_STATES.read_text())
    except (json.JSONDecodeError, OSError):
        return {"exists": True, "readable": False}
    if isinstance(data, dict):
        # PLC-001 shape: {"version":…, "_note":…, "handlers":{name:{enabled:…}}}
        handlers = data.get("handlers")
        if isinstance(handlers, dict):
            disabled = [
                k for k, v in handlers.items()
                if v is False or v == "disabled"
                or (isinstance(v, dict) and v.get("enabled") is False)
            ]
            return {"exists": True, "count": len(handlers), "disabled": disabled}
        disabled = [k for k, v in data.items() if v is False or v == "disabled"]
        return {"exists": True, "count": len(data), "disabled": disabled}
    if isinstance(data, list):
        disabled = [
            e.get("id") for e in data
            if isinstance(e, dict) and e.get("enabled") is False
        ]
        return {"exists": True, "count": len(data), "disabled": disabled}
    return {"exists": True, "shape": type(data).__name__}


def health() -> dict:
    now = datetime.now(timezone.utc)
    cable = _idle_cable(now)
    last_row = cable.pop("_last_row", None)
    return {
        "ts": now.isoformat(timespec="seconds"),
        "idle": cable,
        "last_idle": _last_burst(last_row),
        "queue": _queue(),
        "ceiling": _ceiling(),
        "guards": _guard_statuses(),
        "handlers": _handlers_state(),
        "healthy": cable["healthy"],
    }


def main() -> int:
    as_json = "--json" in sys.argv[1:]
    h = health()
    if as_json:
        print(json.dumps(h, indent=2, ensure_ascii=False, default=str))
        return 0 if h["healthy"] else 1

    idle = h["idle"]
    print(f"cycle_health @ {h['ts']}")
    print(
        f"  idle   hook={'yes' if idle['hook_present'] else 'NO'}"
        f"  last={idle['last_fired'] or 'never'}"
        f"  24h={idle['idles_24h']}  total={idle['idles_total']}"
    )
    last = h["last_idle"]
    if last:
        print(
            f"  last   {last.get('ts')} result={last.get('result')}"
            f" dur={last.get('duration_ms')}ms handlers={last.get('handlers_total')}"
        )
        for name, res in sorted((last.get("handlers") or {}).items()):
            print(f"           {res:6s} {name}")
    q = h["queue"]["stats"]
    print(
        f"  queue  pending={q.get('pending', 0)} approved={q.get('approved', 0)}"
        f" activated={q.get('activated', 0)} rejected={q.get('rejected', 0)}"
    )
    c = h["ceiling"]
    print(
        f"  ceiling L4_AUTO={c['L4_AUTO']}  activated_registry="
        f"{'yes' if c['activated_registry']['exists'] else 'absent'}"
        f" ({len(c['activated_registry']['entries'])} entries)"
    )
    for gid, info in sorted(h["guards"].items()):
        print(
            f"  guard  {gid}: registered={info['registered']}"
            f" declared={info['declared']}"
        )
    hs = h["handlers"]
    if hs.get("exists"):
        print(
            f"  handlers count={hs.get('count', '?')}"
            f" disabled={hs.get('disabled') or 'none'}"
        )
    print(f"  => {'HEALTHY' if h['healthy'] else 'STARVED'}")
    return 0 if h["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
