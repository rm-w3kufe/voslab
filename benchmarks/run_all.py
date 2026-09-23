#!/usr/bin/env python3
"""run_all.py — execute the full vOS capability battery and record baseline.

Suites (each states claim + falsifiable threshold up front):
  H5 determinism   evaluation is pure function of (tree, context)
  H1 honesty       certified outputs never wrong; uncertainty abstains
  H2 evolution     GA compounds, generalizes, beats random
  H3 cost          governance overhead bounded (KNOWN RED in v1)
  H4 chaos         failures degrade gracefully, never crash or lie
  ARC lane         harness valid, zero-baseline floor recorded

Usage: python3 benchmarks/run_all.py [--tag baseline_v1] [--only H1,H5]
Exit code 0 iff every suite passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness

SUITES = [
    ("H5-determinism", "h5_determinism"),
    ("H1-honesty", "h1_honesty"),
    ("H2-evolution", "h2_evolution"),
    ("H3-cost", "h3_cost"),
    ("H4-chaos", "h4_chaos"),
    ("ARC-lane", "arc_lane"),
]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline_v1")
    ap.add_argument("--only", default="")
    ap.add_argument("--seed", type=int, default=harness.DEFAULT_SEED)
    args = ap.parse_args(argv)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = []
    for name, mod in SUITES:
        if only and name not in only and mod not in only:
            continue
        print(f"--- {name} ---", flush=True)
        m = __import__(mod)
        r = harness.run_suite(name, m.run, seed=args.seed)
        results.append(r)
        print(f"    {'PASS' if r['passed'] else 'FAIL'} "
              f"({r['duration_s']}s)", flush=True)

    path = harness.write_results(results, tag=args.tag)
    print()
    print(harness.summarize(results))
    print(f"\nresults -> {path}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
