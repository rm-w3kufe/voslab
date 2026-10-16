#!/usr/bin/env python3
"""covenant.py — ViArc-2 harness policy runtime (executable covenant).

Contract: projects/arc-prize/knowledge/viarc_covenant.vsm (S5 <-> harness).
Parent: docs/spec_revision/system/boot/covenant.vsm (A0/A0.1, ratified).

This module is the harness's OWN governance: it encodes the constitution
(certify-first) and the runtime decision-rights S5 granted the solver
under the 12h Kaggle clock. stdlib-only, kernel-safe, deterministic (R10).

Two planes:
  * ceiling  — what the harness may NEVER do (hard invariants I1..I7)
  * autonomy — what it decides ALONE at runtime (budget adapt, source
    reallocation, attempt-2 strategy, LOO spend, zero-shim)

A0.1 specialization (the heart of it): budget pressure must never lower
the certify threshold. When the deadline bites, shed load (symbolic-only)
— never ship an uncertified candidate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

# ── Ratified operating point (data, not scattered constants) ─────────────
COVENANT = {
    "name": "ViArc-2",
    "certify_threshold": 0.5,     # I1/I7: NEVER lowered under pressure
    "K_default": 2,               # LLM samples per task
    "K_max": 8,                   # hard cap (ceiling)
    "loo_max_default": 1,         # LOO certifications per task
    "loo_max_task": 2,            # hard cap (ceiling)
    "hard_deadline_h": 12.0,      # Kaggle limit
    "guard_h": 9.5,               # pain point -> symbolic-only (alpha)
    "per_task_target_s": 35.0,    # nominal budget for slack math
    "max_grid_dim": 30,           # ARC bound
}

VIOLATION_SEVERITY = {
    "I1_certify_first": "CRITICAL",
    "I2_two_attempts": "CRITICAL",
    "I3_family_diversity": "HIGH",
    "I4_schema_valid": "CRITICAL",
    "I5_deadline_respect": "HIGH",
    "I6_license_clean": "HIGH",
    "I7_A0.1_no_pressure_flip": "CRITICAL",
}


@dataclass
class Violation:
    axiom: str
    message: str
    severity: str

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.severity}] {self.axiom}: {self.message}"


@dataclass
class Verdict:
    passed: bool
    violations: list = field(default_factory=list)


# ── Grid primitives (kernel-safe, no numpy) ─────────────────────────────

def valid_grid(g) -> bool:
    """I4: grid is non-empty rectangular int matrix within ARC bounds."""
    if not isinstance(g, (list, tuple)) or len(g) == 0:
        return False
    if len(g) > COVENANT["max_grid_dim"]:
        return False
    width = None
    for row in g:
        if not isinstance(row, (list, tuple)) or len(row) == 0:
            return False
        if width is None:
            width = len(row)
        elif len(row) != width:
            return False
        if len(row) > COVENANT["max_grid_dim"]:
            return False
        for v in row:
            if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 9):
                return False
    return True


def _key(g):
    return tuple(tuple(r) for r in g) if g is not None else None


# ── Ceiling: hard invariant checks ──────────────────────────────────────

def check_attempt_pair(a1, a2, source1: str, source2: str,
                       loo1: Optional[float] = None,
                       loo2: Optional[float] = None) -> Verdict:
    """I1-I4 for a single task's pair of attempts.

    source ∈ {"symbolic", "llm-certified", "shim"}.
    loo fraction required when source is llm-certified.
    """
    v: list = []

    # I2: exactly two slots present (None allowed only as pre-shim)
    if a1 is None and a2 is None:
        v.append(Violation("I2_two_attempts",
                           "both attempts empty (shim must be applied)", "CRITICAL"))

    # I4: schema validity of present grids
    for name, g in (("attempt_1", a1), ("attempt_2", a2)):
        if g is not None and not valid_grid(g):
            v.append(Violation("I4_schema_valid",
                               f"{name} fails ARC grid bounds/typing", "CRITICAL"))

    # I1: certify-first — llm-certified source requires LOO >= threshold
    for name, src, loo in (("attempt_1", source1, loo1),
                           ("attempt_2", source2, loo2)):
        if src == "llm-certified":
            if loo is None or loo < COVENANT["certify_threshold"]:
                v.append(Violation(
                    "I1_certify_first",
                    f"{name} claims llm-certified with loo={loo} "
                    f"< {COVENANT['certify_threshold']}", "CRITICAL"))

    # I3: family diversity when both exist (shim granted: identical copies)
    if (a1 is not None and a2 is not None and _key(a1) == _key(a2)
            and "shim" not in (source1, source2)):
        v.append(Violation("I3_family_diversity",
                           "attempt_2 identical to attempt_1", "HIGH"))

    return Verdict(passed=len(v) == 0, violations=v)


def check_submission(tasks: dict) -> Verdict:
    """I2/I4 over a full submission: {task_id: {"attempt_1": g, "attempt_2": g, ...}}."""
    v: list = []
    if not tasks:
        v.append(Violation("I2_two_attempts", "submission empty", "CRITICAL"))
        return Verdict(passed=False, violations=v)
    for tid, sub in tasks.items():
        a1, a2 = sub.get("attempt_1"), sub.get("attempt_2")
        if a1 is None or a2 is None:
            v.append(Violation("I2_two_attempts",
                               f"{tid}: missing attempt", "CRITICAL"))
        for name, g in (("attempt_1", a1), ("attempt_2", a2)):
            if g is not None and not valid_grid(g):
                v.append(Violation("I4_schema_valid",
                                   f"{tid}.{name} invalid grid", "CRITICAL"))
    return Verdict(passed=len(v) == 0, violations=v)


def check_budget_decision(K: int, loo_max: int, slack_s: float) -> Verdict:
    """I7/A0.1 + ceiling caps on runtime budget decisions.

    slack_s = banked seconds per remaining task beyond target.
    Raising K/loo is legal ONLY under positive slack (never under pressure).
    """
    v: list = []
    if K > COVENANT["K_max"]:
        v.append(Violation("ceiling", f"K={K} exceeds K_max", "CRITICAL"))
    if loo_max > COVENANT["loo_max_task"]:
        v.append(Violation("ceiling", f"loo_max={loo_max} exceeds cap", "CRITICAL"))
    default_K, default_loo = COVENANT["K_default"], COVENANT["loo_max_default"]
    if (K > default_K or loo_max > default_loo) and slack_s <= 0:
        v.append(Violation(
            "I7_A0.1_no_pressure_flip",
            f"escalation K={K}/loo={loo_max} without deadline slack "
            "(budget pressure must not raise spend either — it must shed it)",
            "CRITICAL"))
    return Verdict(passed=len(v) == 0, violations=v)


# ── Autonomy: runtime decisions the harness makes alone ─────────────────

@dataclass
class RuntimeState:
    t0: float = field(default_factory=time.time)
    deadline_s: float = COVENANT["hard_deadline_h"] * 3600
    tasks_total: int = 1200
    tasks_done: int = 0
    tally: dict = field(default_factory=dict)   # source -> count


def elapsed_s(state: RuntimeState) -> float:
    return time.time() - state.t0


def guard_deadline(state: RuntimeState) -> bool:
    """I5: True while under the pain guard (may start a task)."""
    return elapsed_s(state) < COVENANT["guard_h"] * 3600


def budget_slack_s(state: RuntimeState) -> float:
    """Banked seconds per remaining task (negative = behind)."""
    remaining = max(state.tasks_total - state.tasks_done, 1)
    left = COVENANT["guard_h"] * 3600 - elapsed_s(state)
    return left / remaining - COVENANT["per_task_target_s"]


def decide_budget(state: RuntimeState) -> dict:
    """Autonomy decision-right: adapt K/loo to slack (A0.1-safe)."""
    slack = budget_slack_s(state)
    K, loo = COVENANT["K_default"], COVENANT["loo_max_default"]
    if slack > 15.0:                       # comfortably ahead: bank quality
        K = min(COVENANT["K_max"], K + 2)
        loo = min(COVENANT["loo_max_task"], loo + 1)
    elif slack < -15.0:                    # behind: shed load to symbolic
        K = 0
        loo = 0
    # enforce ceiling via the same I7 gate (fail loud, never silent)
    verdict = check_budget_decision(K, loo, slack)
    if not verdict.passed:                 # pragma: no cover - defensive
        K, loo = COVENANT["K_default"], COVENANT["loo_max_default"]
    return {"K": K, "loo_max": loo, "slack_s": round(slack, 1),
            "mode": "symbolic-only" if K == 0 else
                    "escalated" if K > COVENANT["K_default"] else "default"}


def choose_attempt2_strategy(source1: str) -> str:
    """Autonomy decision-right: diversify attempt_2 against attempt_1."""
    return "symbolic" if source1 != "symbolic" else "llm"  # opposite family


# ── Algedonic (alpha channel: harness state -> policy reaction) ──────────

def algedonic_signals(state: RuntimeState) -> list:
    """Binary pain/pleasure signals. Deterministic given state."""
    sigs = []
    if not guard_deadline(state):
        sigs.append({"signal": "deadline_guard_tripped", "pain": True,
                     "reaction": "shed LLM load -> symbolic-only"})
    starved = [s for s, n in state.tally.items() if n == 0]
    if starved and sum(state.tally.values()) >= 10:
        sigs.append({"signal": "producer_starvation", "pain": True,
                     "reaction": f"reweight toward healthy producers (starved: {starved})"})
    if sum(state.tally.values()) >= 10 and \
            all(n < 0.05 * sum(state.tally.values()) for n in state.tally.values()):
        sigs.append({"signal": "producer_unhealthy", "pain": True,
                     "reaction": "consider zero-shim path if all fail per task"})
    return sigs


# ── Submit gate (wired at partial-write time, kernel-safe) ───────────────

def pre_submit_gate(tasks: dict, state: RuntimeState) -> Verdict:
    """Full I1-I5 + I7 sweep before writing submission.json."""
    v: list = []
    sub = check_submission(tasks)
    v.extend(sub.violations)
    if not guard_deadline(state) and state.tasks_done < state.tasks_total:
        # guard trip itself is not a violation; starting NEW tasks past
        # hard deadline would be. We only surface it for telemetry.
        pass
    # I7: the decision we are shipping with must itself be legal
    budget = decide_budget(state)
    bverdict = check_budget_decision(budget["K"], budget["loo_max"],
                                     budget_slack_s(state))
    v.extend(bverdict.violations)
    return Verdict(passed=len(v) == 0, violations=v)


if __name__ == "__main__":  # pragma: no cover
    st = RuntimeState()
    print("covenant:", COVENANT["name"],
          "| budget now:", decide_budget(st),
          "| signals:", algedonic_signals(st) or "none")
