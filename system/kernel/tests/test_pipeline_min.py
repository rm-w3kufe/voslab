"""test_pipeline_min.py — R2-REDUCIR regression: blind before takes the
minimal path (rate + state + scope), populated args take the full path.

ISOLATION DISCIPLINE (lesson 2026-09-12, learned the hard way): vsf_rsi
freezes its STATE DIR constants at first import, and the kernel conftest
points them at tmp via a session fixture. Therefore this module must NOT
import the bridge at module scope — collection-time import would freeze
PRODUCTION dirs process-wide and break tmp-scoping assertions elsewhere.
The bridge is imported lazily inside the fixture (env already tmp), and
all mutable surfaces (VOS_ROOT drain reads, rate file, integration log,
trust store) are patched to tmp/stubs. Zero production writes.
"""
import sys

import pytest


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / ".opencode" / "plugins" / "operational"))
    import tool_integration_bridge as b  # lazy: env already tmp here
    monkeypatch.setattr(b, "VOS_ROOT", str(tmp_path))
    rl = tmp_path / "rl.json"
    rl.write_text("[]")
    monkeypatch.setattr(b, "_RATE_LIMIT_FILE", str(rl))
    monkeypatch.setattr(b, "log_integration", lambda *a, **k: None)
    calls = {"trust": []}

    class _FakeAssessor:
        def __init__(self, *a, **k):
            pass

        def record_outcome(self, file, ok):
            calls["trust"].append((file, ok))
            return 1.0

    monkeypatch.setitem(sys.modules, "risk_assessor",
                        type(sys)("risk_assessor"))
    monkeypatch.setattr(sys.modules["risk_assessor"], "RiskAssessor",
                        _FakeAssessor, raising=False)
    b._trust_calls = calls  # observability for the drain test
    return b


def blind_ctx(tool="bash"):
    return {"tool": tool, "file": "", "basename": "", "command": "",
            "is_state_changing": True, "is_read_only": False}


def test_blind_takes_min_mode(bridge):
    out = bridge.pipeline_before(blind_ctx())
    assert out.get("mode") == "min"
    assert out["preCheck"]["ok"] is True
    assert out["preCheck"]["socratic"]["truth"] == "TRUE"


def test_populated_takes_full_mode(bridge):
    ctx = blind_ctx()
    ctx["command"] = "echo hi"
    out = bridge.pipeline_before(ctx)
    assert out.get("mode") == "full"
    assert out["preCheck"]["ok"] is True


def test_rate_trips_at_21st_write(bridge):
    ctx = blind_ctx("write")
    verdict = None
    for _ in range(21):
        verdict = bridge.pipeline_before_min(ctx)["preCheck"]
    assert verdict["ok"] is False
    s = verdict["socratic"]
    assert (s["truth"], s["certified"]) == ("FALSE", True)
    assert s["source"] == "no_state_conflict"
    assert s.get("failed_predicates") == ["no_state_conflict"]


def test_rate_allows_first_20(bridge):
    ctx = blind_ctx("write")
    for _ in range(20):
        assert bridge.pipeline_before_min(ctx)["preCheck"]["ok"] is True


def test_drain_applies_spill_exactly_once(bridge, tmp_path):
    import json
    import os
    spill_dir = tmp_path / "state" / "rsi"
    spill_dir.mkdir(parents=True)
    lines = [{"ts": "t", "tool": "read", "file": f"/tmp/d{i}", "ok": True}
             for i in range(5)]
    (spill_dir / "trust_spill.jsonl").write_text(
        "\n".join(json.dumps(e) for e in lines) + "\n")
    assert bridge._drain_trust_spill() == 5
    assert bridge._trust_calls["trust"] == [(f"/tmp/d{i}", True)
                                            for i in range(5)]
    assert not os.path.exists(spill_dir / "trust_spill.jsonl")
    assert list(spill_dir.glob("*.drain-*")) == []
