#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/second-order-loop-v1/canonical_feedback.vsm
"""feedback_loop — Capa 3: session feedback loop for the audit trail.

Automatically generates session summaries from tree traces + attestations,
updates health_history.jsonl, and detects patterns (trends, anomalies).

Runs at session end or on-demand via CLI.

Usage:
    # As module:
    from feedback_loop import FeedbackLoop
    loop = FeedbackLoop()
    report = loop.close_session()

    # CLI:
    python3 feedback_loop.py --close-session
    python3 feedback_loop.py --health-report
    python3 feedback_loop.py --selftest
"""
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

_logger = logging.getLogger("feedback_loop")


def _voslab_path() -> Path:
    return Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class SessionReport:
    """Complete feedback report for a session."""
    session_id: str
    ts: str
    duration_seconds: float
    # Trace stats
    total_traces: int
    truth_distribution: Dict[str, int]
    avg_latency_ms: float
    max_latency_ms: float
    total_nodes_evaluated: int
    # Attestation stats
    total_attestations: int
    attestations_valid: int
    # Pattern detection
    patterns: List[Dict[str, Any]]
    # Health delta
    health_entry: Dict[str, Any]


@dataclass
class HealthEntry:
    """Single entry in health_history.jsonl."""
    ts: str
    session_id: str
    corpus: Dict[str, Any]
    traces: Dict[str, Any]
    attestations: Dict[str, Any]
    patterns: List[Dict[str, Any]]


# ─── Pattern Detection ────────────────────────────────────────────────────────

from health_semantics import (  # noqa: E402  (trace health semantics, R10)
    NON_OPERATIONAL,
    OPERATIONAL_FAILURE,
    classify_trace,
    operational_truths,
)


class PatternDetector:
    """Detect patterns in trace history."""

    def detect(self, traces: List[dict]) -> List[Dict[str, Any]]:
        """Analyze traces and return detected patterns."""
        patterns = []

        if not traces:
            return patterns

        # 1. High failure rate — operational traces only (health_semantics:
        # designed-benign FALSEs like type_prefix/task_* gate verdicts are
        # not failures; counting them cried 83% failure at 76/76 green).
        op_traces = [t for t in traces if classify_trace(t) != NON_OPERATIONAL]
        failures = sum(1 for t in op_traces
                       if classify_trace(t) == OPERATIONAL_FAILURE)
        if failures > 0 and op_traces:
            rate = failures / len(op_traces)
            if rate > 0.5:
                patterns.append({
                    "type": "high_failure_rate",
                    "severity": "warning",
                    "detail": f"{failures}/{len(op_traces)} operational traces FALSE ({rate:.0%})",
                    "rate": round(rate, 3),
                })

        # 2. Latency spike
        latencies = [t.get("total_latency_ms", 0) for t in traces]
        if latencies:
            avg = sum(latencies) / len(latencies)
            max_lat = max(latencies)
            if max_lat > avg * 3 and max_lat > 500:
                patterns.append({
                    "type": "latency_spike",
                    "severity": "info",
                    "detail": f"max={max_lat:.0f}ms vs avg={avg:.0f}ms ({max_lat/avg:.1f}x)",
                    "max_ms": round(max_lat, 1),
                    "avg_ms": round(avg, 1),
                })

        # 3. Repeated failures on same source (operational failures only)
        source_failures = Counter()
        for t in traces:
            if classify_trace(t) == OPERATIONAL_FAILURE:
                source_failures[t.get("final_source", "unknown")] += 1
        for source, count in source_failures.most_common(3):
            if count >= 3:
                patterns.append({
                    "type": "repeated_failure",
                    "severity": "warning",
                    "detail": f"{source} failed {count} times",
                    "source": source,
                    "count": count,
                })

        # 4. Short-circuit patterns (operator didn't fully evaluate)
        short_circuits = sum(1 for t in traces
                            if any(n.get("type") == "short_circuit"
                                   for n in t.get("nodes", [])))
        if short_circuits > len(traces) * 0.3:
            patterns.append({
                "type": "frequent_short_circuit",
                "severity": "info",
                "detail": f"{short_circuits}/{len(traces)} evaluations short-circuited",
                "count": short_circuits,
            })

        # 5. All traces same truth (stale or stuck)
        truths = set(t.get("final_truth", "") for t in traces)
        if len(truths) == 1 and len(traces) >= 5:
            patterns.append({
                "type": "monotonic_truth",
                "severity": "info",
                "detail": f"All {len(traces)} traces returned {truths.pop()}",
            })

        return patterns


# ─── Feedback Loop ────────────────────────────────────────────────────────────

class FeedbackLoop:
    """Session feedback loop: traces → summary → health history → patterns."""

    def __init__(self):
        self._state_dir = _voslab_path() / "state" / "rsi"
        # VOS_HEALTH_FILE: test isolation (conftest sets it to session tmp).
        # Without it, _maybe_run_feedback_loop during pytest appended real
        # health entries (session-<epoch>) to production health_history.
        _hf = os.environ.get("VOS_HEALTH_FILE")
        self._health_file = Path(_hf) if _hf else _voslab_path() / "state" / "health_history.jsonl"
        self._detector = PatternDetector()

    def _read_traces(self, session_id: Optional[str] = None) -> List[dict]:
        """Read traces from the JSONL log, optionally scoped to a session.

        P-EV-R4 (FND-HEALTH-H1-SCOPE, 2026-10-15): unscoped reads returned
        the WHOLE cumulative ledger (2070 entries / 33MB at fix time) and
        the health entry reported it as if it were the session's — the
        "reporte de salud que miente" (identical totals across sessions).
        With session_id, a cheap substring prefilter skips non-matching
        lines before json.loads (33MB scan ~30ms; avoids building the
        8k-entry list), then a strict equality filter rejects false hits
        (session id appearing inside a context blob).

        VOS_TREE_TRACE_FILE: test isolation (conftest sets it to session
        tmp). Without it, _maybe_run_feedback_loop during pytest re-read
        the PRODUCTION tree_traces.jsonl (239MB / 7976 entries, 2026-10-11)
        synchronously per process — the kernel-suite 'flake' (a real ~15s
        CPU stall, worse under parallel runs). Same lesson as RSI_* dirs
        and VOS_HEALTH_FILE.
        """
        _override = os.environ.get("VOS_TREE_TRACE_FILE")
        trace_file = Path(_override) if _override else self._state_dir / "tree_traces.jsonl"
        if not trace_file.exists():
            return []
        traces = []
        for line in trace_file.read_text().strip().split("\n"):
            if not line:
                continue
            if session_id is not None and session_id not in line:
                continue  # substring prefilter; strict check below
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError) as e:
                _logger.debug("trace entry skipped: %s", e)
                continue
            if session_id is not None and entry.get("session_id") != session_id:
                continue
            traces.append(entry)
        return traces

    def _read_attestations(self, trace_ids: Optional[List[str]] = None) -> List[dict]:
        """Read attestation files, optionally scoped to a set of trace_ids.

        Attest files are named {trace_id}.attest.json, so a scoped read is
        a direct file lookup per id — O(session_traces) instead of loading
        all ~11k files (the unscoped path, kept for all_time scope).
        """
        att_dir = self._state_dir / "attestations"
        if not att_dir.exists():
            return []
        atts = []
        if trace_ids is not None:
            files = [att_dir / f"{tid}.attest.json" for tid in trace_ids]
        else:
            files = list(att_dir.glob("*.attest.json"))
        for f in files:
            if not f.exists():
                continue
            try:
                atts.append(json.load(open(f)))
            except (json.JSONDecodeError, OSError) as e:
                _logger.debug("attestation read skipped: %s", e)
                continue
        return atts

    def _verify_attestations(self, atts: List[dict]) -> int:
        """Count how many attestations are valid."""
        try:
            from tree_trace_attest import AttestationVerifier
            verifier = AttestationVerifier()
            valid = 0
            for att in atts:
                if "trace_id" in att:  # single trace attestation
                    r = verifier.verify_trace(att)
                    if r["ok"]:
                        valid += 1
            return valid
        except Exception as e:
            _logger.debug("attestation verifier unavailable: %s", e)
            return len(atts)  # if verifier unavailable, assume valid

    def generate_report(self, session_id: Optional[str] = None) -> SessionReport:
        """Generate a report from traces and attestations.

        P-EV-R4 scope semantics (FND-HEALTH-H1-SCOPE): with session_id the
        report is SESSION-scoped (only that session's traces; attestations
        joined via trace_id filenames) and the entry carries
        scope="session". Without it, scope="all_time" — the entry is
        honest about being cumulative instead of pretending per-session.
        """
        traces = self._read_traces(session_id)
        # Attestation join: session scope → lookup by the session's own
        # trace_ids; all_time → full scan (legacy behaviour).
        atts = self._read_attestations(
            [t["trace_id"] for t in traces if t.get("trace_id")]
            if session_id is not None else None
        )
        valid_atts = self._verify_attestations(atts)

        # Aggregate trace stats
        truths = Counter(t.get("final_truth", "unknown") for t in traces)
        latencies = [t.get("total_latency_ms", 0) for t in traces]
        total_nodes = sum(t.get("total_nodes", 0) for t in traces)

        # Session ID from provided value, else first NON-None trace
        # (legacy "first trace" took None → the entry said "unknown").
        # Scope is decided by the CALLER's intent (param provided or not),
        # never post-hoc: an unscoped read over a file that happens to
        # contain sessions is still all_time.
        session_scoped = session_id is not None
        if not session_id and traces:
            session_id = next(
                (t.get("session_id") for t in traces if t.get("session_id")),
                "unknown",
            )
        session_id = session_id or "unknown"
        scope = "session" if session_scoped else "all_time"

        # Duration
        if traces:
            first_ts = traces[0].get("ts", "")
            last_ts = traces[-1].get("ts", "")
            try:
                from datetime import datetime
                t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                duration = (t2 - t1).total_seconds()
            except (ValueError, TypeError) as e:
                _logger.debug("duration calc failed: %s", e)
                duration = 0
        else:
            duration = 0

        # Patterns
        patterns = self._detector.detect(traces)

        # Health entry
        health_entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            # P-EV-R4: consumers (alerting._check_health_degradation) must
            # never average across scopes — "session" = esta sesion;
            # "all_time" = ledger acumulado (legacy entries pre-date this
            # field and are treated as all_time).
            "scope": scope,
            "traces": {
                "total": len(traces),
                "truths": dict(truths),
                # Health verdicts use operational_truths (benign designed
                # FALSEs excluded); raw truths stay for forensics.
                "operational_truths": operational_truths(traces),
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
                "max_latency_ms": round(max(latencies), 1) if latencies else 0,
                "total_nodes": total_nodes,
            },
            "attestations": {
                "total": len(atts),
                "valid": valid_atts,
                "valid_rate": round(valid_atts / len(atts), 3) if atts else 1.0,
            },
            "patterns": patterns,
        }

        return SessionReport(
            session_id=session_id,
            ts=health_entry["ts"],
            duration_seconds=round(duration, 1),
            total_traces=len(traces),
            truth_distribution=dict(truths),
            avg_latency_ms=health_entry["traces"]["avg_latency_ms"],
            max_latency_ms=health_entry["traces"]["max_latency_ms"],
            total_nodes_evaluated=total_nodes,
            total_attestations=len(atts),
            attestations_valid=valid_atts,
            patterns=patterns,
            health_entry=health_entry,
        )

    def update_health_history(self, report: SessionReport) -> None:
        """Append a health entry to health_history.jsonl."""
        self._health_file.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self._health_file), "a") as f:
            f.write(json.dumps(report.health_entry, default=str) + "\n")

    def update_focus(self, report: SessionReport) -> None:
        """Update current_focus.json with session completion status."""
        focus_file = _voslab_path() / "current_focus.json"
        if not focus_file.exists():
            return

        try:
            focus = json.load(open(focus_file))
            now = report.ts
            updated = False
            for entry in focus:
                if entry.get("status") == "active":
                    entry["status"] = "done"
                    entry["updated_at"] = now
                    entry["note"] = f"Closed by feedback loop: {report.total_traces} traces, {report.total_attestations} attestations"
                    updated = True
            if updated:
                focus_file.write_text(json.dumps(focus, indent=2, default=str))
        except (OSError, json.JSONDecodeError) as e:
            _logger.debug("focus update failed: %s", e)

    def close_session(self, session_id: Optional[str] = None) -> SessionReport:
        """Full session close: report + health + focus + alerts."""
        report = self.generate_report(session_id)
        self.update_health_history(report)
        self.update_focus(report)

        # Capa 4: run alerting check
        try:
            from alerting import AlertMonitor
            monitor = AlertMonitor()
            alerts = monitor.check()
            if alerts:
                report.patterns.extend([{
                    "type": "alert",
                    "severity": a.level,
                    "detail": f"{a.alert_type}: {a.detail}",
                } for a in alerts])
        except Exception as e:
            _logger.debug("alerting check failed: %s", e)

        return report

    def health_report(self) -> Dict[str, Any]:
        """Read health_history.jsonl and produce a summary."""
        if not self._health_file.exists():
            return {"entries": 0, "status": "empty"}

        entries = []
        for line in self._health_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                _logger.debug("health entry skipped: %s", e)
                continue

        if not entries:
            return {"entries": 0, "status": "empty"}

        # Aggregate
        total_traces = sum(e.get("traces", {}).get("total", 0) for e in entries)
        total_atts = sum(e.get("attestations", {}).get("total", 0) for e in entries)
        all_patterns = []
        for e in entries:
            all_patterns.extend(e.get("patterns", []))

        # Pattern frequency
        pattern_types = Counter(p.get("type", "unknown") for p in all_patterns)

        return {
            "entries": len(entries),
            "first_ts": entries[0].get("ts"),
            "last_ts": entries[-1].get("ts"),
            "total_traces": total_traces,
            "total_attestations": total_atts,
            "pattern_frequency": dict(pattern_types),
            "recent_patterns": all_patterns[-5:] if all_patterns else [],
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if "--selftest" in sys.argv:
        return _selftest()

    if "--close-session" in sys.argv:
        loop = FeedbackLoop()
        report = loop.close_session()
        print(f"Session closed: {report.session_id}")
        print(f"  Traces: {report.total_traces}")
        print(f"  Truths: {report.truth_distribution}")
        print(f"  Attestations: {report.attestations_valid}/{report.total_attestations} valid")
        print(f"  Patterns: {len(report.patterns)}")
        for p in report.patterns:
            print(f"    [{p['severity']}] {p['type']}: {p['detail']}")
        print(f"  Health entry appended to state/health_history.jsonl")
        return 0

    if "--health-report" in sys.argv:
        loop = FeedbackLoop()
        report = loop.health_report()
        print(json.dumps(report, indent=2, default=str))
        return 0

    print("usage: feedback_loop.py [--close-session | --health-report | --selftest]")
    return 2


def _selftest():
    """Test pattern detection, report generation, health history update."""
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp(prefix="feedback-test-")
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    try:
        # 1. Pattern detection
        detector = PatternDetector()

        # High failure rate
        traces = [{"final_truth": f"Truth.FALSE", "final_source": f"p{i}", "total_nodes": 1,
                    "total_latency_ms": 10, "nodes": []} for i in range(8)]
        traces += [{"final_truth": "Truth.TRUE", "final_source": "p_ok", "total_nodes": 1,
                     "total_latency_ms": 10, "nodes": []} for _ in range(2)]
        patterns = detector.detect(traces)
        check("high_failure_rate detected",
              any(p["type"] == "high_failure_rate" for p in patterns),
              str([p["type"] for p in patterns]))

        # Latency spike
        traces_ok = [{"final_truth": "Truth.TRUE", "final_source": "ok", "total_nodes": 1,
                       "total_latency_ms": 10, "nodes": []} for _ in range(9)]
        traces_ok.append({"final_truth": "Truth.TRUE", "final_source": "slow", "total_nodes": 1,
                           "total_latency_ms": 5000, "nodes": []})
        patterns2 = detector.detect(traces_ok)
        check("latency_spike detected",
              any(p["type"] == "latency_spike" for p in patterns2))

        # Repeated failures
        traces_rep = [{"final_truth": "Truth.FALSE", "final_source": "broken_pred",
                        "total_nodes": 1, "total_latency_ms": 10, "nodes": []} for _ in range(5)]
        patterns3 = detector.detect(traces_rep)
        check("repeated_failure detected",
              any(p["type"] == "repeated_failure" for p in patterns3))

        # No patterns on clean data (vary truths to avoid monotonic_truth)
        clean = [{"final_truth": "Truth.TRUE" if i % 2 == 0 else "Truth.FALSE",
                   "final_source": f"p{i}", "total_nodes": 1,
                   "total_latency_ms": 50, "nodes": []} for i in range(5)]
        patterns4 = detector.detect(clean)
        check("clean data → no patterns", len(patterns4) == 0)

        # Empty traces
        patterns5 = detector.detect([])
        check("empty traces → no patterns", len(patterns5) == 0)

        # 2. SessionReport structure
        report = SessionReport(
            session_id="test", ts="2026-01-01T00:00:00Z", duration_seconds=60,  # hardcoded-allow: synthetic selftest fixture
            total_traces=10, truth_distribution={"TRUE": 7, "FALSE": 3},
            avg_latency_ms=50.0, max_latency_ms=200.0, total_nodes_evaluated=30,
            total_attestations=10, attestations_valid=10,
            patterns=[], health_entry={},
        )
        check("session report structure", report.total_traces == 10)

        # 3. Health history write/read
        health_file = Path(tmp) / "health_history.jsonl"
        loop = FeedbackLoop()
        loop._health_file = health_file
        # Use a proper health_entry (like generate_report would produce)
        report.health_entry = {
            "ts": report.ts,
            "session_id": report.session_id,
            "traces": {"total": report.total_traces, "truths": report.truth_distribution},
            "attestations": {"total": report.total_attestations, "valid": report.attestations_valid},
            "patterns": [],
        }
        loop.update_health_history(report)
        check("health history written", health_file.exists())
        lines = health_file.read_text().strip().split("\n")
        check("health history readable", len(lines) == 1)
        entry = json.loads(lines[0])
        check("health entry has traces", "traces" in entry)

        # 4. Health report
        report2 = loop.health_report()
        check("health report", report2["entries"] == 1, str(report2))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    print("feedback_loop --selftest")
    for n, ok, d in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else ""))
    print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
