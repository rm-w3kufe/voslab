#!/usr/bin/env python3
"""health_scan.py — Periodic read-only system health scan (process fuel).

Second-order cybernetics starves without repeated measurable processes.
This scan runs the same checks every session and appends one metrics row
to state/health_history.jsonl, producing the improvement curves the RSI
loop needs (accuracy/coverage/latency trends over time).

Read-only by construction: never writes outside state/health_history.jsonl.
Safe to run at BOOT and on session.idle.

Usage:
  health_scan.py          # run scan + append row + print summary
  health_scan.py --json   # machine-readable last row
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
HISTORY = VOSLAB / "state" / "health_history.jsonl"


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=str(VOSLAB))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 127, str(e)


def scan_corpus() -> dict:
    """VSM validation pass rate over docs/ (sample-safe, capped)."""
    files = sorted(VOSLAB.glob("docs/**/*.vsm"))
    checked = failed = 0
    failures: list[str] = []
    for f in files[:400]:
        rc, _ = _run([sys.executable, "scripts/vsl/validator/check.py",
                      str(f.relative_to(VOSLAB))], timeout=30)
        checked += 1
        if rc != 0:
            failed += 1
            if len(failures) < 10:
                failures.append(str(f.relative_to(VOSLAB)))
    return {"checked": checked,
            "pass_rate": round((checked - failed) / max(checked, 1), 4),
            "failures_sample": failures}


def scan_queue() -> dict:
    rc, out = _run([sys.executable, ".opencode/plugins/operational/"
                    "tool_integration_bridge.py", "rsi-queue"])
    try:
        return json.loads(out.strip())["stats"]
    except Exception:
        return {"error": "queue unreadable"}


def scan_state() -> dict:
    def _du(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) \
            if p.exists() else 0
    q = list((VOSLAB / "state" / "rsi" / "queue").glob("*.json")) \
        if (VOSLAB / "state" / "rsi" / "queue").exists() else []
    return {
        "rsi_bytes": _du(VOSLAB / "state" / "rsi"),
        "quarantine_files": len(list((VOSLAB / "state" / "quarantine").glob("*")))
        if (VOSLAB / "state" / "quarantine").exists() else 0,
        "queue_files": len(q),
    }


def main(argv: list[str]) -> int:
    t0 = time.perf_counter()
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "corpus": scan_corpus(),
        "queue": scan_queue(),
        "state": scan_state(),
        "scan_seconds": round(time.perf_counter() - t0, 1),
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a") as f:
        f.write(json.dumps(row) + "\n")
    if "--json" in argv:
        print(json.dumps(row, indent=2))
    else:
        c = row["corpus"]
        print(f"health: corpus {c['checked']} docs pass_rate={c['pass_rate']} "
              f"| queue={row['queue']} | state={row['state']} "
              f"({row['scan_seconds']}s) -> {HISTORY.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
