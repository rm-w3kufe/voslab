"""
vsf-checks — validation of checks for the VSF system.

Provides functions to run and validate integrity checks.
"""

from .check_runner import (
    run_check,
    run_all_checks,
    get_check_status,
    format_check_report,
    list_checks,
    run_checks_by_category,
    load_check_manifest,
    validate_check_manifest,
)
from .shell_check_bridge import ShellCheckBridge

__version__ = "0.1.0"

__all__ = [
    "run_check",
    "run_all_checks",
    "get_check_status",
    "format_check_report",
    "list_checks",
    "run_checks_by_category",
    "load_check_manifest",
    "validate_check_manifest",
    "ShellCheckBridge",
]
