"""vsf-health — System health monitoring predicates for VSF.

Ported from child/scripts/vsl/classifier/vsf_predicates.py
disk_ok, alerts_db_ok, is_high_error_rate, is_consecutive_failures,
is_inactive_instrument, is_temporal_correlation
"""

__version__ = "0.1.0"

# Key exports for common usage
from .health_predicates import (
    disk_ok,
    disk_usage,
    alerts_db_ok,
    is_high_error_rate,
    is_consecutive_failures,
    is_inactive_instrument,
    is_temporal_correlation,
)

__all__ = [
    "disk_ok",
    "disk_usage",
    "alerts_db_ok",
    "is_high_error_rate",
    "is_consecutive_failures",
    "is_inactive_instrument",
    "is_temporal_correlation",
]
