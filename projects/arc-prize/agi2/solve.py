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
            for rc in RSI.rsi_propose(trains, test):
                if rc["grid"] is not None:
                    grid_bytes = rc["grid"].tobytes()
                    a1_bytes = a1.tobytes() if a1 is not None else None
                    if grid_bytes != a1_bytes:
                        a2 = rc["grid"]
                        break
        except Exception:
            pass
    return a1, a2, {"dynamic": r["dynamic"], "fallback": r["fallback"],
                    "trace": [], "n_candidates": len(seen)}


def solve_one(trains, test):
    """Core: one test input -> (attempt_1, attempt_2, meta)."""
    t0 = time.time()
    if AG is None:
        a1, a2, meta = _solve_legacy(trains, test)
    else:
        try:
            a1, a2, meta = AG.decide(trains, test)
        except Exception:
            a1, a2, meta = _solve_legacy(trains, test)
    ms = (time.time() - t0) * 1000.0
    meta["ms"] = ms
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
    """All test inputs -> list of {attempt_1, attempt_2} (Kaggle order)."""
    trains = [(p["input"], p["output"]) for p in task.get("train", [])]
    out = []
    for t in task.get("test", []):
        a1, a2, _meta = solve_one(trains, t["input"])
        out.append({"attempt_1": a1 if a1 is not None else t["input"],
                    "attempt_2": a2 if a2 is not None else
                    (a1 if a1 is not None else t["input"])})
    return out
