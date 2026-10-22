# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-checks/vsf_checks/check_runner.py)
"""
tests/test_check_runner.py — Tests for check runner.
"""

import pytest
import os
import tempfile
from pathlib import Path

from vsf_checks.check_runner import (
    run_check,
    run_all_checks,
    get_check_status,
    format_check_report,
)


def test_run_check_success():
    """Test run_check with a successful command."""
    success, output = run_check("echo", ["test output"])
    assert success is True
    assert "test output" in output


def test_run_check_failure():
    """Test run_check with a failing command."""
    success, output = run_check("ls", ["/nonexistent/path"])
    assert success is False


def test_run_check_timeout():
    """Test run_check with a timeout."""
    success, output = run_check("sleep", ["60"])
    assert success is False
    assert "timeout" in output.lower()


def test_run_check_not_found():
    """Test run_check with non-existent check."""
    success, output = run_check("/nonexistent/check")
    assert success is False
    assert "Error" in output


def test_run_all_checks():
    """Test run_all_checks in a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test checks
        for i in range(3):
            check_path = Path(tmpdir) / f"check_{i}"
            check_path.write_text(f"#!/bin/bash\necho 'check {i}'\nexit {0 if i < 2 else 1}")
            os.chmod(check_path, 0o755)
        
        results = run_all_checks(tmpdir)
        assert len(results) == 3
        assert results["check_0"][0] is True
        assert results["check_1"][0] is True
        assert results["check_2"][0] is False


def test_get_check_status():
    """Test get_check_status function."""
    results = {
        "check_a": (True, "output a"),
        "check_b": (False, "output b"),
    }
    
    assert get_check_status("check_a", results) == "PASS"
    assert get_check_status("check_b", results) == "FAIL"
    assert get_check_status("check_c", results) == "NOT_FOUND"


def test_format_check_report():
    """Test format_check_report function."""
    results = {
        "check_pass": (True, ""),
        "check_fail": (False, "error message"),
    }
    
    report = format_check_report(results)
    assert "check_pass" in report
    assert "check_fail" in report
    assert "✓" in report
    assert "✗" in report


def test_run_all_checks_with_pattern():
    """Test run_all_checks with pattern filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test checks
        for name in ["check_a", "check_b", "other_c"]:
            check_path = Path(tmpdir) / name
            check_path.write_text("#!/bin/bash\nexit 0")
            os.chmod(check_path, 0o755)
        
        results = run_all_checks(tmpdir, pattern="check")
        assert len(results) == 2
        assert "check_a" in results
        assert "check_b" in results
        assert "other_c" not in results
