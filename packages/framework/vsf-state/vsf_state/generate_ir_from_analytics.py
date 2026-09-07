#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/r16-spec-v1/LEARNING-CYCLE-INSTRUMENTS-DESIGN.vsm
"""generate_ir_from_analytics.py — generate learning records from hook analytics patterns.

ABSORCIÓN DE VARIEDAD → APRENDIZAJE (rmw3 S5): the hook analytics instrument
absorbs variety from raw logs and detects patterns. This instrument TAKES those
patterns and generates learning records (IRs) when significant patterns are found.

UPDATED: Now uses socratic engine for pattern classification via pattern_classify.tree.vsm
Predicates: is_high_error_rate, is_consecutive_failures, is_inactive_instrument,
            is_temporal_correlation

The learning cycle is: detect → classify → persist → fix → verify.
This instrument handles the "persist" step for analytics-detected patterns.

Deterministic (R10): reads analytics report, generates IRs.
Does NOT decide significance — uses thresholds from config.

Usage:
  generate_ir_from_analytics.py                    # check and generate if needed
  generate_ir_from_analytics.py --dry-run          # show what would be generated
  generate_ir_fromanalytics.py --min-severity warning  # minimum severity to generate IR
"""
import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add classifier path for socratic engine
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine, _ROOT

ROOT = Path(__file__).resolve().parents[2].parent  # scripts/.. = repo root
ANALYTICS_SCRIPT = ROOT / "scripts" / "state" / "monitoring" / "hook_analytics.py"
LEARNING_RECORDS = ROOT / "docs" / "spec_revision" / "learning_records"
IR_DIR = LEARNING_RECORDS / "learning-record"
PENDING_DIR = LEARNING_RECORDS / ".pending"

# Load tree
TREE = _ROOT / ".opencode/plugins/support/trees/pattern_classify.tree.vsm"

# Thresholds for IR generation
DEFAULT_MIN_SEVERITY = "warning"  # info, warning, critical
DEFAULT_MIN_ERROR_RATE = 10.0     # percentage
DEFAULT_MIN_CONSECUTIVE_FAILS = 5
DEFAULT_MIN_INACTIVE_DAYS = 14


def get_analytics_report(window_hours: int = 168) -> dict:
    """Get analytics report from hook_analytics.py."""
    import subprocess

    cmd = [
        sys.executable,
        str(ANALYTICS_SCRIPT),
        "--json",
        "--window-hours", str(window_hours),
        "--correlate",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"Error getting analytics report: {e}", file=sys.stderr)

    return {}


def classify_pattern(pattern: dict) -> dict:
    """Classify a pattern and determine if it warrants an IR.
    
    Uses socratic engine for classification via pattern_classify.tree.vsm."""
    engine = _create_engine()
    ctx = {"pattern": pattern}
    tree_text = TREE.read_text(encoding="utf-8")
    result = engine.evaluate(tree_text, ctx)
    
    # Map home to classification
    severity = result.home
    family = "novel"
    cls = "instrumentation"
    
    # Classify based on pattern type
    if pattern["type"] == "high_error_rate":
        family = "existing_gap"
        cls = "verification-gap"
    elif pattern["type"] == "consecutive_failures":
        family = "existing_gap"
        cls = "structural"
    elif pattern["type"] == "inactive_instrument":
        family = "instrumentation-census"
        cls = "instrument-readonly"
    elif pattern["type"] == "temporal_correlation":
        family = "policy-instrumentation"
        cls = "design"
    elif pattern["type"] == "instrument_topic_correlation":
        family = "instrument-policy"
        cls = "interpretation-gap"

    return {
        "severity": severity,
        "family": family,
        "class": cls,
    }


def generate_ir(pattern: dict, classification: dict) -> str:
    """Generate a learning record IR from a pattern."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Generate a descriptive name
    pattern_type = pattern["type"].replace("_", "-")
    instrument = pattern.get("instrument", "global")
    name = f"{date_str}_analytics_{pattern_type}_{instrument}"

    # Generate UUID
    ir_uuid = str(uuid.uuid4())

    # Build the IR content
    ir_content = f"""⟦ {name} | LEARNING-RECORD | vsm-1.2.1 | {timestamp} ⟧

@vsm 1.2.1
@status proposed
// learning_records/learning-record/{name}.vsm — auto-generated from hook analytics
// GENERATED: {timestamp}
// PATTERN: {pattern["type"]}

learning_record("{pattern_type.upper()}-{instrument.upper()}-{date_str}") {{
  uuid:      "{ir_uuid}",
  parent:    "hook_analytics.py (auto-generated)",
  family:    "{classification["family"]}",
  class:     "{classification["class"]}",
  severity:  "{classification["severity"]}",
  detection: "{pattern.get("description", pattern["type"])}",
  root_cause: "hook analytics detected pattern: {pattern["type"]}",
  organ:      "S1-operations",
  recursion:  "system",
  canonical:  "logs/agent_plugin.jsonl",
  evidence: "{json.dumps(pattern, indent=2)[:500]}",
  lesson: "hook analytics instrument detected a pattern that warrants
         documentation. This IR was auto-generated to ensure the learning
         cycle captures insights from activation logs.",
  action: "review the pattern and determine if manual intervention is needed",
  trace: {{
    commits: ["auto-generated by hook_analytics.py"],
    checks:  ["hook_analytics.py --json"],
    tests:   [],
  }},
  refs: [],
}}

⟦ /{name} ⟧
"""

    return name, ir_content


def extract_patterns(report: dict) -> list[dict]:
    """Extract significant patterns from analytics report."""
    patterns = []

    # Pattern 1: High error rate
    if report.get("errors", {}).get("error_rate", 0) > DEFAULT_MIN_ERROR_RATE:
        patterns.append({
            "type": "high_error_rate",
            "error_rate": report["errors"]["error_rate"],
            "total_errors": report["errors"]["total_errors"],
            "description": f"High error rate: {report['errors']['error_rate']}%",
        })

    # Pattern 2: Instruments with high failure rates
    for inst, rate in report.get("errors", {}).get("failure_rates", {}).items():
        if rate > DEFAULT_MIN_ERROR_RATE:
            patterns.append({
                "type": "high_error_rate",
                "instrument": inst,
                "error_rate": rate,
                "description": f"{inst}: {rate}% failure rate",
            })

    # Pattern 3: Consecutive failures
    for inst, streak in report.get("errors", {}).get("max_consecutive_fails", {}).items():
        if streak >= DEFAULT_MIN_CONSECUTIVE_FAILS:
            patterns.append({
                "type": "consecutive_failures",
                "instrument": inst,
                "count": streak,
                "description": f"{inst}: {streak} consecutive failures",
            })

    # Pattern 4: Inactive instruments
    for anomaly in report.get("anomalies", []):
        if anomaly["type"] == "inactive" and anomaly.get("days_since_last", 0) > DEFAULT_MIN_INACTIVE_DAYS:
            patterns.append({
                "type": "inactive_instrument",
                "instrument": anomaly["instrument"],
                "days": anomaly["days_since_last"],
                "description": f"{anomaly['instrument']}: {anomaly['days_since_last']} days inactive",
            })

    # Pattern 5: Temporal correlations
    for corr in report.get("learning_correlation", {}).get("correlations", []):
        if corr["type"] == "temporal" and corr["severity"] == "warning":
            patterns.append({
                "type": "temporal_correlation",
                "days": corr["days"],
                "description": corr["description"],
            })

        elif corr["type"] == "instrument-topic":
            patterns.append({
                "type": "instrument_topic_correlation",
                "instrument": corr.get("instrument", "unknown"),
                "days": corr.get("days", []),
                "description": corr["description"],
            })

    return patterns


def main():
    parser = argparse.ArgumentParser(description="Generate IRs from analytics patterns")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")
    parser.add_argument("--min-severity", default=DEFAULT_MIN_SEVERITY,
                        choices=["info", "warning", "critical"],
                        help="Minimum severity to generate IR")
    parser.add_argument("--window-hours", type=int, default=168,
                        help="Analytics window in hours")
    args = parser.parse_args()

    # Get analytics report
    report = get_analytics_report(args.window_hours)
    if not report:
        print("Could not get analytics report", file=sys.stderr)
        sys.exit(1)

    # Extract patterns
    patterns = extract_patterns(report)

    if not patterns:
        print("No significant patterns found")
        sys.exit(0)

    # Filter by severity
    severity_order = {"info": 0, "warning": 1, "critical": 2}
    min_severity = severity_order.get(args.min_severity, 1)

    # Ensure directories exist
    IR_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    generated = []
    for pattern in patterns:
        classification = classify_pattern(pattern)

        # Check severity threshold
        if severity_order.get(classification["severity"], 0) < min_severity:
            continue

        # Generate IR
        name, content = generate_ir(pattern, classification)

        if args.dry_run:
            print(f"Would generate: {name}")
            print(f"  Type: {pattern['type']}")
            print(f"  Severity: {classification['severity']}")
            print(f"  Family: {classification['family']}")
            print(f"  Description: {pattern['description']}")
            print()
        else:
            # Write to pending directory
            pending_path = PENDING_DIR / f"{name}.vsm"
            pending_path.write_text(content, encoding="utf-8")
            generated.append(name)
            print(f"Generated: {name}")

    if not args.dry_run:
        print(f"\n{len(generated)} IR(s) generated in {PENDING_DIR}")
        print("Run 'bash scripts/state/session_learning_scan.sh pass' to verify")


if __name__ == "__main__":
    main()
