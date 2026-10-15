#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/second-order-loop-v1/canonical_feedback.vsm
"""health_scan.py — Periodic read-only system health scan (process fuel).

Second-order cybernetics starves without repeated measurable processes.
This scan runs the same checks every session and appends one metrics row
to state/health_history.jsonl, producing the improvement curves the RSI
loop needs (accuracy/coverage/latency trends over time).

Read-only by construction: never writes outside state/health_history.jsonl.
Invoker (FND-HEALTH-SCAN-UNINVOKED): rsi_cycle._maybe_run_feedback_loop,
the same deferred/throttled block that writes session-health entries
(every _feedback_interval evals). Also safe at BOOT / session.idle.

Corpus scope (2026-10-15): docs/spec_revision/** — the maintained canon
tree. The original docs/** glob measured a 32-file living tree in Sep-2026;
docs/ now holds 1017 files dominated by archive/deploy/sessions artifacts
(pass ~0.22), which would poison Omega's drift with false degradation.

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
CORPUS_GLOB = VOSLAB / "docs" / "spec_revision"  # maintained canon tree


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=str(VOSLAB))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 127, str(e)


def scan_corpus() -> dict:
    """VSM validation pass rate over the maintained canon tree (spec_revision).

    In-process (2026-10-15): validate_vsm_file() imported directly — the
    original 400-subprocess loop cost ~60s+ and can't run inside the
    deferred feedback block; in-process is <1s for the full tree.
    """
    validator_dir = VOSLAB / "scripts" / "vsl" / "validator"
    if str(validator_dir) not in sys.path:
        sys.path.insert(0, str(validator_dir))
    from check import validate_vsm_file  # R16: same validator as FASE-1

    files = sorted(CORPUS_GLOB.glob("**/*.vsm"))
    checked = failed = 0
    failures: list[str] = []
    for f in files[:400]:
        checked += 1
        if not validate_vsm_file(str(f))["valid"]:
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


def run_scan() -> dict:
    """Append one health row (corpus+queue+state) and return it. No print."""
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
    return row


def main(argv: list[str]) -> int:
    row = run_scan()
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
