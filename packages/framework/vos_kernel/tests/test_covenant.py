"""tests/test_covenant.py — Tests for covenant enforcement."""

import pytest
from vos_kernel.covenant import CovenantEnforcer, Verdict, Violation


def test_covenant_enforcer_init():
    """CovenantEnforcer initializes without error."""
    enforcer = CovenantEnforcer()
    assert enforcer._backend in ("vsl-core", "python")


def test_covenant_pass():
    """Covenant passes with adequate trust."""
    enforcer = CovenantEnforcer()
    verdict = enforcer.evaluate(s5_trust=0.8, op_autonomy=0.5)
    assert verdict.passed is True
    assert len(verdict.violations) == 0


def test_covenant_low_trust():
    """Covenant fails with low trust."""
    enforcer = CovenantEnforcer()
    verdict = enforcer.evaluate(s5_trust=0.2, op_autonomy=0.5)
    assert verdict.passed is False
    assert any(v.axiom == "TRUST" for v in verdict.violations)


def test_covenant_autonomy_exceeds_trust():
    """Covenant fails when autonomy exceeds trust."""
    enforcer = CovenantEnforcer()
    verdict = enforcer.evaluate(s5_trust=0.3, op_autonomy=0.8)
    assert verdict.passed is False
    assert any(v.axiom == "A5" for v in verdict.violations)


def test_covenant_pressure():
    """Covenant fails with coercion pressure."""
    enforcer = CovenantEnforcer()
    verdict = enforcer.evaluate(s5_trust=0.8, op_autonomy=0.5, pressure="coercion")
    assert verdict.passed is False
    assert any(v.axiom == "A0.1" for v in verdict.violations)
