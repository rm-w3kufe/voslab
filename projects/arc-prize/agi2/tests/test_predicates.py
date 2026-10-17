#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_vsm_harness.vsm
"""Negative controls for socratic-lite predicates (deterministic, R10).

    python3 tests/test_predicates.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import predicates as P  # noqa: E402

CTX = {"loo_frac": 1.0, "agreement": 0.6, "prior": 0.1, "dynamic": "tiling"}
LOW = {"loo_frac": 0.0, "agreement": 0.1, "prior": 0.0, "dynamic": "x"}


def test_leaf_loo_ge_half():
    assert P.evaluate({"leaf": "loo_ge_half"}, CTX) is True
    assert P.evaluate({"leaf": "loo_ge_half"}, LOW) is False


def test_unknown_leaf_false():
    assert P.evaluate({"leaf": "no_such_pred"}, CTX) is False


def test_and_or_not():
    assert P.evaluate({"and": [{"leaf": "loo_ge_half"},
                               {"leaf": "agreement_strong"}]}, CTX) is True
    assert P.evaluate({"and": [{"leaf": "loo_ge_half"},
                               {"leaf": "prior_known"}]}, LOW) is False
    assert P.evaluate({"or": [{"leaf": "prior_known"},
                              {"leaf": "agreement_strong"}]}, CTX) is True
    assert P.evaluate({"not": {"leaf": "loo_ge_half"}}, LOW) is True


def test_score_linear_parity():
    # exact M1 formula: 0.5*1.0 + 0.3*0.6 + 0.2*0.1 = 0.70
    assert P.score(CTX) == 0.70
    assert P.score(LOW) == 0.03  # 0.5*0 + 0.3*0.1 + 0.2*0


def test_certified_decision():
    assert P.certified(CTX) is True
    assert P.certified(LOW) is False


def test_scoring_terms_weights_sum():
    assert abs(sum(t["weight"] for t in P.SCORING_TERMS) - 1.0) < 1e-9


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"OK: {len(fns)}/{len(fns)} predicate controls green")


if __name__ == "__main__":
    main()
