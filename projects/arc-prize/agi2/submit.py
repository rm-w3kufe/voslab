#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Build competition submission.json from ARC tasks.

    python3 arc-solver/submit.py --tasks <dir|challenges.json> --out submission.json

Input: directory of per-task JSONs ({id: {train, test}}) or a single
ARC challenges.json. Output: {task_id: [{attempt_1, attempt_2}, ...]}
with one entry per test input, in order. Schema-validated before write.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from solve import solve_all_tests  # noqa: E402


def load_tasks(path):
    if os.path.isdir(path):
        tasks = {}
        for f in sorted(glob.glob(os.path.join(path, "*.json"))):
            with open(f) as fp:
                tasks[os.path.splitext(os.path.basename(f))[0]] = \
                    json.load(fp)
        return tasks
    with open(path) as fp:
        return json.load(fp)


def valid_grid(g):
    return (isinstance(g, list) and g and
            all(isinstance(r, list) and r and
                all(isinstance(v, int) and 0 <= v <= 9 for v in r)
                for r in g))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", default="submission.json")
    a = ap.parse_args()
    tasks = load_tasks(a.tasks)
    sub, n_pred = {}, 0
    for tid in sorted(tasks):
        preds = solve_all_tests(tasks[tid])
        if len(preds) != len(tasks[tid].get("test", [])):
            print(f"FAIL {tid}: prediction/test count mismatch")
            return 1
        for pr in preds:
            if not valid_grid(pr["attempt_1"]) or \
                    not valid_grid(pr["attempt_2"]):
                print(f"FAIL {tid}: invalid grid in predictions")
                return 1
        sub[tid] = preds
        n_pred += len(preds)
    with open(a.out, "w") as fp:
        json.dump(sub, fp)
    print(f"submission.json: {len(sub)} tasks, {n_pred} predictions, "
          f"schema OK -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
