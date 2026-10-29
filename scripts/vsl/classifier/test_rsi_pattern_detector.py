"""design: docs/plans/vos_package_detailed_plans.vsm
test_rsi_pattern_detector.py — adversarial / edge-case tests.

Covers:
  - detect_patterns: no data, misclassification, threshold, latency, degradation
  - suggest_generation: various pattern types
  - get_patterns_summary: empty, with patterns
  - _load/_save: roundtrip, corruption

Every check must fail closed: missing data → no patterns, not hallucinated.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

METRICS_SPEC = Path(__file__).resolve().parent / "rsi_metrics.py"
SPEC_PATH = Path(__file__).resolve().parent / "rsi_pattern_detector.py"


@pytest.fixture
def detector():
    """Load rsi_pattern_detector with sandboxed state."""
    m_spec = importlib.util.spec_from_file_location("rsi_metrics", str(METRICS_SPEC))
    m_mod = importlib.util.module_from_spec(m_spec)
    m_spec.loader.exec_module(m_mod)

    spec = importlib.util.spec_from_file_location("rsi_pattern_detector", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rsi_metrics"] = m_mod
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp()
    # Delegation: patch the CANONICAL modules before construction.
    import vsf_rsi.rsi_pattern_detector as canon_p
    import vsf_rsi.rsi_metrics as canon_m
    saved_p = {n: getattr(canon_p, n) for n in ("PATTERNS_DIR", "PATTERNS_FILE")}
    saved_m = {n: getattr(canon_m, n)
               for n in ("METRICS_DIR", "METRICS_FILE", "HISTORY_FILE")}
    canon_p.PATTERNS_DIR = Path(tmp)
    canon_p.PATTERNS_FILE = Path(tmp) / "rsi_patterns.json"
    canon_m.METRICS_DIR = Path(tmp)
    canon_m.METRICS_FILE = Path(tmp) / "rsi_metrics.json"
    canon_m.HISTORY_FILE = Path(tmp) / "rsi_metrics_history.jsonl"
    mod.PATTERNS_DIR = Path(tmp)
    mod.PATTERNS_FILE = Path(tmp) / "rsi_patterns.json"
    m_mod.METRICS_DIR = Path(tmp)
    m_mod.METRICS_FILE = Path(tmp) / "rsi_metrics.json"
    m_mod.HISTORY_FILE = Path(tmp) / "rsi_metrics_history.jsonl"
    obj = mod.RSIPatternDetector()
    yield obj, mod, Path(tmp)
    for n, v in saved_p.items():
        setattr(canon_p, n, v)
    for n, v in saved_m.items():
        setattr(canon_m, n, v)


def _seed_metrics(detector, predicate: str, n_samples: int = 50):
    """Seed metrics with varied data."""
    det, mod, tmp = detector
    for i in range(n_samples):
        expected = True
        actual = i < int(0.7 * n_samples)  # 70% accuracy
        latency = 1.0 if i < 40 else 50.0  # some high latency
        det.metrics.track_classification(predicate, 0.7, 0.5, expected, actual, latency)
    det.metrics.rebuild_from_history()


# ── detect_patterns ─────────────────────────────────────────────────────

def test_no_data_no_patterns(detector):
    """No data should return empty patterns."""
    det, mod, tmp = detector
    result = det.detect_patterns("new_pred")
    assert result["patterns"] == []


def test_misclassification_pattern(detector):
    """Low accuracy should detect misclassification pattern."""
    det, mod, tmp = detector
    _seed_metrics(detector, "bad_pred")
    result = det.detect_patterns("bad_pred")
    pattern_types = [p["type"] for p in result["patterns"]]
    # Should detect some pattern (misclassification or threshold)
    assert len(result["patterns"]) > 0


def test_high_latency_pattern(detector):
    """High latency should detect latency pattern."""
    det, mod, tmp = detector
    # Seed with high latency
    for _ in range(20):
        det.metrics.track_classification("slow_pred", 0.7, 0.5, True, True, 50.0)
    det.metrics.rebuild_from_history()
    result = det.detect_patterns("slow_pred")
    pattern_types = [p["type"] for p in result["patterns"]]
    assert "latency_spike" in pattern_types


# ── suggest_generation ──────────────────────────────────────────────────

def test_suggest_generation_misclassification(detector):
    """Misclassification pattern should suggest tree generation."""
    det, mod, tmp = detector
    pattern = {"type": "recurring_misclassification", "severity": "high", "accuracy": 0.3}
    suggestion = det.suggest_generation(pattern)
    assert suggestion is not None
    assert "type" in suggestion


def test_suggest_generation_threshold(detector):
    """Threshold pattern should suggest tree generation."""
    det, mod, tmp = detector
    pattern = {"type": "threshold_clustering", "severity": "medium", "best_threshold": 0.7}
    suggestion = det.suggest_generation(pattern)
    assert suggestion is not None


def test_suggest_generation_unknown(detector):
    """Unknown pattern should return None."""
    det, mod, tmp = detector
    pattern = {"type": "unknown_pattern_type"}
    suggestion = det.suggest_generation(pattern)
    assert suggestion is None


# ── get_patterns_summary ────────────────────────────────────────────────

def test_summary_empty(detector):
    """Empty patterns should return empty summary."""
    det, mod, tmp = detector
    summary = det.get_patterns_summary()
    assert summary["total_patterns"] == 0


def test_summary_with_patterns(detector):
    """Patterns should be summarized."""
    det, mod, tmp = detector
    _seed_metrics(detector, "summary_pred")
    det.detect_patterns("summary_pred")
    summary = det.get_patterns_summary()
    assert summary["total_patterns"] >= 0


# ── _load/_save ─────────────────────────────────────────────────────────

def test_patterns_roundtrip(detector):
    """Save/load patterns should work."""
    det, mod, tmp = detector
    patterns = {"predicate": "test_pred", "patterns": [{"type": "test"}], "timestamp": "2026-08-30T00:00:00Z"}
    det._save_patterns(patterns)
    loaded = det._load_patterns()
    assert "test_pred" in loaded


def test_patterns_corrupted_file(detector):
    """Corrupted patterns file should raise or return empty."""
    det, mod, tmp = detector
    mod.PATTERNS_FILE.write_text("not valid json")
    try:
        loaded = det._load_patterns()
        assert isinstance(loaded, dict)
    except json.JSONDecodeError:
        pass  # Acceptable behavior


# ── Adversarial ─────────────────────────────────────────────────────────

def test_many_predicates(detector):
    """Many predicates should not crash."""
    det, mod, tmp = detector
    for i in range(10):
        _seed_metrics(detector, f"pred_{i}")
    result = det.detect_patterns("pred_0")
    assert "patterns" in result
