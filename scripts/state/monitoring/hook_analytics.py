#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/r16-spec-v1/LEARNING-CYCLE-INSTRUMENTS-DESIGN.vsm
"""hook_analytics.py — variety absorption for hook activation logs.

ABSORCIÓN DE VARIEDAD (rmw3 S5): the activation log (logs/agent_plugin.jsonl)
contains raw variety — every hook firing, every result, every timestamp.
This instrument ABSORBS that variety and REDUCES it to patterns:
  (a) Frequency: which hooks fire most, which never fire
  (b) Errors: which hooks fail, failure rates, consecutive failures
  (c) Timing: activation gaps, dead periods, anomaly detection
  (d) Correlations: hook failures correlated with learning records

Deterministic (R10): reads logs, computes patterns, outputs report.
Does NOT decide — surfaces patterns for S4/S5 to act on.

Usage:
  hook_analytics.py                    # full report (stdout)
  hook_analytics.py --json             # machine-readable (for hooks)
  hook_analytics.py --window-hours 24  # analyze last N hours only
  hook_analytics.py --correlate       # include learning record correlation

Output: VSM-structured report with patterns, anomalies, recommendations.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2].parent  # scripts/.. = repo root
LOG_FILE = ROOT / "logs" / "agent_plugin.jsonl"
LEARNING_RECORDS = ROOT / "docs" / "spec_revision" / "learning_records"

# ── Log parsing ──────────────────────────────────────────────────────────────

def parse_log(path: Path, window_hours: int | None = None) -> list[dict]:
    """Parse JSONL log, optionally filtering to last N hours."""
    records = []
    if not path.exists():
        return records

    cutoff = None
    if window_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Filter by window
            if cutoff:
                try:
                    ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except (KeyError, ValueError):
                    continue

            records.append(r)

    return records


# ── Pattern detection ────────────────────────────────────────────────────────

def detect_frequency(records: list[dict]) -> dict:
    """Pattern (a): hook activation frequency."""
    instrument_counts = Counter(r.get("instrument", "unknown") for r in records)
    hook_counts = Counter(r.get("hook", "unknown") for r in records)

    # Dead instruments (declared but never fired)
    all_instruments = set(instrument_counts.keys())

    return {
        "total_activations": len(records),
        "instruments": dict(instrument_counts.most_common()),
        "hooks": dict(hook_counts.most_common()),
        "unique_instruments": len(instrument_counts),
        "unique_hooks": len(hook_counts),
    }


def detect_errors(records: list[dict]) -> dict:
    """Pattern (b): error patterns."""
    errors = [r for r in records if r.get("result") in ("error", "fail")]
    error_by_instrument = Counter(r.get("instrument", "unknown") for r in errors)

    # Consecutive failures detection
    consecutive_fails = {}
    current_streak = {}
    max_streaks = {}

    for r in records:
        inst = r.get("instrument", "unknown")
        result = r.get("result", "")

        if result in ("error", "fail"):
            current_streak[inst] = current_streak.get(inst, 0) + 1
            max_streaks[inst] = max(max_streaks.get(inst, 0), current_streak[inst])
        else:
            current_streak[inst] = 0

    # Failure rates
    instrument_totals = Counter(r.get("instrument", "unknown") for r in records)
    failure_rates = {}
    for inst, err_count in error_by_instrument.items():
        total = instrument_totals.get(inst, 0)
        failure_rates[inst] = round(err_count / total * 100, 1) if total > 0 else 0

    return {
        "total_errors": len(errors),
        "error_rate": round(len(errors) / len(records) * 100, 1) if records else 0,
        "errors_by_instrument": dict(error_by_instrument.most_common()),
        "failure_rates": failure_rates,
        "max_consecutive_fails": max_streaks,
    }


def detect_timing(records: list[dict]) -> dict:
    """Pattern (c): timing anomalies."""
    if not records:
        return {"gaps": [], "avg_interval": 0}

    # Parse timestamps
    timestamps = []
    for r in records:
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
            timestamps.append(ts)
        except (KeyError, ValueError):
            continue

    if len(timestamps) < 2:
        return {"gaps": [], "avg_interval": 0}

    timestamps.sort()

    # Calculate intervals
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        intervals.append(delta)

    # Detect gaps (> 1 hour between activations)
    gaps = []
    for i, interval in enumerate(intervals):
        if interval > 3600:  # > 1 hour
            gaps.append({
                "from": timestamps[i].isoformat(),
                "to": timestamps[i + 1].isoformat(),
                "hours": round(interval / 3600, 1),
            })

    avg_interval = sum(intervals) / len(intervals) if intervals else 0

    return {
        "total_intervals": len(intervals),
        "avg_interval_seconds": round(avg_interval, 1),
        "avg_interval_minutes": round(avg_interval / 60, 1),
        "gaps": gaps[:10],  # Top 10 longest gaps
        "max_gap_hours": round(max(intervals) / 3600, 1) if intervals else 0,
    }


def detect_anomalies(records: list[dict]) -> list[dict]:
    """Pattern (d): anomaly detection (simple statistical)."""
    anomalies = []

    # Group by instrument
    by_instrument = defaultdict(list)
    for r in records:
        inst = r.get("instrument", "unknown")
        by_instrument[inst].append(r)

    # Check for instruments with unusual patterns
    for inst, inst_records in by_instrument.items():
        results = [r.get("result", "") for r in inst_records]
        error_count = sum(1 for r in results if r in ("error", "fail"))
        total = len(inst_records)

        # Anomaly: high error rate (> 20%)
        if total >= 5 and error_count / total > 0.2:
            anomalies.append({
                "type": "high_error_rate",
                "instrument": inst,
                "error_rate": round(error_count / total * 100, 1),
                "sample_size": total,
                "severity": "warning",
            })

        # Anomaly: no activations in last 7 days (for non-session hooks)
        if inst_records:
            last_ts = inst_records[-1].get("ts", "")
            try:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - last_dt).days
                if days_since > 7 and inst != "learning-cycle-scan":
                    anomalies.append({
                        "type": "inactive",
                        "instrument": inst,
                        "days_since_last": days_since,
                        "severity": "info",
                    })
            except (KeyError, ValueError):
                pass

    return anomalies


# ── Learning record correlation ──────────────────────────────────────────────

def parse_learning_record(path: Path) -> dict | None:
    """Parse a learning record VSM file and extract metadata."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Extract fields using regex
    result = {"path": str(path), "name": path.stem}

    # Extract @status
    m = re.search(r"@status\s+(\S+)", content)
    if m:
        result["status"] = m.group(1)

    # Extract family
    m = re.search(r"family:\s*(\S+)", content)
    if m:
        result["family"] = m.group(1)

    # Extract class
    m = re.search(r"class:\s*(\S+)", content)
    if m:
        result["class"] = m.group(1)

    # Extract organ
    m = re.search(r"organ:\s*(\S+)", content)
    if m:
        result["organ"] = m.group(1)

    # Extract severity
    m = re.search(r"severity:\s*(\S+)", content)
    if m:
        result["severity"] = m.group(1)

    # Extract lesson (first 100 chars)
    m = re.search(r"lesson:\s*\"([^\"]+)\"", content)
    if m:
        result["lesson"] = m.group(1)[:100]

    # Extract date from header
    m = re.search(r"⟦\s*\S+\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*(\S+)\s*⟧", content)
    if m:
        result["date"] = m.group(1)

    return result


def correlate_learning_records(records: list[dict]) -> dict:
    """Correlate hook activations with learning records.

    CORRELATION PATTERNS:
    1. Temporal: hook failures clustered around learning record creation dates
    2. Topical: hook failures correlate with learning records about the same topic
    3. Instrument: specific hooks fail more when certain learning records exist
    4. Pending: hook failures increase when learning records are pending
    """
    if not LEARNING_RECORDS.exists():
        return {"correlations": [], "record_count": 0}

    # Read learning records
    lr_files = list(LEARNING_RECORDS.rglob("*.vsm"))
    lr_count = len(lr_files)

    # Parse learning records
    lr_data = []
    for lr_file in lr_files:
        parsed = parse_learning_record(lr_file)
        if parsed:
            lr_data.append(parsed)

    # Activations by day
    activations_by_day = Counter()
    errors_by_day = Counter()
    for r in records:
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
            day = ts.strftime("%Y-%m-%d")
            activations_by_day[day] += 1
            if r.get("result") in ("error", "fail"):
                errors_by_day[day] += 1
        except (KeyError, ValueError):
            continue

    # Learning records by date
    lr_by_date = Counter()
    for lr in lr_data:
        date = lr.get("date", "")
        if date:
            # Extract date part from ISO string
            date_part = date[:10] if "T" in date else date
            lr_by_date[date_part] += 1

    # CORRELATION 1: Days with high error rates vs learning record creation
    high_error_days = {day for day, count in errors_by_day.items() if count > 5}
    lr_creation_days = set(lr_by_date.keys())
    overlap_days = high_error_days & lr_creation_days

    correlations = []

    if overlap_days:
        correlations.append({
            "type": "temporal",
            "description": "High error rates on days with learning record creation",
            "days": sorted(overlap_days),
            "severity": "warning",
        })

    # CORRELATION 2: Learning records by family/class
    lr_by_family = Counter(lr.get("family", "unknown") for lr in lr_data)
    lr_by_class = Counter(lr.get("class", "unknown") for lr in lr_data)

    # CORRELATION 3: Instrument-specific patterns
    instrument_errors = Counter()
    for r in records:
        if r.get("result") in ("error", "fail"):
            instrument_errors[r.get("instrument", "unknown")] += 1

    # Check if any instrument has errors on days with learning records
    for inst, error_count in instrument_errors.items():
        if error_count > 10:
            # Find which days this instrument had errors
            inst_error_days = set()
            for r in records:
                if r.get("instrument") == inst and r.get("result") in ("error", "fail"):
                    try:
                        ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
                        inst_error_days.add(ts.strftime("%Y-%m-%d"))
                    except (KeyError, ValueError):
                        continue

            # Check overlap with learning record creation days
            inst_overlap = inst_error_days & lr_creation_days
            if inst_overlap:
                correlations.append({
                    "type": "instrument-topic",
                    "instrument": inst,
                    "description": f"{inst} errors on days with learning record creation",
                    "days": sorted(inst_overlap),
                    "error_count": error_count,
                    "severity": "info",
                })

    # CORRELATION 4: Pending learning records
    pending_dir = LEARNING_RECORDS / ".pending"
    if pending_dir.exists():
        pending_files = list(pending_dir.glob("*.vsm"))
        if pending_files:
            correlations.append({
                "type": "pending",
                "description": f"{len(pending_files)} pending learning records",
                "files": [f.name for f in pending_files[:5]],
                "severity": "info",
            })

    return {
        "record_count": lr_count,
        "parsed_count": len(lr_data),
        "activations_by_day": dict(activations_by_day.most_common(30)),
        "errors_by_day": dict(errors_by_day.most_common(30)),
        "lr_by_date": dict(lr_by_date.most_common(30)),
        "lr_by_family": dict(lr_by_family.most_common(10)),
        "lr_by_class": dict(lr_by_class.most_common(10)),
        "correlations": correlations,
    }


# ── Report generation ────────────────────────────────────────────────────────

def generate_report(records: list[dict], correlate: bool = False) -> dict:
    """Generate full analytics report."""
    freq = detect_frequency(records)
    errors = detect_errors(records)
    timing = detect_timing(records)
    anomalies = detect_anomalies(records)

    report = {
        "summary": {
            "total_records": len(records),
            "unique_instruments": freq["unique_instruments"],
            "unique_hooks": freq["unique_hooks"],
            "error_rate": errors["error_rate"],
            "anomalies_count": len(anomalies),
        },
        "frequency": freq,
        "errors": errors,
        "timing": timing,
        "anomalies": anomalies,
    }

    if correlate:
        report["learning_correlation"] = correlate_learning_records(records)

    return report


def print_report(report: dict):
    """Print human-readable report."""
    s = report["summary"]

    print("=" * 70)
    print("HOOK ACTIVITY ANALYTICS")
    print("=" * 70)
    print(f"  Total activations: {s['total_records']}")
    print(f"  Unique instruments: {s['unique_instruments']}")
    print(f"  Unique hooks: {s['unique_hooks']}")
    print(f"  Error rate: {s['error_rate']}%")
    print(f"  Anomalies detected: {s['anomalies_count']}")
    print()

    # Frequency
    print("─" * 70)
    print("FREQUENCY (top instruments)")
    print("─" * 70)
    for inst, count in list(report["frequency"]["instruments"].items())[:10]:
        print(f"  {inst:40s} {count:6d}")
    print()

    # Errors
    if report["errors"]["total_errors"] > 0:
        print("─" * 70)
        print("ERRORS")
        print("─" * 70)
        print(f"  Total errors: {report['errors']['total_errors']}")
        print(f"  Error rate: {report['errors']['error_rate']}%")
        for inst, count in report["errors"]["errors_by_instrument"].items():
            rate = report["errors"]["failure_rates"].get(inst, 0)
            print(f"  {inst:40s} {count:4d} ({rate}%)")
        print()

        # Max consecutive failures
        if report["errors"]["max_consecutive_fails"]:
            print("  Max consecutive failures:")
            for inst, streak in report["errors"]["max_consecutive_fails"].items():
                if streak > 0:
                    print(f"    {inst}: {streak}")
            print()

    # Timing
    timing = report["timing"]
    if timing["gaps"]:
        print("─" * 70)
        print("TIMING ANOMALIES")
        print("─" * 70)
        print(f"  Avg interval: {timing['avg_interval_minutes']:.1f} min")
        print(f"  Max gap: {timing['max_gap_hours']:.1f} hours")
        print(f"  Gaps > 1 hour: {len(timing['gaps'])}")
        for gap in timing["gaps"][:5]:
            print(f"    {gap['from'][:19]} → {gap['to'][:19]} ({gap['hours']}h)")
        print()

    # Anomalies
    if report["anomalies"]:
        print("─" * 70)
        print("ANOMALIES")
        print("─" * 70)
        for a in report["anomalies"]:
            severity = "⚠" if a["severity"] == "warning" else "ℹ"
            if a["type"] == "high_error_rate":
                print(f"  {severity} HIGH ERROR RATE: {a['instrument']} — {a['error_rate']}% ({a['sample_size']} samples)")
            elif a["type"] == "inactive":
                print(f"  {severity} INACTIVE: {a['instrument']} — {a['days_since_last']} days since last activation")
        print()

    # Learning correlation
    if "learning_correlation" in report:
        lc = report["learning_correlation"]
        print("─" * 70)
        print("LEARNING CORRELATION")
        print("─" * 70)
        print(f"  Learning records: {lc['record_count']}")
        if lc["activations_by_day"]:
            print("  Activations by day (last 30):")
            for day, count in list(lc["activations_by_day"].items())[:10]:
                print(f"    {day}: {count}")
        print()

    print("=" * 70)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hook activation analytics")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--window-hours", type=int, help="Analyze last N hours only")
    parser.add_argument("--correlate", action="store_true", help="Include learning record correlation")
    args = parser.parse_args()

    records = parse_log(LOG_FILE, args.window_hours)

    if not records:
        print("No activation records found.", file=sys.stderr)
        print(f"Log file: {LOG_FILE}", file=sys.stderr)
        sys.exit(0)

    report = generate_report(records, args.correlate)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
