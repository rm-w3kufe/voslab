#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""arc-solver public inference API — pure function, no IO, no state.

Usage:
    from solve import solve_task
    out = solve_task(task)   # task: ARC JSON dict with train/test
    out["attempt_1"]         # primary prediction (p@1 path)
    out["attempt_2"]         # independent blind second opinion or None

Only stdlib + the four vendored engine files in this directory.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import recognizer as R  # noqa: E402

try:
    import agent as AG  # noqa: E402
except Exception:
    AG = None

try:
    import rsi_bridge as RSI  # noqa: E402
except Exception:
    RSI = None

try:
    import llm_harness as LH  # noqa: E402
except Exception:
    LH = None

try:
    import covenant as COV  # noqa: E402
except Exception:
    COV = None


# Run-level tally of decision sources (printed by the kernel at the end:
# "llm+llm-certified" vs dynamics vs fallback — evidence of harness mix).
SOURCE_TALLY = {}

# Runtime state (VSM autonomy): budget decisions + algedonic per task.
_RT = None


def runtime_state():
    global _RT
    if _RT is None and COV is not None:
        _RT = COV.RuntimeState()
    return _RT


def _solve_legacy(trains, test):
    """Pre-agent path (routed + blind second). Fallback if agent missing."""
    r = R.solve_routed(trains, test, use_fallback=True)
    a1 = r["pred"]
    a2 = None
    seen = set(r.get("tried", []))
    for _fname, fn in R.FALLBACK:
        if fn.__name__ in seen:
            continue
        try:
            pred = R.safe_apply(fn, trains, test)
        except Exception:
            continue
        if pred is not None and pred != a1:
            a2 = pred
            break
    # RSI-generated strategies: try as second attempt
    if a2 is None and RSI is not None:
        try:
            a1_key = (tuple(tuple(r) for r in a1)
                      if a1 is not None else None)
            for rc in RSI.rsi_propose(trains, test):
                if rc.get("key") is not None and rc["key"] != a1_key:
                    a2 = rc["grid"]
                    break
        except Exception:
            pass
    return a1, a2, {"dynamic": r["dynamic"], "fallback": r["fallback"],
                    "trace": [], "n_candidates": len(seen)}


def _sym_as_dict(trains, test):
    """agent.decide -> the ensemble's symbolic adapter."""
    a1, a2, meta = AG.decide(trains, test)
    trace = meta.get("trace") or []
    loo = trace[0].get("loo_frac") if trace else 0.0
    return {"a1": a1, "a2": a2, "loo": loo or 0.0, "meta": meta}


def solve_one(trains, test):
    """Core: one test input -> (attempt_1, attempt_2, meta).

    M1 (2026-10-16): when a staged LLM model is present (Kaggle input),
    proposals go through llm_harness.ensemble_decide — certified LLM
    candidates compete with the symbolic solver; certified programs
    outrank fluent guesses. No model (local/smoke): symbolic only.

    M2 (2026-10-16, covenant ratified): runtime autonomy —
      * decide_budget() sets K/LOO per task from deadline slack (A0.1:
        pressure sheds the LLM, never raises certify spend)
      * RSI tool path: when symbolic+grid-LLM both fail AND slack allows,
        the model proposes solve() CODE; rsi_bridge sandbox+LOO-certifies
        it; certified tools compete AND are written back to memory
      * algedonic: past the 9.5h guard the LLM path trips off (pain).
    """
    t0 = time.time()
    state = runtime_state()
    budget = (COV.decide_budget(state)
              if COV is not None and state is not None
              else {"K": None, "loo_max": None, "slack_s": 0.0,
                    "mode": "default"})
    symbolic_only = budget.get("K") == 0

    # Apply runtime budget to the LLM harness (same process globals)
    llm_staged = LH is not None and LH.model_path()
    if llm_staged and budget.get("K") is not None and not symbolic_only:
        try:
            LH.K_SAMPLES = int(budget["K"])
            LH.LOO_MAX = int(budget["loo_max"])
        except Exception:
            pass
    guard_ok = (COV is None or state is None
                or COV.guard_deadline(state))

    if AG is None:
        a1, a2, meta = _solve_legacy(trains, test)
    elif llm_staged and not symbolic_only and guard_ok:
        try:
            ens = LH.ensemble_decide(trains, test,
                                     lambda tr, te: _sym_as_dict(tr, te),
                                     budget=budget)
            a1, a2 = ens["a1"], ens["a2"]
            meta = {"dynamic": "llm+" + str(ens.get("source")),
                    "fallback": a1 is None,
                    "trace": [], "n_candidates": 0,
                    "llm_meta": ens.get("llm_meta"),
                    "sym_loo": ens.get("sym_loo")}
        except Exception:
            d = _sym_as_dict(trains, test)
            a1, a2, meta = d["a1"], d["a2"], d["meta"]
        # NOTE: the RSI-M2 program path now lives INSIDE ensemble_decide
        # (fires on unverified-symbolic + slack, certify-gated, with
        # cross-run memory write-back). This legacy dead-family fallback
        # is kept only as a belt-and-suspenders net.
    elif llm_staged and (symbolic_only or not guard_ok):
        # Algedonic: pain (deadline/pressure) -> shed LLM, symbolic leads
        try:
            a1, a2, meta = AG.decide(trains, test)
            meta["dynamic"] = "symbolic-shed:" + str(meta.get("dynamic", "?"))
        except Exception:
            a1, a2, meta = _solve_legacy(trains, test)
    else:
        try:
            a1, a2, meta = AG.decide(trains, test)
        except Exception:
            a1, a2, meta = _solve_legacy(trains, test)
    ms = (time.time() - t0) * 1000.0
    meta["ms"] = ms
    dyn = str(meta.get("dynamic", "?"))
    SOURCE_TALLY[dyn] = SOURCE_TALLY.get(dyn, 0) + 1
    if state is not None:
        state.tally[dyn] = state.tally.get(dyn, 0) + 1
        state.tasks_done += 1
    return a1, a2, meta


def solve_task(task):
    """Solve one ARC task. Returns dict with attempt_1/attempt_2."""
    trains = [(p["input"], p["output"]) for p in task.get("train", [])]
    tests = task.get("test", [])
    if not trains or not tests:
        return {"attempt_1": None, "attempt_2": None, "dynamic": "empty",
                "fallback": True, "ms": 0.0}
    a1, a2, meta = solve_one(trains, tests[0]["input"])
    return {"attempt_1": a1, "attempt_2": a2, "dynamic": meta["dynamic"],
            "fallback": meta["fallback"], "ms": meta["ms"],
            "trace": meta.get("trace", []),
            "n_candidates": meta.get("n_candidates", 0)}


def solve_all_tests(task):
    """All test inputs -> list of {attempt_1, attempt_2, source, loo}.

    source/loo feed covenant.check_attempt_pair (I1/I3) at RUN_CELL.
    """
    trains = [(p["input"], p["output"]) for p in task.get("train", [])]
    out = []
    for t in task.get("test", []):
        a1, a2, meta = solve_one(trains, t["input"])
        dyn = str(meta.get("dynamic", "?"))
        if a1 is None:
            source, loo = "shim", None
        elif "llm-certified" in dyn:
            source = "llm-certified"
            loo = (meta.get("llm_meta") or {}).get("loo_llm")
        else:
            source, loo = "symbolic", meta.get("sym_loo")
        out.append({"attempt_1": a1 if a1 is not None else t["input"],
                    "attempt_2": a2 if a2 is not None else
                    (a1 if a1 is not None else t["input"]),
                    "source": source, "loo": loo})
    return out
