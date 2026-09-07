"""tests/test_bridge.py — Tests for validation bridge."""

import pytest
from vsf_validation.bridge import (
    is_available,
    list_validators,
    verify_bindings,
    verify_status,
    verify_migration,
    verify_claim,
    verify_dir_schema,
    verify_primer_closure,
    verify_boot_ontology,
    verify_boot_primer,
    validate_all,
)


class TestAvailability:
    def test_is_available(self):
        result = is_available()
        assert isinstance(result, bool)

    def test_list_validators(self):
        result = list_validators()
        assert isinstance(result, list)
        assert len(result) == 8
        assert "verify_bindings" in result
        assert "verify_status" in result


class TestVerifyBindings:
    def test_nonexistent(self):
        result = verify_bindings("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyStatus:
    def test_nonexistent(self):
        result = verify_status("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyMigration:
    def test_nonexistent(self):
        result = verify_migration("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyClaim:
    def test_list_checks(self):
        """Test listing available checks."""
        result = verify_claim()
        assert isinstance(result, dict)
        # Should return status and checks list
        assert "status" in result or "checks" in result or "error" in result

    def test_invalid_check(self):
        """Test with invalid check ID."""
        result = verify_claim(check_ids=["nonexistent_check"])
        assert isinstance(result, dict)


class TestVerifyDirSchema:
    def test_nonexistent(self):
        result = verify_dir_schema("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyPrimerClosure:
    def test_nonexistent(self):
        result = verify_primer_closure("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyBootOntology:
    def test_nonexistent(self):
        result = verify_boot_ontology("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestVerifyBootPrimer:
    def test_nonexistent(self):
        result = verify_boot_primer("/nonexistent/path.vsm")
        assert isinstance(result, dict)


class TestValidateAll:
    def test_nonexistent(self):
        result = validate_all("/nonexistent/path.vsm")
        assert isinstance(result, dict)
        assert len(result) == 8
