# design: docs/plans/obsadj_runner_cadence_options_2026_10_22.vsm (opción A, S5 'de acuerdo' 2026-10-22)
"""Opción A del pendiente P-OBSADJ-RUNNER-CADENCE-2026-10-22 — wiring
del cronometrista del trigger observable (D3-C2->3) en la suite horaria.

Contrato del step (recomendación kernel ejecutada):
  - 'obsadj-check' es step de scheduled_suite STEPS (rc-normalizado:
    no-armado NO es fallo; solo excepción del mecanismo falla →
    failing-step algedónico canon post-shadow 7 ciclos).
  - El wrapper obsadj_step.py encadena --check → --apply (solo ARMED) y
    registra el ajuste real en state/rsi/adjustments.jsonl.
R10 determinístico: mismo disk state → mismo veredicto; sin timers
que decidan, sin random. Texto-level como test_atomic_writers (estilo
canon): asserts sobre el código fuente, no sobre ejecución de timers.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "scripts" / "state" / "monitoring" / "scheduled_suite.py"
WRAP = REPO / "scripts" / "state" / "monitoring" / "obsadj_step.py"
HOT = REPO / "scripts" / "logs" / "hotpath_adjust.py"
GATE = REPO / "packages" / "public" / "vsf-checks" / "checks" / "attribution-valid"


def test_obsadj_check_step_registered():
    src = SUITE.read_text(encoding="utf-8")
    assert '"obsadj-check"' in src, "step ausente del STEPS de la suite"
    assert "obsadj_step.py" in src, "wrapper no referenciado por el step"


def test_wrapper_rc_contract():
    src = WRAP.read_text(encoding="utf-8")
    # rc 0 con no-armado (nunca alerta por estado normal del sistema)
    assert "--check" in src and "--apply" in src
    assert "dentro de umbral" in src, "no-armado debe imprimir estado y rc 0"
    # fallo SOLO en excepción mecanismo (failing-step algedonico post-shadow)
    assert "excepción del mecanismo" in src or "excepcion del mecanismo" in src


def test_mechanism_gated_sufficient():
    src = HOT.read_text(encoding="utf-8")
    # R17-safe: candidates=0 o est_after>umbral → NO actúa (apología honesta)
    assert "sin spans >30d" in src or "candidates" in src
    assert "mecanismo insuficiente" in src


def test_r19_gate_registered():
    src = GATE.read_text(encoding="utf-8")
    assert "R19" in src and "baseline" in src
