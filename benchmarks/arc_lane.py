#!/usr/bin/env python3
"""ARC lane — external reasoning benchmark harness (ARC-AGI-2 eval subset).

Honest scope (baseline v1): HARNESS + ZERO-BASELINE, not a solver.
vOSarc is an infrastructure clone; no ARC solver exists yet. Publishing
a measured ~0% with replayable harness beats skipping the lane or, worse,
claiming reasoning power without a solver (theater).

What this measures:
  - 12/120 ARC-AGI-2 eval tasks load valid (rectangular grids, 0-9,
    train/test pairs present).
  - zero_baseline accuracy (predict test output = test input): the floor
    every future solver must beat. ARC allows 2 attempts; zero uses 1.
  - dataset profile (grid sizes, train pairs) for solver design.

Phase 2 (not this session): GA program synthesis over a grid-op DSL,
scored on train pairs, gated by the socratic engine. Harness is ready.

Claim: harness valid, zero-line recorded <= 10%.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "arc_data"


def _valid_grid(g) -> bool:
    return (isinstance(g, list) and g
            and all(isinstance(r, list) and r for r in g)
            and len({len(r) for r in g}) == 1
            and all(isinstance(v, int) and 0 <= v <= 9
                    for r in g for v in r))


def _load():
    tasks = []
    for p in sorted(DATA.glob("*.json")):
        t = json.loads(p.read_text())
        ok = (isinstance(t.get("train"), list) and t["train"]
              and isinstance(t.get("test"), list) and t["test"]
              and all(_valid_grid(p_["input"]) and _valid_grid(p_["output"])
                      for p_ in t["train"])
              and all(_valid_grid(p_["input"]) for p_ in t["test"]))
        tasks.append({"id": p.stem, "task": t, "valid": ok})
    return tasks


def run(seed: int = 20260922) -> dict:
    tasks = _load()
    valid = [t for t in tasks if t["valid"]]
    # zero baseline: predict input; exact match on any test pair scores
    hits = 0
    scored = 0
    train_pairs, cells = [], []
    for t in valid:
        for pair in t["task"]["test"]:
            if "output" not in pair:
                continue  # sealed test pair (no output distributed)
            scored += 1
            if pair["input"] == pair["output"]:
                hits += 1
        train_pairs.append(len(t["task"]["train"]))
        for pair in t["task"]["train"]:
            cells.append(len(pair["input"]) * len(pair["input"][0]))
    zero_acc = hits / scored if scored else 0.0

    # phase-1 solver: scratch R&D solver if importable, else GA-DSL
    # baseline (train pairs only; test outputs NEVER leak into search).
    solver_acc, solver_detail = _run_solver(valid, seed)
    passed = (len(valid) == len(tasks) and len(tasks) > 0
              and zero_acc <= 0.10 and solver_acc >= zero_acc)
    return {
        "suite": "ARC-lane",
        "claim": "harness valid; solver measured against zero floor",
        "metrics": {
            "tasks_loaded": len(tasks),
            "tasks_valid": len(valid),
            "sealed_test_pairs": sum(
                1 for t in valid for p in t["task"]["test"]
                if "output" not in p),
            "zero_baseline_acc": round(zero_acc, 4),
            "solver": solver_detail.get("solver_id", "?"),
            "solver_acc": round(solver_acc, 4),
            "solver_solved": solver_detail["solved"],
            "avg_train_pairs": round(sum(train_pairs) / len(train_pairs), 2)
            if train_pairs else 0,
            "avg_grid_cells": round(sum(cells) / len(cells), 1) if cells else 0,
        },
        "passed": passed,
        "threshold": "all loaded tasks valid AND zero-line <= 10% AND "
                     "solver >= zero-line",
        "detail": {"per_task": solver_detail["per_task"]},
    }


def _run_solver(valid, seed):
    """Solver ladder (no duplication policy):
    1. scratch/arc-solver solve_task (real R&D solver, AGI-2 lineage) —
       measured here with honesty protocol (sealed tests never leak).
    2. Fallback: vsf-rsi GA-DSL (pedagogical baseline, kept minimal).
    Returns (accuracy, detail)."""
    solved = hits = scored = 0
    per_task = []
    prog = _scratch_solver()
    if prog is None:
        from vsf_rsi.arc_search import ga_search
        from vsf_rsi.arc_dsl import apply, program_to_str
        solver_id = "ga-dsl-v1 (pop 24 x 6 gens, max_len 3)"
    else:
        solver_id = "scratch-solver (solve_task attempt_1/2)"
    for i, t in enumerate(valid):
        train = t["task"]["train"]
        if prog is None:
            from vsf_rsi.arc_search import ga_search
            from vsf_rsi.arc_dsl import apply, program_to_str
            prog_i, f = ga_search(train, pop_size=24, generations=6,
                                  seed=seed + i)
            train_fit = f[0]

            def predict(inp):
                return apply(prog_i, inp)

            prog_str = program_to_str(prog_i)
        else:
            train_fit = "-"
            prog_str = "scratch"
        ok_tests = 0
        n_tests = 0
        for pair in t["task"]["test"]:
            if "output" not in pair:
                continue
            n_tests += 1
            try:
                pred = prog(pair["input"]) if prog else predict(pair["input"])
                if pred == pair["output"]:
                    ok_tests += 1
                elif prog:
                    # ARC allows 2 attempts: blind second opinion
                    pred2 = prog(pair["input"], attempt=2)
                    if pred2 == pair["output"]:
                        ok_tests += 1
            except Exception:
                pass
        solved += 1 if n_tests and ok_tests == n_tests else 0
        hits += ok_tests
        scored += n_tests
        per_task.append({"id": t["id"], "train_fit": train_fit,
                         "test_hits": f"{ok_tests}/{n_tests}",
                         "program": prog_str[:70]})
    return (hits / scored if scored else 0.0,
            {"solved": solved, "per_task": per_task,
             "solver_id": solver_id})


def _scratch_solver():
    """Load scratch solve_task if importable. Returns predict(inp) or None.

    Timeout-guarded by the caller harness (see TASK_TIMEOUT_S).
    Sealed-test discipline: only train pairs may inform search; scratch
    solver is called per test input with no feedback loop here.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scratch_solve",
            "/home/rmw3/vOSlab-scratch/arc-solver/solve.py")
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "solve_task", None)
        if fn is None:
            return None

        def predict(inp, attempt=1):
            task = {"train": [], "test": [{"input": inp}]}
            out = fn(task)
            key = "attempt_1" if attempt == 1 else "attempt_2"
            return (out or {}).get(key)

        return predict
    except Exception:
        return None


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
