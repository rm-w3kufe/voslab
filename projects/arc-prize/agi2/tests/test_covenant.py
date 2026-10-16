#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_covenant.vsm
"""Negative controls for the ViArc-2 covenant harness (deterministic, R10).

    python3 tests/test_covenant.py

Each invariant MUST trip on its violation (fail-loud is the product).
Style: parity.py — plain asserts, no pytest dependency (kernel-safe).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import covenant as C  # noqa: E402

G2 = [[1, 2], [3, 4]]
G3 = [[5, 6, 7], [8, 9, 0], [1, 1, 1]]
G2B = [[9, 9], [9, 9]]


def test_I1_rejects_uncertified_llm():
    v = C.check_attempt_pair(G2, G2B, "llm-certified", "symbolic",
                             loo1=0.33, loo2=None)
    assert not v.passed, "I1 must reject llm-certified with loo < 0.5"
    assert any(x.axiom == "I1_certify_first" for x in v.violations)


def test_I1_accepts_certified_llm():
    v = C.check_attempt_pair(G2, G2B, "llm-certified", "symbolic",
                             loo1=0.5, loo2=None)
    assert v.passed, "I1 must accept llm-certified with loo >= 0.5"


def test_I2_rejects_empty_pair():
    v = C.check_attempt_pair(None, None, "shim", "shim")
    assert not v.passed and any(x.axiom == "I2_two_attempts" for x in v.violations)


def test_I3_rejects_duplicate_family():
    v = C.check_attempt_pair(G2, [[1, 2], [3, 4]], "symbolic", "symbolic")
    assert not v.passed and any(x.axiom == "I3_family_diversity" for x in v.violations)


def test_I3_allows_shim_copies():
    v = C.check_attempt_pair(G2, [[1, 2], [3, 4]], "shim", "shim")
    assert v.passed, "zero-shim is a granted right: identical copies OK"


def test_I4_rejects_ragged_grid():
    v = C.check_attempt_pair([[1, 2], [3]], G2B, "symbolic", "symbolic")
    assert not v.passed and any(x.axiom == "I4_schema_valid" for x in v.violations)


def test_I4_rejects_out_of_range():
    v = C.check_attempt_pair([[1, 22]], G2B, "symbolic", "symbolic")
    assert not v.passed and any(x.axiom == "I4_schema_valid" for x in v.violations)


def test_I7_rejects_escalation_under_pressure():
    # behind schedule: negative slack. Raising K is a CRITICAL flip.
    v = C.check_budget_decision(K=4, loo_max=1, slack_s=-20.0)
    assert not v.passed
    assert any(x.axiom == "I7_A0.1_no_pressure_flip" for x in v.violations)


def test_I7_allows_escalation_under_slack():
    v = C.check_budget_decision(K=4, loo_max=2, slack_s=+60.0)
    assert v.passed, "escalation under positive slack is a granted right"


def test_ceiling_caps():
    v = C.check_budget_decision(K=9, loo_max=1, slack_s=100.0)
    assert not v.passed and any(x.axiom == "ceiling" for x in v.violations)


def test_decide_budget_sheds_under_pressure():
    st = C.RuntimeState()
    st.tasks_total = 1200
    st.tasks_done = 0
    st.t0 = st.t0 - (C.COVENANT["guard_h"] * 3600)  # pretend we're late
    b = C.decide_budget(st)
    assert b["K"] == 0 and b["mode"] == "symbolic-only", \
        "behind schedule => shed LLM load (A0.1 behavior)"


def test_decide_budget_escalates_with_banked_time():
    st = C.RuntimeState()
    # almost done with lots of wall-clock left => huge banked slack
    st.tasks_done = st.tasks_total - 100
    b = C.decide_budget(st)
    assert b["K"] > C.COVENANT["K_default"], "banked time may raise K"
    assert b["K"] <= C.COVENANT["K_max"]


def test_algedonic_deadline_signal():
    st = C.RuntimeState()
    st.t0 = st.t0 - (C.COVENANT["guard_h"] * 3600 + 1)
    sigs = C.algedonic_signals(st)
    assert any(s["signal"] == "deadline_guard_tripped" for s in sigs)


def test_algedonic_starvation_signal():
    st = C.RuntimeState()
    st.tally = {"symbolic": 30, "llm-certified": 0}
    sigs = C.algedonic_signals(st)
    assert any(s["signal"] == "producer_starvation" for s in sigs)


def test_submission_gate_rejects_hole():
    tasks = {"t1": {"attempt_1": G2, "attempt_2": G2B}}
    v = C.check_submission(tasks)
    assert v.passed
    tasks["t2"] = {"attempt_1": None, "attempt_2": None}
    v = C.check_submission(tasks)
    assert not v.passed and any(x.axiom == "I2_two_attempts" for x in v.violations)


def test_attempt2_strategy_opposite_family():
    assert C.choose_attempt2_strategy("symbolic") == "llm"
    assert C.choose_attempt2_strategy("llm-certified") == "symbolic"


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"OK: {len(fns)}/{len(fns)} covenant negative controls green")


if __name__ == "__main__":
    main()
