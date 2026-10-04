#!/usr/bin/env python3
"""
test_vos_kernel.py — Minimal tests for vos_kernel utilities.
Verifies vsm_kernel, focus_extended, and agent_results modules.
"""
import sys
import os
import json

# Add framework to path so vos_kernel.utils can be imported
_FRAMEWORK_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_FRAMEWORK_DIR))

from vos_kernel.utils.vsm_kernel import (
    VSM_VERSION,
    get_timestamp,
    vsm_header,
    vsm_footer,
    validate_vsm_content,
)
# vsm_footer_with_type was dropped in the vOSlab vsm_kernel (Sep30): the
# canonical footer is the SHORT form (vsm_footer -> "⟦ /name ⟧", preferred
# by scripts/vsl/validator/check.py). The external repo still carries the
# deprecated helper; this test follows the vOSlab contract (S5 containment).


def test_vsm_version_exists():
    """VSM_VERSION must be defined."""
    assert VSM_VERSION is not None, "VSM_VERSION is None"
    assert len(VSM_VERSION) > 0, "VSM_VERSION is empty"


def test_get_timestamp_format():
    """Timestamp must be ISO 8601 UTC."""
    ts = get_timestamp()
    assert "T" in ts, f"Timestamp missing T separator: {ts}"
    assert ts.endswith("Z"), f"Timestamp not UTC: {ts}"
    assert len(ts) == 20, f"Timestamp wrong length: {ts} ({len(ts)} chars)"


def test_vsm_header_format():
    """Header must contain name, type, version, timestamp."""
    h = vsm_header("test", "TEST-v1")
    assert "⟦" in h, "Header missing ⟦"
    assert "test" in h, "Header missing name"
    assert "TEST-v1" in h, "Header missing type"
    assert "T" in h, "Header missing timestamp"


def test_vsm_footer_returns_string():
    """Footer must return a non-empty string."""
    f = vsm_footer("test")
    assert isinstance(f, str), f"Footer is {type(f)}, expected str"
    assert len(f) > 0, "Footer is empty"
    assert "⟦" in f, "Footer missing ⟦"
    assert "test" in f, "Footer missing name"


def test_validate_vsm_content_returns_dict():
    """Validation must return a dict with valid key."""
    content = "⟦ test | TEST-v1 | 1.2.1 | 2026-09-07T18:00:00Z ⟧\n\nContent\n\n⟦ /test ⟧"
    result = validate_vsm_content(content)
    assert isinstance(result, dict), f"Result is {type(result)}, expected dict"
    assert "valid" in result, "Result missing 'valid' key"


def test_validate_vsm_content_detects_bad_footer():
    """Content with long footer format should fail validation."""
    # Long footer = full format (name | type | version | date) is INVALID
    content = "⟦ test | TEST-v1 | vsm-1.2.1 | 2026-09-07T18:00:00Z ⟧\n\nContent\n\n⟦ /test | TEST-v1 | vsm-1.2.1 | 2026-09-07T18:00:00Z ⟧"
    result = validate_vsm_content(content)
    # Should report footer error (long format not accepted)
    assert result["valid"] is False or any("footer" in str(e).lower() for e in result.get("errors", []))


def test_focus_extended_import():
    """focus_extended module should be importable."""
    from vos_kernel.utils import focus_extended
    assert focus_extended is not None


def test_agent_results_import():
    """agent_results module should be importable."""
    from vos_kernel.utils import agent_results
    assert agent_results is not None


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
