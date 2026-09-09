"""vsf-hooks-analytics — Hook metrics and deep audit for VSF.

Ported from child/scripts/hook_metrics.py and child/scripts/deep_audit.py
"""

__version__ = "0.1.0"

# Key exports for common usage
from .hook_metrics import HookMetrics
from .deep_audit import DeepAudit

__all__ = [
    "HookMetrics",
    "DeepAudit",
]
