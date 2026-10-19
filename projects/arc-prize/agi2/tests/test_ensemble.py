#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_covenant.vsm
"""Regression: ensemble_decide program path (v12 lever) — I3/I1 safety.

    python3 tests/test_ensemble.py

The RSI-M2 branch may only ship when (a) the symbolic side is UNVERIFIED,
(b) there is positive deadline slack (A0.1), and (c) attempt_2 is a
DISTINCT candidate — never a copy of attempt_1 (I3) and never a blind
fallback. Certify-first for the toolbox (I1) is enforced by propose_tools
(mocked here; mechanics covered by test_rsi_tools).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import llm_harness as LH  # noqa: E402
import covenant as C  # noqa: E402

TRAINS = [([[1, 2], [3, 4]], [[1, 2], [3, 4]]),
          ([[5, 0], [0, 5]], [[5, 0], [0, 5]])]
TEST = [[9, 8], [7, 6]]

PROG_GRID = [[1, 2], [3, 4]]
OTHER_GRID = [[9, 9], [9, 9]]
LLM_GRID = [[7, 7], [7, 7]]


def _k(g):
    return tuple(tuple(r) for r in g)


def _sym(a1, a2, loo=0.0):
    return {"a1": a1, "a2": a2, "loo": loo}


def _program_calls(monkeypatch, prog_grid):
    calls = {"n": 0}

    def fake_program(tr, te):
        calls["n"] += 1
        if prog_grid is None:
            return None
        return {"grid": prog_grid, "key": _k(prog_grid),
                "loo": 1.0, "code": "def solve(trains, test):\n    return test\n"}

    monkeypatch.setattr(LH, "propose_program", fake_program)
    return calls


def _run(monkeypatch, sym, prog_grid, llm=None, budget=None):
    _program_calls(monkeypatch, prog_grid)
    monkeypatch.setattr(LH, "propose", lambda tr, te: llm)
    monkeypatch.setattr(LH, "_remember_program", lambda p, tr: True)
    return LH.ensemble_decide(TRAINS, TEST, lambda tr, te: sym,
                              budget=budget or {"slack_s": 100.0})


def test_program_leads_with_distinct_a2(monkeypatch):
    out = _run(monkeypatch, _sym(OTHER_GRID, None), PROG_GRID)
    assert out["source"] == "rsi-tool"
    assert _k(out["a1"]) == _k(PROG_GRID)
    assert _k(out["a2"]) == _k(OTHER_GRID)
    assert out["llm_meta"]["program_loo"] == 1.0


def test_program_a2_falls_back_to_llm_when_sym_collides(monkeypatch):
    # sym.a1 equals the program output and sym.a2 is None → the distinct
    # second opinion must come from the LLM grid, never a copy (I3).
    llm = {"grid": LLM_GRID, "key": _k(LLM_GRID), "agreement": 0.5,
           "n_unique": 2, "loo_llm": None}
    out = _run(monkeypatch, _sym(PROG_GRID, None), PROG_GRID, llm=llm)
    assert out["source"] == "rsi-tool"
    assert _k(out["a2"]) == _k(LLM_GRID)
    assert _k(out["a1"]) != _k(out["a2"])
    verdict = C.check_attempt_pair(out["a1"], out["a2"], "rsi-tool", "rsi-tool")
    assert verdict.passed, verdict.violations


def test_program_never_ships_without_distinct_a2(monkeypatch):
    # every candidate collides with the program → fall through (I3-safe)
    llm = {"grid": PROG_GRID, "key": _k(PROG_GRID), "agreement": 0.5,
           "n_unique": 1, "loo_llm": None}
    out = _run(monkeypatch, _sym(PROG_GRID, None), PROG_GRID, llm=llm)
    assert out["source"] != "rsi-tool"


def test_program_not_taken_under_no_slack(monkeypatch):
    # A0.1: no program spend without positive slack
    calls = _program_calls(monkeypatch, PROG_GRID)
    monkeypatch.setattr(LH, "propose", lambda tr, te: None)
    monkeypatch.setattr(LH, "_remember_program", lambda p, tr: True)
    out = LH.ensemble_decide(TRAINS, TEST, lambda tr, te: _sym(OTHER_GRID, None),
                             budget={"slack_s": 0.0})
    assert calls["n"] == 0
    assert out["source"] != "rsi-tool"


def test_program_not_taken_when_symbolic_verified(monkeypatch):
    # verified symbolic already leads (certified > fluent > program guess)
    calls = _program_calls(monkeypatch, PROG_GRID)
    monkeypatch.setattr(LH, "propose", lambda tr, te: None)
    monkeypatch.setattr(LH, "_remember_program", lambda p, tr: True)
    out = LH.ensemble_decide(TRAINS, TEST,
                             lambda tr, te: _sym(OTHER_GRID, [[0, 0], [0, 0]], loo=0.75),
                             budget={"slack_s": 100.0})
    assert calls["n"] == 0
    assert out["source"] == "symbolic"
    assert _k(out["a1"]) == _k(OTHER_GRID)


if __name__ == "__main__":  # pragma: no cover
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
