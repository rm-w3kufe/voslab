#!/usr/bin/env python3
"""s3_review_surface.py — S3* supervision review surface, report MVP (B1/A rescue).
design: docs/design/sources/driver-topology-v1/driver_topology.vsm

Reads the DURABLE S3* audit stream (B1: audit_stream.jsonl persisted by
vsf-audit-logger) and answers the strategic question (s3_allocation §12):
"is autonomous regulation aligned with ENDS, or drifting?" — volume, trend,
distribution, anomalies. Acting on the answer is double-loop (A5, human).

Sections:
  VOLUME ....... events in window, by type; resource moved (grants)
  TREND ........ per-day counts over trailing window: rising/stable/falling
  DISTRIBUTION . by audit_source, role, action
  ANOMALIES .... chronically propped target (>=5 grants, 0 restores in
                 window); standing escalations (escalated==true latest);
                 test-escalation rows listed separately (never counted
                 as findings — test data in a durable log is honest only
                 when labeled)

Tolerant reader: malformed lines counted and skipped, never fatal.
Exit 1 iff anomalies (cron-visible); 0 otherwise. --json for opsroom use.

Suggested cadence: weekly (strategic judgment, not a 5-min loop):
    0 6 * * 0 flock -n /var/lock/vsf_review_surface.lock \
      pct exec 101 -- cat /var/log/vsf-audit/audit_stream.jsonl | \
      python3 /usr/local/bin/s3_review_surface.py --stdin --days 7 \
      >> /var/log/vsf-review-surface.log 2>&1
Default input is the live log path (runs on the log host); --stdin and
--days / --chronic-threshold keep tests and deploys honest.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

DEFAULT_LOG = os.environ.get("VSF_AUDIT_LOG",
                             "/var/lib/vsf-audit/audit_stream.jsonl")
LIVE_DEFAULT = "/var/log/vsf-audit/audit_stream.jsonl"
CHRONIC_DEFAULT = 5


def _parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def load_events(source):
    """Yield (event_dict) from a path or stdin; returns (events, malformed)."""
    if source == "-":
        text = sys.stdin.read()
        lines = text.splitlines()
    else:
        try:
            with open(source, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError as exc:
            print(f"review_surface: cannot read {source}: {exc}", file=sys.stderr)
            return [], 0
    events, malformed = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(e, dict):
            events.append(e)
        else:
            malformed += 1
    return events, malformed


def _in_window(ts, since):
    return ts is not None and ts >= since


def analyze(events, malformed, days, chronic_threshold):
    """Pure analysis over parsed events. Returns the report dict."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    windowed = []
    for e in events:
        ts = _parse_ts(e.get("ts") or e.get("timestamp") or "")
        if _in_window(ts, since):
            windowed.append((ts, e))

    by_type = Counter()
    by_source = Counter()
    by_role = Counter()
    by_action = Counter()
    per_day = Counter()
    cores_moved = 0
    mem_moved = 0
    test_rows = 0
    grants_by_target = Counter()
    restores_by_target = Counter()
    standing_escalations = []
    for ts, e in windowed:
        etype = e.get("event_type", "?")
        if isinstance(e.get("escalation_id"), str) and \
                e["escalation_id"].startswith("test-"):
            test_rows += 1
            continue
        by_type[etype] += 1
        by_source[e.get("audit_source", "?")] += 1
        by_role[e.get("role", "?")] += 1
        by_action[e.get("action", "?")] += 1
        per_day[ts.date().isoformat()] += 1
        if etype == "s3_resource_grant":
            try:
                cores_moved += int(e.get("grant_cores", 0) or 0)
                mem_moved += int(e.get("grant_mem_mb", 0) or 0)
            except (TypeError, ValueError):
                pass
            tgt = str(e.get("vmid", "?"))
            grants_by_target[tgt] += 1
        elif etype == "s3_resource_restore":
            restores_by_target[str(e.get("vmid", "?"))] += 1
        if e.get("escalated") is True:
            standing_escalations.append({
                "ts": ts.isoformat(),
                "type": etype,
                "target": str(e.get("vmid", e.get("role", "?"))),
                "reason": str(e.get("escalation_reason",
                                    e.get("reason", "")))[:160],
            })

    days_sorted = sorted(per_day)
    half = len(days_sorted) // 2
    first = sum(per_day[d] for d in days_sorted[:half] or ["x"])
    second = sum(per_day[d] for d in days_sorted[half:] or ["y"])
    if second > first * 1.5:
        trend = "rising"
    elif first > second * 1.5:
        trend = "falling"
    else:
        trend = "stable"

    chronic = sorted(
        [{"target": t, "grants": n,
          "restores": restores_by_target.get(t, 0)}
         for t, n in grants_by_target.items()
         if n >= chronic_threshold and restores_by_target.get(t, 0) == 0],
        key=lambda r: -r["grants"])

    return {
        "window_days": days,
        "events_total": len(events),
        "events_in_window": len(windowed),
        "malformed_skipped": malformed,
        "test_rows_labeled": test_rows,
        "volume": {
            "by_type": dict(by_type.most_common()),
            "cores_granted": cores_moved,
            "mem_mb_granted": mem_moved,
        },
        "trend": {"direction": trend, "per_day": dict(sorted(per_day.items()))},
        "distribution": {
            "by_source": dict(by_source.most_common()),
            "by_role": dict(by_role.most_common()),
            "by_action": dict(by_action.most_common()),
        },
        "anomalies": {
            "chronically_propped": chronic,
            "standing_escalations": standing_escalations[-20:],
        },
    }


def render(report) -> str:
    lines = []
    a = lines.append
    a(f"S3* supervision review — trailing {report['window_days']}d")
    a(f"events: {report['events_in_window']} in window "
      f"({report['events_total']} parsed, "
      f"{report['malformed_skipped']} malformed skipped, "
      f"{report['test_rows_labeled']} test rows labeled-not-counted)")
    a("VOLUME:")
    for k, v in report["volume"]["by_type"].items():
        a(f"  {k}: {v}")
    a(f"  resource moved: {report['volume']['cores_granted']} cores, "
      f"{report['volume']['mem_mb_granted']} MB")
    a(f"TREND: {report['trend']['direction']}")
    for d, v in report["trend"]["per_day"].items():
        a(f"  {d}: {v}")
    a("DISTRIBUTION:")
    for dim in ("by_source", "by_role", "by_action"):
        a(f"  {dim}: " + ", ".join(
            f"{k}={v}" for k, v in report["distribution"][dim].items()))
    an = report["anomalies"]
    a("ANOMALIES:")
    if not an["chronically_propped"] and not an["standing_escalations"]:
        a("  none — regulation within bounds this window")
    for r in an["chronically_propped"]:
        a(f"  CHRONIC target={r['target']} grants={r['grants']} "
          f"restores={r['restores']} (structural problem masked as tuning?)")
    for s in an["standing_escalations"]:
        a(f"  ESCALATION {s['ts']} {s['type']} target={s['target']}: "
          f"{s['reason']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    source, days, threshold, as_json = LIVE_DEFAULT, 7, CHRONIC_DEFAULT, False
    i = 0
    while i < len(args):
        if args[i] == "--stdin":
            source = "-"
        elif args[i] == "--file" and i + 1 < len(args):
            i += 1
            source = args[i]
        elif args[i] == "--days" and i + 1 < len(args):
            i += 1
            try:
                days = max(1, int(args[i]))
            except ValueError:
                pass
        elif args[i] == "--chronic-threshold" and i + 1 < len(args):
            i += 1
            try:
                threshold = max(1, int(args[i]))
            except ValueError:
                pass
        elif args[i] == "--json":
            as_json = True
        i += 1
    events, malformed = load_events(source)
    report = analyze(events, malformed, days, threshold)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(render(report), end="")
    an = report["anomalies"]
    return 1 if (an["chronically_propped"] or an["standing_escalations"]) else 0


if __name__ == "__main__":
    sys.exit(main())
