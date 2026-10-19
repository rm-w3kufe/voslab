#!/usr/bin/env python3
"""external_detectors — Delta A de hardening-gaps-2026-10 (ad2dfd3).

# design: docs/spec_revision/design-sources/hardening-gaps-2026-10.vsm

ALGEDONIC-TRIAGE-v1 es un consumer maduro (AUS/triage/remediate) pero sus
producers son eventos INTERNOS (gates, bridge, alerts de state). Este módulo
es el family de producers de trabajos EXTERNOS que faltaba:

  1. external_job_stall  — job RUNNING sin progreso por T (SFT 12h hang).
  2. no_progress         — job con cero steps tras su ventana de arranque.
  3. resource_waste      — presupuesto asignado >> usado (slack 25108s).
  4. reality_score_shock — score externo == 0 tras artefacto certificado.

R10: detectores puros y deterministas — `now` es inyectable; sin LLM, sin
red en el path de detección. El emitter appendea al canal canónico
`state/rsi/alerts.jsonl` (formato {alert_id, ts, level, alert_type, source,
detail}) que alert_triage.py ya consume; los alert_types nuevos se clasifican
como HEALTH (algedonic_triage.vsm §2, post-detector R16).

Uso:
  external_detectors.py check [--registry PATH] [--alerts PATH] [--now ISO]
  external_detectors.py probe [--registry PATH] [--timeout S]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_REGISTRY = os.path.join(os.path.dirname(__file__), "external_jobs.json")
DEFAULT_ALERTS = os.path.join(ROOT, "state", "rsi", "alerts.jsonl")

# Umbrales por defecto (deterministas; el registry puede sobreescribir por job)
STALL_MAX_MIN = 20.0        # RUNNING sin progreso por 20min = stall
PROGRESS_WINDOW_MIN = 30.0  # cero steps en 30min tras arranque = no_progress
WASTE_MIN_USED_FRAC = 0.25  # <25% del presupuesto usado con >50% del tiempo
WASTE_MIN_ELAPSED_S = 3600.0

LEVEL = "error"


def _parse_ts(value) -> _dt.datetime:
    if isinstance(value, _dt.datetime):
        return value
    s = str(value or "").replace("Z", "+00:00")
    dt = _dt.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _now_utc(now=None) -> _dt.datetime:
    if now is None:
        return _dt.datetime.now(_dt.timezone.utc)
    return _parse_ts(now)


# ── detectores puros (R10) ────────────────────────────────────────────────

def detect_stall(jobs, now) -> list[dict]:
    """Job phase=running con last_progress_ts más viejo que stall_max_min."""
    now = _now_utc(now)
    out = []
    for j in jobs:
        if str(j.get("phase", "")).lower() != "running":
            continue
        lp = j.get("last_progress_ts")
        if not lp:
            continue
        age_min = (now - _parse_ts(lp)).total_seconds() / 60.0
        if age_min > float(j.get("stall_max_min", STALL_MAX_MIN)):
            out.append({
                "level": LEVEL,
                "alert_type": "external_job_stall",
                "source": f"external-detectors({j.get('name', '?')})",
                "detail": (f"job {j.get('name')} RUNNING sin progreso "
                           f"{age_min:.1f}min (> {j.get('stall_max_min', STALL_MAX_MIN)})"),
            })
    return out


def detect_no_progress(jobs, now) -> list[dict]:
    """Job phase=running con steps==0 tras su ventana de arranque."""
    now = _now_utc(now)
    out = []
    for j in jobs:
        if str(j.get("phase", "")).lower() != "running":
            continue
        if j.get("steps") is None:
            continue
        started = j.get("started_ts") or j.get("last_progress_ts")
        if not started:
            continue
        window = float(j.get("progress_window_min", PROGRESS_WINDOW_MIN))
        age_min = (now - _parse_ts(started)).total_seconds() / 60.0
        if int(j.get("steps", 0)) == 0 and age_min > window:
            out.append({
                "level": LEVEL,
                "alert_type": "no_progress",
                "source": f"external-detectors({j.get('name', '?')})",
                "detail": (f"job {j.get('name')} con 0 steps tras "
                           f"{age_min:.1f}min (> ventana {window})"),
            })
    return out


def detect_waste(jobs, now) -> list[dict]:
    """Job phase=running con used_s << budget_s (asignación ociosa)."""
    now = _now_utc(now)
    out = []
    for j in jobs:
        if str(j.get("phase", "")).lower() != "running":
            continue
        budget = float(j.get("budget_s") or 0)
        used = float(j.get("used_s") or 0)
        if budget <= 0:
            continue
        started = j.get("started_ts")
        if not started:
            continue
        elapsed = (now - _parse_ts(started)).total_seconds()
        frac = used / budget
        if (frac < WASTE_MIN_USED_FRAC and elapsed > max(WASTE_MIN_ELAPSED_S, budget * 0.5)):
            out.append({
                "level": LEVEL,
                "alert_type": "resource_waste",
                "source": f"external-detectors({j.get('name', '?')})",
                "detail": (f"job {j.get('name')} usó {used:.0f}s de budget "
                           f"{budget:.0f}s ({frac:.0%}) tras {elapsed:.0f}s elapsed"),
            })
    return out


def detect_score_shock(submissions) -> list[dict]:
    """Score externo == 0 tras un artefacto interno certificado (H-FMT class)."""
    out = []
    for s in submissions or []:
        if float(s.get("score") or 0) == 0.0 and s.get("artifact_certified"):
            out.append({
                "level": LEVEL,
                "alert_type": "reality_score_shock",
                "source": f"external-detectors({s.get('competition', '?')})",
                "detail": (f"score 0 en {s.get('competition')} tras artefacto "
                           f"certificado ({s.get('ref', '?')}) — reality gate "
                           f"o formato; diagnosticar antes de re-push"),
            })
    return out


# ── emitter canónico (canal algedónico existente) ─────────────────────────

def _unacked_keys(alerts_path: str) -> set[tuple]:
    keys = set()
    if not os.path.exists(alerts_path):
        return keys
    try:
        with open(alerts_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("acknowledged"):
                    continue
                keys.add((row.get("alert_type"), row.get("source")))
    except OSError:
        pass
    return keys


def emit(alerts: list[dict], alerts_path: str = DEFAULT_ALERTS) -> int:
    """Appendea alertas al canal canónico; dedupe por (type, source) unacked."""
    if not alerts:
        return 0
    existing = _unacked_keys(alerts_path)
    n = 0
    os.makedirs(os.path.dirname(alerts_path), exist_ok=True)
    with open(alerts_path, "a") as fh:
        for a in alerts:
            key = (a.get("alert_type"), a.get("source"))
            if key in existing:
                continue
            row = {
                "alert_id": f"alert-{int(time.time() * 1000)}-{os.getpid() % 1000000:06d}",
                "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "level": a.get("level", LEVEL),
                "alert_type": a["alert_type"],
                "source": a["source"],
                "detail": a["detail"],
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing.add(key)
            n += 1
    return n


# ── adapter de estado (única parte con red; nunca en el path de detección) ─

def probe_kaggle(registry_path: str = DEFAULT_REGISTRY, timeout: int = 30) -> dict:
    """Actualiza phase/last_progress de jobs declarados con kaggle_kernel.

    Determinista en SU efecto observable: sólo escribe el registry. RUNNING
    + logs no vacíos => last_progress_ts=now. QUEUED/COMPLETE/ERROR => phase.
    """
    kg = os.path.expanduser("~/.local/share/kaggle/venv/bin/kaggle")
    env = dict(os.environ, KAGGLE_CONFIG_DIR=os.path.expanduser("~/.kaggle"))
    with open(registry_path) as fh:
        reg = json.load(fh)
    updated = {}
    for j in reg.get("jobs", []):
        slug = j.get("kaggle_kernel")
        if not slug:
            continue
        try:
            out = subprocess.run(
                [kg, "kernels", "status", slug],
                capture_output=True, text=True, timeout=timeout, env=env,
            ).stdout
            phase = "unknown"
            for pfx in ("KernelWorkerStatus.", "WorkerStatus."):
                if pfx in out:
                    phase = out.split(pfx, 1)[1].split()[0].strip("[]'\"")
                    break
            j["phase"] = phase.lower()
            if phase.upper() == "RUNNING":
                logs = subprocess.run(
                    [kg, "kernels", "logs", slug],
                    capture_output=True, text=True, timeout=timeout, env=env,
                ).stdout
                if logs.strip():
                    j["last_progress_ts"] = _dt.datetime.now(
                        _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            updated[j.get("name", slug)] = j["phase"]
        except (subprocess.SubprocessError, OSError) as e:
            j["probe_error"] = repr(e)[:120]
    with open(registry_path, "w") as fh:
        json.dump(reg, fh, indent=2, ensure_ascii=False)
    return updated


# ── CLI ────────────────────────────────────────────────────────────────────

def run_check(registry_path: str, alerts_path: str, now=None) -> int:
    with open(registry_path) as fh:
        reg = json.load(fh)
    jobs = reg.get("jobs", [])
    alerts = (
        detect_stall(jobs, now)
        + detect_no_progress(jobs, now)
        + detect_waste(jobs, now)
        + detect_score_shock(reg.get("submissions", []))
    )
    n = emit(alerts, alerts_path)
    print(f"external_detectors: {len(jobs)} jobs, {len(alerts)} findings, "
          f"{n} emitted (dedupe on)")
    for a in alerts:
        print(f"  [{a['alert_type']}] {a['detail']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="corre los detectores sobre el registry")
    c.add_argument("--registry", default=DEFAULT_REGISTRY)
    c.add_argument("--alerts", default=DEFAULT_ALERTS)
    c.add_argument("--now", default=None, help="ISO override (tests/forensis)")
    p = sub.add_parser("probe", help="actualiza el registry vía kaggle CLI")
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    p.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return run_check(args.registry, args.alerts, args.now)
    if args.cmd == "probe":
        updated = probe_kaggle(args.registry, args.timeout)
        print("probe:", updated or "sin jobs kaggle")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
