"""Tests P2 — emisiones advisories en rsi_cycle y bridge (G-34).

PLEASURE-CHANNEL-001 fase P2 (proposal design EVENTOS — fuentes wired):
  - socratic evaluate certified TRUE (rsi_cycle._log_event) -> unit=evaluate success=True
  - socratic evaluate certified FALSE -> success=False (probe A wiring
    2026-10-08: el fallo nativo por fin llega al ledger; ERROR no emite)
  - cierre de sesion limpio (bridge learn-pipeline stage) -> unit=session_close
Ambas advisory + fail-open: jamas rompen su flujo huésped ni tocan
alerts.jsonl (F2). Aislamiento: RSI_PLEASURE_FILE (conftest + monkeypatch),
VOSLAB_PATH/VOS_ROOT a tmp — cero escrituras en estado real.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from vos_kernel import pleasure_emitter as pe

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "pleasure.jsonl"
    monkeypatch.setenv("RSI_PLEASURE_FILE", str(path))
    return path


# ── rsi_cycle: socratic certified TRUE ──────────────────────────────────

def _cycle_stub(monkeypatch, tmp_path):
    import rsi_cycle  # kernel tests: conftest ya aiso envs RSI_*
    monkeypatch.setattr(rsi_cycle, "VOSLAB_PATH", tmp_path)
    return rsi_cycle, rsi_cycle.RSICycle.__new__(rsi_cycle.RSICycle)


def test_certified_true_emits_evaluate_pleasure(ledger, tmp_path, monkeypatch):
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "TRUE", "certified": True, "source": "op:AND",
         "evidence": {"ok": 1}},
        {},
    )
    recs = pe.read_history(ledger)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["unit"] == "evaluate" and rec["success"] is True
    assert rec["connection"] == "op:AND"
    assert "truth=TRUE cert=True" in rec["detail"]
    # el log huésped se escribio igual (emision jamas lo rompe)
    log = tmp_path / "logs" / "agent_plugin.jsonl"
    assert log.exists() and "evaluate" in log.read_text()


def test_not_certified_does_not_emit(ledger, tmp_path, monkeypatch):
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "TRUE", "certified": False, "source": "op:AND"},
        {},
    )
    assert not ledger.exists() or pe.read_history(ledger) == []


# ── rsi_cycle: socratic certified FALSE (probe A wiring 2026-10-08) ────

def test_certified_false_emits_evaluate_deception(ledger, tmp_path, monkeypatch):
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "FALSE", "certified": True, "source": "action_forbidden",
         "evidence": {"cmd": "rm -rf /"}},
        {},
    )
    recs = pe.read_history(ledger)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["unit"] == "evaluate" and rec["success"] is False
    assert rec["connection"] == "action_forbidden"
    assert "truth=FALSE cert=True" in rec["detail"]
    # el log huésped conserva su error (doble verdad: dolor + error host)
    log = tmp_path / "logs" / "agent_plugin.jsonl"
    assert log.exists() and "FALSE" in log.read_text()


def test_false_not_certified_does_not_emit(ledger, tmp_path, monkeypatch):
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "FALSE", "certified": False, "source": "op:AND"},
        {},
    )
    assert not ledger.exists() or pe.read_history(ledger) == []


def test_error_does_not_emit(ledger, tmp_path, monkeypatch):
    # ERROR sin decision certificada = ruido, no decepcion — no emite
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "ERROR", "certified": True, "source": "op:AND"},
        {},
    )
    assert not ledger.exists() or pe.read_history(ledger) == []


def test_custom_action_events_do_not_emit(ledger, tmp_path, monkeypatch):
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event("state.reconcile", {"truth": "TRUE", "certified": True},
                    {}, action="reconcile custom")
    assert not ledger.exists() or pe.read_history(ledger) == []


def test_emitter_failure_is_fail_open_for_logging(ledger, tmp_path, monkeypatch):
    # ledger en un path increable (parent es un FILE) -> OSError interna
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setenv("RSI_PLEASURE_FILE", str(blocker / "p.jsonl"))
    mod, inst = _cycle_stub(monkeypatch, tmp_path)
    inst._log_event(
        "evaluate",
        {"truth": "TRUE", "certified": True, "source": "op:X"},
        {},
    )
    log = tmp_path / "logs" / "agent_plugin.jsonl"
    assert log.exists()  # logging intacto pese al fallo del emisor


# ── bridge: cierre de sesion limpio ─────────────────────────────────────

@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / ".opencode" / "plugins" / "operational"))
    import tool_integration_bridge as b  # lazy (leccion 2026-09-12)
    monkeypatch.setattr(b, "VOS_ROOT", str(tmp_path))
    monkeypatch.setattr(b, "log_integration", lambda *a, **k: None)
    (tmp_path / "state" / "cache").mkdir(parents=True, exist_ok=True)
    return b


def _focus(root, entries):
    (root / "current_focus.json").write_text(json.dumps(entries))


def test_clean_focus_emits_session_close(bridge, tmp_path, ledger):
    _focus(tmp_path, [{"ref": "A", "status": "done"},
                      {"ref": "B", "status": "done"}])
    out = bridge._pleasure_session_close_stage()
    assert out["emitted"] is True
    recs = pe.read_history(ledger)
    assert len(recs) == 1
    assert recs[0]["unit"] == "session_close" and recs[0]["success"] is True
    assert recs[0]["connection"] == "__global__"
    assert recs[0]["detail"] == "2 focus done"
    # marker anti-duplicado persistido (transicion, no estado)
    marker = tmp_path / "state" / "cache" / ".pleasure_close_marker"
    assert marker.exists()


def test_repeat_idle_same_snapshot_does_not_reemit(bridge, tmp_path, ledger):
    _focus(tmp_path, [{"ref": "A", "status": "done"}])
    assert bridge._pleasure_session_close_stage()["emitted"] is True
    again = bridge._pleasure_session_close_stage()
    assert again["emitted"] is False
    assert again["reason"] == "snapshot unchanged"
    assert len(pe.read_history(ledger)) == 1


def test_dirty_focus_does_not_emit(bridge, tmp_path, ledger):
    _focus(tmp_path, [{"ref": "A", "status": "done"},
                      {"ref": "B", "status": "active"}])
    out = bridge._pleasure_session_close_stage()
    assert out["emitted"] is False
    assert out["reason"] == "focus not all done"
    assert not ledger.exists()


def test_empty_or_missing_focus_does_not_emit(bridge, tmp_path, ledger):
    out = bridge._pleasure_session_close_stage()
    assert out["emitted"] is False and out["reason"] == "no focus file"
    _focus(tmp_path, [])
    out = bridge._pleasure_session_close_stage()
    assert out["emitted"] is False and out["reason"] == "no focus entries"


def test_new_clean_snapshot_reemits(bridge, tmp_path, ledger):
    _focus(tmp_path, [{"ref": "A", "status": "done"}])
    assert bridge._pleasure_session_close_stage()["emitted"] is True
    _focus(tmp_path, [{"ref": "A", "status": "done"},
                      {"ref": "B", "status": "done"}])
    assert bridge._pleasure_session_close_stage()["emitted"] is True
    assert len(pe.read_history(ledger)) == 2


def test_broken_focus_file_is_fail_open(bridge, tmp_path, ledger):
    (tmp_path / "current_focus.json").write_text("{no-json")
    out = bridge._pleasure_session_close_stage()
    assert out["emitted"] is False
    assert out["reason"].startswith("fail-open:")
    assert not ledger.exists()
