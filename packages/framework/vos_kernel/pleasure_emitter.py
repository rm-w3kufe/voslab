"""Algedonic PLURE channel — G-34 / PLEASURE-CHANNEL-001 (P1 core).

Emisor determinista (R10) de placer estadistico: sorpresa de recompensa
positiva (Schultz 1997) contra un baseline rolling + sorpresa de racha
en bits que CRECE con la racha (Hebb 1949).

Design canon: docs/plans/pleasure_channel_proposal.vsm (@status ratified,
milestones N=3,5,8 ratificados por S5 2026-10-07 — R17 cumplido ANTES de
cualquier emision en vivo). Amended G-36b (S5 2026-10-08, firma rmw3:
"escalera Fib + Laplace"): {3,5,8} SON Fibonacci — la escalera se abre
a 13,21,34,... (racha larga cobra SIN esperar un fallo) y p_m usa
suavizado Laplace ((exitos+1)/(n+2)) de modo que bits > 0 SIEMPRE en
un hito: el logro no muere de certeza. rpe queda puro RPE (1-p sobre
la ventana): la sorpresa sigue muriendo en p=1 por diseño.

Guards:
  R10  funcion pura de (historial, evento, ventana): misma entrada, misma
       salida y mismo event_id — sin aleatoriedad.
  F2   asimetria estricta: este modulo NUNCA toca alerts.jsonl ni el lado
       del dolor; los fallos se registran SOLO como baseline (emissions=[]),
       jamas generan placer ni accion.
  R17  jamas auto-execute: solo append a state/rsi/pleasure.jsonl.
       Cero veto, cero cambio de codigo, cero throw hacia los flujos
       (los callers envuelven en try/except — fail-open).

Storage: state/rsi/pleasure.jsonl (espejo de alerts.jsonl, append-only,
rotacion >10000 lineas -> conserva ultimas 5000). Cada linea es UN
evento de unidad evaluado (exitoso o fallido) con sus emisiones inline
(emissions=[] si no hubo sorpresa) — el archivo es a la vez ledger de
baseline (tasa de exito rolling) y canal de placer.

Unidades de evento (proposal design EVENTOS): gate_run (corrida de
gates), evaluate (ciclo socratic), session_close (cierre de sesion).
La ventana rolling reutiliza la ratificada G-03 de 7 dias (7d G-03 /
21d CC-8.1 disponibles como parametros).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ratificados por S5 2026-10-07 (proposal design METRIC.milestones).
MILESTONES: tuple[int, ...] = (3, 5, 8)
# G-36b (S5 2026-10-08): {3,5,8} = fibonacci(4..6) — hito valido todo
# n >= 3 de la escalera fibonacci (13, 21, 34, ...). 1 y 2 son fib pero
# ESTAN bajo la base ratificada: no disparan.
MILESTONE_MIN: int = 3
# Ventana rolling ratificada G-03 (proposal reusa ventanas ratificadas).
DEFAULT_WINDOW_DAYS: float = 7.0
# Rotacion espejo de alerting.py (_emit): >10000 lineas -> ultimas 5000.
_ROTATE_AT = 10000
_ROTATE_KEEP = 5000

WORKSPACE = Path(__file__).resolve().parents[3]  # vOSlab/packages/framework/vos_kernel/ -> vOSlab


def pleasure_file() -> Path:
    """Ledger path: RSI_PLEASURE_FILE (tests/overrides) o default tracked."""
    env = os.environ.get("RSI_PLEASURE_FILE")
    if env:
        return Path(env)
    return WORKSPACE / "state" / "rsi" / "pleasure.jsonl"


def _parse_ts(value: Any) -> datetime | None:
    """ISO-8601 Z (o offset) -> aware datetime; basura -> None (determinista)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_id(ts: str, unit: str, success: bool, detail: str) -> str:
    """Id deterministico del evento (R10: misma entrada -> mismo id)."""
    canon = f"{ts}|{unit}|{int(bool(success))}|{detail}"
    return "pev-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def _is_fibonacci(n: int) -> bool:
    """True ssi n es un numero de Fibonacci (entero exacto, determinista R10).

    Criterio clasico: 5n^2 +/- 4 es cuadrado perfecto. math.isqrt es
    exacto en Python (enteros arbitrarios) — sin float, sin frontera.
    """
    if n < 0:
        return False
    five_n2 = 5 * n * n
    for cand in (five_n2 + 4, five_n2 - 4):
        root = math.isqrt(cand)
        if root * root == cand:
            return True
    return False


def evaluate(
    history: list[dict[str, Any]],
    event: dict[str, Any],
    window_days: float = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Pure core (R10): evaluacion de un evento contra su historial.

    history: registros previos del ledger (con unit/success/ts).
    event: {"ts", "unit", "success", "detail"?} — todavia NO en history.

    Reglas (proposal design METRIC, amended G-36b):
      baseline p = tasa de exito rolling sobre la unidad, ventana
      `window_days` (eventos previos con ts <= actual — ráfagas de
      mismo segundo encadenan, orden de append; p=0 sin datos).
      RPE  = 1 - p  en cada exito; emite SOLO sorpresa positiva
      (p=1 -> RPE=0 -> silencio = verdes rutinarios no inundan).
      racha N = exitos consecutivos inmediatamente previos + 1 (la racha
      es de SECUENCIA, no se trunca en la ventana); emision en todo
      hito de la escalera fibonacci N >= 3 (3, 5, 8, 13, 21, ... — los
      tres umbrales ratificados 2026-10-07 son fibonacci, S5 firmo la
      escalera completa 2026-10-08) con bits = N * (-log2 p_m), donde
      p_m se calcula sobre (ventana ∪ cadena de racha) con SUAVIZADO
      LAPLACE p_m = (exitos+1)/(n+2): 0 < p_m < 1 siempre, sin
      -log2(0) y sin silencio por certeza — el logro eterno, la
      sorpresa (rpe) la que muere en p=1.
      Fallo: streak=0, sin emisiones (el dolor vive en alerts.jsonl).

    Returns registro canonico: p/streak/rpe + emissions[] (cada emision
    con kind, magnitude, magnitude_unit, y p/streak en milestones).
    """
    unit = event.get("unit", "")
    e_ts = _parse_ts(event.get("ts"))
    if e_ts is None:
        raise ValueError("event.ts invalido (ISO-8601 requerido)")

    seq = [
        h for h in history
        if h.get("unit") == unit and _parse_ts(h.get("ts")) is not None
    ]
    # Orden por ts con sort ESTABLE: los empates de segundo conservan el
    # orden de append (orden real de los eventos).
    seq.sort(key=lambda h: _parse_ts(h["ts"]))

    # previos con ts <= actual: una ráfaga de eventos en el MISMO
    # segundo se encadena entre si (fix G-36b 2026-10-08 — antes el <
    # estricto excluia a los hermanos de mismo-ts y 3 paralelos en la
    # racha 1597 calcularon streak=1597 tres veces => hito x3). El
    # evento actual jamas esta en history (emit evalua ANTES de append).
    prior = [h for h in seq if _parse_ts(h["ts"]) <= e_ts]

    # racha de secuencia: exitos consecutivos inmediatamente previos
    chain = 0
    for h in reversed(prior):
        if h.get("success"):
            chain += 1
        else:
            break

    # baseline rolling sobre la ventana
    window = timedelta(days=float(window_days))
    win_idx = {
        i for i, h in enumerate(prior)
        if (e_ts - _parse_ts(h["ts"])) <= window
    }
    if win_idx:
        p_raw = sum(1 for i in win_idx if prior[i].get("success")) / len(win_idx)
    else:
        p_raw = 0.0
    # verdad registrada: TODO se deriva del p redondeado (R10 audit-able:
    # p, rpe y bits del registro son recomputables entre si sin drift).
    p_window = round(p_raw, 6)

    success = bool(event.get("success"))
    streak = (chain + 1) if success else 0
    rpe: float | None = None
    emissions: list[dict[str, Any]] = []

    if success:
        rpe = round(1.0 - p_window, 6)
        if rpe > 0:
            emissions.append(
                {"kind": "rpe", "magnitude": rpe, "magnitude_unit": "rpe"}
            )
        if streak >= MILESTONE_MIN and _is_fibonacci(streak):
            # p_m sobre ventana ∪ cadena de racha (indices de `prior`)
            # + Laplace G-36b: (exitos+1)/(n+2) — 0 < p_m < 1 siempre,
            # el hito cobra aunque todo este en verde (logro eterno).
            n = len(prior)
            idx = win_idx | set(range(n - chain, n))
            if idx:
                succ = sum(1 for i in idx if prior[i].get("success"))
                p_m = round((succ + 1) / (len(idx) + 2), 6)
                if 0 < p_m < 1:
                    bits = round(streak * (-math.log2(p_m)), 6)
                    if bits > 0:
                        emissions.append(
                            {"kind": "milestone", "magnitude": bits,
                             "magnitude_unit": "bits", "streak": streak,
                             "p": p_m}
                        )

    return {
        "p": p_window,
        "streak": streak,
        "rpe": rpe,
        "emissions": emissions,
    }


def read_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Ledger -> registros validos (lineas corruptas se ignoran, determinista)."""
    target = path or pleasure_file()
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("unit"):
            records.append(rec)
    return records


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append espejo-alerts + rotacion >10000 -> ultimas 5000."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > _ROTATE_AT:
        path.write_text(
            "\n".join(lines[-_ROTATE_KEEP:]) + "\n", encoding="utf-8"
        )


def trust_spill_file() -> Path:
    """Transporte de trust: RSI_TRUST_SPILL_FILE (tests) o el spill
    productivo que drena RiskAssessor (bridge _drain_trust_spill)."""
    env = os.environ.get("RSI_TRUST_SPILL_FILE")
    if env:
        return Path(env)
    return WORKSPACE / "state" / "rsi" / "trust_spill.jsonl"


def apply_hebbian(event: dict[str, Any]) -> dict[str, Any]:
    """P3 feedback Hebbiano (proposal HEBBIAN-FEEDBACK): cada
    pleasure_event (emissions no vacias) potencia LA CONEXION que lo
    causo — efecto real, advisory, fail-open por efecto.

    1. trust: append {ts, tool:"pleasure", file:<connection>, ok:true} a
       state/rsi/trust_spill.jsonl — el drain productivo (bridge,
       claim atomico) aplica RiskAssessor.record_outcome(+0.05
       asimetrico arriba / -0.20 abajo, cap 1.0 — "hoy solo 0.75/0.5").
    2. pesos: vsf_rsi.adaptive_weights.record_outcome(component,
       quality=min(WeightConfig.drift_max, magnitud)) — el techo
       POR EPOCA reutiliza drift_max=0.95 de WeightConfig (la red
       jamas se infla sin limite: max_weight 0.8 + renormalize ya
       viven ahi dentro).

    Kill-switch: VOS_PLEASURE_FEEDBACK=0 desactiva ambos efectos.
    paralysis_guard (F2): jamas reduce thresholds ni toca alerts.jsonl.
    Returns resumen de efectos (nunca lanza).
    """
    out: dict[str, Any] = {"effects": []}
    if os.environ.get("VOS_PLEASURE_FEEDBACK", "1") == "0":
        out["reason"] = "disabled"
        return out
    emissions = event.get("emissions") or []
    if not emissions:
        return out  # solo los pleasure_event potencian (silencio no refuerza)
    connection = str(event.get("connection") or "__global__")

    # 1. trust spill (existente, drenado en la proxima sesion activa)
    try:
        spill = trust_spill_file()
        spill.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": event.get("ts") or _now_ts(),
            "tool": "pleasure",
            "file": connection,
            "ok": True,
        }
        with spill.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        out["effects"].append("trust-spill")
    except Exception as exc:  # noqa: BLE001 — fail-open por efecto
        out["effects"].append(f"trust-spill:fail-open:{type(exc).__name__}")

    # 2. pesos adaptativos (vsf-rsi)
    try:
        import sys as _sysw
        rsi_path = str(WORKSPACE / "packages" / "public" / "vsf-rsi")
        if rsi_path not in _sysw.path:
            _sysw.path.insert(0, rsi_path)
        from vsf_rsi import adaptive_weights
        ceiling = float(adaptive_weights.WeightConfig().drift_max)
        quality = round(min(ceiling, max(float(e.get("magnitude", 0.0))
                                         for e in emissions)), 6)
        adaptive_weights.record_outcome(connection, quality)
        out["effects"].append("weights")
        out["quality"] = quality
    except Exception as exc:  # noqa: BLE001 — fail-open por efecto
        out["effects"].append(f"weights:fail-open:{type(exc).__name__}")
    return out


def emit(
    unit: str,
    success: bool,
    ts: str | None = None,
    detail: str = "",
    source: str = "",
    connection: str = "",
    window_days: float = DEFAULT_WINDOW_DAYS,
    path: Path | None = None,
    feedback: bool = False,
) -> dict[str, Any]:
    """Avala un evento de unidad, evalua y persiste (append-only).

    feedback=True (wired en los callers P2: gate transitions, socratic
    certified, session close) aplica P3 sobre pleasure_event: Hebb via
    trust spill + pesos adaptativos (advisory, fail-open).

    Returns el registro persistido (con emissions[] posiblemente vacio).
    No lanza hacia los flujos por diseño de storage: los callers
    fail-open (P2) envuelven esta funcion; aqui solo falla I/O real.
    """
    target = path or pleasure_file()
    event_ts = ts or _now_ts()
    history = read_history(target)
    result = evaluate(
        history,
        {"ts": event_ts, "unit": unit, "success": success, "detail": detail},
        window_days=window_days,
    )
    record: dict[str, Any] = {
        "event_id": _event_id(event_ts, unit, success, detail),
        "ts": event_ts,
        "unit": unit,
        "success": bool(success),
        "p": result["p"],
        "streak": result["streak"],
        "rpe": result["rpe"],
        "emissions": result["emissions"],
        "detail": detail,
        "source": source,
        "connection": connection,
    }
    append_record(target, record)
    if feedback and record["emissions"]:
        apply_hebbian(record)  # fail-open interno: jamas propaga
    return record


def stats(path: Path | None = None) -> dict[str, Any]:
    """Resumen determinista del canal (para narrativa P4 / CLI)."""
    records = read_history(path)
    by_kind: dict[str, int] = {}
    total_mag = 0.0
    milestones = 0
    for rec in records:
        for em in rec.get("emissions", []):
            kind = em.get("kind", "?")
            by_kind[kind] = by_kind.get(kind, 0) + 1
            total_mag += float(em.get("magnitude", 0.0))
            if kind == "milestone":
                milestones += 1
    units = sorted({r.get("unit", "?") for r in records})
    last_ts = records[-1].get("ts") if records else None
    return {
        "events": len(records),
        "successes": sum(1 for r in records if r.get("success")),
        "emissions": sum(by_kind.values()),
        "emissions_by_kind": {k: by_kind[k] for k in sorted(by_kind)},
        "milestones": milestones,
        "total_magnitude": round(total_mag, 6),
        "units": units,
        "last_ts": last_ts,
        "file": str(path or pleasure_file()),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pleasure_emitter",
        description="Algedonic pleasure channel (G-34) — emit/consulta",
    )
    parser.add_argument("--emit", metavar="UNIT",
                        help="evaluar y persistir un evento de unidad")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ok", action="store_true", help="evento exitoso")
    group.add_argument("--fail", action="store_true", help="evento fallido")
    parser.add_argument("--detail", default="", help="detalle humano")
    parser.add_argument("--source", default="", help="origen del evento")
    parser.add_argument("--connection", default="",
                        help="conexion Hebbiana (clave de confianza)")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_DAYS,
                        help="ventana rolling en dias (default 7 = G-03)")
    parser.add_argument("--file", default=None,
                        help="override del ledger (default RSI_PLEASURE_FILE)")
    parser.add_argument("--stats", action="store_true", help="resumen del canal")
    args = parser.parse_args(argv)

    target = Path(args.file) if args.file else None

    if args.stats:
        print(json.dumps(stats(target), ensure_ascii=False, indent=2))
        return 0

    if args.emit:
        if args.ok == args.fail:
            parser.error("--emit requiere exactamente --ok o --fail")
        rec = emit(
            args.emit,
            success=args.ok,
            detail=args.detail,
            source=args.source,
            connection=args.connection,
            window_days=args.window,
            path=target,
        )
        print(json.dumps(rec, ensure_ascii=False))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
