"""error-burst gate — negative control para el detector S2 error_burst
(shadow-inventory-2026-10 / task SHADOW-ERROR-TRIAGE-1).

R16 detector-first: el gate prueba que detect_error_burst PUDE fire (una
clase con ≥N level=error en la ventana) y que NO fire por debajo del
umbral (anti-always-on). Un detector no-op es exactamente el fallo que
dejó los 13 level=error de la semana sin triage — el gate lo rechaza.

check(path): importa variety_census desde `path`, inyecta conteos que
DEBEN producir alerta error_burst y conteos bajo umbral que NO deben
disparar; retorna 1 si el detector es no-op o siempre-fire (rechaza).

negative_case(): copia de variety_census con detect_error_burst
neuterado (retorna [] siempre) — el gate DEBE rechazarla.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile

from gate_suite.harness import register

_REAL = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "scripts", "state", "monitoring", "variety_census.py",
))


def _load(path: str):
    spec = importlib.util.spec_from_file_location("census_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(path: str) -> int:
    """0 = detector fire en umbral y calla bajo umbral; 1 = no-op/always."""
    if not os.path.isfile(path):
        return 0  # out of scope
    try:
        mod = _load(path)
    except Exception:
        return 1  # módulo irrelevante = detector inexistente = rechaza

    failures = []

    if not hasattr(mod, "detect_error_burst"):
        print("error-burst REJECT: detect_error_burst ausente")
        return 1
    threshold = int(getattr(mod, "BURST_THRESHOLD", 5))

    # 1. DEBE fire: clase en (exactamente) el umbral
    fired = mod.detect_error_burst(
        {("tool-bridge", "bridge.error"): threshold}, threshold)
    if not fired or fired[0].get("alert_type") != "error_burst":
        failures.append("detect_error_burst no-op en umbral")

    # 2. NO debe fire: clase bajo el umbral (anti-always-on)
    quiet = mod.detect_error_burst(
        {("tool-bridge", "bridge.error"): threshold - 1}, threshold)
    if quiet:
        failures.append("detect_error_burst firea bajo umbral (always-on)")

    if failures:
        print(f"error-burst REJECT: {', '.join(failures)}")
        return 1
    return 0


def negative_case() -> str:
    """Copia de variety_census con detect_error_burst neuterada (no-op)."""
    root = tempfile.mkdtemp(prefix="voslab_errburst_")
    dst = os.path.join(root, "variety_census.py")
    with open(_REAL) as fh:
        src = fh.read()
    src = src.replace(
        "def detect_error_burst(", "def _orig_detect_error_burst(", 1)
    src += (
        "\n\ndef detect_error_burst(*a, **k):\n"
        "    return []  # NC fixture: neutered no-op detector\n"
    )
    with open(dst, "w") as fh:
        fh.write(src)
    return dst


register("error-burst", check, negative_case)
