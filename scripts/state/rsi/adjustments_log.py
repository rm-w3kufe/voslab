#!/usr/bin/env python3
"""adjustments_log.py — ajuste observable: registro schema-validado (Fase A D3-C2->3).

Diseño vivo: docs/design/sources/rsi-observer-v1/vsf_rsi_design.vsm
Propuesta ratificada: docs/plans/observable_adjustment_metric_2026_10_22.vsm
(S5 rmw3 go 2026-10-22: "perfecto. 1. Go / 2. aceptado" — FASE A + criterio
D3-C4 rubérico aceptado como canon).

Criterio D3-C4 (rubric): >= 1 entrada en state/rsi/adjustments.jsonl con
delta > 0 atribuible a una pred activada y reproducible. Nada cuenta como
ajuste si no es reversible, no determinístico o no atribuible (anti-inflado).

Entrada (una por línea, JSONL):
    {"ts", "pred", "pred_sha", "mecanismo", "before", "after",
     "delta", "delta_unit", "evidencia", "reversible", "escrito_por"}

mecanismo ∈ {demo-tmp-replay, retention-trigger, threshold-override,
             quarantine-domain, cadence-override} — cerrado (R10):
             agregar uno = editar ESTE módulo + demo/gate, nunca stdin.

R10: validación determinística; mismo archivo → mismo veredicto siempre.
Uso:
    python3 scripts/state/rsi/adjustments_log.py --list
    cat entry.json | python3 scripts/state/rsi/adjustments_log.py --register
    python3 scripts/state/rsi/adjustments_log.py --selftest
    python3 scripts/state/rsi/adjustments_log.py --validate <path>
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]

MECHANISMS = (
    "demo-tmp-replay",
    "retention-trigger",
    "threshold-override",
    "quarantine-domain",
    "cadence-override",
)

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
REQUIRED_KEYS = {"ts", "pred", "pred_sha", "mecanismo", "before", "after",
                 "delta", "delta_unit", "evidencia", "reversible",
                 "escrito_por"}


def valid_entry(entry: dict):
    """Validate one adjustment entry. Deterministic (R10).

    Returns (True, "") or (False, reason).
    """
    if not isinstance(entry, dict):
        return False, "entrada no es dict"
    missing = REQUIRED_KEYS - set(entry)
    if missing:
        return False, "claves faltantes: " + ", ".join(sorted(missing))
    extra = set(entry) - REQUIRED_KEYS
    if extra:
        return False, "claves extra no permitidas: " + ", ".join(sorted(extra))
    if not isinstance(entry["ts"], str) or not entry["ts"]:
        return False, "ts vacío"
    try:
        time.strptime(entry["ts"], TS_FORMAT)
    except ValueError:
        return False, f"ts no Z-format ({TS_FORMAT}): {entry['ts']!r}"
    for k in ("pred", "mecanismo", "evidencia", "escrito_por"):
        if not isinstance(entry[k], str) or not entry[k].strip():
            return False, f"{k} vacío"
    if entry["mecanismo"] not in MECHANISMS:
        return False, f"mecanismo no registrado: {entry['mecanismo']!r}"
    if not isinstance(entry["pred_sha"], str) or len(entry["pred_sha"]) != 16 \
            or any(c not in "0123456789abcdef" for c in entry["pred_sha"]):
        return False, "pred_sha debe ser hex 16"
    if not isinstance(entry["delta"], (int, float)) or \
            isinstance(entry["delta"], bool) or entry["delta"] <= 0:
        return False, "delta debe ser numérico > 0 (anti-inflado)"
    if not isinstance(entry["delta_unit"], str) or not entry["delta_unit"]:
        return False, "delta_unit vacío"
    if not isinstance(entry["before"], str) or not isinstance(entry["after"], str) \
            or entry["before"] == entry["after"]:
        return False, "before/after vacíos o idénticos (sin cambio = sin ajuste)"
    if entry["reversible"] is not True:
        return False, "reversible debe ser true (contrato anti-inflado)"
    if entry["escrito_por"] not in ("fase-b-demo", "hotpath_adjust",
                                    "s5-script"):
        return False, f"escrito_por no registrado: {entry['escrito_por']!r}"
    return True, ""


def _real_state() -> Path:
    return VOSLAB / "state" / "rsi" / "adjustments.jsonl"


def append_entry(entry: dict, path: Path | None = None) -> tuple[bool, str]:
    """Validate then append one JSONL line (mkdir parents)."""
    ok, why = valid_entry(entry)
    if not ok:
        return False, why
    if path is None:
        path = _real_state()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return True, "apuntada"


def read_entries(path: Path | None = None) -> list:
    if path is None:
        path = _real_state()
    if not path.is_file():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError(f"adjustments.jsonl línea {i}: JSON inválido")
    return out


def tree_sha16(tree: dict) -> str:
    """Pin-sha compatible con _pin_activation (rsi_cycle.py): sha256 de
    json.dumps(tree, sort_keys=True), 16 hex. Atribución verificable."""
    return hashlib.sha256(
        json.dumps(tree, sort_keys=True).encode()).hexdigest()[:16]


def selftest() -> int:
    """End-to-end: demo replay de hotpath_adjust + schema validación.

    El demo vive en tmp (VOSLAB_PATH sintético — nunca toca el real):
    1. hotpath_adjust.selftest() devuelve entries (delta>0) + report path
       tmp; el delta REPLICA determinístico.
    2. Cada entry DEBE pasar valid_entry (schema + anti-inflado).
    Exit 0 = mecanismo demostrable y reproducible (witness D3-C4).
    """
    demo = subprocess.run(
        [sys.executable,
         str(VOSLAB / "scripts" / "logs" / "hotpath_adjust.py"),
         "--selftest"],
        capture_output=True, text=True, timeout=120)
    if demo.returncode != 0:
        print(f"FAIL: replay demo rc={demo.returncode}\n{demo.stdout}")
        print(demo.stderr[-400:])
        return 1
    try:
        payload = json.loads(demo.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(f"FAIL: demo sin JSON final:\n{demo.stdout[-400:]}")
        return 1
    entries = payload.get("entries", [])
    if not entries:
        print("FAIL: demo sin entries (delta witness ausente)")
        return 1
    vs_check = 0
    for e in entries:
        ok, why = valid_entry(e)
        if not ok:
            print(f"FAIL: entry demo inválida: {why}\n{json.dumps(e)[:300]}")
            return 1
        if e.get("delta", 0) <= 0:
            print(f"FAIL: delta <= 0 (sin efecto): {e.get('delta')}")
            return 1
        vs_check += 1
    print(f"PASS: {vs_check} entries demo válidas (schema + delta>0) — "
          f"criterio D3-C4 demostrable/reproducible (witness tmp)")
    return 0


def main() -> int:
    ap_args = sys.argv[1:]
    if not ap_args:
        ap_args = ["--list"]
    if ap_args == ["--list"]:
        ents = read_entries()
        for i, e in enumerate(ents, 1):
            print(f"{i}. pred={e.get('pred')} mecanismo={e.get('mecanismo')} "
                  f"delta={e.get('delta')}({e.get('delta_unit')}) "
                  f"escrito={e.get('escrito_por')} ts={e.get('ts')}")
        if not ents:
            print("(vacía — sin ajustes registrados)")
        return 0
    if ap_args == ["--register"]:
        payload = sys.stdin.read()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            print(f"FAIL: stdin JSON inválido: {e}")
            return 1
        entries = data if isinstance(data, list) else [data]
        for e in entries:
            ok, why = append_entry(e)
            if not ok:
                print(f"FAIL: {why}")
                return 1
            ts = e.get("ts")
            print(f"APUNTADA: pred={e.get('pred')} delta={e.get('delta')} "
                  f"ts={ts} → state/rsi/adjustments.jsonl")
        return 0
    if ap_args == ["--selftest"]:
        return selftest()
    if ap_args[:1] == ["--validate"] and len(ap_args) == 2:
        p = Path(ap_args[1])
        if not p.is_file():
            print(f"FAIL: archivo ausente: {p}")
            return 1
        bad = 0
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"FAIL línea {i}: JSON inválido ({exc})")
                bad += 1
                continue
            ok, why = valid_entry(e)
            if not ok:
                print(f"FAIL línea {i}: {why}")
                bad += 1
        print("VALID: todas las líneas en schema" if not bad
              else f"REJECTED: {bad} líneas inválidas")
        return 1 if bad else 0
    print("usage: [--list|--register|--selftest|--validate <file>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
