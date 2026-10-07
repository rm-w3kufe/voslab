#!/usr/bin/env python3
"""abstention_audit.py — §6.3 census + window verdict (REFS-OPT-001 F4.2).

Counting deliverable of the abstention audit ("conteo de salidas
TRUE/UNKNOWN/fail por evaluación, logs + canon stats") — READ-ONLY,
emission lives elsewhere:

  traces   final_truth / final_certified census: full file, rolling
           window, operational split (health_semantics.classify_trace).
  log      evaluate.* entries from logs/agent_plugin.jsonl: class
           (operational | test) split and truth= buckets
           (TRUE / FALSE / UNKNOWN / ERROR / none).
  window   abstention_window_stats() — the SAME logic the alarm uses
           (single source: system/kernel/alerting.py). `would_fire`
           tells whether the algedonic abstention_collapse signal would
           raise right now.

Emission ONLY in AlertMonitor (alerting.py --check; bridge stage
`abstention-check` at session.created, dedup: unacked or <24h). This
script never opens state/rsi/alerts.jsonl.

Deterministic (R10): file contents + wall clock. rc: 0 = report
produced (default, even when would_fire); with --check rc=1 iff
would_fire. Paths resolve from VOSLAB_PATH (same override as
alerting) — production trace files are ~60MB, full census takes
seconds; not for hot paths.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_VOS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_VOS_ROOT / "system" / "kernel"))

from alerting import DEFAULT_THRESHOLDS, abstention_window_stats  # noqa: E402
from health_semantics import NON_OPERATIONAL, classify_trace  # noqa: E402

#: truth=... lives inside the log entry's action field (rsi_cycle format).
TRUTH_RE = re.compile(r"truth=(\w+)")


def _root() -> Path:
    return Path(os.environ.get("VOSLAB_PATH", str(_VOS_ROOT)))


def read_traces(path: Path) -> list[dict]:
    """Parse tree_traces.jsonl (bad lines skipped, like AlertMonitor)."""
    if not path.is_file():
        return []
    traces = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            traces.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return traces


def census_truths(traces: list[dict]) -> dict:
    """final_truth / final_certified counters over a trace list."""
    truths: Counter = Counter()
    certified: Counter = Counter()
    for t in traces:
        truths[str(t.get("final_truth", "?"))] += 1
        certified[str(t.get("final_certified", "?"))] += 1
    return {"total": len(traces), "truths": dict(truths),
            "certified": dict(certified)}


def census_log(path: Path) -> dict:
    """evaluate.* census from the live unified log (rotated archives out
    of scope — the live file holds the recent window an audit needs)."""
    if not path.is_file():
        return {"total": 0, "by_event": {},
                "truths": {"operational": {}, "test": {}}}
    by_event: Counter = Counter()
    buckets = {"operational": Counter(), "test": Counter()}
    total = 0
    for line in path.read_text(encoding="utf-8",
                               errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        event_type = str(entry.get("event_type", ""))
        if not event_type.startswith("evaluate"):
            continue
        total += 1
        by_event[event_type] += 1
        match = TRUTH_RE.search(str(entry.get("action", "")))
        truth = match.group(1) if match else "none"
        cls = "test" if entry.get("class") == "test" else "operational"
        buckets[cls][truth] += 1
    return {
        "total": total,
        "by_event": dict(by_event),
        "truths": {"operational": dict(buckets["operational"]),
                   "test": dict(buckets["test"])},
    }


def build_report(window: int, sustain_h: float) -> dict:
    root = _root()
    traces = read_traces(root / "state" / "rsi" / "tree_traces.jsonl")
    operational = [t for t in traces
                   if classify_trace(t) != NON_OPERATIONAL]
    stats = abstention_window_stats(traces, window, sustain_h)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "traces": {**census_truths(traces),
                   "operational": census_truths(operational)},
        "log": census_log(root / "logs" / "agent_plugin.jsonl"),
        "window": stats,
        "would_fire": stats["would_fire"],
    }


def _human(report: dict) -> str:
    tr = report["traces"]
    op = tr["operational"]
    lg = report["log"]
    w = report["window"]
    lines = [
        f"abstention audit — {report['ts']}",
        f"traces: {tr['total']} total | truths {tr['truths']} | "
        f"certified {tr['certified']}",
        f"  operational: {op['total']} | truths {op['truths']} | "
        f"certified {op['certified']}",
        f"log: {lg['total']} evaluate events | truths {lg['truths']}",
        f"window: {w['samples']}/{w['window']} samples, span {w['span_h']}h "
        f"(sustain {w['sustain_h']}h), abstentions {w['abstentions']}, "
        f"last_abstention {w['last_abstention_ts']}",
        f"would_fire: {report['would_fire']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="§6.3 abstention census (read-only; alarm lives in alerting)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report")
    parser.add_argument("--check", action="store_true",
                        help="rc=1 iff the alarm would fire now")
    parser.add_argument("--window", type=int,
                        default=DEFAULT_THRESHOLDS["abstention_window"])
    parser.add_argument("--sustain-h", type=float,
                        default=DEFAULT_THRESHOLDS["abstention_sustain_h"])
    args = parser.parse_args(argv)

    report = build_report(args.window, args.sustain_h)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str))
    else:
        print(_human(report))

    if args.check and report["would_fire"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
