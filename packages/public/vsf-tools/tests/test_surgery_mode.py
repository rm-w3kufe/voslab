# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-tools/vsf_tools/surgery_mode.py)
"""tests/test_surgery_mode.py — Tests for surgery mode."""

import os
import tempfile
import pytest
from pathlib import Path
from vsf_tools.surgery_mode import SurgeryMode, enable, disable, status, is_active


class TestSurgeryMode:
    def test_enable_disable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            
            # Enable
            result = sm.enable()
            assert result["status"] == "enabled"
            assert sm.is_active() is True
            
            # Disable
            result = sm.disable()
            assert result["status"] == "disabled"
            assert sm.is_active() is False
    
    def test_status_inactive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            result = sm.status()
            assert result["status"] == "inactive"
    
    def test_status_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            sm.enable()
            result = sm.status()
            assert result["status"] == "active"
            assert "age_min" in result
    
    def test_check_auto_disable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            sm.safety_timeout_min = -1  # Force timeout
            
            sm.enable()
            result = sm.check()
            assert result["status"] == "auto_disabled"
            assert sm.is_active() is False
    
    def test_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            sm.enable()
            sm.disable()
            
            history = sm.history()
            assert len(history) == 2
            assert history[0]["action"] == "enabled"
            assert history[1]["action"] == "disabled"
    
    def test_double_disable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SurgeryMode(tmpdir)
            result = sm.disable()
            assert result["status"] == "already_off"


class TestConvenienceFunctions:
    def test_enable_disable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = enable(tmpdir)
            assert result["status"] == "enabled"
            
            result = disable(tmpdir)
            assert result["status"] == "disabled"
    
    def test_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = status(tmpdir)
            assert "status" in result
    
    def test_is_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_active(tmpdir) is False
            enable(tmpdir)
            assert is_active(tmpdir) is True
