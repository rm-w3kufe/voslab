# design: docs/evaluation/system_evaluation_2026_10_14.vsm (SUT: scripts/vsl/tools/extractor_vacuity.py)
"""Tests EV-R3 / P-EV-R3 — anti-vacuity battery + gate (extractor-vacuity).

EV-R3 rubrica D5-C1/D5-C3: un extractor sin fuente debe GRIITAR. Live
provenance (2026-10-15): version_scan.py resolvio ROOT con dirname³ desde
su antigua casa scripts/vsl/ tras la mudanza a scripts/vsl/tools/ →
CORPUS muerto → 0 lineas rc=0 → vsm-version-coherent PASS vacio
(FND-VERSION-SCAN-ROOT-OFFBYONE). Estos tests bloquean la clase:

  - battery live: 4/4 probes con evidencia positiva (count > 0)
  - target vacio / inexistente / sin headers → rechazado (empty ≠ healthy)
  - fixture valida → aceptada (discrimina, no es always-fail)
  - determinismo R10: mismo input → mismo rc
  - registro del gate NC + negative_case rechazado siempre
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_GATE_SUITE = str(Path(__file__).resolve().parents[1])
if _GATE_SUITE not in sys.path:
    sys.path.insert(0, _GATE_SUITE)

# scripts/ es tooling plano (sin __init__.py): cargar el driver por path.
_REPO = Path(__file__).resolve().parents[4]
_TOOLS = _REPO / "scripts" / "vsl" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from gate_suite import gates as gates_pkg  # noqa: E402  (registers gates)
from gate_suite.harness import GATES  # noqa: E402
from gate_suite.gates import extractor_vacuity as ev  # noqa: E402

import extractor_vacuity as driver  # noqa: E402

VALID_DOC = (
    "⟦ ev_r3_fixture | T-v1 | vsm-1.2.1 | 2026-10-15T14:52:41Z ⟧\n"
    "\n@vsm 1.2.1\n@status active\n\n// fixture\n\n"
    "⟦ /ev_r3_fixture ⟧\n"
)
HEADERLESS = "// just a comment\nno header here\n"


def _tmp_target(tmp_path: Path, content: str, name: str = "doc.vsm") -> Path:
    root = tmp_path / "corpus"
    root.mkdir(exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")
    return root


# ── battery: live evidence (positive counts, never empty-is-healthy) ────────

def test_live_gate_battery_non_vacuous():
    """check('') runs the live battery: every probe must extract >0."""
    assert ev.check("") == 0


def test_live_battery_reports_all_probes(capfd):
    # capfd: la bateria corre como subprocess, su stdout viaja por fd.
    assert ev.check("") == 0
    out = capfd.readouterr().out
    for probe in ("version_scan", "lifecycle_census", "dep_graph", "doc_manifest"):
        assert probe in out, f"probe {probe} missing from battery report"
    assert "4/4 probes non-vacuous" in out


# ── the vacuity class: vanished source must be rejected ─────────────────────

def test_empty_target_rejected(tmp_path):
    """Empty corpus = source vanished, never '0 findings = clean'."""
    empty = tmp_path / "vanished"
    empty.mkdir()
    assert driver.probe_version_scan(empty)[0] is False
    assert ev.check(str(empty)) != 0


def test_missing_target_rejected(tmp_path):
    assert ev.check(str(tmp_path / "does-not-exist")) != 0


def test_headerless_corpus_rejected(tmp_path):
    """No headers → distribution empty → unverifiable ≠ healthy."""
    root = _tmp_target(tmp_path, HEADERLESS, name="plain.vsm")
    ok, detail = driver.probe_version_scan(root)
    assert ok is False
    assert "DISTRIBUTION" in detail or "counted nothing" in detail


# ── discriminant, not always-fail: a healthy fixture passes ─────────────────

def test_valid_fixture_accepted(tmp_path):
    root = _tmp_target(tmp_path, VALID_DOC)
    ok, detail = driver.probe_version_scan(root)
    assert ok is True, detail
    assert ev.check(str(root)) == 0


def test_battery_deterministic_r10(tmp_path):
    """R10: same input → same verdict (no clock, no randomness)."""
    root = _tmp_target(tmp_path, VALID_DOC)
    assert ev.check(str(root)) == ev.check(str(root))


def test_driver_executable_as_script(tmp_path):
    """The battery is a tool: runs standalone, rc propagates."""
    root = _tmp_target(tmp_path, VALID_DOC)
    script = Path(ev._DRIVER)
    r = subprocess.run(
        [sys.executable, str(script), "--target", str(root)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ── gate wiring: NC registration + negative case ALWAYS rejected ────────────

def test_gate_registered_with_negative_case():
    names = [g.name for g in GATES]
    assert "extractor-vacuity" in names, gates_pkg.__name__


def test_negative_case_always_rejected():
    """NC24: empty temp corpus must be rejected by check()."""
    path = ev.negative_case()
    try:
        assert Path(path).is_dir()
        assert not list(Path(path).rglob("*.vsm"))
        assert ev.check(path) != 0
    finally:
        shutil.rmtree(path, ignore_errors=True)
