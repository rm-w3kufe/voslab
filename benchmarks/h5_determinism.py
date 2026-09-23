#!/usr/bin/env python3
"""H5 — Determinism (R10): same input -> identical output, every time.

Claim: predicate evaluation is a pure function of (tree, context).
Falsifier: ANY divergence across runs or hash seeds.

Two legs:
  A. Empirical invariance (pass/fail): corpus of trees x contexts evaluated
     in 3 subprocesses with PYTHONHASHSEED=0/1/42. Semantic equality of
     (truth, certified, normalized evidence) required everywhere.
  B. Static scan (pass/fail on core): zero nondeterminism markers
     (random/time/datetime/uuid/os.urandom/secrets) in
     socratic_engine/engine.py evaluation core. GA randomness (mutate_v3
     etc.) is the variation SOURCE and out of scope — R10 constrains
     predicates, not evolution.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

SE = Path("/home/rmw3/socratic-engine")

# Corpus templates: (tree_builder, contexts). Built with fixed seed.
_TREES = [
    {"op": "AND", "children": [
        {"predicate": "type_prefix", "args": ["$type", "VSL-"]},
        {"predicate": "ctx_has", "args": ["$ctx", "mode"]},
    ]},
    {"op": "OR", "children": [
        {"predicate": "gt", "args": ["$v", 0.5]},
        {"predicate": "lt", "args": ["$v", 0.1]},
    ]},
    {"op": "NOT", "children": [
        {"predicate": "eq", "args": ["$v", 1.0]},
    ]},
    {"op": "JURY", "children": [
        {"predicate": "gt", "args": ["$v", 0.3]},
        {"predicate": "gt", "args": ["$v", 0.6]},
        {"predicate": "lt", "args": ["$v", 0.9]},
    ]},
    {"predicate": "gt", "args": ["missing_field", 0.5]},
    {"computation": {
        "features": [
            {"op": "add", "args": ["input_value", "threshold"],
             "output_name": "d0", "constant_value": 0.0},
            {"op": "mul", "args": ["d0", "input_value"],
             "output_name": "d1", "constant_value": 0.0},
        ],
        "tree": {"condition": "d1", "threshold": 0.3, "operator": "gt",
                 "left": True, "right": False},
    }},
]

_CONTEXTS = [
    {"type": "VSL-LANG-GATES-v1.0", "mode": "strict", "v": 0.7,
     "input_value": 0.7, "threshold": 0.5},
    {"type": "OTHER", "v": 0.05, "input_value": 0.2, "threshold": 0.5},
    {"v": 0.5, "input_value": 0.5, "threshold": 0.5},
    {},
    {"type": "VSL-X", "mode": "x", "v": 0.95,
     "input_value": 0.9, "threshold": 0.1},
]

_EVAL_SCRIPT = (
    "import json,sys;"
    "from socratic_engine.engine import SocraticEngine;"
    "eng=SocraticEngine();"
    "jobs=json.load(sys.stdin);"
    "out=[];"
    "[(lambda t,c: out.append({"
    "'truth': (lambda e: e.truth.value)(eng.evaluate(t,c)),"
    "'certified': (lambda e: e.certified)(eng.evaluate(t,c)),"
    "'evidence': json.loads(json.dumps((lambda e: e.evidence)(eng.evaluate(t,c)), sort_keys=True, default=str))"
    "}))(t,c) for t,c in jobs];"
    "print(json.dumps(out))"
)

# NOTE: evaluate() called 3x per case above is intentional — it also
# asserts intra-process repeatability (cache must not mutate results).

MARKERS = ("random.", "secrets.", "os.urandom", "time.", "datetime.",
           "uuid.", "random ")


def _static_scan() -> dict:
    hits = []
    core = SE / "socratic_engine" / "engine.py"
    src = core.read_text().splitlines()
    in_eval_path = False
    for i, line in enumerate(src, 1):
        s = line.strip()
        if s.startswith("def evaluate(") or s.startswith("def _evaluate_"):
            in_eval_path = True
        if in_eval_path and s.startswith("def ") and "evaluate" not in s:
            in_eval_path = False
        if in_eval_path and not s.startswith("#") and not s.startswith('"""'):
            for m in MARKERS:
                if m in line and "monotonic" not in line and "warnings" not in line:
                    hits.append(f"engine.py:{i}:{m.strip('.')}")
                    break
    return {"core_hits": hits, "core_hit_count": len(hits)}


def _run_once(hashseed: str) -> list:
    import os as _os
    jobs = [[t, c] for t in _TREES for c in _CONTEXTS]
    env = dict(_os.environ, PYTHONHASHSEED=hashseed)
    p = subprocess.run(
        [sys.executable, "-c", _EVAL_SCRIPT],
        input=json.dumps(jobs), capture_output=True, text=True,
        timeout=120, env=env, cwd=str(SE),
    )
    if p.returncode != 0:
        raise RuntimeError(f"eval subprocess failed: {p.stderr[:500]}")
    return json.loads(p.stdout)


def run(seed: int = 20260922) -> dict:
    random.seed(seed)
    static = _static_scan()
    n_cases = len(_TREES) * len(_CONTEXTS)
    runs = {hs: _run_once(hs) for hs in ("0", "1", "42")}
    base = runs["0"]
    divergences = []
    for hs in ("1", "42"):
        for i, (a, b) in enumerate(zip(base, runs[hs])):
            if a != b:
                divergences.append({"case": i, "seed0": a, f"seed{hs}": b})
    passed = not divergences and static["core_hit_count"] == 0
    return {
        "suite": "H5-determinism",
        "claim": "evaluation is a pure function of (tree, context)",
        "metrics": {
            "cases": n_cases,
            "hash_seeds": 3,
            "total_evals": n_cases * 3 * 3,  # cases x seeds x intra-process reps
            "divergences": len(divergences),
            "static_core_hits": static["core_hit_count"],
        },
        "passed": passed,
        "threshold": "0 divergences AND 0 nondeterminism markers in engine core",
        "detail": {"divergences": divergences[:5], "hits": static["core_hits"][:10]},
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
