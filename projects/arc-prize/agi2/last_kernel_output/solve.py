#!/usr/bin/env python3
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


def solve_one(trains, test):
    """Core: one test input -> (attempt_1, attempt_2, meta)."""
    t0 = time.time()
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
    ms = (time.time() - t0) * 1000.0
    return a1, a2, {"dynamic": r["dynamic"], "fallback": r["fallback"],
                   "ms": ms}


def solve_task(task):
    """Solve one ARC task. Returns dict with attempt_1/attempt_2."""
    trains = [(p["input"], p["output"]) for p in task.get("train", [])]
    tests = task.get("test", [])
    if not trains or not tests:
        return {"attempt_1": None, "attempt_2": None, "dynamic": "empty",
                "fallback": True, "ms": 0.0}
    a1, a2, meta = solve_one(trains, tests[0]["input"])
    return {"attempt_1": a1, "attempt_2": a2, "dynamic": meta["dynamic"],
            "fallback": meta["fallback"], "ms": meta["ms"]}


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
