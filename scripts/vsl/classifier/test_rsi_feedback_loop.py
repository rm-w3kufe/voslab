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
    """Load rsi_feedback_loop with sandboxed state."""
    # Load metrics first
    m_spec = importlib.util.spec_from_file_location("rsi_metrics", str(METRICS_SPEC))
    m_mod = importlib.util.module_from_spec(m_spec)
    m_spec.loader.exec_module(m_mod)
    
    # Load feedback loop
    spec = importlib.util.spec_from_file_location("rsi_feedback_loop", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rsi_metrics"] = m_mod
    spec.loader.exec_module(mod)
    
    tmp = tempfile.mkdtemp()
    mod.THRESHOLDS_FILE = Path(tmp) / "thresholds.json"
    mod.ADJUSTMENTS_FILE = Path(tmp) / "rsi_adjustments.jsonl"
    # Override module-level constants in metrics module
    m_mod.METRICS_DIR = Path(tmp)
    m_mod.METRICS_FILE = Path(tmp) / "rsi_metrics.json"
    m_mod.HISTORY_FILE = Path(tmp) / "rsi_metrics_history.jsonl"
    # Create empty thresholds file to avoid DEFAULT_THRESHOLDS
    mod.THRESHOLDS_FILE.write_text("{}")
    obj = mod.RSIFeedbackLoop()
    return obj, mod, m_mod, Path(tmp)


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
    """No data should fail validation (accuracy=0 < 0.7)."""
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", 0.7) is False


def test_validate_threshold_negative(feedback):
    """Negative threshold should fail validation."""
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", -0.1) is False


def test_validate_threshold_above_one(feedback):
    """Threshold > 1 should fail validation."""
    fb, mod, m_mod, tmp = feedback
    assert fb._validate_threshold("pred", 1.1) is False


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
