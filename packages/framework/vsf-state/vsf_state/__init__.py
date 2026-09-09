"""
vsf-state — Scripts de estado del sistema VSF.

Proporciona functions para el manejo de estado del sistema.
"""

__version__ = "0.1.0"

# Key exports for common usage
from .algedonic_pub import publish_beacon, subscribe_beacon
from .hook_analytics import compute_hook_metrics, export_analytics
from .witness_verify import verify_witness, get_certificate_info
from .tasks_reconcile import reconcile_tasks, validate_task_state
from .monitor_reconcile import monitor_services, reconcile_state
from .service_watchdog import check_service_health, restart_service
from .cyberfilter_variety import filter_variety, compute_variety_metrics
from .handoff_archive import archive_handoffs, restore_handoff

__all__ = [
    "publish_beacon",
    "subscribe_beacon",
    "compute_hook_metrics",
    "export_analytics",
    "verify_witness",
    "get_certificate_info",
    "reconcile_tasks",
    "validate_task_state",
    "monitor_services",
    "reconcile_state",
    "check_service_health",
    "restart_service",
    "filter_variety",
    "compute_variety_metrics",
    "archive_handoffs",
    "restore_handoff",
]
