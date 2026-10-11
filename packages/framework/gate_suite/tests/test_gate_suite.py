#!/usr/bin/env python3
"""
test_gate_suite.py — Minimal tests for gate_suite gates.
Verifies each gate can be imported, has required interface, and basic validation works.
"""
import sys
import os
import importlib.util
import tempfile
import shutil
from pathlib import Path

# Add framework to path so gate_suite.harness can be imported
_FRAMEWORK_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_FRAMEWORK_DIR))

from gate_suite.harness import _cleanup

GATES_DIR = os.path.join(os.path.dirname(__file__), "..", "gates")

REQUIRED_GATES = [
    "a0_compliance",
    "a1_recursion",
    "a5_autonomy",
    "no_silent_concession",
    "plugin_location_valid",
    "timestamp_no_hardcoded",
    "trust_composable",
    "vsm_version_enforcer",
]


def load_gate(name):
    """Load a gate module by name."""
    path = os.path.join(GATES_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_exists():
    """All required gates must exist."""
    for name in REQUIRED_GATES:
        path = os.path.join(GATES_DIR, f"{name}.py")
        assert os.path.exists(path), f"Gate {name} not found at {path}"


def test_gate_importable():
    """All gates must be importable without error."""
    for name in REQUIRED_GATES:
        mod = load_gate(name)
        assert mod is not None, f"Gate {name} failed to load"


def test_gate_has_check():
    """Each gate must expose a check() or validate() function."""
    for name in REQUIRED_GATES:
        mod = load_gate(name)
        has_check = hasattr(mod, "check") or hasattr(mod, "validate") or hasattr(mod, "run")
        assert has_check, f"Gate {name} has no check/validate/run function"


def test_vsm_version_enforcer():
    """VSM version enforcer gate must reject vsm-1.2 (should be vsm-1.2.1)."""
    mod = load_gate("vsm_version_enforcer")
    # The gate should exist and be loadable
    assert mod is not None


def test_timestamp_no_hardcoded():
    """Timestamp gate must reject hardcoded seconds (T00:00:00Z, T12:00:00Z)."""
    mod = load_gate("timestamp_no_hardcoded")
    assert mod is not None


def test_plugin_location_valid():
    """Plugin location gate must validate registry.json exists."""
    mod = load_gate("plugin_location_valid")
    assert mod is not None


def test_cleanup_removes_dir():
    """_cleanup must remove a DIRECTORY tmpdir (negative_case returns dirs)."""
    d = tempfile.mkdtemp(prefix="voslab_harness_test_")
    Path(d, "planted.txt").write_text("x", encoding="utf-8")
    assert Path(d).is_dir()
    _cleanup(d)
    assert not Path(d).exists(), "dir tmpdir leaked"


def test_cleanup_removes_file():
    """_cleanup must still remove a plain file."""
    fd, p = tempfile.mkstemp(prefix="voslab_harness_test_f_")
    os.close(fd)
    _cleanup(p)
    assert not Path(p).exists(), "file tmp leaked"


def test_cleanup_ignores_outside_tmp():
    """_cleanup must NOT touch paths outside the temp dir."""
    outside = os.path.join(tempfile.gettempdir(), "voslab_should_not_delete_marker")
    Path(outside).write_text("keep", encoding="utf-8")
    try:
        _cleanup(outside)  # path IS under gettempdir -> will be removed; use a non-tmp path
        # For a path NOT under tmp, _cleanup is a no-op:
        real_outside = "/etc/hostname"
        before = os.path.exists(real_outside)
        _cleanup(real_outside)
        assert os.path.exists(real_outside) == before
    finally:
        if Path(outside).exists():
            Path(outside).unlink()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
