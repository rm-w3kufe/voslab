"""test_integration_log.py — anti-regresión: integration_log vive.

log_integration hace dual-write (unified + state/integration_log.jsonl);
los lectores (recent/session-stats) ven lo escrito; el cap de 1MB recorta
por tail. Hermético: VOS_ROOT e INTEGRATION_LOG a tmp, import perezoso
(disciplina freeze), cero writes de producción.
"""
from pathlib import Path

import pytest


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    import sys
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / ".opencode" / "plugins" / "operational"))
    import tool_integration_bridge as b  # lazy: env already tmp here
    monkeypatch.setattr(b, "VOS_ROOT", str(tmp_path))
    monkeypatch.setattr(b, "INTEGRATION_LOG",
                        str(tmp_path / "integration_log.jsonl"))
    return b


def _after(tool="bash", file="(no file)", outcome="success", command=""):
    return {"phase": "after", "tool": tool, "file": file,
            "outcome": outcome, "command": command}


def test_dual_write(bridge, tmp_path):
    bridge.log_integration(_after())
    uni = tmp_path / "logs" / "agent_plugin.jsonl"
    assert uni.is_file()
    import json
    assert json.loads(uni.read_text().strip())["source"] == "rsi-cycle"
    ilog = tmp_path / "integration_log.jsonl"
    assert ilog.is_file()
    line = json.loads(ilog.read_text().strip())
    assert (line["phase"], line["tool"], line["outcome"]) == (
        "after", "bash", "success")
    assert "ts" in line and "date" in line


def test_readers_see_writes(bridge):
    bridge.log_integration(_after(outcome="success"))
    bridge.log_integration(_after(outcome="failure"))
    bridge.log_integration({"phase": "before", "tool": "bash",
                            "file": "", "outcome": "allowed"})
    recent = bridge.get_recent_actions(20)
    assert len(recent) == 2  # only after-entries
    assert {e["outcome"] for e in recent} == {"success", "failure"}
    stats = bridge.get_session_stats()
    assert stats["total"] == 3
    assert stats["success"] == 1
    assert stats["failure"] == 2  # failure + non-success "allowed"


def test_cap_trims_by_tail(bridge, tmp_path):
    ilog = tmp_path / "integration_log.jsonl"
    ilog.write_text(("{\"phase\":\"after\",\"tool\":\"x\"}\n") * 40000)
    assert ilog.stat().st_size > 1024 * 1024
    bridge.log_integration(_after(tool="capped"))
    import json
    lines = ilog.read_text().strip().splitlines()
    assert len(lines) <= 2001
    assert json.loads(lines[-1])["tool"] == "capped"
