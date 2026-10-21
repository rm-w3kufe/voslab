# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T3-F3: alerts-triage boot step)
"""T3-F3 — paso alerts-triage en session boot: errores sin clasificar
en el PRIMER reporte a S5.

Plan 2026-10-20 T3: el bootstrap line decía volumen ("N unacked") pero
nunca urgencia — el backlog 7d sin triage (>220) quedaba invisible hasta
que S5 preguntaba. Fix: nuevo cmd de bridge `alerts-triage`
(_alerts_triage_stage → alert_triage.triage_repo, SOLO lectura: clasifica
NOW/DEFER/ACCUMULATE, nunca ack) + session-lifecycle lo appendea a la
linea bootstrap del session.created; un fallo LOGGEA fila de error (R9:
el path anti-R9 no se tapa), nunca rompe el boot (mismo trato que
rsi-queue-digest pero con trace).

Estos tests pinnean: (1) forma del JSON del cmd via CLI (hermético —
solo claves/tipos, jamás conteos en vivo); (2) contrato estático del
lado TS (ambas variantes del bootstrap llevan triageSummary, el call
viene ANTES de la fila report, rama de error con trace). R16: design
heredado del SUT (plan).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = _ROOT / ".opencode" / "plugins" / "operational" / "tool_integration_bridge.py"
LIFECYCLE = _ROOT / ".opencode" / "plugins" / "operational" / "session-lifecycle.ts"


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-W", "ignore", str(BRIDGE), *argv],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "VOS_ROOT": str(_ROOT)},
    )


def test_bridge_alerts_triage_shape():
    """CLI alerts-triage → forma compacta para la linea bootstrap (read-only)."""
    proc = _run("alerts-triage")
    assert proc.returncode == 0, proc.stderr[-500:]
    start = proc.stdout.find("{")
    assert start != -1, proc.stdout[:300]
    out = json.loads(proc.stdout[start:])
    assert "error" not in out, out
    counts = out["counts"]
    for k in ("unacked", "now", "defer", "accumulate_groups",
              "accumulate_alerts"):
        assert isinstance(counts[k], int), k
    assert isinstance(out["cutoff"], (int, float))
    assert isinstance(out["top_now"], list)
    for a in out["top_now"]:  # forma compacta, sin filas crudas
        assert set(a) <= {"alert_type", "source", "impact", "aus", "ts"}


def test_stage_error_branch_fail_loud():
    """R9: la rama de error devuelve {"error": ...} — jamás un dict vacío."""
    src = BRIDGE.read_text(encoding="utf-8")
    assert "def _alerts_triage_stage()" in src
    i = src.index("def _alerts_triage_stage()")
    body = src[i:i + 1600]
    assert 'return {"error"' in body
    assert "triage_repo" in body


def test_session_lifecycle_boot_report_includes_triage():
    """Contrato TS: triage en AMBAS variantes del bootstrap y ANTES del log."""
    src = LIFECYCLE.read_text(encoding="utf-8")
    # ambas variantes (con report y sin report) llevan la clasificación
    assert src.count("${triageSummary}") == 2
    # el call existe y corre ANTES de la primera fila report a S5
    call_i = src.index('callBridge("alerts-triage"')
    log_i = src.index("bootstrap: ${report")
    assert call_i < log_i
    # rama de error con trace (nunca silenciosa) + default honesto n/a
    assert 'let triageSummary = "triage: n/a"' in src
    assert "triage failed on create" in src
