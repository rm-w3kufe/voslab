"""Tests P3 — feedback Hebbiano del canal de placer (G-34).

PLEASURE-CHANNEL-001 fase P3 (proposal HEBBIAN-FEEDBACK):
  - trust: spill {ts,tool:"pleasure",file:<connection>,ok:true} ->
    RiskAssessor +0.05 asimetrico (drain productivo, cap 1.0)
  - pesos: vsf_rsi.adaptive_weights.record_outcome(component,
    quality=min(WeightConfig.drift_max, magnitud)) — techo por epoca
    reutiliza drift_max (proposal: "reuse drift_max=0.95 de WeightConfig")
  - solo pleasure_event (emissions no vacias) potencian; kill-switch
    VOS_PLEASURE_FEEDBACK=0; fail-open por efecto; F2: jamas alerts.

Aislamiento total: ledger + spill en tmp, _manager de adaptive_weights
reemplazado por spy — cero escrituras en estado real.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from vos_kernel import pleasure_emitter as pe

_RSI_PATH = str(pe.WORKSPACE / "packages" / "public" / "vsf-rsi")


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    ledger = tmp_path / "pleasure.jsonl"
    spill = tmp_path / "trust_spill.jsonl"
    monkeypatch.setenv("RSI_PLEASURE_FILE", str(ledger))
    monkeypatch.setenv("RSI_TRUST_SPILL_FILE", str(spill))
    monkeypatch.delenv("VOS_PLEASURE_FEEDBACK", raising=False)
    if _RSI_PATH not in sys.path:
        sys.path.insert(0, _RSI_PATH)
    from vsf_rsi import adaptive_weights as aw

    class SpyManager:
        def __init__(self):
            self.calls: list[tuple[str, float]] = []
            self.saves = 0

        def record_outcome(self, component, quality, **kw):
            self.calls.append((component, round(float(quality), 6)))

        def save(self):
            self.saves += 1

    spy = SpyManager()
    monkeypatch.setattr(aw, "_manager", spy)
    return SimpleNamespace(spy=spy, spill=spill, ledger=ledger, aw=aw)


def _spill_lines(spill):
    if not spill.exists():
        return []
    return [json.loads(x) for x in spill.read_text().splitlines() if x.strip()]


def test_emit_default_is_feedback_off(wired):
    pe.emit("gate_run", True, ts="2026-10-07T01:00:00Z",
            connection="checks/x", path=wired.ledger)   # feedback=False default
    rec = pe.read_history(wired.ledger)
    assert rec and rec[0]["emissions"] != []   # hubo pleasure_event
    assert _spill_lines(wired.spill) == []      # pero sin hebbiano
    assert wired.spy.calls == []


def test_emit_with_feedback_applies_trust_and_weights(wired):
    rec = pe.emit("gate_run", True, ts="2026-10-07T01:00:00Z",
                  detail="81/81", connection="checks/run_gates",
                  path=wired.ledger, feedback=True)
    assert rec["emissions"] != []               # primer dato: RPE=1
    lines = _spill_lines(wired.spill)
    assert len(lines) == 1
    assert lines[0]["file"] == "checks/run_gates"
    assert lines[0]["ok"] is True and lines[0]["tool"] == "pleasure"
    # techo: magnitud 1.0 -> quality clamped a drift_max (0.95)
    assert wired.spy.calls == [
        ("checks/run_gates", round(wired.aw.WeightConfig().drift_max, 6))
    ]


def test_silent_event_applies_nothing(wired):
    # historia 100% verde en ventana -> sin emisiones -> sin refuerzo
    for h in range(1, 4):
        pe.emit("gate_run", True, ts=f"2026-10-01T0{h}:00:00Z", path=wired.ledger)
    rec = pe.emit("gate_run", True, ts="2026-10-01T04:00:00Z",
                  path=wired.ledger, feedback=True)
    assert rec["emissions"] == []               # rutina: RPE=0, hito p_m=1
    assert _spill_lines(wired.spill) == []
    assert wired.spy.calls == []


def test_failure_event_applies_nothing(wired):
    rec = pe.emit("gate_run", False, ts="2026-10-07T01:00:00Z",
                  path=wired.ledger, feedback=True)
    assert rec["emissions"] == []               # el dolor jamas refuerza (F2)
    assert _spill_lines(wired.spill) == []
    assert wired.spy.calls == []


def test_ceiling_reuses_drift_max_for_big_magnitude(wired):
    # bits 2.94 (sorpresa de racha grande) -> quality tope drift_max
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "gate_run",
          "connection": "checks/big",
          "emissions": [{"kind": "milestone", "magnitude": 2.94,
                         "magnitude_unit": "bits", "streak": 5}]}
    out = pe.apply_hebbian(ev)
    assert "weights" in out["effects"]
    assert out["quality"] == wired.aw.WeightConfig().drift_max == 0.95
    assert wired.spy.calls == [("checks/big", 0.95)]


def test_small_rpe_quality_is_unclamped(wired):
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "evaluate",
          "connection": "op:AND",
          "emissions": [{"kind": "rpe", "magnitude": 0.125,
                         "magnitude_unit": "rpe"}]}
    out = pe.apply_hebbian(ev)
    assert out["quality"] == 0.125
    assert wired.spy.calls == [("op:AND", 0.125)]


def test_kill_switch_disables_all_effects(wired, monkeypatch):
    monkeypatch.setenv("VOS_PLEASURE_FEEDBACK", "0")
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "gate_run",
          "connection": "c",
          "emissions": [{"kind": "rpe", "magnitude": 1.0,
                         "magnitude_unit": "rpe"}]}
    out = pe.apply_hebbian(ev)
    assert out["effects"] == [] and out["reason"] == "disabled"
    assert _spill_lines(wired.spill) == []
    assert wired.spy.calls == []


def test_default_connection_is_global(wired):
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "session_close",
          "emissions": [{"kind": "rpe", "magnitude": 1.0,
                         "magnitude_unit": "rpe"}]}
    pe.apply_hebbian(ev)
    assert _spill_lines(wired.spill)[0]["file"] == "__global__"


def test_trust_spill_failure_is_fail_open(wired, tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setenv("RSI_TRUST_SPILL_FILE", str(blocker / "spill.jsonl"))
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "gate_run",
          "connection": "c",
          "emissions": [{"kind": "rpe", "magnitude": 1.0,
                         "magnitude_unit": "rpe"}]}
    out = pe.apply_hebbian(ev)                   # jamas lanza
    assert any(e.startswith("trust-spill:fail-open") for e in out["effects"])
    assert "weights" in out["effects"]           # el otro efecto sigue


def test_weights_failure_is_fail_open(wired, monkeypatch):
    monkeypatch.setitem(sys.modules, "vsf_rsi", None)  # ImportError forzado
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "gate_run",
          "connection": "c",
          "emissions": [{"kind": "rpe", "magnitude": 1.0,
                         "magnitude_unit": "rpe"}]}
    out = pe.apply_hebbian(ev)                   # jamas lanza
    assert any(e.startswith("weights:fail-open") for e in out["effects"])
    assert "trust-spill" in out["effects"]       # trust aplica igual
    assert len(_spill_lines(wired.spill)) == 1


def test_feedback_jamais_touched_alerts(wired):
    # F2: la ruta hebbiana no sabe que alerts.jsonl existe
    ev = {"ts": "2026-10-07T01:00:00Z", "unit": "gate_run",
          "connection": "c",
          "emissions": [{"kind": "rpe", "magnitude": 1.0,
                         "magnitude_unit": "rpe"}]}
    pe.apply_hebbian(ev)
    assert "alerts" not in wired.spill.read_text()
    src = Path(pe.__file__).read_text()
    assert "import alerting" not in src and "AlertMonitor" not in src
