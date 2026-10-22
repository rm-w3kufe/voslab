#!/usr/bin/env python3
"""obsadj_step.py — wrapper rc-normalizado del trigger observable (D3-C2->3).

# design: docs/spec_revision/design-sources/rsi-observer-v1/vsf_rsi_design.vsm
# route: scheduled_suite.py STEPS ('obsadj-check') + monitoring_runners.vsm
#
# Contrato (opción A, S5 'de acuerdo con la recomendación' 2026-10-22):
#   rc 0  -> mecanismo corrió (armado o no). NO alerta por 'no armado'
#            (hot-path dentro de umbral o sin spans >30d: estado NORMAL
#            del sistema, NO es fallo). El stamp del suite registra rc/secs.
#   rc 1  -> excepción REAL del mecanismo (bug/import/error de disco):
#            failing-step → alerta algedónica canon del suite (post-shadow).
#   (el wrapper no toma argumentos: uso inválido = argparse hotpath n/a)
#
# Imprime una línea resumen para el tail del stamp. Determinístico (R10):
# mismo disk state → mismo veredicto y misma línea.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

VOS = Path(__file__).resolve().parents[2]
HOT = VOS / "scripts" / "logs" / "hotpath_adjust.py"


def main() -> int:
    try:
        chk = subprocess.run(
            [sys.executable, str(HOT), "--check"],
            capture_output=True, text=True, timeout=120, cwd=str(VOS))
        if chk.returncode not in (0, 1, 2):
            print(f"obsadj-check: probe rc={chk.returncode} inesperado",
                  file=sys.stderr)
            return 1
        armed = "ARMED" in (chk.stdout or "")
        if not armed:
            print("obsadj-check: dentro de umbral (no armado) — sin ajuste",
                  file=sys.stdout)
            return 0
        ap = subprocess.run(
            [sys.executable, str(HOT), "--apply"],
            capture_output=True, text=True, timeout=300, cwd=str(VOS))
        if ap.returncode != 0:
            print(f"obsadj-apply rc={ap.returncode}: "
                  f"{(ap.stdout or ap.stderr)[-200:]}", file=sys.stderr)
            return 1
        summary = (ap.stdout or "").strip().splitlines()
        line = next(
            (l for l in summary if l.startswith("ENTRY APUNTADA")), "")
        payload = {}
        try:
            blob = ap.stdout[ap.stdout.index("{"):ap.stdout.rindex("}") + 1]
            payload = json.loads(blob)
        except (ValueError, json.JSONDecodeError):
            payload = {}
        entry = payload.get("entry") or {}
        print(f"obsadj-check: ARMED → apply OK — ajuste registrado "
              f"delta={entry.get('delta')}({entry.get('delta_unit')}) "
              f"{line}", file=sys.stdout)
        return 0
    except subprocess.TimeoutExpired:
        print("obsadj-check: timeout del mecanismo", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — wrapper debe DETECTAR y reportar
        print(f"obsadj-check: excepción del mecanismo: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
