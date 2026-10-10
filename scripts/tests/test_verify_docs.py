"""Tests para scripts/doc_tracking/verify_docs.py (F5 Fase 3 ligera).

Determinista (R10): fixtures con contenido fijo, mismo algoritmo de
sha256[0:16] que doc_manifest. Aislamiento (R1): overrides de env
DOC_MANIFEST_VOSLAB / DOC_MANIFEST / DOC_MANIFEST_VSF en subprocess.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "doc_tracking" / "verify_docs.py"


def _sha(p: Path) -> str:
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return "sha256:" + h


def _sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()[:16]


def _mk(tmp_path: Path):
    voslab = tmp_path / "voslab"
    vsf = tmp_path / "vsf"
    (voslab / "state").mkdir(parents=True)
    (voslab / "docs" / "mirror").mkdir(parents=True)
    (voslab / "docs" / "canon_mirror").mkdir(parents=True)
    vsf.mkdir()
    # e1 present: source == dest (dest en canon_mirror)
    (vsf / "a.vsm").write_text("contenido A\n")
    (voslab / "docs" / "canon_mirror" / "a.vsm").write_text("contenido A\n")
    # e2 modified: source != dest
    (vsf / "b.vsm").write_text("fuente B\n")
    (voslab / "docs" / "mirror" / "b.vsm").write_text("copia B divergente\n")
    # e3: dest declarado pero ausente en disco
    (vsf / "c.vsm").write_text("contenido C\n")
    # huerfanos: en canon_mirror (tier canon, accionable) y en
    # docs/mirror (tier native, informativo)
    (voslab / "docs" / "canon_mirror" / "extra.vsm").write_text("stale\n")
    (voslab / "docs" / "mirror" / "native_extra.vsm").write_text("nativo\n")
    entries = [
        {"id": "a", "source": str(vsf / "a.vsm"),
         "dest": "docs/canon_mirror/a.vsm", "status": "present",
         "priority": "medium", "checksum": _sha(vsf / "a.vsm")},
        {"id": "b", "source": str(vsf / "b.vsm"),
         "dest": "docs/mirror/b.vsm", "status": "modified",
         "priority": "high", "checksum": _sha(vsf / "b.vsm")},
        {"id": "c", "source": str(vsf / "c.vsm"),
         "dest": "docs/mirror/gone.vsm", "status": "present",
         "priority": "medium", "checksum": _sha(vsf / "c.vsm")},
    ]
    manifest = voslab / "state" / "doc_manifest.jsonl"
    manifest.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return voslab, vsf, manifest


def _run(voslab: Path, vsf: Path, manifest: Path, *args: str):
    env = {**os.environ,
           "DOC_MANIFEST_VOSLAB": str(voslab),
           "DOC_MANIFEST_VSF": str(vsf),
           "DOC_MANIFEST": str(manifest)}
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env)


def _summary(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_baseline_buckets_and_queue(tmp_path):
    voslab, vsf, manifest = _mk(tmp_path)
    proc = _run(voslab, vsf, manifest)
    assert proc.returncode == 0, proc.stderr
    s = _summary(proc)
    assert s["ok"] and s["baseline"] is True
    assert s["entries"] == 3
    assert s["source_drifted"] == 0
    assert s["faltantes"] == 1          # e3 dest gone
    assert s["huerfanos"] == 2          # canon (stale) + native
    assert s["huerfanos_canon"] == 1
    assert s["huerfanos_native"] == 1
    assert s["huerfanos_canon_list"] == ["docs/canon_mirror/extra.vsm"]
    assert s["cola_modified"] == 1      # e2
    assert s["changelog_appended"] == 0  # baseline sin cambios
    state = voslab / "state" / "doc_tracking" / "verify_state.json"
    assert state.exists()
    assert not (voslab / "state" / "doc_tracking"
                / "doc_changelog.jsonl").exists()
    queue = (voslab / "state" / "doc_tracking"
             / "review_queue.jsonl").read_text().strip().splitlines()
    assert len(queue) == 1
    assert json.loads(queue[0])["id"] == "b"
    orphans = (voslab / "state" / "doc_tracking"
               / "orphans.jsonl").read_text().strip().splitlines()
    assert len(orphans) == 2
    assert json.loads(orphans[0])["tier"] == "canon"


def test_dest_modify_logged_then_idempotent(tmp_path):
    voslab, vsf, manifest = _mk(tmp_path)
    assert _run(voslab, vsf, manifest).returncode == 0   # baseline
    dest = voslab / "docs" / "canon_mirror" / "a.vsm"
    before = _sha(dest)
    dest.write_text("contenido A editado\n")
    after = _sha(dest)

    proc = _run(voslab, vsf, manifest)
    assert proc.returncode == 0
    s = _summary(proc)
    assert s["baseline"] is False
    assert s["changelog_appended"] == 1
    log = (voslab / "state" / "doc_tracking"
           / "doc_changelog.jsonl").read_text().strip().splitlines()
    assert len(log) == 1
    e = json.loads(log[0])
    assert e["doc_id"] == "a" and e["action"] == "modify"
    assert e["checksum_before"] == before
    assert e["checksum_after"] == after
    assert e["ts"].endswith("Z")

    # sin cambios -> sin entradas nuevas (idempotente)
    proc2 = _run(voslab, vsf, manifest)
    assert _summary(proc2)["changelog_appended"] == 0
    assert len((voslab / "state" / "doc_tracking"
                / "doc_changelog.jsonl").read_text().strip().splitlines()) == 1


def test_source_drift_logged(tmp_path):
    voslab, vsf, manifest = _mk(tmp_path)
    assert _run(voslab, vsf, manifest).returncode == 0   # baseline
    src = vsf / "b.vsm"
    src.write_text("fuente B upstream cambio\n")
    proc = _run(voslab, vsf, manifest)
    s = _summary(proc)
    assert s["source_drifted"] == 1
    assert s["changelog_appended"] == 1
    e = json.loads((voslab / "state" / "doc_tracking"
                    / "doc_changelog.jsonl").read_text().strip())
    assert e["doc_id"] == "b" and e["action"] == "source-modify"
    assert e["checksum_before"] != e["checksum_after"]


def test_missing_manifest_rc2(tmp_path):
    voslab, vsf, _ = _mk(tmp_path)
    proc = _run(voslab, vsf, tmp_path / "no_existe.jsonl")
    assert proc.returncode == 2
    assert _summary(proc)["ok"] is False


def test_dry_run_writes_nothing(tmp_path):
    voslab, vsf, manifest = _mk(tmp_path)
    proc = _run(voslab, vsf, manifest, "--dry-run")
    assert proc.returncode == 0
    s = _summary(proc)
    assert s["dry_run"] and s["baseline"] is True
    assert not (voslab / "state" / "doc_tracking").exists()
