#!/usr/bin/env python3
"""S3 guardia programada — SHADOW-SCHEDULED-SUITE-1 (ratificado S5 2026-10-20).

design: docs/spec_revision/design-sources/shadow-scheduled-suite-design.vsm

Fase 1 (landeada): systemd user timer horario, familia vsf-* existente
(gates-daily/docs-reconcile). gap-resolver NO sirve como runner: su forma
es de EVENTO/archivo, no de tiempo — ajuste transparente post-ratificación.
Fase 2 (consideración S5): runner arch-agnostic (WSL→LXC→bare-metal/VM)
vía API; agentes de vOS anidados reportando sin sistema completo junto al
núcleo (modelo n02) — task RUNNER-ARCH-API-1.

Ciclo (suite completa ~55s medido + censo + externos + canary):
  1. run-gates           86 live + 27 NC
  2. variety-census      census + error_burst (N=5, S2)
  3. external-run        probe ANTES de check — pareja obligada (S8)
  4. env-parity-canary   D-SA3 (rmw3 S5 2026-10-20, voto A): 3 tests
     corren SIN VOSLAB_PATH (env strippado) en UNA invocacion y en orden
     envenenador->victima: test_audit_pipeline (el setdefault que
     enveneno la sesion A4) -> test_bridge (live=0 si el root queda
     mal) -> test_gates_green (run_gates interno). Detecta la clase
     env/cwd en <=1h (antes: solo el weekly, <=7d). ~10-20s.

Shadow: primeros SHADOW_CYCLES=7 ciclos log-only (sin alerts.jsonl);
despues, rc!=0 de cualquier paso → UNA alert HEALTH algedónica.
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
    # D3-C2->3 (opción A, S5 'de acuerdo' 2026-10-22): trigger observable
    # del pred bridge_query_sessions_hotpath — rc-normalizado (no-armado
    # NO es fallo); excepción mecanismo = failing-step algedónico.
    ("obsadj-check", [
        sys.executable, str(VOS / "scripts/state/monitoring/obsadj_step.py")]),
    # D-SA3 canary (voto S5 2026-10-20): env sin VOSLAB_PATH, orden matters —
    # el envenenador historico importa ANTES que la victima para que un
    # regreso de setdefault-con-profundidad-mala falle aqui, en la hora.
    ("env-parity-canary", [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--import-mode=importlib",
        str(VOS / "system/kernel/tests/test_audit_pipeline.py"),
        str(VOS / "packages/framework/epistemic_graph/tests/test_bridge.py"),
        str(VOS / "packages/framework/vos_kernel/tests/test_second_order_loop_e2e.py::test_gates_green"),
    ], "strip-voslab-path"),
]


def step_env(kind: str | None):
    """strip-voslab-path: full env copy minus VOSLAB_PATH (D-SA3). None = hereda."""
    if kind == "strip-voslab-path":
        e = dict(os.environ)
        e.pop("VOSLAB_PATH", None)
        return e
    return None


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
    for item in STEPS:
        name, cmd = item[0], item[1]
        envx = step_env(item[2] if len(item) > 2 else None)
        s = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=STEP_TIMEOUT_S, cwd=str(VOS), env=envx)
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
    # atomic (T6-F1, plan 2026-10-20): unique pid-tmp + replace — readers of
    # scheduled_suite_last.json (canary, tests) never see a torn stamp.
    _tmp = STAMP.parent / f".{STAMP.name}.{os.getpid()}.tmp"
    _tmp.write_text(json.dumps(stamp, indent=2, ensure_ascii=False) + "\n")
    os.replace(_tmp, STAMP)
    # v1 reporter (design runner_telemetry_api_design v1.1, S5 'todo
    # autorizado'): fire-and-forget POST al server staging; UNA API caída
    # NUNCA cambia el rc del ciclo (fail-open per contract). El POST se
    # hace DESPUÉS del replace local — el store local siempre se escribe
    # primero, R9-compatible.
    _report_to_api(stamp)
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


def _report_to_api(stamp: dict) -> None:
    """fire-and-forget POST al runner API (loopback staging). El rc local
    de la suite es lo ÚNICO que decide el outcome del ciclo."""
    url = os.environ.get("RUNNER_API_URL")
    if not url:
        return
    try:
        import urllib.request
        payload = {"api": "1.0", "producer": "scheduled_suite",
                   "agent_id": os.environ.get("RUNNER_AGENT_ID",
                                              "vsf-sched-suite-wsl"),
                   **{k: stamp.get(k) for k in
                      ("cycle_n", "ts", "wall_s", "ok", "steps")}}
        data = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(
            f"{url}/api/v1/cycles", data=data,
            headers={"Content-Type": "application/json",
                     "X-VOS-Agent": payload["agent_id"]}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8", errors="replace")[:120]
            print(f"[runner-api] {url}: {body}")
    except Exception as e:  # noqa: BLE001 — fail-open absoluto
        print(f"[runner-api] POST skip ({str(e)[:80]}) — ciclo local ok")


if __name__ == "__main__":
    sys.exit(main())
