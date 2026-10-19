"""external-detectors gate — negative control para los producers algedonicos
de trabajos externos (Delta A, hardening-gaps-2026-10 / task
HARDENING-ALGEDONIC-EXT-1).

R16 detector-first: este gate prueba que los 4 detectores PUEDEN fire.
Un detector no-op (devuelve [] siempre) es exactamente el fallo que dejó
al SFT colgado 12h sin señal — el gate lo rechaza.

check(path): importa el módulo detector en `path`, le inyecta estados que
DEBEN producir alerta (stall / no_progress / waste / score_shock) y retorna
1 si ALGÚN detector es no-op (rechaza), 0 si los 4 fire (acepta).

negative_case(): copia del detector real con los 4 detectores neutraizados
(retornan []) — el gate DEBE rechazarla.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import os
import shutil
import tempfile

from gate_suite.harness import register

_REAL = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "scripts", "state", "monitoring", "external_detectors.py",
))


def _load(path: str):
    spec = importlib.util.spec_from_file_location("ext_det_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now_iso(min_ago: float) -> str:
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(minutes=min_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(path: str) -> int:
    """0 = los 4 detectores fire con estados inyectados; 1 = hay no-op."""
    if not os.path.isfile(path):
        return 0  # out of scope
    try:
        mod = _load(path)
    except Exception:
        return 1  # módulo irrelevante = detector inexistente = rechaza

    failures = []

    stall = mod.detect_stall(
        [{"name": "t", "phase": "running",
          "last_progress_ts": _now_iso(60), "stall_max_min": 20}], None)
    if not stall or stall[0].get("alert_type") != "external_job_stall":
        failures.append("detect_stall no-op")

    np_ = mod.detect_no_progress(
        [{"name": "t", "phase": "running", "steps": 0,
          "started_ts": _now_iso(120), "progress_window_min": 30}], None)
    if not np_ or np_[0].get("alert_type") != "no_progress":
        failures.append("detect_no_progress no-op")

    waste = mod.detect_waste(
        [{"name": "t", "phase": "running", "budget_s": 7200, "used_s": 100,
          "started_ts": _now_iso(180)}], None)
    if not waste or waste[0].get("alert_type") != "resource_waste":
        failures.append("detect_waste no-op")

    shock = mod.detect_score_shock(
        [{"competition": "t", "score": 0, "artifact_certified": True}])
    if not shock or shock[0].get("alert_type") != "reality_score_shock":
        failures.append("detect_score_shock no-op")

    if failures:
        print(f"external-detectors REJECT: {', '.join(failures)}")
        return 1
    return 0


def negative_case() -> str:
    """Copia del detector con los 4 detectores neutraizados (no-ops)."""
    root = tempfile.mkdtemp(prefix="voslab_extdet_")
    dst = os.path.join(root, "external_detectors.py")
    with open(_REAL) as fh:
        src = fh.read()
    for fn in ("detect_stall", "detect_no_progress", "detect_waste",
               "detect_score_shock"):
        src = src.replace(
            f"def {fn}(", f"def _orig_{fn}(", 1)
        src += (
            f"\n\ndef {fn}(*a, **k):\n"
            f"    return []  # NC fixture: neutered no-op detector\n"
        )
    with open(dst, "w") as fh:
        fh.write(src)
    return dst


register("external-detectors", check, negative_case)
