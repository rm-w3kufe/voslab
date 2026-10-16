#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Oracle miner (T1 mecanico): encuentra detector-gaps en serio.

Todo puzzle unsolved donde una toolbox-fn resuelve el test es un
lead: la estrategia EXISTE, falta el detector. NO es regla probada
(un oracle-hit puede ser suerte) — cada lead pasa por probe + LOO.

    python3 arc-agi3/oracle_mine.py --data data/training [--out leads.json]

Lee el ultimo reporte full-1000 para la lista de unsolved.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recognizer as R  # noqa: E402
import solver_smart_v2 as v2  # noqa: E402
import solver_v3 as v3  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/training")
    ap.add_argument("--report", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.report is None:
        cands = sorted(glob.glob("arc-agi3/state/rsi_reports/"
                                 "recognizer_*.json"))
        a.report = cands[-1]
    rep = json.load(open(a.report))
    puzzles = v2.load_puzzles(a.data)
    unsolved = [r["id"] for r in rep["rows"] if not r["solved"]]
    print(f"unsolved: {len(unsolved)}")
    by_strat, leads = Counter(), []
    for i, pid in enumerate(sorted(unsolved)):
        p = puzzles.get(pid)
        if p is None:
            continue
        t = v2.get_train_pairs(p)
        test, exp = v2.get_test_input(p), p["test"][0]["output"]
        try:
            winners = R.oracle_solvers(t, test, exp)
        except Exception as e:
            print(f"EXC {pid}: {str(e)[:80]}")
            continue
        for w in winners:
            by_strat[w] += 1
        if winners:
            dyn = next(r["dynamic"] for r in rep["rows"] if r["id"] == pid)
            leads.append({"id": pid, "dynamic": dyn, "solvers": winners})
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(unsolved)} ... ({len(leads)} con hits)")
    print(f"con hits: {len(leads)}/{len(unsolved)}")
    print("por estrategia:")
    for w, n in by_strat.most_common(15):
        print(f"  {w:28s} {n}")
    if a.out:
        json.dump({"leads": leads,
                   "by_strategy": dict(by_strat)}, open(a.out, "w"))
        print(f"leads -> {a.out}")


if __name__ == "__main__":
    main()
