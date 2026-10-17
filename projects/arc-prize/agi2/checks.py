#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_covenant.vsm
"""checks.py — in-kernel gate suite (vsf-checks style, Kaggle edition).

Six fail-loud gates run at pre-submit time, same declared-vs-observed
discipline as the hub's 84 live checks. stdlib-only, deterministic (R10).

    run_gates(tasks_json, sub, state, tally) -> [GateResult]

Each gate: name, passed, detail. The RUN_CELL prints the table; any FAIL
is loud but never crashes the write (competition needs a file).
"""
from __future__ import annotations

from dataclasses import dataclass

import covenant as COV


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}  {self.name}: {self.detail}"


def gate_schema_valid(sub: dict) -> GateResult:
    """G1: every shipped attempt is an ARC-valid grid (I4)."""
    bad = []
    for tid, preds in sub.items():
        for i, pr in enumerate(preds):
            for k in ("attempt_1", "attempt_2"):
                if not COV.valid_grid(pr.get(k)):
                    bad.append(f"{tid}[{i}].{k}")
    return GateResult("schema-valid", not bad,
                      f"{len(bad)} invalid grids" if bad
                      else f"{len(sub)} tasks x grids OK")


def gate_two_attempts(sub: dict) -> GateResult:
    """G2: every task has both attempts (I2)."""
    missing = [tid for tid, preds in sub.items()
               if not preds or any(
                   p.get("attempt_1") is None or p.get("attempt_2") is None
                   for p in preds)]
    return GateResult("two-attempts", not missing,
                      f"{len(missing)} tasks with holes" if missing
                      else f"{len(sub)} tasks complete")


def gate_family_diversity(sub: dict) -> GateResult:
    """G3: attempt_2 differs from attempt_1 unless shim (I3)."""
    dups = []
    for tid, preds in sub.items():
        for i, pr in enumerate(preds):
            a1, a2 = pr.get("attempt_1"), pr.get("attempt_2")
            src = pr.get("source", "symbolic")
            if a1 is not None and a2 is not None and src != "shim" \
                    and COV._key(a1) == COV._key(a2):
                dups.append(f"{tid}[{i}]")
    return GateResult("family-diversity", not dups,
                      f"{len(dups)} identical pairs" if dups
                      else "all pairs diversified or shim")


def gate_covenant_pairs(sub: dict) -> GateResult:
    """G4: per-pair covenant (I1 certify-first among them)."""
    viol = []
    for tid, preds in sub.items():
        for i, pr in enumerate(preds):
            v = COV.check_attempt_pair(
                pr.get("attempt_1"), pr.get("attempt_2"),
                pr.get("source", "symbolic"), "unverified",
                pr.get("loo"), None)
            if not v.passed:
                viol.extend(f"{tid}[{i}]:{x.axiom}" for x in v.violations)
    return GateResult("covenant-pairs", not viol,
                      "; ".join(viol[:5]) if viol else "all pairs certified")


def gate_deadline_respect(state) -> GateResult:
    """G5: run completed under the guard band (I5)."""
    ok = COV.guard_deadline(state) or state.tasks_done >= state.tasks_total
    return GateResult("deadline-respect", ok,
                      f"elapsed {COV.elapsed_s(state)/3600:.2f}h "
                      f"done {state.tasks_done}/{state.tasks_total}")


def gate_license_clean(modules_written: list) -> GateResult:
    """G6: kernel stayed self-contained (only whitelisted files written)."""
    allowed_prefixes = ("recognizer", "solver_smart_v2", "solver_v3",
                        "rsi_module", "agent", "solve", "rsi_bridge",
                        "composer", "llm_serialize", "llm_harness",
                        "covenant", "predicates", "checks")
    stray = [m for m in modules_written
             if not any(m.startswith(p) for p in allowed_prefixes)]
    return GateResult("license-clean", not stray,
                      f"stray writes: {stray}" if stray
                      else f"{len(modules_written)} modules self-contained")


def run_gates(sub: dict, state, tally: dict,
              modules_written: list = None) -> list:
    """Run the full suite. modules_written optional (G6 skipped if None)."""
    results = [
        gate_schema_valid(sub),
        gate_two_attempts(sub),
        gate_family_diversity(sub),
        gate_covenant_pairs(sub),
        gate_deadline_respect(state),
    ]
    if modules_written is not None:
        results.append(gate_license_clean(modules_written))
    return results


if __name__ == "__main__":  # pragma: no cover
    st = COV.RuntimeState()
    demo = {"t1": [{"attempt_1": [[1]], "attempt_2": [[2]],
                    "source": "symbolic", "loo": 1.0}]}
    for r in run_gates(demo, st, {"symbolic": 1}, ["solve.py"]):
        print(r)
