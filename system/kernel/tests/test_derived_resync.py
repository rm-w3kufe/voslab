"""test_derived_resync.py — P-EV-R2 auto-resync de derived blocks.

R10: todas las funciones son deterministas (mismo input → mismo output),
sin clock ni aleatoriedad en las decisiones. Los tests usan fixtures en
tmp; el parser del manifest se reutiliza del verifier (fuente única).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "scripts" / "vsl" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import derived_resync as dr  # noqa: E402


def _mk_manifest(tmp: Path, pin: str, rel: str = "kernel/foo.py") -> Path:
    """Minimal manifest with ONE string-path pin (the parsed form)."""
    m = tmp / "boot_manifest.vsm"
    m.write_text(
        '@vsm 1.0\nmanifest("boot") {\n'
        f'  artifact("{rel}",\n'
        f'           layer=occasion, role=evaluates, hash="{pin}",\n'
        f'           owner="test") {{}},\n'
        '  artifact(@doc_covenant,\n'
        '           layer=canon, role=declares, hash="15685d39de3cfae7",\n'
        '           owner="test") {{}},\n'
        '  artifact("state/mcp.service",\n'
        '           layer=mcp, role=serves, hash="runtime service (no file)",\n'
        '           owner="test") {{}},\n'
        "}\n"
    )
    return m


def test_check_boot_pins_detects_stale_and_clean(tmp_path, monkeypatch):
    """Pin viejo → drift; pin actualizado → clean. Determinista."""
    f = tmp_path / "kernel" / "foo.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    real = dr.sha16(f)
    man = _mk_manifest(tmp_path, pin="0000000000000000")
    monkeypatch.setattr(dr, "MANIFEST", man)
    monkeypatch.setattr(dr, "ROOT", tmp_path)

    drift = dr.check_boot_pins(base=tmp_path)
    assert len(drift) == 1
    assert drift[0]["path"] == "kernel/foo.py"
    assert drift[0]["disk"] == real

    # apply reescribe el pin → segunda pasada clean
    n = dr.apply_boot_pins(drift)
    assert n == 1
    assert dr.check_boot_pins(base=tmp_path) == []
    assert f'hash="{real}"' in man.read_text()


def test_boot_pins_skip_symbolic_and_runtime(tmp_path, monkeypatch):
    """@ids canónicos y 'runtime service' no se hash-comparan (no son files)."""
    f = tmp_path / "kernel" / "foo.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    man = _mk_manifest(tmp_path, pin=dr.sha16(f))
    monkeypatch.setattr(dr, "MANIFEST", man)
    monkeypatch.setattr(dr, "ROOT", tmp_path)
    assert dr.check_boot_pins(base=tmp_path) == []


def test_missing_file_reported_never_pin_deleted(tmp_path, monkeypatch):
    """File ausente: reporte honesto, el pin NO se borra (R9/R17-ish)."""
    man = _mk_manifest(tmp_path, pin="0000000000000000", rel="kernel/gone.py")
    monkeypatch.setattr(dr, "MANIFEST", man)
    monkeypatch.setattr(dr, "ROOT", tmp_path)
    drift = dr.check_boot_pins(base=tmp_path)
    assert len(drift) == 1 and drift[0]["disk"] is None
    n = dr.apply_boot_pins(drift)
    assert n == 0
    assert 'hash="0000000000000000"' in man.read_text()  # pin intacto


def test_scripts_fingerprint_deterministic_and_sensitive(tmp_path):
    """Mismo árbol → mismo fp; un byte cambia → fp cambia; pyc ignorado (R10)."""
    (tmp_path / "scripts" / "a").mkdir(parents=True)
    (tmp_path / "scripts" / "a" / "tool.py").write_text("v = 1\n")
    fp1 = dr.scripts_fingerprint(tmp_path)
    assert fp1 == dr.scripts_fingerprint(tmp_path)  # determinista

    (tmp_path / "scripts" / "a" / "tool.py").write_text("v = 22\n")
    fp2 = dr.scripts_fingerprint(tmp_path)
    assert fp2 != fp1  # el contenido cambió → fp cambia

    # __pycache__/.pyc no contaminan el fingerprint
    (tmp_path / "scripts" / "a" / "__pycache__").mkdir()
    (tmp_path / "scripts" / "a" / "__pycache__" / "tool.cpython-314.pyc").write_bytes(b"\x00")
    assert dr.scripts_fingerprint(tmp_path) == fp2


def test_stamp_roundtrip_and_resync_report(tmp_path, monkeypatch):
    """resync() sin apply: reporta stale sin tocar el stamp; apply con
    tool ausente → regenerated False y stamp intacto (solo se estampa
    cuando el regen real corrió ok)."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "s.py").write_text("q = 1\n")
    # fixture file para el pin del manifest (si no existe → disk None, no reescribible)
    (tmp_path / "kernel").mkdir(parents=True)
    (tmp_path / "kernel" / "foo.py").write_text("x = 1\n")
    monkeypatch.setattr(dr, "ROOT", tmp_path)
    monkeypatch.setattr(dr, "STAMP", tmp_path / "state" / "stamp.json")
    # SAFETY: jamas invocar el generator real desde un test (regeneraría
    # los manifests del repo vivo) — apuntar a un tool inexistente.
    monkeypatch.setattr(dr, "SCRIPTS_MANIFEST_TOOL", tmp_path / "no_tool.py")
    man = _mk_manifest(tmp_path, pin="0000000000000000")
    monkeypatch.setattr(dr, "MANIFEST", man)
    # tasks_reconcile inexistente en el tmp → reporte de error, nunca raise
    rep = dr.resync(apply=False)
    assert rep["ok"] is False
    assert rep["scripts"]["stale"] is True
    assert not dr.STAMP.exists()  # check jamas escribe

    # apply: boot pins + sin stamp (tool ausente → regenerated False)
    rep2 = dr.resync(apply=True)
    assert rep2["boot_pins"] == []  # post-apply clean
    assert rep2["scripts"].get("regenerated") is False
    assert not dr.STAMP.exists()
