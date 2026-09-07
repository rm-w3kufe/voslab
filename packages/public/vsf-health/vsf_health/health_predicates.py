"""health_predicates.py — System health monitoring predicates.

Ported from child/scripts/vsl/classifier/vsf_predicates.py
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════
# DISK HEALTH
# ═══════════════════════════════════════════════════════════════════════

def disk_ok(
    path: str = "/",
    min_free_gb: float = 1.0,
) -> bool:
    """True if disk has sufficient free space."""
    try:
        stat = os.statvfs(path)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        return free_gb >= min_free_gb
    except (OSError, AttributeError):
        return False


def disk_usage(path: str = "/") -> Dict[str, Any]:
    """Get disk usage statistics."""
    try:
        stat = os.statvfs(path)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        used_gb = total_gb - free_gb
        return {
            "total_gb": round(total_gb, 2),
            "free_gb": round(free_gb, 2),
            "used_gb": round(used_gb, 2),
            "percent_used": round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0,
        }
    except (OSError, AttributeError):
        return {"error": "cannot stat filesystem"}


# ═══════════════════════════════════════════════════════════════════════
# ALERTS DATABASE
# ═══════════════════════════════════════════════════════════════════════

def alerts_db_ok(db_path: str) -> bool:
    """True if alerts database exists and is queryable."""
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except (sqlite3.Error, OSError):
        return False


def alerts_db_stats(db_path: str) -> Dict[str, Any]:
    """Get alerts database statistics."""
    if not os.path.exists(db_path):
        return {"exists": False}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        
        # Count total alerts
        cursor.execute("SELECT COUNT(*) FROM alerts")
        total = cursor.fetchone()[0]
        
        # Count by severity
        cursor.execute("SELECT severity, COUNT(*) FROM alerts GROUP BY severity")
        by_severity = dict(cursor.fetchall())
        
        # Count recent (last 24h)
        cursor.execute("""
            SELECT COUNT(*) FROM alerts 
            WHERE timestamp > datetime('now', '-1 day')
        """)
        recent = cursor.fetchone()[0]
        
        conn.close()
        return {
            "exists": True,
            "total": total,
            "by_severity": by_severity,
            "recent_24h": recent,
        }
    except (sqlite3.Error, OSError) as e:
        return {"exists": True, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# ERROR RATE MONITORING
# ═══════════════════════════════════════════════════════════════════════

def is_high_error_rate(
    error_count: int | None,
    total_count: int | None,
    threshold: float = 0.1,
) -> bool:
    """True if error rate exceeds threshold (default 10%)."""
    if error_count is None or total_count is None:
        return False
    if total_count == 0:
        return False
    return (error_count / total_count) > threshold


def compute_error_rate(error_count: int | None, total_count: int | None) -> float:
    """Compute error rate as a fraction."""
    if error_count is None or total_count is None:
        return 0.0
    if total_count == 0:
        return 0.0
    return error_count / total_count


# ═══════════════════════════════════════════════════════════════════════
# CONSECUTIVE FAILURES
# ═══════════════════════════════════════════════════════════════════════

def is_consecutive_failures(
    results: List[bool],
    max_consecutive: int = 3,
) -> bool:
    """True if there are more than max_consecutive consecutive failures."""
    consecutive = 0
    for result in results:
        if not result:
            consecutive += 1
            if consecutive > max_consecutive:
                return True
        else:
            consecutive = 0
    return False


def count_consecutive_failures(results: List[bool]) -> int:
    """Count the maximum number of consecutive failures."""
    max_consecutive = 0
    consecutive = 0
    for result in results:
        if not result:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
    return max_consecutive


# ═══════════════════════════════════════════════════════════════════════
# INACTIVE INSTRUMENT
# ═══════════════════════════════════════════════════════════════════════

def is_inactive_instrument(
    last_activity_timestamp: float | None,
    current_timestamp: float | None,
    inactive_threshold_seconds: float = 3600,
) -> bool:
    """True if instrument has been inactive for too long."""
    if last_activity_timestamp is None or current_timestamp is None:
        return False
    return (current_timestamp - last_activity_timestamp) > inactive_threshold_seconds


def inactive_duration(
    last_activity_timestamp: float | None,
    current_timestamp: float | None,
) -> float:
    """Get duration since last activity in seconds."""
    if last_activity_timestamp is None or current_timestamp is None:
        return 0.0
    return current_timestamp - last_activity_timestamp


# ═══════════════════════════════════════════════════════════════════════
# TEMPORAL CORRELATION
# ═══════════════════════════════════════════════════════════════════════

def is_temporal_correlation(
    timestamps: List[float],
    window_seconds: float = 60,
    min_events: int = 3,
) -> bool:
    """True if there are min_events within window_seconds."""
    if len(timestamps) < min_events:
        return False
    sorted_ts = sorted(timestamps)
    for i in range(len(sorted_ts) - min_events + 1):
        window = sorted_ts[i + min_events - 1] - sorted_ts[i]
        if window <= window_seconds:
            return True
    return False


def temporal_density(
    timestamps: List[float],
    window_seconds: float = 60,
) -> float:
    """Compute event density (events per window)."""
    if not timestamps or window_seconds <= 0:
        return 0.0
    sorted_ts = sorted(timestamps)
    total_window = sorted_ts[-1] - sorted_ts[0]
    if total_window <= 0:
        return len(timestamps)
    return len(timestamps) / (total_window / window_seconds)
