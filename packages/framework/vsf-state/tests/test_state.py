"""tests/test_state.py — Tests for state package surface.

Rewritten 2026-09-24: the old version was tautological
(try/except ImportError: assert True — passes even when the package
is broken; it missed the 16-missing-names bug entirely). These assert
real contracts. Environment-coupled modules (monitor_reconcile,
service_watchdog) are tested where their deps exist, SKIPPED with
reason elsewhere — never silently passed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import vsf_state


def test_all_names_resolve():
    """Every __all__ entry must exist (catches phantom exports)."""
    assert len(vsf_state.__all__) >= 20
    missing = [n for n in vsf_state.__all__ if not hasattr(vsf_state, n)]
    assert missing == [], f"phantom exports: {missing}"


def test_version_present():
    assert vsf_state.__version__ == "0.1.0"


@pytest.mark.parametrize("mod", [
    "algedonic_pub",
    "hook_analytics",
    "witness_verify",
    "tasks_reconcile",
    "tasks_validate",
    "cyberfilter_variety",
    "handoff_archive",
])
def test_submodule_imports(mod):
    """Core modules import cleanly without checkout layout."""
    assert __import__(f"vsf_state.{mod}", fromlist=["x"]) is not None


def test_monitor_reconcile_import():
    """Needs n02 topology context (resolve_lxc at module level)."""
    try:
        import vsf_state.monitor_reconcile  # noqa: F401
    except KeyError as e:
        pytest.skip(f"no n02 topology context: {e}")


def test_service_watchdog_import():
    """Needs vOSlab checkout layout (vsf_socratic_engine import)."""
    try:
        import vsf_state.service_watchdog  # noqa: F401
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"checkout-only dependency: {e}")


def test_s5_ca_imports():
    """s5_ca exists and imports cleanly."""
    import vsf_state.s5_ca  # noqa: F401
    assert True
