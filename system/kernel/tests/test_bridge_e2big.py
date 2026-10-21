# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T3-F1: E2BIG stdin transport)
"""test_bridge_e2big.py — E2BIG class fix (task E2BIG-BRIDGE-STDIN-2026-10-16).

callBridge now sends args as a JSON array on stdin behind --args-stdin;
argv carries command + flag only. Linux caps one argv string at
MAX_ARG_STRLEN (128KiB) and the total at ARG_MAX, so MB-class payloads
(gap-resolver socratic-tree-file) died with E2BIG at spawn — 81 alerts
2026-10-14→20 (T3-F1 root cause, 2026-10-20).

These tests pin the python boundary of the transport:
  - stdin dispatch reaches the handler with the parsed array,
  - a 3MiB single payload rides stdin without E2BIG,
  - argv transport stays byte-compatible (shell/manual callers),
  - empty stdin → args=[],
  - a non-array payload fails loud (R9) on stderr + rc!=0.

Read-only commands only (graph-query / vsm-check-content / query-context)
— zero state writes (isolation discipline, lesson 2026-09-12).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = _ROOT / ".opencode" / "plugins" / "operational" / "tool_integration_bridge.py"


def _run(*argv: str, stdin_bytes: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-W", "ignore", str(BRIDGE), *argv],
        input=stdin_bytes.decode("utf-8"),  # text mode: str, not bytes (json.dumps is ascii-safe)
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "VOS_ROOT": str(_ROOT)},
    )


def _first_json(text: str) -> dict:
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    return json.loads(text[start:]) if start != -1 else json.loads(text)


def test_args_stdin_dispatch_reaches_handler():
    """flag + JSON array on stdin: args[0]=='stats' must reach graph-query."""
    proc = _run("graph-query", "--args-stdin",
                stdin_bytes=json.dumps(["stats"]).encode())
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "usage:" not in proc.stdout  # would mean args arrived empty
    assert "nodes" in proc.stdout


def test_args_stdin_huge_payload_no_e2big():
    """3MiB single payload via stdin — the E2BIG class must not recur."""
    big = json.dumps([{"content": "x" * (3 * 1024 * 1024)}])  # args array: [cmd-arg]
    proc = _run("vsm-check-content", "--args-stdin",
                stdin_bytes=big.encode())
    assert proc.returncode == 0, (proc.stderr or proc.stdout)[-500:]
    assert "E2BIG" not in (proc.stderr + proc.stdout)
    out = _first_json(proc.stdout)
    assert "valid" in out or "errors" in out or "warning" in out


def test_argv_transport_stays_compatible():
    """No flag → old argv path (shell/manual callers, byte-compat)."""
    proc = _run("graph-query", "stats")
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "usage:" not in proc.stdout
    assert "nodes" in proc.stdout


def test_args_stdin_empty_stdin_means_no_args():
    """flag + empty stdin → args=[] (no parse error, no crash)."""
    proc = _run("query-context", "--args-stdin")
    assert proc.returncode == 0, proc.stderr[-500:]
    assert _first_json(proc.stdout)  # valid JSON context


def test_args_stdin_rejects_non_array_payload():
    """R9 fail-loud: payload must be a JSON array, not an object."""
    proc = _run("graph-query", "--args-stdin",
                stdin_bytes=json.dumps({"a": 1}).encode())
    assert proc.returncode != 0
    assert "JSON array" in (proc.stdout + proc.stderr)
