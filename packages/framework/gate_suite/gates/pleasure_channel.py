"""pleasure-channel gate — G-34 / PLEASURE-CHANNEL-001 (ratified 2026-10-07).

The algedonic pleasure channel must stay a NARRATIVE store — never an
action queue (proposal guards F2 asymmetry + R17 never-auto-execute).
The bash check `pleasure-channel` audits the live workspace; this gate is
its negative-control twin:

  - check(path): "" -> live workspace ledger; <dir> -> fixture dir.
    0 = channel alive and bounded: >= 1 schema-valid event, no
    auto-action field (auto_exec/action/command/...), no undeclared
    field, and the emitter module + its tests exist (module/tests are
    resolved against the REPO, so a fixture's only defect can be the
    ledger itself — the negative case stays discriminant).
    1 = proven defect (empty/absent ledger, malformed event, or an
    action field — an action field would make the channel an R17
    violation, and accepting it would make this gate a proxy).
  - negative_case(): temp ledger whose single event carries
    `auto_exec: true` — MUST ALWAYS be rejected (exit != 0).

Run standalone:  python3 packages/framework/gate_suite/gates/pleasure_channel.py
Run by harness:  register("pleasure-channel", check, negative_case)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Direct execution has no package context: put packages/framework on the path.
_FRAMEWORK = Path(__file__).resolve().parents[2]
if __package__ in (None, "") and str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from gate_suite.harness import register  # noqa: E402

_ROOT = Path(__file__).resolve().parents[4]

#: Declared ledger schema (storage contract, proposal EVENTOS).
ALLOWED: frozenset[str] = frozenset({
    "event_id", "ts", "unit", "success", "p", "rpe", "streak",
    "emissions", "detail", "source", "connection",
})
#: Any of these on an event = the channel became an action queue (R17/F2).
BANNED: frozenset[str] = frozenset({
    "auto_exec", "auto_action", "action", "command", "cmd", "exec",
    "run_script", "execute",
})


def _module_ok() -> list[str]:
    """Repo-side half of the contract: emitter + tests present (R16)."""
    problems: list[str] = []
    mod = _ROOT / "packages" / "framework" / "vos_kernel" / "pleasure_emitter.py"
    tests = (_ROOT / "packages" / "framework" / "vos_kernel" / "tests"
             / "test_pleasure_emitter.py")
    if not mod.is_file():
        problems.append(f"module missing: {mod}")
    else:
        try:
            text = mod.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"module unreadable: {exc}")
        else:
            for pat in ("os.system", "subprocess", "Popen(", "eval("):
                if pat in text:
                    problems.append(
                        f"execution primitive in emitter ({pat}) — F2/R17")
            if "open(" in text and "alerts.jsonl" in text:
                # both literals present: only a docstring mention is legal,
                # an open() call naming the alerts ledger is not (F2)
                for line in text.splitlines():
                    if "open(" in line and "alerts.jsonl" in line:
                        problems.append(f"emitter opens alerts.jsonl: {line.strip()[:80]}")
    if not tests.is_file():
        problems.append(f"tests missing: {tests}")
    return problems


def check(path: str) -> int:
    """0 = channel alive and bounded; 1 = proven defect."""
    root = Path(path) if path else _ROOT
    problems = _module_ok()
    ledger = root / "state" / "rsi" / "pleasure.jsonl"
    if not ledger.is_file():
        problems.append(f"ledger missing: {ledger}")
        for p in problems:
            print(f"pleasure-channel: {p}", file=sys.stderr)
        return 1
    valid = 0
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        problems.append(f"ledger unreadable: {exc}")
        lines = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            problems.append(f"line {i}: not JSON")
            continue
        if not isinstance(r, dict) or not isinstance(r.get("unit"), str) or not r.get("unit"):
            problems.append(f"line {i}: missing unit")
            continue
        if not isinstance(r.get("success"), bool):
            problems.append(f"line {i}: success not bool")
            continue
        if not isinstance(r.get("ts"), str) or "T" not in r["ts"]:
            problems.append(f"line {i}: ts not ISO")
            continue
        hit = set(r) & BANNED
        if hit:
            problems.append(f"line {i}: auto-action field(s) {sorted(hit)} — R17")
            continue
        extra = set(r) - ALLOWED
        if extra:
            problems.append(f"line {i}: undeclared field(s) {sorted(extra)}")
            continue
        valid += 1
    if valid < 1:
        problems.append("no schema-valid event (channel not alive)")
    for p in problems:
        print(f"pleasure-channel: {p}", file=sys.stderr)
    return 1 if problems else 0


def report() -> int:
    """Real run: full report, rc as check('')."""
    return check("")


def negative_case() -> str:
    """Temp ledger whose only defect is an auto-execution field (R17)."""
    root = Path(tempfile.mkdtemp(prefix="voslab_pleasure_"))
    rsi = root / "state" / "rsi"
    rsi.mkdir(parents=True)
    event = {
        "event_id": "pev-negative",
        "ts": "2026-10-07T12:00:00Z",
        "unit": "gate_run",
        "success": True,
        "p": 0.0,
        "rpe": 1.0,
        "streak": 3,
        "emissions": [{"kind": "rpe", "magnitude": 1.0,
                       "magnitude_unit": "rpe"}],
        "detail": "planted: the channel decided to act",
        "auto_exec": True,   # <- the R17 violation the gate must catch
    }
    (rsi / "pleasure.jsonl").write_text(json.dumps(event) + "\n",
                                        encoding="utf-8")
    return str(root)


register("pleasure-channel", check, negative_case)


if __name__ == "__main__":
    sys.exit(report())
