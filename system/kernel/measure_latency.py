#!/usr/bin/env python3
"""measure_latency.py — F2.1: Measure eval latency baseline.

Runs 100 evaluations with diverse tree shapes, reports distribution.
Run periodically to detect regressions.

Usage:
    python3 system/kernel/measure_latency.py
    python3 system/kernel/measure_latency.py --iterations 200
"""
import sys
import time
import statistics
import os
from pathlib import Path

# Ensure kernel is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("VOSLAB_PATH", str(Path(__file__).resolve().parent.parent.parent))

import rsi_cycle  # noqa: E402


def measure(iterations: int = 100) -> dict:
    cycle = rsi_cycle.RSICycle()
    cycle._feedback_interval = 999999  # disable feedback during measurement

    trees = [
        {"predicate": "task_has_work", "kwargs": {}},
        {"predicate": "state_consistent", "kwargs": {}},
        {"op": "AND", "children": [
            {"predicate": "state_consistent", "kwargs": {}},
            {"predicate": "naming_conforms", "kwargs": {}},
        ]},
        {"op": "OR", "children": [
            {"predicate": "task_has_work", "kwargs": {}},
            {"predicate": "state_consistent", "kwargs": {}},
        ]},
    ]

    # Warm up (3 evals to stabilize caches)
    for i in range(3):
        cycle.evaluate(trees[i % len(trees)], {"warmup": True})

    latencies = []
    for i in range(iterations):
        tree = trees[i % len(trees)]
        start = time.perf_counter()
        cycle.evaluate(tree, {"iteration": i})
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    result = {
        "n": n,
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
        "avg_ms": round(statistics.mean(latencies), 1),
        "stdev_ms": round(statistics.stdev(latencies), 1),
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(sorted_lat[int(n * 0.95)], 1),
        "p99_ms": round(sorted_lat[int(n * 0.99)], 1),
    }

    # Distribution buckets
    buckets = {"<30": 0, "30-50": 0, "50-100": 0, "100-200": 0, "200-500": 0, ">500": 0}
    for l in latencies:
        if l < 30: buckets["<30"] += 1
        elif l < 50: buckets["30-50"] += 1
        elif l < 100: buckets["50-100"] += 1
        elif l < 200: buckets["100-200"] += 1
        elif l < 500: buckets["200-500"] += 1
        else: buckets[">500"] += 1
    result["distribution"] = buckets

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Measure eval latency baseline")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    result = measure(args.iterations)

    print(f"=== Eval Latency Baseline (F2.1) ===")
    print(f"N={result['n']}")
    print(f"min={result['min_ms']}ms  max={result['max_ms']}ms  avg={result['avg_ms']}ms  stdev={result['stdev_ms']}ms")
    print(f"p50={result['p50_ms']}ms  p95={result['p95_ms']}ms  p99={result['p99_ms']}ms")
    print()
    print("Distribution:")
    for bucket, count in result["distribution"].items():
        bar = "#" * count
        print(f"  {bucket:>8}: {count:3d} {bar}")
    print()
    print(f"Suggested alerting thresholds (data-driven):")
    print(f'  latency_spike_ms: {result["p99_ms"] * 3:.0f}ms  (3x p99)')


if __name__ == "__main__":
    main()
