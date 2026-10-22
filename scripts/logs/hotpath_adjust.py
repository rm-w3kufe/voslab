#!/usr/bin/env python3
"""hotpath_adjust.py — Fase A D3-C2->3: ajuste observable del hot-path query_sessions.

Diseño vivo: docs/spec_revision/design-sources/rsi-observer-v1/vsf_rsi_design.vsm
Propuesta ratificada: docs/plans/observable_adjustment_metric_2026_10_22.vsm
Candidato 1: pred activado `bridge_query_sessions_hotpath` (sha 5d0ad33d).
  trigger: cold-scan del hot-path > umbral (BYTES del span set — R10, el
           tiempo NO es determinístico; observado 2026-10-21: 215MB ≈ 11.5s)
  acción:  log_retention.apply() — archivar spans >30d (MOVE-only, R17-safe,
           mecanismo PRE-ratificado por S5, retención 2026-10-21)
  registro: state/rsi/adjustments.jsonl (adjustments_log.append_entry)

Aplicación: determinística — mismo estado disk → mismo veredicto.
Uso:
    --check    reporte del estado (dry-run, no cambia nada)
    --apply    ejecutar el mecanismo si armado y suficiente
    --selftest demo tmp end-to-end (delta>0 real; witness para el gate)
    --measure  diagnóstico con timer, SOLO humano, NUNCA decide
"""
import gzip
import json
import os
import sys
import time
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import log_retention  # noqa: E402

sys.path.insert(0, str(VOSLAB / "scripts" / "state" / "rsi"))
import adjustments_log  # noqa: E402

# Umbral bytes del hot-path (light probe determinístico — sin timer):
# 215MB/250 spans ≈ 11.5s cold-scan observado; 120MB ≈ demarcación honesta.
PROBABLY_HOT_BYTES = int(
    os.environ.get("HOTPATH_BYTES_THRESHOLD", str(120 * 2 ** 20)))  # 120MB
PRED_NAME = "bridge_query_sessions_hotpath"
PRED_SHA = "5d0ad33de836706f"  # state/rsi/activated.json (bindeado)
EVID = "state/logs_retention.json"


def _adjustments_ts() -> str:
    return time.strftime(adjustments_log.TS_FORMAT, time.gmtime())


def current_threshold() -> int:
    """Umbral vivo (dinámico — el selftest lo baja por env; R10: el valor
    es pura función del env/disk, sin random ni reloj)."""
    return int(os.environ.get("HOTPATH_BYTES_THRESHOLD",
                              str(PROBABLY_HOT_BYTES)))


def probe(voslab: Path) -> dict:
    """Light probe: bytes/count de spans vivos (logs/*.gz, archive excluido).

    NEVER timer-based (R10): bytes determinísticos, outer cost model
    (bytes_proportional cold-scan)."""
    log_dir = voslab / "logs"
    out = {"bytes": 0, "spans": 0, "candidates": 0, "candidates_bytes": 0}
    if not log_dir.is_dir():
        return out
    n = 0
    b = 0
    for f in sorted(log_dir.iterdir()):
        if f.is_file() and f.name.startswith("agent_plugin") \
                and f.name.endswith(".gz"):
            b += f.stat().st_size
            n += 1
    cand = list(log_retention.candidates()) if voslab == VOSLAB \
        else _tmp_candidates(voslab)
    out["bytes"] = b
    out["spans"] = n
    out["candidates"] = len(cand)
    out["candidates_bytes"] = sum(c.stat().st_size for c in cand)
    return out


def _tmp_candidates(voslab: Path):
    """candidates() con VOSLAB_PATH tmp inyectado (sin hard-frozen global)."""
    saved = os.environ.get("VOSLAB_PATH")
    os.environ["VOSLAB_PATH"] = str(voslab)
    try:
        return list(log_retention.candidates())
    finally:
        if saved is None:
            os.environ.pop("VOSLAB_PATH", None)
        else:
            os.environ["VOSLAB_PATH"] = saved


def build_entry(voslab: Path, before: dict, after: dict, moved: list,
                escritor: str) -> dict:
    """Entry del ajuste: atribuid (pred+sha), antes/después y delta real."""
    mecanismo = "demo-tmp-replay" if escritor == "fase-b-demo" \
        else "retention-trigger"
    return {
        "ts": _adjustments_ts(),
        "pred": PRED_NAME,
        "pred_sha": PRED_SHA,
        "mecanismo": mecanismo,
        "before": f"{before['spans']} spans, {before['bytes']} bytes vivos "
                  f">= umbral {current_threshold()}",
        "after": f"{after['spans']} spans, {after['bytes']} bytes vivos "
                 f"(archivados {len(moved)}: {', '.join(moved) if moved else 'n/a'})",
        "delta": before["bytes"] - after["bytes"],
        "delta_unit": "bytes_spans_vivos",
        "evidencia": EVID if voslab == VOSLAB else "demo-report.json",
        "reversible": True,
        "escrito_por": escritor,
    }


def apply_mechanism(voslab: Path, escritor: str = "hotpath_adjust") -> dict:
    """Armed → trigger log_retention.apply() → entry delta-verificada."""
    before = probe(voslab)
    thresh = current_threshold()
    if before["bytes"] <= thresh:
        return {"armed": False, "reason": "dentro del umbral "
                f"({before['bytes']} bytes <= {thresh})",
                "before": before, "after": None, "entry": None, "moved": []}
    if before["candidates"] == 0:
        return {"armed": True, "reason": "hot PERO sin spans >30d "
                "archivables — la rotación viva no es la causa; reporta "
                "sin actuar (honestidad)",
                "before": before, "after": None, "entry": None, "moved": []}
    est_after = before["bytes"] - before["candidates_bytes"]
    if est_after > thresh:
        return {"armed": True, "reason": "hot y el archivo NO suficiente -- "
                "mecanismo insuficiente; NO auto-actúa (apología honesta)",
                "before": before, "after": None, "entry": None, "moved": []}
    if voslab == VOSLAB:
        moved = log_retention.apply()
        log_retention.state_write(moved)
    else:
        moved = []
        archive = voslab / "logs" / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        for c in _tmp_candidates(voslab):
            dst = archive / c.name
            if dst.exists():
                continue
            c.rename(dst)
            moved.append(dst.name)
        (voslab / "demo-report.json").write_text(
            json.dumps({"moved": moved, "umbral": PROBABLY_HOT_BYTES,
                        "before": before, "ts": _adjustments_ts()},
                       ensure_ascii=False, indent=2))
    after_p = probe(voslab)
    entry = build_entry(voslab, before, after_p, moved, escritor)
    ok, why = adjustments_log.valid_entry(entry)
    if not ok:
        raise RuntimeError(f"entry generada inválida (bug Fase A): {why}")
    return {"armed": True, "reason": "ajustado — spans >30d archivados",
            "before": before, "after": after_p, "entry": entry, "moved": moved}


def _measure(voslab: Path) -> dict:
    """Diagnóstico EXPLÍCITO con timer (humano; no decide nada)."""
    log_dir = voslab / "logs"
    t0 = time.time()
    nb = 0
    for f in sorted(log_dir.iterdir()):
        if f.name.startswith("agent_plugin") and f.name.endswith(".gz"):
            try:
                with gzip.open(f, "rb") as fh:
                    while fh.read(1 << 20):
                        nb += 1 << 20
            except OSError:
                continue
    return {"leidos_mb": nb // (1 << 20), "wall_s": round(time.time() - t0, 2)}


def _selftest() -> int:
    """Demo tmp end-to-end → JSON con entries delta>0 (witness atemporal)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        vos = Path(td)
        logs = vos / "logs"
        logs.mkdir()
        now = time.time()
        fresh = logs / "agent_plugin.jsonl.1999999900.jsonl.gz"
        fresh.write_bytes(b"\x1f\x8b" + b"0" * 200000)  # 200KB pseudo-gz
        os.utime(fresh, (now - 86400, now - 86400))
        for i in range(3):
            f = logs / f"agent_plugin.jsonl.19999999{3 - i}00.jsonl.gz"
            f.write_bytes(b"\x1f\x8b" + b"0" * 200000)  # 200KB ea.
            old = now - 40 * 86400
            os.utime(f, (old, old))
        saved = os.environ.get("HOTPATH_BYTES_THRESHOLD")
        os.environ["HOTPATH_BYTES_THRESHOLD"] = str(300000)  # 300KB demo
        try:
            r = apply_mechanism(vos, escritor="fase-b-demo")
        finally:
            if saved is None:
                os.environ.pop("HOTPATH_BYTES_THRESHOLD", None)
            else:
                os.environ["HOTPATH_BYTES_THRESHOLD"] = saved
        out = {"armed": r["armed"], "reason": r["reason"],
               "before": r.get("before"), "after": r.get("after"),
               "entries": [r["entry"]] if r.get("entry") else [],
               "moved": r.get("moved", [])}
        if not r["armed"] or not r.get("entry"):
            print(json.dumps(out, ensure_ascii=False)[:400])
            return 1
        if r["entry"]["delta"] <= 0:
            print(f"FAIL: delta=0 ({r['entry']['delta']})", file=sys.stderr)
            return 1
        ok, why = adjustments_log.valid_entry(r["entry"])
        if not ok:
            print(f"FAIL: entry demo inválida: {why}", file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False))
        return 0


def main() -> int:
    args = sys.argv[1:]
    if args == ["--check"]:
        b = probe(VOSLAB)
        thresh = current_threshold()
        armed = b["bytes"] > thresh
        print(f"hot-path probe: {b['spans']} spans vivos, {b['bytes']} bytes; "
              f"umbral {thresh} → "
              f"{'ARMED (hot-path hot)' if armed else 'dentro de umbral'}; "
              f"{b['candidates']} spans >30d archivables "
              f"({b['candidates_bytes']} bytes)")
        return 0
    if args == ["--apply"]:
        r = apply_mechanism(VOSLAB)
        print(json.dumps({k: r.get(k) for k in
                          ("armed", "reason", "before", "after", "moved")},
                         ensure_ascii=False, indent=2))
        if r.get("entry"):
            ok, why = adjustments_log.append_entry(r["entry"])
            if not ok:
                print(f"FAIL: entry real no apuntada: {why}", file=sys.stderr)
                return 1
            print(f"ENTRY APUNTADA: delta={r['entry']['delta']} "
                  f"({r['entry']['delta_unit']}) → "
                  f"state/rsi/adjustments.jsonl")
        return 0 if r["armed"] else 1
    if args == ["--selftest"]:
        return _selftest()
    if args == ["--measure"]:
        print(json.dumps(_measure(VOSLAB), indent=2))
        return 0
    print("usage: [--check|--apply|--selftest|--measure]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
