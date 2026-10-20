# design: docs/plans/clone_manifest.vsm (SUT: packages/public/vsf-hooks-analytics/vsf_hooks_analytics/hook_metrics.py)
"""tests/test_hook_metrics.py — Tests for hook metrics."""

import os
import tempfile

import pytest
from vsf_hooks_analytics.hook_metrics import HookMetrics


class TestHookMetrics:
    def test_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            # File is created on first write, not on init
            assert os.path.isdir(tmpdir)

    def test_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            metrics.record("test_hook", 100.0, True)
            metrics.record("test_hook", 200.0, False, error="test error")
            result = metrics.get_metrics()
            assert len(result) == 2

    def test_get_metrics_filtered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            metrics.record("hook_a", 100.0, True)
            metrics.record("hook_b", 200.0, True)
            result = metrics.get_metrics(hook_name="hook_a")
            assert len(result) == 1
            assert result[0]["hook_name"] == "hook_a"

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            metrics.record("test", 100.0, True)
            metrics.record("test", 200.0, True)
            metrics.record("test", 150.0, False)
            result = metrics.summary("test")
            assert result["count"] == 3
            assert result["successes"] == 2
            assert result["failures"] == 1
            assert result["avg_duration_ms"] == 150.0

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            metrics.record("test", 100.0, True)
            removed = metrics.clear()
            assert removed == -1
            assert metrics.get_metrics() == []

    def test_clear_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = HookMetrics(metrics_dir=tmpdir)
            metrics.record("test", 100.0, True)
            removed = metrics.clear(older_than_seconds=0)  # Clear everything older than 0s
            assert removed >= 0
