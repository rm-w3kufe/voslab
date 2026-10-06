"""Negative-control harness for gate-suite.

The defect we found in vsf's `checks/plugin-location-valid` was a BROKEN
negative control: it could not discriminate a violating artifact from a valid
one, so the gate was effectively a no-op. This harness makes that impossible
to ship unnoticed.

Each gate registers:
  - name:           unique gate id
  - check(path):    runs the gate on an artifact; returns 0 if ACCEPTED,
                    nonzero if REJECTED
  - negative_case:  builds an artifact the gate MUST reject, returns its path

`run_negative_controls()` proves every gate is NECESSARY: it feeds each gate
its own negative case and asserts the gate REJECTS it. If a gate accepts its
negative case (exit 0), the harness fails — exactly catching the vsf defect.

Logging:
  Gate evaluations are logged to logs/agent_plugin.jsonl in unified JSONL format.
  NC rejection reports go to stderr labeled [NC:<gate>] (G-35) so fixture
  noise stays visible without masquerading as live failures.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _log_gate_eval(gate_name: str, result: str, passed: bool, detail: str = "") -> None:
    """Append a gate evaluation record to the unified JSONL log."""
    try:
        # Use environment variable or default to cwd/logs
        log_path = Path(os.environ.get("VOS_LOG_DIR", Path.cwd() / "logs")) / "agent_plugin.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": None,
            "level": "activation",
            "source": gate_name,
            "event_type": "gate.evaluate",
            "event_id": f"gate:{gate_name}:{datetime.now(timezone.utc).timestamp():.0f}",
            "action": f"negative_control: {gate_name}",
            "result": result,
            "detail": detail,
            "context": {"passed": passed},
        }

        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never throw


@dataclass
class Gate:
    name: str
    check: "callable[[str], int]"          # path -> exit code (0 accept, !=0 reject)
    negative_case: "callable[[], str]"     # () -> path to artifact that MUST be rejected


GATES: list[Gate] = []


def register(name: str, check, negative_case) -> None:
    """Register a gate with its negative-control case."""
    GATES.append(Gate(name, check, negative_case))


def _cleanup(path: str) -> None:
    if path.startswith(tempfile.gettempdir()):
        try:
            os.remove(path)
        except OSError:
            pass


def run_negative_controls() -> int:
    """Return 0 if ALL gates reject their negative cases; else 1.

    A nonzero return means at least one gate is a no-op (broken negative
    control) and must not ship.

    G-35 (2026-10-06): each gate's rejection report is captured and
    re-emitted with an [NC:<gate>] prefix. The report must stay visible —
    it proves WHY the fixture was rejected (epistemic value intact) — but
    it is fixture noise by design and must never be mistakable for a live
    failure (cry-wolf: unlabeled NC lines cost a full diagnosis pass on
    the 2026-10-06 boot before the one real red gate was found).
    """
    failed: list[str] = []
    print(
        "NEGATIVE CONTROL DETAIL — expected fixture rejections "
        "(by design; verdict follows the block)",
        file=sys.stderr,
    )
    for g in GATES:
        path = g.negative_case()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            rc = g.check(path)
        _cleanup(path)
        for line in buf.getvalue().splitlines():
            print(f"[NC:{g.name}] {line}", file=sys.stderr)
        passed = rc != 0
        if rc == 0:
            failed.append(g.name)
        _log_gate_eval(
            g.name,
            "ok" if passed else "error",
            passed,
            detail=f"negative_control: exit_code={rc}",
        )
    if failed:
        print(
            "NEGATIVE CONTROL FAIL — gates that do NOT catch their own "
            f"negative case (no-op defect): {failed}"
        )
        return 1
    print(f"NEGATIVE CONTROL PASS — {len(GATES)} gates verified necessary")
    return 0


def run_live_checks() -> int:
    """Run every shipped check in packages/public/vsf-checks/checks against
    the live workspace (empty target = self-audit).

    G-11 closed 2026-10-03: run_gates previously proved gates necessary
    (negative controls) but never verified the actual workspace — 39 of 65
    checks were red unnoticed. Returns 0 iff every check passes; each run is
    logged to the unified log so the instrument set self-observes.
    """
    import subprocess

    checks_dir = Path(__file__).resolve().parents[2] / "public" / "vsf-checks" / "checks"
    if not checks_dir.is_dir():
        print(f"LIVE CHECKS FAIL — checks dir missing: {checks_dir}")
        return 1
    # bash runs them by name; skip only docs (README).
    checks = sorted(p for p in checks_dir.iterdir() if p.is_file() and not p.name.endswith(".md"))
    passed = 0
    failed: list[tuple[str, int]] = []
    for check in checks:
        try:
            proc = subprocess.run(
                ["bash", str(check), ""],
                capture_output=True, text=True, timeout=60,
            )
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = 124
        except OSError as exc:
            rc = 126
            proc = type("P", (), {"stderr": str(exc)})()
        ok = rc == 0
        if ok:
            passed += 1
        else:
            failed.append((check.name, rc))
        _log_gate_eval(
            f"live:{check.name}",
            "ok" if ok else "error",
            ok,
            detail=f"live: exit_code={rc}",
        )
    if failed:
        print(
            f"LIVE CHECKS FAIL — {len(failed)}/{passed + len(failed)} red:"
        )
        for name, rc in failed:
            print(f"  rc={rc:>3}  {name}")
        return 1
    print(f"LIVE CHECKS PASS — {passed} checks green")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_negative_controls())
