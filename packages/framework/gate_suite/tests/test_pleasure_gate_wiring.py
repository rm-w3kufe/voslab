"""Tests P2 — transiciones rojo→verde del gate suite -> placer (G-34).

PLEASURE-CHANNEL-001 fase P2: `_pleasure_gate_transitions` emite SOLO en
cambios reales rojo→verde (primera corrida sin baseline no celebra),
fail-open ante estado corrupto, y jamas toca el rc. Ledger aislado por
RSI_PLEASURE_FILE; estado previo por VOS_GATE_TRANSITIONS_FILE (ambos
tmp por test).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_FRAMEWORK_DIR = str(Path(__file__).resolve().parents[1])
if _FRAMEWORK_DIR not in sys.path:
    sys.path.insert(0, _FRAMEWORK_DIR)

from gate_suite.harness import _pleasure_gate_transitions  # noqa: E402

from vos_kernel import pleasure_emitter as pe  # noqa: E402


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    state = tmp_path / "gate_last_results.json"
    ledger = tmp_path / "pleasure.jsonl"
    monkeypatch.setenv("VOS_GATE_TRANSITIONS_FILE", str(state))
    monkeypatch.setenv("RSI_PLEASURE_FILE", str(ledger))
    # P3 hebbiano suspendido aqui (se prueba aislado en test_pleasure_feedback)
    monkeypatch.setenv("VOS_PLEASURE_FEEDBACK", "0")
    return state, ledger


def _records(ledger):
    return pe.read_history(ledger) if ledger.exists() else []


def test_first_run_without_baseline_does_not_celebrate(wired):
    state, ledger = wired
    _pleasure_gate_transitions([("check-a", 0), ("check-b", 1)])
    assert state.exists()  # baseline persistida
    assert _records(ledger) == []  # sin previo -> sin celebracion


def test_red_to_green_emits_pleasure_event(wired):
    state, ledger = wired
    _pleasure_gate_transitions([("check-a", 1), ("check-b", 1)])  # baseline rojo
    _pleasure_gate_transitions([("check-a", 0), ("check-b", 1)])  # a recupera
    recs = _records(ledger)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["unit"] == "gate_run" and rec["success"] is True
    assert "check-a" in rec["detail"]
    assert rec["connection"] == "checks/check-a"
    assert rec["emissions"] != []  # hubo sorpresa positiva (p<1 o primer dato)


def test_green_to_green_does_not_reemit(wired):
    state, ledger = wired
    _pleasure_gate_transitions([("check-a", 1)])
    _pleasure_gate_transitions([("check-a", 0)])   # emite
    _pleasure_gate_transitions([("check-a", 0)])   # ya verde: silencio
    _pleasure_gate_transitions([("check-a", 0)])   # idem
    assert len(_records(ledger)) == 1


def test_green_to_red_emits_nothing_then_red_to_green_again(wired):
    state, ledger = wired
    _pleasure_gate_transitions([("check-a", 0)])   # baseline verde
    _pleasure_gate_transitions([("check-a", 1)])   # cae: dolor (alerts) no placer
    assert _records(ledger) == []
    _pleasure_gate_transitions([("check-a", 0)])   # se recupera: celebra
    assert len(_records(ledger)) == 1


def test_new_check_appearing_is_not_a_transition(wired):
    state, ledger = wired
    _pleasure_gate_transitions([("check-a", 1)])
    _pleasure_gate_transitions([("check-a", 1), ("check-new", 0)])
    assert _records(ledger) == []  # check nuevo verde no es rojo→verde


def test_corrupt_baseline_is_fail_open(wired):
    state, ledger = wired
    state.write_text("{{{corrupt")
    _pleasure_gate_transitions([("check-a", 0)])   # no lanza, no celebra
    assert _records(ledger) == []
    # y a partir de ahi la baseline vuelve a funcionar
    _pleasure_gate_transitions([("check-a", 1)])
    _pleasure_gate_transitions([("check-a", 0)])
    assert len(_records(ledger)) == 1

# ── P5: gate pleasure-channel (NC 22 -> 23) ─────────────────────────────────

class TestPleasureChannelGate:
    """Gate python del canal: vivo acepta, fixture R17 siempre rechaza."""

    @staticmethod
    def _gate():
        from gate_suite.gates import pleasure_channel as g
        return g

    @staticmethod
    def _ledger(root: Path, rows) -> None:
        rsi = root / "state" / "rsi"
        rsi.mkdir(parents=True, exist_ok=True)
        (rsi / "pleasure.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8")

    @staticmethod
    def _event(**over):
        ev = {"event_id": "pev-t", "ts": "2026-10-07T12:00:00Z",
              "unit": "gate_run", "success": True, "p": 0.5, "rpe": 0.5,
              "streak": 1, "emissions": [], "detail": "t",
              "source": "test", "connection": "checks/x"}
        ev.update(over)
        return ev

    def test_live_workspace_channel_alive(self, capsys):
        # el workspace real tiene canal vivo (>=1 evento valido)
        assert self._gate().check("") == 0

    def test_negative_case_always_rejected_r17(self, capsys):
        path = self._gate().negative_case()
        rc = self._gate().check(path)
        err = capsys.readouterr().err
        assert rc != 0
        assert "auto_exec" in err and "R17" in err

    def test_missing_ledger_rejected(self, tmp_path, capsys):
        (tmp_path / "state" / "rsi").mkdir(parents=True)
        assert self._gate().check(str(tmp_path)) != 0
        assert "ledger missing" in capsys.readouterr().err

    def test_corrupt_event_rejected(self, tmp_path, capsys):
        self._ledger(tmp_path, [self._event(ts="not-a-date")])
        assert self._gate().check(str(tmp_path)) != 0
        assert "ts not ISO" in capsys.readouterr().err

    def test_undeclared_field_rejected(self, tmp_path, capsys):
        self._ledger(tmp_path, [self._event(shadow_field=1)])
        assert self._gate().check(str(tmp_path)) != 0
        assert "shadow_field" in capsys.readouterr().err

    def test_valid_fixture_accepted(self, tmp_path, capsys):
        self._ledger(tmp_path, [
            self._event(),
            self._event(event_id="pev-t2",
                        emissions=[{"kind": "rpe", "magnitude": 0.5,
                                    "magnitude_unit": "rpe"}]),
        ])
        assert self._gate().check(str(tmp_path)) == 0

