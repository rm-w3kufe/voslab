"""tests/test_invariants.py — Tests for invariant checking."""

import pytest
from vos_kernel.invariants import InvariantChecker, CheckResult


def test_checker_init():
    """InvariantChecker initializes with default checks."""
    checker = InvariantChecker()
    assert "write" in checker._pre_checks
    assert len(checker._pre_checks["write"]) > 0


def test_preconditions_pass():
    """Pre-conditions pass for safe action."""
    checker = InvariantChecker()
    result = checker.check_preconditions(
        action="write",
        file="/tmp/test.txt",
        content="hello world",
        trust=0.8,
        autonomy=0.5,
    )
    assert result.passed is True
    assert len(result.failures) == 0


def test_a0_compliance_fail():
    """A0 compliance fails for prohibited content."""
    checker = InvariantChecker()
    result = checker.check_preconditions(
        action="write",
        content="warfare_instrumentation active",
    )
    assert result.passed is False
    assert any("a0_no_prohibited" in f for f in result.failures)


def test_trust_bounds_fail():
    """Trust bounds fail when autonomy exceeds trust."""
    checker = InvariantChecker()
    result = checker.check_preconditions(
        action="write",
        trust=0.3,
        autonomy=0.8,
    )
    assert result.passed is False
    assert any("trust_bounds" in f for f in result.failures)


def test_postconditions():
    """Post-conditions work similarly to pre-conditions."""
    checker = InvariantChecker()
    result = checker.check_postconditions(
        action="write",
        file="/tmp/test.txt",
    )
    assert result.passed is True  # no post-conditions registered by default
