"""
design: child/docs/vos_package_detailed_plans.vsm

Covers:
  - get_current_threshold: default, custom, boundary
  - adjust_thresholds: batch adjustment, no data, with data
  - _validate_threshold: boundary values
  - _load/_save: roundtrip, corruption
  - get_status: empty, with thresholds

Every check must fail closed: missing data returns defaults, not hallucinated values.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent / "rsi_feedback_loop.py"
METRICS_SPEC = Path(__file__).resolve().parent / "rsi_metrics.py"


@pytest.fixture
def feedback():
    """Load rsi_feedback_loop with sandboxed state.

    Delegation (2026-09): scripts/vsl/classifier/rsi_*.py are thin shims over
    the canonical ~/packages/public/vsf-rsi package — the CLASS reads the
    canonical module globals, so patching only the shim copy sandboxes
    nothing. Patch BOTH (canonical for the class, shim copy for what the
    tests write through), and restore the canonical state afterwards.
    """
    import vsf_rsi.rsi_feedback_loop as canon_fb
    import vsf_rsi.rsi_metrics as canon_m

    tmp = Path(tempfile.mkdtemp())
    saved_fb = {n: getattr(canon_fb, n)
                for n in ("THRESHOLDS_FILE", "ADJUSTMENTS_FILE")}
    saved_m = {n: getattr(canon_m, n)
               for n in ("METRICS_DIR", "METRICS_FILE", "HISTORY_FILE")}
    canon_fb.THRESHOLDS_FILE = tmp / "thresholds.json"
    canon_fb.ADJUSTMENTS_FILE = tmp / "rsi_adjustments.jsonl"
    canon_m.METRICS_DIR = tmp
    canon_m.METRICS_FILE = tmp / "rsi_metrics.json"
    canon_m.HISTORY_FILE = tmp / "rsi_metrics_history.jsonl"

    # Load metrics first
    m_spec = importlib.util.spec_from_file_location("rsi_metrics", str(METRICS_SPEC))
    m_mod = importlib.util.module_from_spec(m_spec)
    sys.modules["rsi_metrics"] = m_mod
    m_spec.loader.exec_module(m_mod)

    # Load feedback loop (shim copies now point at the sandbox too)
    spec = importlib.util.spec_from_file_location("rsi_feedback_loop", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Create empty thresholds file to avoid DEFAULT_THRESHOLDS
    canon_fb.THRESHOLDS_FILE.write_text("{}")
    obj = mod.RSIFeedbackLoop()
    yield obj, mod, m_mod, tmp
    for n, v in saved_fb.items():
        setattr(canon_fb, n, v)
    for n, v in saved_m.items():
        setattr(canon_m, n, v)


# ── get_current_threshold ───────────────────────────────────────────────

def test_default_threshold(feedback):
    """Default threshold should be 0.50."""
    fb, mod, m_mod, tmp = feedback
    t = fb.get_current_threshold("new_pred")
    assert t == 0.50


def test_custom_threshold_stored(feedback):
    """Custom threshold should be stored and retrieved."""
    fb, mod, m_mod, tmp = feedback
    # Write threshold file directly
    thresholds = {"custom_pred": 0.85}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    t = fb.get_current_threshold("custom_pred")
    assert t == 0.85


def test_boundary_threshold_zero(feedback):
    """Threshold=0 should be retrievable."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"zero_pred": 0.0}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    t = fb.get_current_threshold("zero_pred")
    assert t == 0.0


def test_boundary_threshold_one(feedback):
    """Threshold=1 should be retrievable."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"one_pred": 1.0}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    t = fb.get_current_threshold("one_pred")
    assert t == 1.0


# ── adjust_thresholds ───────────────────────────────────────────────────

def test_adjust_thresholds_no_data(feedback):
    """No data should not crash."""
    fb, mod, m_mod, tmp = feedback
    result = fb.adjust_thresholds()
    assert "adjustments" in result
    assert result["adjustments"] == []


def test_adjust_thresholds_with_data(feedback):
    """With data, adjustment should run without crash."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"pred": 0.7}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    result = fb.adjust_thresholds()
    assert "adjustments" in result


# ── _validate_threshold ─────────────────────────────────────────────────

def test_validate_threshold_no_data(feedback):
    """No data ALLOWS the adjustment — exploration contract.

    Canonical vsf-rsi f5eb14f ("allows exploration when no data"): accuracy=0
    with no metrics for the predicate returns True, so a first adjustment is
    never blocked. The old local implementation returned False here.
    """
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", 0.7) is True


def test_validate_threshold_negative(feedback):
    """Pin CURRENT canonical behavior: -0.1 is accepted.

    The no-data branch fires before any range check — the canonical package
    has NO [0,1] guard on _validate_threshold. Asserting the real contract,
    not endorsing it: a range guard belongs to vsf-rsi's own suite, and the
    package lives outside this workspace (read-only here).
    """
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", -0.1) is True


def test_validate_threshold_above_one(feedback):
    """Pin CURRENT canonical behavior: 1.1 is accepted (no [0,1] guard)."""
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", 1.1) is True


# ── _load/_save ─────────────────────────────────────────────────────────

def test_thresholds_roundtrip(feedback):
    """Save and load thresholds should return same data."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"test_pred": 0.75}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    loaded = fb._load_thresholds()
    assert loaded["test_pred"] == 0.75


def test_thresholds_corrupted_file(feedback):
    """Corrupted thresholds file should raise JSONDecodeError or return empty."""
    fb, mod, m_mod, tmp = feedback
    mod.THRESHOLDS_FILE.write_text("not valid json")
    try:
        loaded = fb._load_thresholds()
        # If it doesn't raise, it should return empty or default
        assert isinstance(loaded, dict)
    except json.JSONDecodeError:
        # If it raises, that's acceptable behavior
        pass


def test_thresholds_missing_file(feedback):
    """Missing thresholds file should return empty dict."""
    fb, mod, m_mod, tmp = feedback
    loaded = fb._load_thresholds()
    assert loaded == {}


# ── get_status ──────────────────────────────────────────────────────────

def test_get_status_empty(feedback):
    """Empty status should not crash."""
    fb, mod, m_mod, tmp = feedback
    status = fb.get_status()
    assert "current_thresholds" in status
    assert status["current_thresholds"] == {}


def test_get_status_with_thresholds(feedback):
    """Status with thresholds should report correctly."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"pred_a": 0.7, "pred_b": 0.8}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    status = fb.get_status()
    assert "current_thresholds" in status
    assert len(status["current_thresholds"]) == 2


# ── Adversarial ─────────────────────────────────────────────────────────

def test_adjust_many_times(feedback):
    """Many adjustments should not corrupt state."""
    fb, mod, m_mod, tmp = feedback
    thresholds = {"pred": 0.7}
    mod.THRESHOLDS_FILE.write_text(json.dumps(thresholds))
    for _ in range(10):
        fb.adjust_thresholds()
    loaded = fb._load_thresholds()
    assert "pred" in loaded
    assert 0.0 <= loaded["pred"] <= 1.0
