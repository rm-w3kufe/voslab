# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-checks/vsf_checks/shell_check_bridge.py)
"""
tests/test_shell_check_bridge.py — Tests for shell check bridge.
"""

import pytest
import tempfile
from pathlib import Path

from vsf_checks.shell_check_bridge import ShellCheckBridge


def test_shell_check_bridge_init():
    """Test ShellCheckBridge initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge = ShellCheckBridge(tmpdir)
        assert bridge.checks_dir == Path(tmpdir)


def test_list_checks_empty():
    """Test list_checks with empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge = ShellCheckBridge(tmpdir)
        result = bridge.list_checks()
        assert result == []


def test_list_checks():
    """Test list_checks with files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test check files
        for i in range(3):
            check_path = Path(tmpdir) / f"check_{i}"
            check_path.write_text("#!/bin/bash\nexit 0")
            check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        result = bridge.list_checks()
        
        assert len(result) == 3
        assert "check_0" in result
        assert "check_1" in result
        assert "check_2" in result


def test_run_check_success():
    """Test run_check with successful check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create successful check
        check_path = Path(tmpdir) / "success_check"
        check_path.write_text("#!/bin/bash\necho 'success'\nexit 0")
        check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        success, output = bridge.run_check("success_check")
        
        assert success is True
        assert "success" in output


def test_run_check_failure():
    """Test run_check with failing check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create failing check
        check_path = Path(tmpdir) / "fail_check"
        check_path.write_text("#!/bin/bash\necho 'error'\nexit 1")
        check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        success, output = bridge.run_check("fail_check")
        
        assert success is False
        assert "error" in output


def test_run_check_not_found():
    """Test run_check with non-existent check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge = ShellCheckBridge(tmpdir)
        success, output = bridge.run_check("nonexistent")
        
        assert success is False
        assert "no encontrado" in output


def test_run_all_checks():
    """Test run_all_checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test checks
        for i in range(3):
            check_path = Path(tmpdir) / f"check_{i}"
            check_path.write_text(f"#!/bin/bash\necho 'check {i}'\nexit {0 if i < 2 else 1}")
            check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        results = bridge.run_all_checks()
        
        assert len(results) == 3
        assert results["check_0"][0] is True
        assert results["check_1"][0] is True
        assert results["check_2"][0] is False


def test_get_check_categories():
    """Test get_check_categories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test checks with categories
        for name in ["boot-check", "boot-other", "vsl-check", "other-check"]:
            check_path = Path(tmpdir) / name
            check_path.write_text("#!/bin/bash\nexit 0")
            check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        categories = bridge.get_check_categories()
        
        assert "boot" in categories
        assert "vsl" in categories
        assert "other" in categories
        assert len(categories["boot"]) == 2


def test_run_checks_by_category():
    """Test run_checks_by_category."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test checks
        for name in ["boot-check", "boot-other", "vsl-check"]:
            check_path = Path(tmpdir) / name
            check_path.write_text("#!/bin/bash\nexit 0")
            check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        results = bridge.run_checks_by_category("boot")
        
        assert len(results) == 2
        assert "boot-check" in results
        assert "boot-other" in results


def test_get_check_info():
    """Test get_check_info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test check
        check_path = Path(tmpdir) / "test-check"
        check_path.write_text("#!/bin/bash\nexit 0")
        check_path.chmod(0o755)
        
        bridge = ShellCheckBridge(tmpdir)
        info = bridge.get_check_info("test-check")
        
        assert info["name"] == "test-check"
        assert info["category"] == "test"
        assert "path" in info
        assert "size" in info


def test_get_check_info_not_found():
    """Test get_check_info with non-existent check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge = ShellCheckBridge(tmpdir)
        info = bridge.get_check_info("nonexistent")
        
        assert "error" in info
