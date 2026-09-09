"""vsf-rsi-core — RSI bridge for vOSlab.

Bridges to the existing vsf-rsi package at ~/packages/public/vsf-rsi/
which contains the full RSI implementation (40+ modules).
"""

__version__ = "0.1.0"

# Key exports for common usage
from .bridge import (
    genetic_algorithm_run,
    forest_generate,
    tree_generate,
    predicate_generate,
    compute_metrics,
    detect_gaps,
    detect_patterns,
    feedback_loop_step,
    register_component,
    list_components,
    is_available,
    get_version,
)

__all__ = [
    "genetic_algorithm_run",
    "forest_generate",
    "tree_generate",
    "predicate_generate",
    "compute_metrics",
    "detect_gaps",
    "detect_patterns",
    "feedback_loop_step",
    "register_component",
    "list_components",
    "is_available",
    "get_version",
]
