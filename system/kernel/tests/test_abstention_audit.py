"""Tests for the §6.3 abstention audit (F4.2).

Two layers, both hermetic (tmp state dirs — never production
state/rsi/alerts.jsonl):

  alerting.abstention_window_stats / _check_abstention_collapse
      window verdict, dedup, re-signal-after-ack rules, check() wiring.
  scripts/state/monitoring/abstention_audit.py
      census counts + rc contract (default rc=0; --check rc=1 iff
      would_fire) under VOSLAB_PATH fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VOS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOS_ROOT / "system" / "kernel"))

from alerting import (  # noqa: E402
    AlertMonitor,
    DEFAULT_THRESHOLDS,
    abstention_window_stats,
)

AUDIT_SCRIPT = (VOS_ROOT / "scripts" / "state" / "monitoring"
                / "abstention_audit.py")

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)  # hardcoded-allow: synthetic test fixture
WINDOW = DEFAULT_THRESHOLDS["abstention_window"]
SUSTAIN = DEFAULT_THRESHOLDS["abstention_sustain_h"]


def _trace(i: int, *, certified: bool = True,
           truth: str = "Truth.TRUE", hours: float = 2.0) -> dict:
    ts = (EPOCH + timedelta(hours=i * hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "trace_id": f"t{i}", "ts": ts, "session_id": "s1",
        "tree_shape": "p", "final_truth": truth,
        "final_certified": certified, "final_source": "pred",
        "total_nodes": 1, "predicates_evaluated": 1,
        "operators_evaluated": 0, "total_latency_ms": 5,
        "context_keys": [], "attestation": None, "nodes": [],
    }


def _write_traces(path: Path, traces: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(t) for t in traces) + "\n",
                    encoding="utf-8")


def _monitor(tmp: Path) -> AlertMonitor:
    monitor = AlertMonitor()
    monitor._state_dir = tmp
    monitor._alerts_file = tmp / "alerts.jsonl"  # never emit to production
    monitor._health_file = tmp / "no_health.jsonl"
    return monitor


# ── abstention_window_stats (pure) ──────────────────────────────────────────

def test_stats_fire_on_full_certified_window():
    traces = [_trace(i) for i in range(WINDOW)]
    stats = abstention_window_stats(traces, WINDOW, SUSTAIN)
    assert stats["would_fire"] is True
    assert stats["abstentions"] == 0
    assert stats["samples"] == WINDOW
    assert stats["span_h"] >= SUSTAIN


def test_stats_quiet_with_uncertified():
    traces = [_trace(i) for i in range(WINDOW)]
    traces[WINDOW - 1]["final_certified"] = False
    stats = abstention_window_stats(traces, WINDOW, SUSTAIN)
    assert stats["would_fire"] is False
    assert stats["abstentions"] == 1
    assert stats["last_abstention_ts"] is not None


def test_stats_quiet_with_unknown_root():
    traces = [_trace(i) for i in range(WINDOW)]
    traces[10]["final_truth"] = "Truth.UNKNOWN"
    stats = abstention_window_stats(traces, WINDOW, SUSTAIN)
    assert stats["would_fire"] is False
    assert stats["abstentions"] == 1


def test_stats_needs_full_window():
    traces = [_trace(i) for i in range(WINDOW // 4)]
    stats = abstention_window_stats(traces, WINDOW, SUSTAIN)
    assert stats["enough_samples"] is False
    assert stats["would_fire"] is False


def test_stats_needs_sustained_span():
    # full window but all the same second → not sustained
    traces = [_trace(i, hours=0.0) for i in range(WINDOW)]
    stats = abstention_window_stats(traces, WINDOW, SUSTAIN)
    assert stats["span_h"] == 0.0
    assert stats["would_fire"] is False


def test_stats_empty_input():
    stats = abstention_window_stats([], WINDOW, SUSTAIN)
    assert stats["would_fire"] is False
    assert stats["samples"] == 0


# ── AlertMonitor._check_abstention_collapse ─────────────────────────────────

def test_check_emits_once_then_dedups(tmp_path):
    _write_traces(tmp_path / "tree_traces.jsonl",
                  [_trace(i) for i in range(WINDOW)])
    monitor = _monitor(tmp_path)
    alerts = monitor._check_abstention_collapse()
    assert len(alerts) == 1
    assert alerts[0].alert_type == "abstention_collapse"
    assert alerts[0].level == "warning"
    assert alerts[0].evidence["abstentions"] == 0
    again = monitor._check_abstention_collapse()
    assert again == []  # unacked → episode already signalled
    assert len(monitor._read_alerts()) == 1


def test_check_quiet_when_abstentions_present(tmp_path):
    traces = [_trace(i) for i in range(WINDOW)]
    traces[5]["final_certified"] = False
    _write_traces(tmp_path / "tree_traces.jsonl", traces)
    monitor = _monitor(tmp_path)
    assert monitor._check_abstention_collapse() == []
    assert not (tmp_path / "alerts.jsonl").exists()


def test_check_silent_while_ack_fresh(tmp_path):
    """acked but younger than 24h → still one episode (suppressed)."""
    _write_traces(tmp_path / "tree_traces.jsonl",
                  [_trace(i) for i in range(WINDOW)])
    monitor = _monitor(tmp_path)
    first = monitor._check_abstention_collapse()
    assert len(first) == 1
    assert monitor.acknowledge(first[0].alert_id) is True
    assert monitor._check_abstention_collapse() == []
    assert len(monitor._read_alerts()) == 1


def test_check_reemits_after_ack_and_age(tmp_path):
    """acked + older than 24h → fresh observation may signal again."""
    _write_traces(tmp_path / "tree_traces.jsonl",
                  [_trace(i) for i in range(WINDOW)])
    monitor = _monitor(tmp_path)
    old = {
        "alert_id": "alert-old-0001",
        "ts": "2026-01-01T00:00:00Z",  # hardcoded-allow: synthetic fixture (well before cutoff)
        "level": "warning",
        "alert_type": "abstention_collapse",
        "source": "abstention-audit",
        "detail": "prior episode",
        "evidence": {}, "trace_id": None, "session_id": None,
        "acknowledged": True,
    }
    monitor._alerts_file.write_text(json.dumps(old) + "\n", encoding="utf-8")
    alerts = monitor._check_abstention_collapse()
    assert len(alerts) == 1
    assert alerts[0].alert_id != "alert-old-0001"
    assert len(monitor._read_alerts()) == 2


def test_check_included_in_full_check(tmp_path):
    _write_traces(tmp_path / "tree_traces.jsonl",
                  [_trace(i) for i in range(WINDOW)])
    monitor = _monitor(tmp_path)
    alerts = monitor.check()  # all five checks; only ours may fire here
    types = [a.alert_type for a in alerts]
    assert types == ["abstention_collapse"]


def test_check_not_fired_on_production_like_data(tmp_path):
    """Recent production shape: 182/200 uncertified → quiet."""
    traces = []
    for i in range(WINDOW):
        certified = not (i % 200 < 182)  # 18 certified True / 200
        traces.append(_trace(i, certified=certified))
    _write_traces(tmp_path / "tree_traces.jsonl", traces)
    monitor = _monitor(tmp_path)
    assert monitor._check_abstention_collapse() == []


# ── abstention_audit.py CLI (VOSLAB_PATH fixtures) ──────────────────────────

def _audit(*args: str, root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOSLAB_PATH": str(root)}
    return subprocess.run([sys.executable, str(AUDIT_SCRIPT), *args],
                          capture_output=True, text=True, timeout=60,
                          env=env)


def _fixture_root(tmp: Path, traces: list[dict],
                  log_entries: list[dict] | None = None) -> Path:
    _write_traces(tmp / "state" / "rsi" / "tree_traces.jsonl", traces)
    if log_entries is not None:
        (tmp / "logs").mkdir(parents=True, exist_ok=True)
        (tmp / "logs" / "agent_plugin.jsonl").write_text(
            "\n".join(json.dumps(e) for e in log_entries) + "\n",
            encoding="utf-8")
    return tmp


def test_audit_json_report_counts(tmp_path):
    traces = [_trace(i) for i in range(300)]
    traces[250]["final_certified"] = False  # inside the last-200 window
    log_entries = [
        {"event_type": "evaluate.evaluate",
         "action": "evaluate truth=TRUE cert=true source=p", "class": "operational"},
        {"event_type": "evaluate.failure",
         "action": "evaluate truth=FALSE cert=true", "class": "operational"},
        {"event_type": "evaluate.evaluate",
         "action": "pytest truth=TRUE", "class": "test"},
        {"event_type": "tool.execute.after", "action": "x", "class": "operational"},
    ]
    root = _fixture_root(tmp_path, traces, log_entries)
    proc = _audit("--json", "--window", str(WINDOW), root=root)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["traces"]["total"] == 300
    assert report["traces"]["certified"]["False"] == 1
    assert report["log"]["total"] == 3  # tool.execute.after excluded
    assert report["log"]["truths"]["operational"] == {"TRUE": 1, "FALSE": 1}
    assert report["log"]["truths"]["test"] == {"TRUE": 1}
    assert report["window"]["samples"] == WINDOW
    assert report["would_fire"] is False  # one uncertified → quiet


def test_audit_check_rc_contract(tmp_path):
    root_fire = _fixture_root(tmp_path / "fire",
                              [_trace(i) for i in range(WINDOW)],
                              log_entries=[])
    proc = _audit("--json", "--check", "--window", str(WINDOW),
                  root=root_fire)
    assert proc.returncode == 1, (proc.returncode, proc.stderr)

    root_quiet = _fixture_root(tmp_path / "quiet",
                               [_trace(i) for i in range(10)])
    proc2 = _audit("--json", "--check", "--window", str(WINDOW),
                   root=root_quiet)
    assert proc2.returncode == 0
    # default mode: report only — rc=0 even when would_fire
    proc3 = _audit("--json", "--window", str(WINDOW), root=root_fire)
    assert proc3.returncode == 0


def test_audit_graceful_on_empty_root(tmp_path):
    (tmp_path / "empty").mkdir()
    proc = _audit("--json", root=tmp_path / "empty")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["traces"]["total"] == 0
    assert report["log"]["total"] == 0
    assert report["would_fire"] is False


def test_audit_human_mode(tmp_path):
    root = _fixture_root(tmp_path, [_trace(i) for i in range(20)],
                         log_entries=[])
    proc = _audit(root=root)
    assert proc.returncode == 0, proc.stderr
    assert "abstention audit" in proc.stdout
    assert "would_fire: False" in proc.stdout
