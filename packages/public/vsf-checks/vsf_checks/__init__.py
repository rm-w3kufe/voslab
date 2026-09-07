"""
vsf-checks — Validación de checks del sistema VSF.

Proporciona functions para ejecutar y validar checks de integridad.
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
