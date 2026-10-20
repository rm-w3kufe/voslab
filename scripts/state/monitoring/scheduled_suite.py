#!/usr/bin/env python3
"""S3 guardia programada — SHADOW-SCHEDULED-SUITE-1 (ratificado S5 2026-10-20).

design: docs/spec_revision/design-sources/shadow-scheduled-suite-design.vsm

Fase 1 (landeada): systemd user timer horario, familia vsf-* existente
(gates-daily/docs-reconcile). gap-resolver NO sirve como runner: su forma
es de EVENTO/archivo, no de tiempo — ajuste transparente post-ratificación.
Fase 2 (consideración S5): runner arch-agnostic (WSL→LXC→bare-metal/VM)
vía API; agentes de vOS anidados reportando sin sistema completo junto al
núcleo (modelo n02) — task RUNNER-ARCH-API-1.

Ciclo (suite completa ~55s medido + censo + externos):
  1. run-gates        86 live + 27 NC
  2. variety-census   census + error_burst (N=5, S2)
  3. external-run     probe ANTES de check — pareja obligada (S8)

Shadow: primeros SHADOW_CYCLES=7 ciclos log-only (sin alerts.jsonl);
después, rc!=0 de cualquier paso → UNA alert HEALTH algedónica.
Fail-loud SIEMPRE: stamp + agent_plugin.jsonl en cada ciclo (R9).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VOS = Path("/home/rmw3/vOSlab")
STAMP = VOS / "state/monitoring/scheduled_suite_last.json"
ALERTS = VOS / "state/rsi/alerts.jsonl"
EVENTS = VOS / "logs/agent_plugin.jsonl"
SHADOW_CYCLES = 7
STEP_TIMEOUT_S = 600

STEPS = [
    ("run-gates", [sys.executable, str(VOS / "packages/framework/run_gates.py")]),
    ("variety-census", [sys.executable,
                        str(VOS / "scripts/state/monitoring/variety_census.py")]),
    ("external-run", [sys.executable,
                      str(VOS / "scripts/state/monitoring/external_detectors.py"),
                      "run"]),
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def alert(level: str, atype: str, detail: str, evidence: dict) -> None:
    rec = {
        "alert_id": f"alert-{int(time.time()*1000)}-{os.getpid()}",
        "ts": utcnow(), "level": level, "alert_type": atype,
        "source": "vsf-scheduled-suite.timer", "detail": detail[:500],
        "evidence": evidence, "trace_id": None, "session_id": None,
    }
    with ALERTS.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def event(result: str, wall_ms: int, detail: dict) -> None:
    rec = {
        "ts": utcnow(), "pid": os.getpid(), "level": "info",
        "source": "scheduled-suite", "event_type": "cycle.suite",
        "event_id": f"suite-{int(time.time()*1000)}", "session_id": None,
        "action": "scheduled_suite_cycle", "result": result,
        "detail": detail, "context": {"shadow": detail.get("shadow")},
        "duration_ms": wall_ms,
    }
    with EVENTS.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    os.environ.setdefault("KAGGLE_CONFIG_DIR", str(Path.home() / ".kaggle"))
    prev = json.loads(STAMP.read_text()) if STAMP.is_file() else {}
    cycle_n = int(prev.get("cycle_n", 0)) + 1
    shadow = cycle_n <= SHADOW_CYCLES
    t0 = time.time()
    results, worst = [], 0
    for name, cmd in STEPS:
        s = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=STEP_TIMEOUT_S, cwd=str(VOS))
            rc = p.returncode
            tail = ((p.stdout or "")[-300:] + "|" + (p.stderr or "")[-150:])
        except subprocess.TimeoutExpired:
            rc, tail = 99, f"timeout {STEP_TIMEOUT_S}s"
        results.append({"name": name, "rc": rc,
                        "secs": round(time.time() - s, 1), "tail": tail})
        worst = max(worst, rc)
    wall = round(time.time() - t0, 1)
    stamp = {"cycle_n": cycle_n, "shadow": shadow, "ts": utcnow(),
             "wall_s": wall, "ok": worst == 0, "steps": results}
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(stamp, indent=2, ensure_ascii=False) + "\n")
    event("pass" if worst == 0 else "fail", int(wall * 1000),
          {"cycle_n": cycle_n, "shadow": shadow, "ok": worst == 0,
           "rcs": {r["name"]: r["rc"] for r in results}})
    if worst != 0:
        detail = "; ".join(f"{r['name']}({r['rc']})" for r in results if r["rc"])
        if shadow:
            print(f"[shadow {cycle_n}/{SHADOW_CYCLES}] FAIL silencioso: {detail}")
        else:
            alert("error", "scheduled_suite_fail", detail,
                  {"cycle_n": cycle_n, "rcs": [r["rc"] for r in results]})
            print(f"FAIL (alert emitida): {detail}")
    else:
        print(f"cycle {cycle_n}{' (shadow)' if shadow else ''}: PASS "
              f"en {wall}s — pasos: " +
              ", ".join(f"{r['name']}={r['secs']}s" for r in results))
    return worst


if __name__ == "__main__":
    sys.exit(main())
