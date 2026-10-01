"""Tests for A-8 — integrate_modules: modules via canal (EP-5 added the
third module, round_runner, as registered PRC).

Evidencia exigida por el backlog: registration + verify events +
BackboneEvent por los 7 steps, sin rewrite de los modulos. Assertions
derive from im.MODULES (registry keys = file stems) so future module
registrations do not break the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vos_kernel.backbone import integrate_modules as im
from vos_kernel.backbone.backbone import Backbone
from vos_kernel.backbone.backbone_event import Step

STEPS = [s.value for s in Step]


def expected_registry_keys() -> set[str]:
    """Registry key = module file stem (unique stems -> unique keys)."""
    return {Path(rel).stem for rel in im.MODULES.values()}


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


def test_all_modules_integrate_end_to_end(state_dir):
    outcomes = im.integrate(state_dir)
    assert set(outcomes) == set(im.MODULES)
    assert all(outcomes.values())


def test_registry_records_all_modules(state_dir):
    im.integrate(state_dir)
    registry = json.loads((state_dir / "component_registry.json").read_text())
    assert set(registry) == expected_registry_keys()
    assert all(rec["type"] == "script" for rec in registry.values())
    assert registry["graph"]["status"] == "active"  # set by step_activate
    assert registry["round_runner"]["status"] == "active"  # EP-5 PRC


def test_backbone_status_reaches_monitor_ok(state_dir):
    backbone = Backbone(state_dir=state_dir)
    im.integrate(state_dir)
    status = backbone.get_status()
    assert len(status) == len(im.MODULES)
    for comp, comp_status in status.items():
        assert comp_status["current_step"] == "monitor", comp
        assert comp_status["status"] == "ok", comp
        assert [h["step"] for h in comp_status["history"]] == STEPS


def test_seven_events_per_module_in_order(state_dir):
    backbone = Backbone(state_dir=state_dir)
    im.integrate(state_dir)
    events = backbone.get_events(limit=100)
    assert len(events) == len(STEPS) * len(im.MODULES)  # 7 steps x N modules
    for comp in {e["component"] for e in events}:
        steps = [e["step"] for e in events if e["component"] == comp]
        assert steps == STEPS, comp
        assert all(e["status"] == "ok" for e in events if e["component"] == comp)


def test_module_filter_selects_one(state_dir):
    outcomes = im.integrate(state_dir, only="trace_graph")
    assert outcomes == {"trace_graph": True}
    registry = json.loads((state_dir / "component_registry.json").read_text())
    assert set(registry) == {"graph"}


def test_missing_module_fails_at_route(state_dir, monkeypatch):
    monkeypatch.setattr(im, "MODULES", {"ghost": "packages/nope/ghost.py"})
    outcomes = im.integrate(state_dir)
    assert outcomes == {"ghost": False}
    backbone = Backbone(state_dir=state_dir)
    events = backbone.get_events(limit=10)
    assert events[0]["step"] == "route"
    assert events[0]["status"] == "error"


def test_syntax_error_fails_lifecycle(state_dir, monkeypatch, tmp_path):
    broken = tmp_path / "broken_mod.py"
    broken.write_text("def broken(\n")
    monkeypatch.setattr(im, "MODULES", {"broken_mod": str(broken)})
    outcomes = im.integrate(state_dir)
    assert outcomes == {"broken_mod": False}
    backbone = Backbone(state_dir=state_dir)
    # failed step is logged as an ERROR event before abort
    err = [e for e in backbone.get_events(limit=10) if e["status"] == "error"]
    assert err and err[0]["step"] in ("verify", "evaluate")


def test_main_exit_code_zero(state_dir, capsys):
    rc = im.main(["--state-dir", str(state_dir)])
    assert rc == 0
    assert "OK   trace_graph" in capsys.readouterr().out


def test_main_exit_code_one_on_failure(state_dir, monkeypatch, tmp_path):
    broken = tmp_path / "broken_mod.py"
    broken.write_text("def broken(\n")
    monkeypatch.setattr(im, "MODULES", {"broken_mod": str(broken)})
    rc = im.main(["--state-dir", str(state_dir), "--module", "broken_mod"])
    assert rc == 1


def test_deterministic_outcomes(state_dir):
    """R10: mismo input -> mismo output."""
    first = im.integrate(state_dir)
    second = im.integrate(state_dir)
    assert first == second
