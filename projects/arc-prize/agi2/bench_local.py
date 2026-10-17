#!/usr/bin/env python3
"""Local benchmark for the AGI-2 solver against ARC training puzzles.

Exact-match p@1 (attempt_1) and p@2 (either attempt) over every test
output. SIGALRM per-puzzle timeout keeps one stuck task from hanging
the run. Deterministic: sorted file order, no sampling.
"""
import glob
import json
import os
import signal
import sys
import time
from collections import Counter

AGI2 = os.path.expanduser("~/vOSlab/projects/arc-prize/agi2")
if not os.path.isdir(AGI2):
    AGI2 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AGI2)
from solve import solve_task  # noqa: E402

# Portable data: env override -> beside the code (LXC 114) -> vOSlab hub
_here = os.path.dirname(os.path.abspath(__file__))
DATA_CANDIDATES = [
    os.environ.get("BENCH_DATA", ""),
    os.path.join(_here, "..", "data", "training"),
    os.path.expanduser("~/vOSlab/projects/arc-prize/data/training"),
]
DATA = []
for _c in DATA_CANDIDATES:
    if _c:
        DATA = sorted(glob.glob(os.path.join(_c, "*.json")))
        if DATA:
            break
OUT = os.environ.get("BENCH_OUT", os.path.join("/tmp", "bench_agi2.json"))
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else len(DATA)
TIMEOUT_S = float(os.environ.get("BENCH_TIMEOUT", "2.0"))


class Timeout(Exception):
    pass


def _alarm(_sig, _frame):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def to_list(g):
    if g is None:
        return None
    if hasattr(g, "tolist"):
        return g.tolist()
    return g


def grids_equal(a, b):
    return to_list(a) == to_list(b)


def main():
    files = DATA[:LIMIT]
    n = len(files)
    p1 = p2 = timeout = crashed = both_none = 0
    dyn = Counter()
    ms_total = 0.0
    per_dyn = {}
    rows = []

    for i, path in enumerate(files):
        tid = os.path.basename(path)[:-5]
        try:
            with open(path) as fh:
                task = json.load(fh)
        except Exception:
            crashed += 1
            continue
        tests = task.get("test", [])
        signal.alarm(int(TIMEOUT_S) + 1 if TIMEOUT_S < 1 else int(TIMEOUT_S))
        try:
            out = solve_task(task)
            signal.alarm(0)
        except Timeout:
            signal.alarm(0)
            timeout += 1
            rows.append({"id": tid, "result": "timeout"})
            continue
        except Exception as e:
            signal.alarm(0)
            crashed += 1
            rows.append({"id": tid, "result": "crash",
                         "err": type(e).__name__[:40]})
            continue

        a1, a2 = out.get("attempt_1"), out.get("attempt_2")
        ms_total += out.get("ms", 0.0)
        d = str(out.get("dynamic", "?"))
        dyn[d] += 1
        slot = per_dyn.setdefault(d, {"n": 0, "p1": 0, "p2": 0})
        slot["n"] += 1

        if a1 is None and a2 is None:
            both_none += 1
            rows.append({"id": tid, "result": "none", "dynamic": d})
            continue

        ok1 = all(grids_equal(a1, t.get("output")) for t in tests) if tests else False
        ok2 = ok1 or (all(grids_equal(a2, t.get("output"))
                          for t in tests) if tests and a2 is not None else False)
        p1 += ok1
        p2 += ok2
        slot["p1"] += ok1
        slot["p2"] += ok2
        rows.append({"id": tid, "result": "p2" if ok2 else
                     ("p1" if ok1 else "miss"), "dynamic": d})

        if (i + 1) % 100 == 0:
            print(f"  ...{i+1}/{n}  p1={p1} p2={p2} t/o={timeout}", flush=True)

    elapsed_note = f"bench limit={n}"
    print("=" * 60)
    print(f"n={n}  p@1={p1} ({p1/max(n,1):.1%})  p@2={p2} "
          f"({p2/max(n,1):.1%})  timeout={timeout}  crash={crashed}  "
          f"both_none={both_none}")
    print(f"ms mean={ms_total/max(n-timeout-crashed,1):.0f}")
    print("top dynamics:")
    for name, c in dyn.most_common(12):
        s = per_dyn[name]
        print(f"  {name:22s} n={c:4d}  p1={s['p1']:3d}  p2={s['p2']:3d} "
              f"({s['p1']/max(c,1):.0%})")
    out = {
        "n": n, "p1": p1, "p2": p2, "timeout": timeout, "crash": crashed,
        "both_none": both_none,
        "p1_rate": p1 / max(n, 1), "p2_rate": p2 / max(n, 1),
        "dynamics": dict(dyn.most_common()),
        "per_dynamic": per_dyn,
        "rows": rows,
    }
    if not DATA:
        raise SystemExit("no puzzles found; set BENCH_DATA or place "
                         "training under ../data/training")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    print("saved", OUT, flush=True)


if __name__ == "__main__":
    main()
