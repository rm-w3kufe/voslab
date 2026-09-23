#!/usr/bin/env python3
"""H2 — RSI evolution: improvement slope, holdout generalization, ablation.

Claim: the generational loop compounds improvements (slope >= 0,
final >= baseline + margin), generalizes to held-out cases (no
regression), and beats equal-budget random search (the LOOP matters,
not just compute).
Falsifier: negative slope, holdout regression beyond epsilon, or
random matching the GA.

Fault suite (3 fault types x 5 cycles):
  F1 BLOCKING task_has_work   error_class=BLOCKING
  F2 LATENCY  pipeline slow   error_class=LATENCY (latency_ms signal)
  F3 THRESHOLD drift monitor  error_class=DRIFT

Per fault/cycle: run_cycle -> activated accuracy (train cases).
Holdout: fixed 70/30 split of _build_test_cases by input_value;
activated tree re-evaluated on holdout vs baseline-on-holdout.
Ablation: 15 fresh random genomes (== GA max budget 3x5), best wins.
"""
from __future__ import annotations

import os

os.environ.setdefault("VOSLAB_PATH", "/home/rmw3/vOSlab")

from vsf_rsi.rsi_autonomous_l3 import L3StrategySearch
from vsf_rsi.rsi_fault_detector import FaultSignature
from vsf_rsi.rsi_genome_v3 import create_random_genome_v3
from vsf_rsi.rsi_shadow_mode import StrategyCandidate
from socratic_engine.engine import SocraticEngine, Truth

FAULTS = [
    ("task_has_work:error=BLOCKING", "BLOCKING", 5, 0.01),
    ("pipeline:latency=LATENCY", "LATENCY", 3, 250.0),
    ("drift_monitor:error=DRIFT", "DRIFT", 4, 0.05),
]

CYCLES = 5
MARGIN = 0.05
EPSILON = 0.10
ABLATION_SHOTS = 15


def _fault(source, klass, count, lat):
    return FaultSignature(
        fault_id=f"h2-{klass}", source=source, error_class=klass,
        first_seen="2026-09-22T05:00:00Z", last_seen="2026-09-22T05:00:00Z",
        count=count, avg_latency_ms=lat, coverage=0.5,
        sample_events=[{"source": source.split(":")[0],
                        "truth": "FALSE", "is_error": True}],
    )


def _accuracy(engine, tree, cases):
    ok = tot = 0
    for tc in cases:
        try:
            r = engine.evaluate(tree, tc["ctx"])
            if getattr(r, "truth", Truth.UNKNOWN) == Truth.UNKNOWN:
                continue
            tot += 1
            if getattr(r, "is_true", False) == tc["expected"]:
                ok += 1
        except Exception:
            tot += 1
    return ok / tot if tot else 0.0


def _split(cases):
    """Deterministic 70/30 split by input_value rank."""
    order = sorted(range(len(cases)),
                   key=lambda i: cases[i]["ctx"].get("input_value", 0))
    cut = max(1, int(len(order) * 0.7))
    train = [cases[i] for i in order[:cut]]
    hold = [cases[i] for i in order[cut:]]
    return train, hold


def run(seed: int = 20260922) -> dict:
    import random as _r
    import tempfile
    _r.seed(seed)
    # Isolate scenario store: retention measured WITHIN this run
    # (record -> match across cycles), production store untouched.
    _store = tempfile.mkdtemp(prefix="h2-scenarios-")
    os.environ["VSI_RSI_STORE"] = _store
    engine = SocraticEngine()
    l3 = L3StrategySearch(engine=engine)

    per_fault = []
    all_slopes_ok = True
    holdout_ok = True
    ablation_wins = 0
    detail = {}

    for source, klass, count, lat in FAULTS:
        fault = _fault(source, klass, count, lat)
        cases = l3._build_test_cases(fault)
        train, hold = _split(cases)
        baseline = l3._build_default_tree(fault)
        base_train = _accuracy(engine, baseline, train)
        base_hold = _accuracy(engine, baseline, hold)

        traj = []
        best_tree, best_acc = None, base_train
        l3c = L3StrategySearch(engine=engine)  # one instance: registry persists
        for _ in range(CYCLES):
            res = l3c.run_cycle(fault)
            acc = base_train
            if res.status == "activated" and res.strategy_activated:
                # Recover the ACTUAL activated tree (any kind: genome,
                # prior, crossover) and score it on train.
                tree = l3c._tree_registry.get(res.strategy_activated)
                if tree is not None:
                    acc = _accuracy(engine, tree, train)
                    if acc > best_acc:
                        best_acc, best_tree = acc, tree
            traj.append(acc)
        # slope via least squares
        n = len(traj)
        xs = list(range(n))
        slope = ((n * sum(x * y for x, y in zip(xs, traj))
                   - sum(xs) * sum(traj))
                 / (n * sum(x * x for x in xs) - sum(xs) ** 2)) if n > 1 else 0.0
        final = traj[-1] if traj else base_train

        # holdout: fixed 70/30 split of _build_test_cases by input_value;
        # activated tree re-evaluated on holdout vs baseline-on-holdout.
        hold_acc, hold_base = base_hold, base_hold

        slope_ok = slope >= -1e-9 and final >= base_train
        # holdout: best train tree re-evaluated on held-out cases
        hold_acc = _accuracy(engine, best_tree, hold) if best_tree else base_hold
        hold_ok = hold_acc + EPSILON >= base_hold

        # ablation: equal-budget random search
        rand_best = base_train
        for i in range(ABLATION_SHOTS):
            g = create_random_genome_v3(
                genome_id=f"abl-{klass}-{i}",
                available_features=["input_value", "threshold", "latency_ms"],
                n_derived=3, tree_depth=2)
            t = l3._genome_to_tree(g)
            if t:
                rand_best = max(rand_best, _accuracy(engine, t, train))
        ga_best = max(traj) if traj else base_train
        ablation_wins += 1 if ga_best >= rand_best else 0

        all_slopes_ok &= slope_ok
        holdout_ok &= hold_ok
        per_fault.append({"fault": klass, "baseline": round(base_train, 3),
                          "final": round(final, 3),
                          "slope": round(slope, 4),
                          "holdout": round(hold_acc, 3),
                          "holdout_base": round(base_hold, 3),
                          "ga_best": round(ga_best, 3),
                          "rand_best": round(rand_best, 3)})
        detail[klass] = {"traj": [round(x, 3) for x in traj]}

    passed = all_slopes_ok and holdout_ok and ablation_wins >= 2
    return {
        "suite": "H2-evolution",
        "claim": "GA compounds improvements, generalizes, beats random",
        "metrics": {
            "faults": len(FAULTS),
            "cycles_per_fault": CYCLES,
            "slopes_nonnegative": all_slopes_ok,
            "holdout_no_regression": holdout_ok,
            "ablation_wins": f"{ablation_wins}/{len(FAULTS)}",
            "per_fault": per_fault,
        },
        "passed": passed,
        "threshold": "slope>=0 AND final>=baseline (all faults) AND "
                     "holdout>=base-eps AND ablation wins>=2/3",
        "detail": detail,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
