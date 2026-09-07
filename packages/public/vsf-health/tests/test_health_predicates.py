"""tests/test_health_predicates.py — Tests for health predicates."""

import os
import sqlite3
import tempfile
import time

import pytest
from vsf_health.health_predicates import (
    disk_ok,
    disk_usage,
    alerts_db_ok,
    alerts_db_stats,
    is_high_error_rate,
    compute_error_rate,
    is_consecutive_failures,
    count_consecutive_failures,
    is_inactive_instrument,
    inactive_duration,
    is_temporal_correlation,
    temporal_density,
)


class TestDiskOk:
    def test_root(self):
        result = disk_ok("/")
        assert isinstance(result, bool)

    def test_with_threshold(self):
        result = disk_ok("/", min_free_gb=0.001)
        assert isinstance(result, bool)


class TestDiskUsage:
    def test_root(self):
        result = disk_usage("/")
        assert "total_gb" in result or "error" in result

    def test_nonexistent(self):
        result = disk_usage("/nonexistent")
        assert "error" in result


class TestAlertsDbOk:
    def test_nonexistent(self):
        assert alerts_db_ok("/nonexistent/path.db") is False

    def test_with_temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            assert alerts_db_ok(db_path) is True
        finally:
            os.unlink(db_path)


class TestAlertsDbStats:
    def test_nonexistent(self):
        result = alerts_db_stats("/nonexistent/path.db")
        assert result["exists"] is False

    def test_with_temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY, severity TEXT, timestamp TEXT)")
            conn.execute("INSERT INTO alerts (severity, timestamp) VALUES ('high', datetime('now'))")
            conn.execute("INSERT INTO alerts (severity, timestamp) VALUES ('low', datetime('now'))")
            conn.commit()
            conn.close()
            result = alerts_db_stats(db_path)
            assert result["exists"] is True
            assert result["total"] == 2
        finally:
            os.unlink(db_path)


class TestHighErrorRate:
    def test_high(self):
        assert is_high_error_rate(5, 10) is True

    def test_low(self):
        assert is_high_error_rate(1, 10) is False

    def test_zero_total(self):
        assert is_high_error_rate(0, 0) is False


class TestComputeErrorRate:
    def test_normal(self):
        assert compute_error_rate(5, 10) == 0.5

    def test_zero_total(self):
        assert compute_error_rate(0, 0) == 0.0


class TestConsecutiveFailures:
    def test_many_failures(self):
        results = [False, False, False, False, True]
        assert is_consecutive_failures(results, max_consecutive=3) is True

    def test_few_failures(self):
        results = [False, False, True, False]
        assert is_consecutive_failures(results, max_consecutive=3) is False

    def test_count(self):
        results = [False, False, False, True, False, False]
        assert count_consecutive_failures(results) == 3


class TestInactiveInstrument:
    def test_inactive(self):
        now = time.time()
        assert is_inactive_instrument(now - 7200, now) is True

    def test_active(self):
        now = time.time()
        assert is_inactive_instrument(now - 60, now) is False


class TestInactiveDuration:
    def test_duration(self):
        now = time.time()
        assert inactive_duration(now - 3600, now) == 3600


class TestTemporalCorrelation:
    def test_correlated(self):
        now = time.time()
        timestamps = [now + i * 10 for i in range(5)]  # 5 events in 40s
        assert is_temporal_correlation(timestamps, window_seconds=60, min_events=3) is True

    def test_not_correlated(self):
        timestamps = [i * 100 for i in range(5)]  # 5 events spread over 400s
        assert is_temporal_correlation(timestamps, window_seconds=60, min_events=3) is False

    def test_too_few_events(self):
        timestamps = [1.0, 2.0]
        assert is_temporal_correlation(timestamps, window_seconds=60, min_events=3) is False


class TestTemporalDensity:
    def test_density(self):
        timestamps = [1.0, 2.0, 3.0, 4.0, 5.0]
        # 5 events over 4 seconds = 1.25 events per second
        result = temporal_density(timestamps, window_seconds=1.0)
        assert result == 1.25

    def test_empty(self):
        assert temporal_density([], window_seconds=1.0) == 0.0
