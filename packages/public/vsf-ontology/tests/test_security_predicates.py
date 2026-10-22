# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-ontology/vsf_ontology/security_predicates.py)
"""tests/test_security_predicates.py — Tests for security predicates."""

import pytest
from vsf_ontology.security_predicates import (
    ctx_gt,
    procedure_match_context,
    procedure_match_instrument,
    const_true,
    has_pattern,
    purpose_in_forbidden_set,
    resource_coercion_detected,
    has_approval,
)


class TestCtxGt:
    def test_numeric(self):
        assert ctx_gt(10, 5) is True

    def test_numeric_reverse(self):
        assert ctx_gt(5, 10) is False

    def test_string(self):
        assert ctx_gt("b", "a") is True

    def test_mixed(self):
        assert ctx_gt("10", 5) is True


class TestProcedureMatchContext:
    def test_equal(self):
        assert procedure_match_context("a", "a") is True

    def test_not_equal(self):
        assert procedure_match_context("a", "b") is False


class TestProcedureMatchInstrument:
    def test_equal(self):
        assert procedure_match_instrument("a", "a") is True

    def test_not_equal(self):
        assert procedure_match_instrument("a", "b") is False


class TestConstTrue:
    def test_true(self):
        assert const_true() is True


class TestHasPattern:
    def test_match(self):
        assert has_pattern({"cmd": "rm -rf /"}, r"rm -rf") is True

    def test_no_match(self):
        assert has_pattern({"cmd": "ls -la"}, r"rm -rf") is False

    def test_invalid_regex(self):
        assert has_pattern({"cmd": "test"}, r"[invalid") is False


class TestPurposeInForbiddenSet:
    def test_forbidden(self):
        assert purpose_in_forbidden_set({"purpose": "disable safety"}) is True

    def test_safe(self):
        assert purpose_in_forbidden_set({"purpose": "run tests"}) is False

    def test_bypass(self):
        assert purpose_in_forbidden_set({"action": "bypass covenant"}) is True


class TestResourceCoercionDetected:
    def test_destructive(self):
        assert resource_coercion_detected({"command": "rm -rf /"}) is True

    def test_safe(self):
        assert resource_coercion_detected({"command": "ls -la"}) is False

    def test_mkfs(self):
        assert resource_coercion_detected({"command": "mkfs.ext4 /dev/sda1"}) is True


class TestHasApproval:
    def test_approved(self):
        assert has_approval({"content": "Approved by: rmw3"}) is True

    def test_ratified(self):
        assert has_approval({"content": "This document is RATIFIED"}) is True

    def test_no_approval(self):
        assert has_approval({"content": "Just a regular document"}) is False

    def test_empty(self):
        assert has_approval({}) is False
