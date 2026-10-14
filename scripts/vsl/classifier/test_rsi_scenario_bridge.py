"""
design: docs/spec_revision/system/s1-operations/vos_package_detailed_plans.vsm

Covers:
  - failures_to_gaps: no failures, with failures, predicate filter
  - gaps_to_corrections: no gaps, with gaps, no corrections
  - full_bridge: bidirectional flow

Every check must fail closed: missing data → empty results, not hallucinated.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Load bridge
BRIDGE_PATH = Path(__file__).resolve().parent / "rsi_scenario_bridge.py"
SPEC = importlib.util.spec_from_file_location("rsi_scenario_bridge", str(BRIDGE_PATH))
bridge_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge_mod)


@pytest.fixture
def sm_store(monkeypatch):
    """Create sandboxed scenario-memory store.

    The canonical scenario_memory resolves its store via _get_store(),
    which reads the VSI_RSI_STORE env var FIRST — the module-level STORE
    global is a snapshot nothing reads at runtime (patching it sandboxes
    nothing; that mistake left 22 real scenarios visible to the tests).
    """
    tmp = tempfile.mkdtemp()
    store = Path(tmp) / "scenarios"
    store.mkdir()
    monkeypatch.setenv("VSI_RSI_STORE", str(store))
    return store


# ── failures_to_gaps ────────────────────────────────────────────────────

def test_no_failures(sm_store):
    """No failure scenarios should return 0 gaps."""
    result = bridge_mod.failures_to_gaps()
    assert result["total_failures"] == 0
    assert result["failure_gaps"] == []


def test_with_failures(sm_store):
    """Failure scenarios should produce gap signals."""
    # Current contract: the bridge counts outcome == "failure" (the old
    # quality="fail" kwarg and outcome="detected" are both gone).
    import vsf_rsi.scenario_memory as sm
    sm.record("hook failed", "failure", "checks/autonomy-cert",
              fault_signature="hook_fail_001")
    result = bridge_mod.failures_to_gaps()
    assert result["total_failures"] == 1
    assert result["failure_gaps"][0]["type"] == "scenario_failure"
    assert result["failure_gaps"][0]["scenario_id"]


def test_predicate_filter(sm_store):
    """Predicate filter should only return matching failures."""
    import vsf_rsi.scenario_memory as sm
    sm.record("ac failed", "failure", "checks/ac", fault_signature="ac_stasis_fail")
    sm.record("hook failed", "failure", "checks/hook", fault_signature="hook_fail_001")
    result = bridge_mod.failures_to_gaps(predicate_name="ac_stasis")
    assert result["total_failures"] == 1


# ── gaps_to_corrections ────────────────────────────────────────────────

def test_no_gaps(sm_store):
    """No RSI gaps should return empty corrections."""
    result = bridge_mod.gaps_to_corrections("new_pred")
    assert result["total_gaps"] == 0


# ── full_bridge ─────────────────────────────────────────────────────────

def test_full_bridge_returns_dict():
    """Full bridge should return a dict with both flows."""
    result = bridge_mod.full_bridge("ac_stasis_critical")
    assert "failures_to_gaps" in result
    assert "gaps_to_corrections" in result
    assert "bridge_timestamp" in result


# ── Adversarial ─────────────────────────────────────────────────────────

def test_empty_store(sm_store):
    """Empty store should not crash any function."""
    result = bridge_mod.full_bridge()
    assert "failures_to_gaps" in result


def test_corrupted_scenario(sm_store):
    """Corrupted scenario file should be skipped."""
    # Write a corrupted scenario
    (sm_store / "corrupt.json").write_text("not valid json")
    # Write a valid failure
    (sm_store / "good.json").write_text(json.dumps({
        "id": "good001", "decision": "test", "outcome": "failure",
        "correction_path": "fix", "fault_signature": "test_fail",
    }))
    result = bridge_mod.failures_to_gaps()
    assert result["total_failures"] == 1  # corrupted skipped
