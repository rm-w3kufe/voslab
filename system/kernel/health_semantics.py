"""health_semantics — what counts as an operational failure (R10 deterministic).

Why: production tree_traces mix two kinds of FALSE:

  (a) operational checks failing — state_consistent, scripts_*,
      composites over real predicates, etc. Real pain; counts against
      health.
  (b) designed-benign verdicts/observations — test_always_false (a
      pytest-only fixture predicate), type_prefix classification misses
      (FALSE = no prefix matched), task_* observations (FALSE = nothing
      active/queued) and security gate verdicts (action_forbidden &
      friends: FALSE = the gate FIRED, i.e. the machinery worked — the
      attempted-action signal lives in vsf-rsi scenario memory).

Counting (b) as failures made health scream "83% FALSE" while the gate
suite was 76/76 green and tests 529 green (evidence 2026-10-05). D-15
did the same split for the unified-log channel; this module is the
trace channel.

Semantics: pure functions, no I/O, no clock — same trace dict ->
same classification (R10).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# Sources whose FALSE/TRUE is by design, not health signal.
BENIGN_SOURCES = frozenset({
    "test_always_false",   # pytest-only predicate (registered in test_rsi_cycle)
    "type_prefix",         # classification: FALSE = no prefix match
    "task_active",         # observation: FALSE = no active task
    "task_has_work",       # observation: FALSE = nothing queued
    "action_forbidden",    # security verdict: FALSE = gate fired (worked)
    "path_forbidden",      # security verdict: FALSE = gate fired (worked)
    "policy_locked",       # security verdict: FALSE = gate fired (worked)
    "ctx_contains",        # classification leaf: FALSE = branch not taken
    "ctx_equals",          # classification leaf: FALSE = branch not taken
    "ctx_has",             # classification leaf: FALSE = branch not taken
})

OPERATIONAL_FAILURE = "operational_failure"
OPERATIONAL_SUCCESS = "operational_success"
NON_OPERATIONAL = "non_operational"


def _predicate_false_names(trace: dict) -> List[str]:
    """Names of predicate nodes evaluated FALSE inside this trace."""
    names: List[str] = []
    for node in trace.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "predicate":
            continue
        if "FALSE" in str(node.get("truth", "")):
            names.append(str(node.get("name") or node.get("source") or "unknown"))
    return names


def classify_trace(trace: dict) -> str:
    """Classify one trace for health accounting.

    operational_failure  — real check failed; counts in numerator+denominator
    operational_success  — real check passed
    non_operational      — designed-benign verdict; excluded from both
    """
    truth = str(trace.get("final_truth", ""))
    final_src = str(trace.get("final_source", ""))
    is_fail = "FALSE" in truth or "ERROR" in truth
    is_ok = "TRUE" in truth

    if final_src in BENIGN_SOURCES:
        return NON_OPERATIONAL

    if final_src.startswith("op:"):
        if not is_fail:
            return OPERATIONAL_SUCCESS if is_ok else NON_OPERATIONAL
        false_preds = _predicate_false_names(trace)
        if not false_preds:
            # Legacy/absent node detail: conservative — count it, never
            # hide a real composite failure behind missing forensics.
            return OPERATIONAL_FAILURE
        if any(name not in BENIGN_SOURCES for name in false_preds):
            return OPERATIONAL_FAILURE
        return NON_OPERATIONAL

    if is_fail:
        return OPERATIONAL_FAILURE
    if is_ok:
        return OPERATIONAL_SUCCESS
    return NON_OPERATIONAL  # UNKNOWN / missing truth


def operational_counts(traces: List[dict]) -> Tuple[int, int, int]:
    """-> (operational_total, operational_failures, operational_successes)."""
    total = 0
    failures = 0
    successes = 0
    for trace in traces:
        cls = classify_trace(trace)
        if cls == OPERATIONAL_FAILURE:
            total += 1
            failures += 1
        elif cls == OPERATIONAL_SUCCESS:
            total += 1
            successes += 1
    return total, failures, successes


def operational_truths(traces: List[dict]) -> Dict[str, int]:
    """Truth-shaped dict for health entries: {"Truth.TRUE": n, "Truth.FALSE": m}."""
    _, failures, successes = operational_counts(traces)
    return {"Truth.TRUE": successes, "Truth.FALSE": failures}
