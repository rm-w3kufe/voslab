#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Build the self-contained Kaggle submission notebook (stdlib only).

    python3 arc-solver/build_notebook.py [--out kaggle_notebook.ipynb]

Embeds the vendored engine + solve/submit as data (no internet at
eval time). The notebook discovers tasks under /kaggle/input,
solves with solve_all_tests (2 attempts), validates the schema and
writes /kaggle/working/submission.json. CPU, offline, deterministic.
Per-task try/except: a single bad task can never sink the run
(falls back to input-copy for that task only, logged).
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["recognizer.py", "solver_smart_v2.py", "solver_v3.py",
           "rsi_module.py", "agent.py", "solve.py", "rsi_bridge.py",
           "composer.py", "llm_serialize.py", "llm_harness.py"]

RUN_CELL = '''import glob, json, os, sys, time

# Coverage over depth: at ~82s/puzzle with K=4+LOO2 the full eval set
# overruns the 12h kernel; K=2+LOO1 (~25-40s) covers every task inside
# the 9.5h LLM budget (certify stays: majority of 2 + 1 LOO check).
os.environ.setdefault("LLM_K_SAMPLES", "2")
os.environ.setdefault("LLM_LOO_MAX", "1")

MODULES = __MODULES__

for name, src in MODULES.items():
    with open(name, "w") as fp:
        fp.write(src)
print("modules written:", sorted(MODULES))

sys.path.insert(0, os.getcwd())
from solve import solve_all_tests

CANDIDATES = ["/kaggle/input"]
tasks = {}
for root in CANDIDATES:
    for dirpath, _dn, files in os.walk(root):
        if dirpath.count(os.sep) - root.count(os.sep) > 3:
            continue
        for f in files:
            if not f.endswith(".json"):
                continue
            p = os.path.join(dirpath, f)
            try:
                with open(p) as fp:
                    d = json.load(fp)
            except Exception as e:
                print("skip unreadable", p, e)
                continue
            if isinstance(d, dict) and "train" in d and "test" in d:
                tasks[os.path.splitext(f)[0]] = d
            elif isinstance(d, dict):
                for tid, t in d.items():
                    if isinstance(t, dict) and "train" in t and "test" in t:
                        tasks[tid] = t
print("tasks found:", len(tasks))
assert tasks, "no ARC tasks discovered under /kaggle/input"

def valid_grid(g):
    return (isinstance(g, list) and g and all(
        isinstance(r, list) and r and all(
            isinstance(v, int) and 0 <= v <= 9 for v in r) for r in g))

# M1 (2026-10-16): LLM deadline guard + resumable partial. The LLM
# path serves puzzles until the deadline; the rest fall back to the
# symbolic engine (always fast, always completes the schema).
t0 = time.time()
DEADLINE_S = float(os.environ.get("LLM_BUDGET_SECONDS", str(9.5 * 3600)))
try:
    import llm_harness as LH
    LH.set_deadline(t0 + DEADLINE_S)
    print(f"llm budget: {DEADLINE_S/3600:.1f}h, model:",
          "staged" if LH.model_path() else "absent (symbolic only)")
except Exception as e:
    print("llm harness unavailable:", e)

PART = "/kaggle/working/submission.partial.json"
sub = {}
if os.path.exists(PART):
    try:
        sub = json.load(open(PART))
        print("resumed from partial:", len(sub), "tasks")
    except Exception:
        sub = {}

SMOKE_N = int(os.environ.get("SMOKE_N", "0"))  # 12 = GPU smoke; 0 = full
for tid in sorted(tasks)[:SMOKE_N or None]:
    if tid in sub:
        continue
    try:
        preds = solve_all_tests(tasks[tid])
        assert len(preds) == len(tasks[tid]["test"])
        for pr in preds:
            assert valid_grid(pr["attempt_1"]) and valid_grid(pr["attempt_2"])
        sub[tid] = preds
    except Exception as e:
        print("TASK FAIL", tid, repr(e)[:200], "-> input-copy fallback")
        sub[tid] = [{"attempt_1": t["input"], "attempt_2": t["input"]}
                    for t in tasks[tid]["test"]]
    if len(sub) % 20 == 0:
        with open(PART, "w") as fp:
            json.dump(sub, fp)
        print(f"checkpoint {len(sub)}/{len(tasks)} "
              f"({time.time()-t0:.0f}s)")
out = "/kaggle/working/submission.json"
try:
    os.makedirs(os.path.dirname(out), exist_ok=True)
except Exception:
    out = "submission.json"
with open(out, "w") as fp:
    json.dump(sub, fp)
print(f"wrote {out}: {len(sub)} tasks in {time.time()-t0:.1f}s")
try:
    import solve as _S
    print("source tally:", getattr(_S, "SOURCE_TALLY", {}))
except Exception:
    pass
'''

MD_CELL = """# ARC-AGI-2 solver v2 (symbolic + LLM harness, offline, GPU)
Hybrid engine: deterministic symbolic propose (dynamics + composer
program enumeration, LOO-certified, 8.9% local baseline) AND a staged
Qwen2.5-3B-Instruct (pre-trained, dataset-mounted, no internet) whose
grid serializations are CERTIFIED before competing: V1 self-consistency
(majority of K samples) + V2 leave-one-out understanding (the model
must reproduce held-out train outputs). Certified symbolic programs
outrank fluent guesses; the LLM only leads when the symbolic side is
unverified and its own LOO-understanding passes. Resumable partial +
LLM deadline guard; schema-validated submission.json, 2 attempts per
test input. Apache-2.0 weights, evaluation offline (rules-legal).
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    mods = {}
    for name in MODULES:
        with open(os.path.join(HERE, name)) as fp:
            mods[name] = fp.read()
    run = RUN_CELL.replace("__MODULES__", json.dumps(mods))
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3",
                           "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
            "kaggle": {"accelerator": "gpu", "isInternetEnabled": False,
                       "dockerImageVersionId": 0},
        },
        "cells": [
            {"cell_type": "markdown", "metadata": {},
             "source": MD_CELL.splitlines(keepends=True)},
            {"cell_type": "code", "metadata": {}, "execution_count": None,
             "outputs": [], "source": run.splitlines(keepends=True)},
        ],
    }
    out = a.out or os.path.join(HERE, "kaggle_notebook.ipynb")
    with open(out, "w") as fp:
        json.dump(nb, fp)
    print(f"notebook: {out} ({os.path.getsize(out)} bytes, "
          f"{len(mods)} modules embedded)")


if __name__ == "__main__":
    main()
