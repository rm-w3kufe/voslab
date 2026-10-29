#!/usr/bin/env python3
# design: docs/design/sources/hardening-gaps-2026-10.vsm (Delta E) +
#         TASKS.vsm > HARDENING-GAIN-LEDGER-1
"""opportunity_ledger.py — ledger de oportunidades (HARDENING-GAIN-LEDGER-1, Delta E).

Firmas REPETIDAS (umbral E3) que sugieren mejora de tool/harness/check
→ propuesta emitida (NO auto-impl: R16 design-first → tests → S5
ratifica kernel-level). Patrón: pattern-memory write-back harness ARC v12.

Entrada (una por línea, JSONL, state/rsi/opportunity_ledger.jsonl):
    {"ts", "firma", "firmas_repetidas", "evidencia", "estado",
     "propuesta", "escrito_por"}
  firma: literal con la clase del problema (dedup key).
  firmas_repetidas: int >= 2 (el umbral E3 es la razón de ser del ledger;
                   1 sola ocurrencia NO entra).
  evidencia: lista de refs verificables (commits, paths, ts).
  estado ∈ {landed, propuesta, descartada} — cerrado (R10):
           agregar estado = editar ESTE módulo + --selftest.
  propuesta: qué MEJORAR (no la impl).

R10: validación determinística; mismo archivo → mismo veredicto siempre.
Uso:
    python3 scripts/state/rsi/opportunity_ledger.py --list
    cat entry.json | python3 scripts/state/rsi/opportunity_ledger.py --register
    python3 scripts/state/rsi/opportunity_ledger.py --selftest
您       python3 scripts/state/rsi/opportunity_ledger.py --validate [--path X]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent.parent / "state" / "rsi" / \
    "opportunity_ledger.jsonl"
STATES = ("landed", "propuesta", "descartada")
REQUIRED = ("ts", "firma", "firmas_repetidas", "evidencia", "estado",
            "propuesta", "escrito_por")


def valid_entry(e: dict) -> tuple[bool, str]:
    if not isinstance(e, dict):
        return False, "entry no es dict"
    missing = [k for k in REQUIRED if k not in e]
    if missing:
        return False, f"falta {missing}"
    if not isinstance(e["ts"], str) or not e["ts"].endswith("Z"):
        return False, "ts no es ISO-Z"
    if not isinstance(e["firma"], str) or len(e["firma"]) < 8:
        return False, "firma < 8 chars"
    n = e["firmas_repetidas"]
    if not isinstance(n, int) or n < 2:
        return False, f"firmas_repetidas={n!r} < 2 (umbral E3)"
    if not isinstance(e["evidencia"], list) or not e["evidencia"]:
        return False, "evidencia vacía"
    if e["estado"] not in STATES:
        return False, f"estado '{e['estado']}' fuera de {STATES}"
    if not isinstance(e["propuesta"], str) or len(e["propuesta"]) < 20:
        return False, "propuesta < 20 chars (sin cuerpo)"
    return True, ""


def register(e: dict) -> tuple[bool, str]:
    ok, why = valid_entry(e)
    if not ok:
        return False, why
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return True, ""


def list_entries(path: Path | None = None) -> list[dict]:
    tgt = path or LEDGER
    if not tgt.exists():
        return []
    out = []
    for line in tgt.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def validate(path: Path | None = None) -> int:
    tgt = path or LEDGER
    if not tgt.exists():
        print(f"FAIL: ledger no existe: {tgt}")
        return 1
    bad = []
    for i, line in enumerate(tgt.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception as exc:  # noqa: BLE001 — fail-loud unreadable line
            bad.append((i + 1, f"JSON inválido: {exc}"))
            continue
        ok, why = valid_entry(e)
        if not ok:
            bad.append((i + 1, why))
    if bad:
        for i, why in bad:
            print(f"FAIL línea {i}: {why}")
        return 1
    n = len(list_entries(tgt))
    print(f"ledger valid: {n} entradas schema-OK")
    return 0


def selftest() -> int:
    good = {"ts": "2026-10-23T12:00:00Z", "firma": "firma-fixture-larga",
            "firmas_repetidas": 3,
            "evidencia": ["commit abc123"],
            "estado": "propuesta", "propuesta": "mejora del harness con "
            "descrito en el cuerpo entero", "escrito_por": "selftest"}
    ok, why = valid_entry(good)
    assert ok, why
    for mutate, want_fail in (
        ({**good, "firmas_repetidas": 1}, "umbral"),
        ({**good, "estado": "adios"}, "estado cerrado"),
        ({**good, "ts": "2026-10-23T12:00:00"}, "ts sin Z"),
        ({k: v for k, v in good.items() if k != "propuesta"}, "campo"),
        ({**good, "evidencia": []}, "evidencia vacía"),
        ({**good, "propuesta": "corta"}, "propuesta corta"),
    ):
        ok, why = valid_entry(mutate)
        assert not ok, f"fixture debió fallar ({want_fail}): {why}"
    print("selftest OK (7 fixtures deterministas, R10)")
    return 0


def main(argv: list[str]) -> int:
    args = argv or []
    if args[0:1] == ["--selftest"]:
        return selftest()
    if args[0:1] == ["--validate"]:
        tgt = Path(args[2]) if len(args) > 2 and args[1] == "--path" else None
        return validate(tgt)
    if args[0:1] == ["--list"]:
        for e in list_entries():
            print(json.dumps(e, ensure_ascii=False, indent=1))
        return 0
    if args[0:1] == ["--register"]:
        e = json.loads(sys.stdin.read())
        ok, why = register(e)
        print("registered" if ok else f"REJECTED: {why}")
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
