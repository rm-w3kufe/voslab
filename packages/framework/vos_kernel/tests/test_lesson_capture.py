# design: docs/plans/lesson_capture_protocol.vsm
"""Tests de lesson_capture (O1, P-A-LEARN-DISTILL ratificado 2026-10-15).

Cubre las contenciones C1/C2/C5 del protocolo sin invocar el real sobre
state/lessons/: tmp_path + monkeypatch de LESSONS/INDEX (R10 determinista,
sin reloj salvo _now espurio controlado).

Design: docs/plans/lesson_capture_protocol.vsm
"""
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _ROOT / "scripts/state/lessons/lesson_capture.py"

GOOD = {
    "claim": "el claim canonico exige provenance completa",
    "porque": "C1 sin fuente_ts+session_id no permite trazar la leccion",
    "alternativas": "aceptar lecciones sin fuente (truth-decay silencioso)",
    "fuente_ts": "2026-10-15T19:11:07Z",
    "session_id": "ses_unit_test_2026_10_15",
}


def _run(args, cwd=_ROOT):
    return subprocess.run([sys.executable, str(_SCRIPT)] + args,
                          capture_output=True, text=True, cwd=cwd, timeout=30)


def test_c1_missing_fields_rejected():
    r = _run(["--lesson", json.dumps({"claim": "x"})])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "C1" in r.stderr and "missing required" in r.stderr


def test_c1_bad_timestamp_rejected():
    bad = dict(GOOD, fuente_ts="2026-10-15 19:00:00")
    r = _run(["--lesson", json.dumps(bad)])
    assert r.returncode == 1
    assert "ISO-8601 UTC" in r.stderr


def test_capture_ok_and_versioned(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lesson_capture", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LESSONS", tmp_path)
    monkeypatch.setattr(mod, "INDEX", tmp_path / "index.jsonl")

    assert mod.cmd_capture(json.dumps(GOOD)) == 0
    files = list(tmp_path.glob("lc-*.vsm"))
    assert len(files) == 1, files
    txt = files[0].read_text(encoding="utf-8")
    assert "@vsm 1.2.1" in txt and "@status active" in txt  # C5: archivo versionado
    assert "fuente_ts" in txt
    rows = mod._load_index()
    assert len(rows) == 1 and rows[0]["status"] == "active"


def test_c2_session_cap(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lesson_capture", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LESSONS", tmp_path)
    monkeypatch.setattr(mod, "INDEX", tmp_path / "index.jsonl")

    for i in range(3):
        les = dict(GOOD, claim=f"leccion {i}",
                   fuente_ts=f"2026-10-15T19:1{i}:07Z")
        assert mod.cmd_capture(json.dumps(les)) == 0, f"lesson {i} debia pasar"
    les4 = dict(GOOD, claim="cuarta", fuente_ts="2026-10-15T19:13:07Z")
    assert mod.cmd_capture(json.dumps(les4)) == 1  # C2 cap


def test_collision_rejected(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lesson_capture", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LESSONS", tmp_path)
    monkeypatch.setattr(mod, "INDEX", tmp_path / "index.jsonl")

    assert mod.cmd_capture(json.dumps(GOOD)) == 0
    assert mod.cmd_capture(json.dumps(GOOD)) == 1  # mismo lesson_id derivado


def test_gc_archives_stale(tmp_path, monkeypatch):
    import importlib.util
    from datetime import datetime, timedelta, timezone
    spec = importlib.util.spec_from_file_location("lesson_capture", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LESSONS", tmp_path)
    monkeypatch.setattr(mod, "INDEX", tmp_path / "index.jsonl")

    stale = (datetime.now(timezone.utc) - timedelta(days=31)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "lc-stale-test.vsm").write_text(
        "x\n@status active\n", encoding="utf-8")
    mod._append_index({"lesson_id": "lc-stale-test", "session_id": "s",
                       "fuente_ts": stale, "captured_at": stale,
                       "reconfirm_by": stale, "status": "active"})
    r = _run(["--stats"])  # smoke: stats corre con index real ajeno
    assert r.returncode == 0
    assert mod.cmd_gc() == 0  # gc ok (rc 0 = ejecutado; count vive en stdout)
    rows = mod._load_index()
    assert rows[0]["status"] == "archived"  # C3 decay
    assert "@status archived" in (tmp_path / "lc-stale-test.vsm").read_text()


def test_usage_no_args_rc2():
    r = _run([])
    assert r.returncode == 2
