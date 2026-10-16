#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Parity harness: the packaged solver must reproduce the engine score.

    python3 arc-solver/tests/parity.py --data data/training [--max N]

Compares solve_task() attempt_1 against expected outputs AND against
the engine's latest full-1000 solved set. Any divergence fails loud.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "arc-agi3"))

from solve import solve_task  # noqa: E402
import solver_smart_v2 as v2  # noqa: E402


def grids_equal(a, b):
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    return all(len(r1) == len(r2) and all(x == y for x, y in zip(r1, r2))
               for r1, r2 in zip(a, b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/training")
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--report", default=None,
                    help="engine report JSON for solved-set parity "
                         "(default: latest state/rsi_reports)")
    args = ap.parse_args()
    puzzles = v2.load_puzzles(args.data)
    ids = sorted(puzzles)[:args.max]
    solved, p2, ms = [], [], []
    for pid in ids:
        p = puzzles[pid]
        out = solve_task(p)
        exp = p["test"][0]["output"]
        ms.append(out["ms"])
        if grids_equal(out["attempt_1"], exp):
            solved.append(pid)
        elif grids_equal(out["attempt_2"], exp):
            p2.append(pid)
    print(f"n={len(ids)} p@1={len(solved)} p@2-only={len(p2)} "
          f"p@2-total={len(solved) + len(p2)} "
          f"ms_avg={sum(ms) / len(ms):.1f} "
          f"ms_p95={sorted(ms)[int(len(ms) * 0.95)]:.1f}")
    rep = args.report
    if rep is None:
        cands = sorted(glob.glob("arc-agi3/state/rsi_reports/"
                                 "recognizer_*.json"))
        rep = cands[-1] if cands else None
    if rep:
        eng = {r["id"] for r in json.load(open(rep))["rows"]
               if r["solved"]}
        only_pkg = sorted(set(solved) - eng)
        only_eng = sorted(eng - set(solved))
        print(f"solved-set parity vs {os.path.basename(rep)}: "
              f"only_pkg={only_pkg or 'NONE'} only_eng={only_eng or 'NONE'}")
        if only_pkg or only_eng:
            return 1
    else:
        print("no engine report found: set parity skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
