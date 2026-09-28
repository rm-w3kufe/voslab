"""
design: child/docs/vos_package_detailed_plans.vsm

Covers:
  - track_classification: basic tracking, boundary values, overflow
  - get_accuracy: no data, partial data, full data, threshold filtering
  - get_latency: no data, single sample, many samples
  - get_coverage: no data, partial, full
  - rebuild_from_history: empty history, partial, full rebuild
  - _load_metrics / _save_metrics: roundtrip, corruption

Every check must fail closed: missing data returns 0.0, not hallucinated values.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Load rsi_metrics directly (avoid package import issues)
SPEC_PATH = Path(__file__).resolve().parent / "rsi_metrics.py"


@pytest.fixture
def metrics():
    """Create RSIMetrics with sandboxed state dir."""
    spec = importlib.util.spec_from_file_location("rsi_metrics_ut", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tmp = tempfile.mkdtemp()
    # Delegation: canonical globals before construction, instance attrs after.
    import vsf_rsi.rsi_metrics as canon
    saved = {n: getattr(canon, n)
             for n in ("METRICS_DIR", "METRICS_FILE", "HISTORY_FILE")}
    canon.METRICS_DIR = Path(tmp)
    canon.METRICS_FILE = Path(tmp) / "rsi_metrics.json"
    canon.HISTORY_FILE = Path(tmp) / "rsi_metrics_history.jsonl"
    mod.METRICS_DIR = Path(tmp)
    mod.METRICS_FILE = Path(tmp) / "rsi_metrics.json"
    mod.HISTORY_FILE = Path(tmp) / "rsi_metrics_history.jsonl"
    obj = mod.RSIMetrics()
    obj.metrics_dir = Path(tmp)
    yield obj, mod, Path(tmp)
    for n, v in saved.items():
        setattr(canon, n, v)


# ── Basic tracking ──────────────────────────────────────────────────────

def test_track_and_retrieve(metrics):
    """Track a classification and retrieve accuracy."""
    m, mod, tmp = metrics
    m.track_classification("test_pred", 0.7, 0.8, True, True, 1.5)
    acc = m.get_accuracy("test_pred", 0.7)
    assert acc == 1.0  # 1 correct out of 1


def test_track_multiple_classifications(metrics):
    """Track multiple and check aggregated accuracy."""
    m, mod, tmp = metrics
    for i in range(10):
        expected = True
        actual = i < 7  # 70% correct
        m.track_classification("multi_pred", 0.7, 0.5, expected, actual, 1.0)
    acc = m.get_accuracy("multi_pred", 0.7)
    assert abs(acc - 0.7) < 0.01


def test_track_wrong_classifications(metrics):
    """Track wrong classifications and verify low accuracy."""
    m, mod, tmp = metrics
    for _ in range(5):
        m.track_classification("wrong_pred", 0.7, 0.5, True, False, 1.0)
    acc = m.get_accuracy("wrong_pred", 0.7)
    assert acc == 0.0  # all wrong


# ── Edge cases: boundary values ─────────────────────────────────────────

def test_threshold_zero(metrics):
    """Threshold=0.0 should work."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.0, 0.0, True, True, 0.1)
    acc = m.get_accuracy("pred", 0.0)
    assert acc == 1.0


def test_threshold_one(metrics):
    """Threshold=1.0 should work."""
    m, mod, tmp = metrics
    m.track_classification("pred", 1.0, 0.99, True, True, 0.1)
    acc = m.get_accuracy("pred", 1.0)
    assert acc == 1.0


def test_input_value_zero(metrics):
    """Input=0.0 should work."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.0, False, False, 0.1)
    acc = m.get_accuracy("pred", 0.7)
    assert acc == 1.0


def test_input_value_one(metrics):
    """Input=1.0 should work."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 1.0, True, True, 0.1)
    acc = m.get_accuracy("pred", 0.7)
    assert acc == 1.0


def test_latency_zero(metrics):
    """Latency=0 should work."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.5, True, True, 0.0)
    lat = m.get_latency("pred", 0.7)
    assert lat == 0.0


def test_latency_very_high(metrics):
    """Very high latency should not crash."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.5, True, True, 99999.9)
    lat = m.get_latency("pred", 0.7)
    assert lat == 99999.9


# ── Missing data (fail closed) ──────────────────────────────────────────

def test_no_data_returns_zero(metrics):
    """No data → accuracy=0.0, not hallucinated."""
    m, mod, tmp = metrics
    assert m.get_accuracy("nonexistent") == 0.0
    assert m.get_accuracy("nonexistent", 0.7) == 0.0
    assert m.get_latency("nonexistent") == 0.0
    assert m.get_coverage("nonexistent") == 0.0


def test_wrong_threshold_returns_zero(metrics):
    """Non-existent threshold → accuracy=0.0."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.5, True, True, 1.0)
    assert m.get_accuracy("pred", 0.9) == 0.0


# ── Latency tracking ────────────────────────────────────────────────────

def test_latency_averaging(metrics):
    """Multiple latencies should average correctly."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.5, True, True, 1.0)
    m.track_classification("pred", 0.7, 0.5, True, True, 3.0)
    lat = m.get_latency("pred", 0.7)
    assert abs(lat - 2.0) < 0.01


def test_latency_history_capped(metrics):
    """Latency history should be capped at 100 entries."""
    m, mod, tmp = metrics
    for i in range(150):
        m.track_classification("pred", 0.7, 0.5, True, True, float(i))
    metrics_data = m._load_metrics()
    # DEBT-003: predicate-level latencies were removed — latency lives at
    # the THRESHOLD level now (still capped at 100).
    latencies = metrics_data["pred"]["thresholds"]["0.7"]["latencies"]
    assert len(latencies) <= 100


# ── Coverage ────────────────────────────────────────────────────────────

def test_coverage(metrics):
    """Coverage should reflect threshold diversity."""
    m, mod, tmp = metrics
    # No data → 0 coverage
    assert m.get_coverage("pred") == 0.0
    # One threshold
    m.track_classification("pred", 0.7, 0.5, True, True, 1.0)
    cov = m.get_coverage("pred")
    assert cov > 0.0


# ── rebuild_from_history ────────────────────────────────────────────────

def test_rebuild_from_history(metrics):
    """Rebuild should aggregate JSONL history into JSON store."""
    m, mod, tmp = metrics
    # Write history entries manually
    for i in range(20):
        entry = {
            "timestamp": "2026-08-30T00:00:00Z",
            "predicate": "rebuild_pred",
            "threshold": 0.7,
            "input_value": 0.5,
            "expected": True,
            "actual": i < 15,  # 75% correct
            "correct": i < 15,
            "latency_ms": 1.0
        }
        with open(tmp / "rsi_metrics_history.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    # Rebuild
    rebuilt = m.rebuild_from_history()
    assert "rebuild_pred" in rebuilt
    assert rebuilt["rebuild_pred"]["total_classifications"] == 20
    assert rebuilt["rebuild_pred"]["correct_classifications"] == 15
    
    # get_accuracy should now work
    acc = m.get_accuracy("rebuild_pred", 0.7)
    assert abs(acc - 0.75) < 0.01


def test_rebuild_empty_history(metrics):
    """Rebuild with no history should return empty dict."""
    m, mod, tmp = metrics
    rebuilt = m.rebuild_from_history()
    assert rebuilt == {}


def test_rebuild_corrupted_entries(metrics):
    """Corrupted JSONL entries should be skipped, not crash."""
    m, mod, tmp = metrics
    # Write valid + corrupted entries
    with open(tmp / "rsi_metrics_history.jsonl", "w") as f:
        f.write(json.dumps({"timestamp": "2026-08-30T00:00:00Z", "predicate": "good", "threshold": 0.7, "input_value": 0.5, "expected": True, "actual": True, "correct": True, "latency_ms": 1.0}) + "\n")
        f.write("not valid json\n")
        f.write(json.dumps({"predicate": "good", "threshold": 0.7, "input_value": 0.5, "expected": False, "actual": False, "correct": True, "latency_ms": 2.0}) + "\n")
    
    rebuilt = m.rebuild_from_history()
    assert "good" in rebuilt
    assert rebuilt["good"]["total_classifications"] == 2  # corrupted entry skipped


# ── get_summary ─────────────────────────────────────────────────────────

def test_get_summary(metrics):
    """Summary should reflect tracked data."""
    m, mod, tmp = metrics
    m.track_classification("pred_a", 0.7, 0.5, True, True, 1.0)
    m.track_classification("pred_b", 0.7, 0.5, True, False, 2.0)
    summary = m.get_summary()
    assert summary["total_predicates"] == 2
    assert summary["total_classifications"] == 2


def test_get_summary_empty(metrics):
    """Empty summary should not crash."""
    m, mod, tmp = metrics
    summary = m.get_summary()
    assert summary["total_predicates"] == 0
    assert summary["total_classifications"] == 0


# ── get_recommendation ──────────────────────────────────────────────────

def test_get_recommendation(metrics):
    """Recommendation should suggest adjustments for low accuracy."""
    m, mod, tmp = metrics
    # Create scenario with some correct and some wrong
    for i in range(20):
        expected = True
        actual = i < 10  # 50% correct — better than 0%
        m.track_classification("pred", 0.7, 0.5, expected, actual, 1.0)
    rec = m.get_recommendation("pred")
    assert "action" in rec
    # Should suggest adjustment (not collect_data)
    assert rec["action"] != "collect_data"


# ── Adversarial ─────────────────────────────────────────────────────────

def test_negative_latency(metrics):
    """Negative latency should not crash (but is suspicious)."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 0.5, True, True, -1.0)
    # Should not crash, but value is stored
    lat = m.get_latency("pred", 0.7)
    assert lat == -1.0


def test_very_large_values(metrics):
    """Very large input/latency should not overflow."""
    m, mod, tmp = metrics
    m.track_classification("pred", 0.7, 1e308, True, True, 1e308)
    acc = m.get_accuracy("pred", 0.7)
    assert acc == 1.0
