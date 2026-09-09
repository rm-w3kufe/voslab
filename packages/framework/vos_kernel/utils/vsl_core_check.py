"""vsl_core_check.py — Shared helper for checking vsl-core availability.

Provides a centralized way to check if vsl-core (Rust) is available.
Used by covenant.py and other modules that need to detect vsl-core.

Usage:
    from vos_kernel.utils.vsl_core_check import has_vsl_core, require_vsl_core
    
    if has_vsl_core():
        # Use Rust implementation
        import vsl_core
    else:
        # Fall back to Python implementation
        pass
"""

from __future__ import annotations

import sys


def has_vsl_core() -> bool:
    """Check if vsl-core (Rust bindings) is available.
    
    Returns:
        True if vsl_core can be imported, False otherwise.
    """
    try:
        import vsl_core
        return True
    except ImportError:
        return False


def require_vsl_core() -> None:
    """Require vsl-core to be available.
    
    Raises:
        ImportError: If vsl_core is not available.
    """
    if not has_vsl_core():
        raise ImportError(
            "vsl-core is required but not available. "
            "Install with: pip install vsl-core"
        )


# Module-level check for quick access
HAS_VSL_CORE = has_vsl_core()
