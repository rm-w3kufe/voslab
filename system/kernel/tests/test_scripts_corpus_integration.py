"""test_scripts_corpus_integration.py — RSI integration of the migrated
~/vsf scripts corpus (S5 2026-10-02: "todos los scripts tienen que
integrarse al pipeline socratic engine RSI; nada corre desde ~/vsf").

Covers:
  - scripts_migrated_ok / scripts_corpus_manifest_ok semantics
    (TRUE in workspace, fail-open without workspace, FALSE on concrete
    evidence — R10 deterministic, no I/O beyond stat/read)
  - registration through RSICycle's PREDICATES dict
  - evaluate_action's tree actually wires the new predicates
  - the corpus manifest machine contract (family:/file: lines)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import stub_predicates as sp
from socratic_engine import Truth


# ─── predicate semantics ────────────────────────────────────────────────────

def test_predicates_true_in_workspace():
    """In vOSlab the migrated corpus + manifest are complete → TRUE."""
    r1 = sp.scripts_migrated_ok()
    assert r1.truth == Truth.TRUE, r1.evidence
    assert r1.source == "scripts_migrated_ok"
    assert r1.evidence["missing"] == []
    assert r1.evidence["beacon_ca"] is True

    r2 = sp.scripts_corpus_manifest_ok()
    assert r2.truth == Truth.TRUE, r2.evidence
    assert r2.evidence["missing_families"] == []
    assert r2.evidence["covered"] >= 17


def test_fail_open_without_workspace(monkeypatch):
    """No current_focus.json anywhere → fail-open TRUE (state_consistent rule)."""
    monkeypatch.setattr(sp, "_find_workspace", lambda *a, **k: None)
    assert sp.scripts_migrated_ok().truth == Truth.TRUE
    r = sp.scripts_corpus_manifest_ok()
    assert r.truth == Truth.TRUE
    assert "fail-open" in r.evidence["reason"]


def _fake_ws(tmp_path: Path) -> Path:
    (tmp_path / "current_focus.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_missing_family_is_false(tmp_path, monkeypatch):
    """Absent family dir = concrete evidence → FALSE with names."""
    ws = _fake_ws(tmp_path)
    (ws / "scripts" / "algedonic").mkdir(parents=True)
    (ws / "scripts" / "algedonic" / "x.py").write_text("# x\n")
    monkeypatch.setattr(sp, "_find_workspace", lambda *a, **k: ws)
    r = sp.scripts_migrated_ok()
    assert r.truth == Truth.FALSE
    assert "vsl" in r.evidence["missing"]
    assert r.evidence["beacon_ca"] is False


def test_empty_family_is_false(tmp_path, monkeypatch):
    """A family dir that exists but is empty counts as drift."""
    ws = _fake_ws(tmp_path)
    (ws / "_beacon_ca").mkdir()
    for fam in sp._MIGRATED_SCRIPT_FAMILIES:
        (ws / "scripts" / fam).mkdir(parents=True, exist_ok=True)
    # all families empty → empty list populated
    monkeypatch.setattr(sp, "_find_workspace", lambda *a, **k: ws)
    r = sp.scripts_migrated_ok()
    assert r.truth == Truth.FALSE
    assert "state" in r.evidence["empty"]


def test_corpus_manifest_missing_is_false(tmp_path, monkeypatch):
    ws = _fake_ws(tmp_path)
    monkeypatch.setattr(sp, "_find_workspace", lambda *a, **k: ws)
    r = sp.scripts_corpus_manifest_ok()
    assert r.truth == Truth.FALSE
    assert "update_scripts_manifest.py" in r.evidence["hint"]


def test_corpus_manifest_family_coverage(tmp_path, monkeypatch):
    """Manifest parses the machine contract: family:<name>:<count>."""
    ws = _fake_ws(tmp_path)
    target = ws / "system" / "instance" / "vsf-instance-v1"
    target.mkdir(parents=True)
    real = (Path(__file__).resolve().parents[3] / "system" / "instance" /
            "vsf-instance-v1" / "scripts_manifest.vsm")
    (target / "scripts_manifest.vsm").write_text(
        real.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sp, "_find_workspace", lambda *a, **k: ws)
    r = sp.scripts_corpus_manifest_ok()
    assert r.truth == Truth.TRUE, r.evidence
    assert r.evidence["covered"] >= 17


def test_manifest_file_lists_are_sha16():
    """Every file: line carries a 16-hex digest (deterministic census)."""
    real = (Path(__file__).resolve().parents[3] / "system" / "instance" /
            "vsf-instance-v1" / "scripts_manifest.vsm")
    checked = 0
    for line in real.read_text(encoding="utf-8").splitlines():
        if line.startswith("file:"):
            digest = line.rsplit(":", 1)[-1]
            assert len(digest) == 16 and all(c in "0123456789abcdef"
                                             for c in digest), line
            checked += 1
    assert checked > 100


# ─── registration + wiring ─────────────────────────────────────────────────

def test_registered_in_cycle_predicates():
    import rsi_cycle
    names = rsi_cycle.RSICycle().get_predicates()
    for n in ("scripts_migrated_ok", "scripts_corpus_manifest_ok",
              "scripts_manifest"):
        assert n in names, f"{n} not registered in RSICycle"


def test_evaluate_action_tree_wires_scripts_predicates():
    """The full action gate (bridge.evaluate_action) evaluates both."""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / ".opencode" / "plugins" / "operational"))
    import inspect
    import tool_integration_bridge as b  # lazy (isolation discipline)
    src = inspect.getsource(b.evaluate_action)
    assert '"predicate": "scripts_migrated_ok"' in src
    assert '"predicate": "scripts_corpus_manifest_ok"' in src
