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
    passed = len(valid) == len(tasks) and len(tasks) > 0 and zero_acc <= 0.10
    return {
        "suite": "ARC-lane",
        "claim": "harness valid; zero-baseline floor recorded",
        "metrics": {
            "tasks_loaded": len(tasks),
            "tasks_valid": len(valid),
            "sealed_test_pairs": sum(
                1 for t in valid for p in t["task"]["test"]
                if "output" not in p),
            "zero_baseline_acc": round(zero_acc, 4),
            "avg_train_pairs": round(sum(train_pairs) / len(train_pairs), 2)
            if train_pairs else 0,
            "avg_grid_cells": round(sum(cells) / len(cells), 1) if cells else 0,
            "solver": "none (phase 2: GA program synthesis over grid DSL)",
        },
        "passed": passed,
        "threshold": "all loaded tasks valid AND zero-line <= 10%",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
