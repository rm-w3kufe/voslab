#!/usr/bin/env python3
"""activation_batch_report — weekly activation-queue batch for S5.

design: docs/plans/hygiene_audit_plan_2026_10_21.vsm (H2-F2: cadencia (ii) batch semanal)
route: vsf-gates-weekly.sh step-3 (Sun 04:00, Persistent=true) + invocación manual
verify: --selftest harness (fixtures en tmpdirs, aserciones internas) + pase manual

CLAIM: cada domingo el estado de la cola de activación se escribe en un
report fresco y, si hay candidatos esperando decisión S5, UNA sola alerta
hygiene_batch_ready (level notice, plataforma unacked → session boot).
Sin pendientes: PASS silencioso (estilo de la flota, no spam).
  pass → report escrito + alerta SÓLO si pending>0 (dadu: source y edad)
  fail → nunca; el pipeline DE reports no es un gate (el gate es otro);
         sólo rc != 0 cuando los args son absurdos o los dirs imposibles
Determinístico (R10): sin random, sin wall-clock salvo stamps de salida.

Anti-inflado: el report NUNCA aprueba/activa — kernel propone (cola),
S5 dispone (rsi-approve). El runner es la cara de la cadencia (ii).
"""
from __future__ import annotations

import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# ---------- dirs (defaults espejo del kernel/bridge, ver plan H0) ----------
DEFAULT_KERNEL_QUEUE = Path(os.environ.get(
    "RSI_QUEUE_DIR", "/home/rmw3/vOSlab/state/rsi/queue"))
DEFAULT_BRIDGE_QUEUE = Path("/home/rmw3/vOSlab/packages/public/state/queue")
DEFAULT_REPORT_PATH = Path("/home/rmw3/vOSlab/state/hygiene/queue_batch_report.json")
DEFAULT_ALERTS_PATH = Path("/home/rmw3/vOSlab/state/rsi/alerts.jsonl")
DEFAULT_LOG_PATH = Path("/home/rmw3/vOSlab/logs/agent_plugin.jsonl")

STATUSES = ("pending", "approved", "activated", "rejected")


def scan_queue(qdir: Path, label: str) -> dict:
    """Lee una cola de activación sin mutarla. Determinístico."""
    entries = []
    counts = {}
    if qdir.is_dir():
        for fn in sorted(qdir.glob("*.json")):
            try:
                data = json.loads(fn.read_text())
            except (json.JSONDecodeError, OSError):
                counts.setdefault("unreadable", 0)
                counts["unreadable"] += 1
                continue
            status = str(data.get("status", "missing"))
            counts.setdefault(status, 0)
            counts[status] += 1
            if status == "pending":
                try:
                    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        str(data.get("queued_at", "")).replace("Z", "+00:00")
                    )).total_seconds() / 3600.0
                except ValueError:
                    age_h = None
                entries.append({
                    "name": data.get("name", fn.stem),
                    "queue": label,
                    "source": data.get("source", "missing"),
                    "age_hours": round(age_h, 1) if age_h is not None else None,
                })
    return {"dir": str(qdir), "label": label, "counts": counts,
            "pending": sorted(entries, key=lambda e: (e["age_hours"] is None, e["age_hours"] or 0),
                              reverse=True)}


def report(kernel_queue: Path = DEFAULT_KERNEL_QUEUE,
           bridge_queue: Path = DEFAULT_BRIDGE_QUEUE,
           report_path: Path = DEFAULT_REPORT_PATH,
           alerts_path: Path = DEFAULT_ALERTS_PATH,
           log_path: Path = DEFAULT_LOG_PATH,
           write_report: bool = True, write_alert: bool = True) -> dict:
    """Genera el report del batch (y la alerta si toca). Devuelve el summary."""
    now = datetime.now(timezone.utc)
    summary = {
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "queues": [scan_queue(kernel_queue, "kernel"),
                   scan_queue(bridge_queue, "bridge")],
    }
    pending = sorted(summary["queues"][0]["pending"] + summary["queues"][1]["pending"],
                     key=lambda e: (e["age_hours"] is None, e["age_hours"] or 0),
                     reverse=True)
    summary["decisions_waiting_for_s5"] = [e["name"] for e in pending]
    summary["protocol"] = ("rsi-approve <name> → activated próximo ciclo "
                           "(plan hygiene_audit §chain_ratificado [3]-(ii))")

    if write_report:
        os.makedirs(report_path.parent, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False))

    if write_alert and pending:
        os.makedirs(alerts_path.parent, exist_ok=True)
        rec = {
            "alert_id": "alert-" + hashlib.sha256(
                (summary["generated_at"] + "|batch").encode()).hexdigest()[:12],
            "ts": summary["generated_at"],
            "level": "notice",
            "alert_type": "hygiene_batch_ready",
            "source": "activation_batch_report",
            "detail": f"{len(pending)} pending en cola de activación — batch S5: "
                      + ", ".join(e["name"] for e in pending[:8]),
            "evidence": {"names": [e["name"] for e in pending]},
            "trace_id": None, "session_id": None,
        }
        with open(alerts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log(summary, pending, log_path)
    return summary


def log(summary: dict, pending: list, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """1 línea formato B al log unificado (schema 2026-09-09)."""
    try:
        ev_id = hashlib.sha256(summary["generated_at"].encode()).hexdigest()[:10]
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "pid": os.getpid(), "level": "activation",
            "source": "activation-batch-report",
            "event_type": "hygiene.batch_report",
            "event_id": f"hygiene:batch:{ev_id}",
            "session_id": os.environ.get("VOS_SESSION_ID"),
            "action": f"batch report pending={len(pending)}",
            "result": "ok",
            "detail": {"decisions": [e["name"] for e in pending[:8]]},
            "context": {},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el report no es el gate; log best-effort


# ---------- selftest ----------
def selftest() -> int:
    tmp = Path("/tmp/opencode/hygiene_selftest")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    qk, qb, report_p, alerts_p = tmp / "kernel", tmp / "bridge", tmp / "report.json", tmp / "alerts.jsonl"
    qk.mkdir(parents=True); qb.mkdir()
    now = datetime.now(timezone.utc)

    def entry(name, status, queue, source="hygiene:audit"):
        p = (qk if queue == "kernel" else qb) / f"{name}.json"
        p.write_text(json.dumps({
            "name": name, "status": status, "source": source,
            "queued_at": now.isoformat(),
        }))
    entry("fake_hygiene_pending", "pending", "kernel")
    entry("fake_reject", "rejected", "kernel")
    entry("fake_activated", "activated", "bridge")
    ok = True

    rs = report(kernel_queue=qk, bridge_queue=qb,
                report_path=report_p, alerts_path=alerts_p,
                log_path=tmp / "log.jsonl",
                write_report=True, write_alert=True)
    if not report_p.exists():
        ok = False
    ok &= rs["decisions_waiting_for_s5"] == ["fake_hygiene_pending"]
    ok &= rs["queues"][0]["counts"].get("rejected") == 1
    ok &= rs["queues"][1]["counts"].get("activated") == 1
    # report escrito contiene las decisiones
    on_disk = json.loads(report_p.read_text())
    ok &= on_disk["decisions_waiting_for_s5"] == ["fake_hygiene_pending"]
    # alerta única con el nombre pending
    lines = alerts_p.read_text().strip().splitlines()
    ok &= len(lines) == 1
    if lines:
        a = json.loads(lines[0])
        ok &= a["alert_type"] == "hygiene_batch_ready" and a["level"] == "notice"
        ok &= "fake_hygiene_pending" in a["evidence"]["names"]
    # vacío → sin alerta (sin spam)
    for p in list(qk.glob("*.json")):
        p.unlink()
    for p in list(qb.glob("*.json")):
        p.unlink()
    entry("activated_only", "activated", "kernel")
    rs2 = report(kernel_queue=qk, bridge_queue=qb,
                 report_path=tmp / "report2.json", alerts_path=alerts_p,
                 log_path=tmp / "log.jsonl",
                 write_report=True, write_alert=True)
    ok &= rs2["decisions_waiting_for_s5"] == []
    ok &= len(alerts_p.read_text().strip().splitlines()) == 1  # no Double alert
    print(f"activation_batch_report: SELFTEST {'PASS' if ok else 'FAIL'} — "
          f"(pending→alerta única; rejected/activated excluidos; vacío→silencioso)")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(report() is not None and 0 or 0)
