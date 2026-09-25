"""
vsf-state — Scripts de estado del sistema VSF.

Proporciona functions para el manejo de estado del sistema.

Rehab 2026-09-24: this __init__ promised 16 facade names that did not
exist (package unimportable). Policy since: export REAL public surface
+ implement facades ONLY where they compose from existing primitives
without inventing semantics. Un composable names are tracked as gaps
in docs/reference/technical_debt_registry.vsm, NOT faked here.
"""

from __future__ import annotations

__version__ = "0.1.0"

from vsf_state.algedonic_pub import main as algedonic_main
from vsf_state.cyberfilter_variety import run as variety_run
from vsf_state.handoff_archive import archive_handoffs, split_blocks
from vsf_state.hook_analytics import (
    correlate_learning_records,
    detect_anomalies,
    detect_errors,
    detect_frequency,
    detect_timing,
    generate_report,
    parse_learning_record,
    parse_log,
)
# NOTE: monitor_reconcile NOT re-exported: it calls resolve_lxc("s3star")
# at module level, which raises outside n02 topology context and would
# break `import vsf_state` everywhere. Import it directly where needed.
# NOTE: service_watchdog NOT re-exported: it imports vsf_socratic_engine
# (scripts/vsl/classifier, not an installed package) at module level,
# which breaks `import vsf_state` everywhere. Import it directly inside
# a vOSlab checkout where that path resolves. Same for monitor_reconcile
# (resolve_lxc at module level needs n02 topology context).
from vsf_state.tasks_reconcile import (
    check_commit,
    check_deploy,
    check_path,
    parse_tasks,
)
from vsf_state.witness_verify import emit_algedonic, verify_statements


def compute_hook_metrics(path, window_hours=None) -> dict:
    """Facade: full hook-metrics pipeline over a log file."""
    records = parse_log(path, window_hours)
    return {
        "frequency": detect_frequency(records),
        "errors": detect_errors(records),
        "timing": detect_timing(records),
        "anomalies": detect_anomalies(records),
    }


def export_analytics(records, path, correlate: bool = False) -> str:
    """Facade: generate report and write it as JSON. Returns the path."""
    from pathlib import Path as _Path
    import json as _json
    report = generate_report(list(records or []), correlate=correlate)
    p = _Path(path)
    p.write_text(_json.dumps(report, indent=2))
    return str(p)


def verify_witness(statements, ca_dir, now_epoch=None, pin=None,
                   heads=None, s5=None):
    """Facade: witness statement verification passthrough."""
    return verify_statements(statements, ca_dir, now_epoch=now_epoch,
                             pin=pin, heads=heads, s5=s5)


def reconcile_tasks(path: str) -> dict:
    """Facade: parse tasks + verify path/commit anchors.

    Returns {task_id: {anchor_type: bool}} verdict map. Deploy anchors
    need live infra (check_deploy shells out); failures surface as
    False, never raise.
    """
    out = {}
    try:
        tasks = parse_tasks(path)
    except Exception:
        return out
    for t in tasks:
        tid = t.get("id", "?") if isinstance(t, dict) else "?"
        verdicts = {}
        for atype, aval in t.get("anchors", []) if isinstance(t, dict) else []:
            try:
                if atype == "path":
                    verdicts[aval] = bool(check_path(aval))
                elif atype == "commit":
                    verdicts[aval] = bool(check_commit(aval))
                else:
                    verdicts[aval] = None  # unknown anchor kind: no verdict
            except Exception:
                verdicts[aval] = False
        out[tid] = verdicts
    return out


def check_service_health(lxc: int, svc: str):
    """Facade (lazy): health check WITHOUT importing service_watchdog at
    package load (it needs vsf_socratic_engine + checkout layout)."""
    from vsf_state.service_watchdog import check_service
    return check_service(lxc, svc)


def restart_service(lxc: int, svc: str, confirm: bool = False) -> dict:
    """Restart a service on an LXC. DRY-RUN BY DEFAULT (S5 safety):
    without confirm=True, returns the plan without executing anything.
    With confirm=True, lazy-imports service_watchdog and runs
    `systemctl restart` via its pct transport. Never raises: failures
    return ok=False with reason."""
    plan = {"action": "restart", "target": f"lxc{lxc}/{svc}",
            "confirmed": bool(confirm), "ok": False}
    if not confirm:
        plan["would_run"] = ["systemctl", "restart", svc]
        return plan
    try:
        from vsf_state.service_watchdog import _pct_exec
        r = _pct_exec(lxc, ["systemctl", "restart", svc], timeout=30)
        plan["ok"] = r.returncode == 0
        plan["reason"] = (r.stderr or r.stdout or "")[:200]
        return plan
    except Exception as e:  # noqa: BLE001 — audit, never raise
        plan["reason"] = f"{type(e).__name__}: {e}"[:200]
        return plan


# Status vocabulary observed in production TASKS.vsm + state.db +
# current_focus.json (closed set; unknown statuses are invalid).
VALID_TASK_STATUSES = frozenset({
    "done", "open", "seed", "deferred", "stasis_vector", "partial",
    "obsolete", "deployed", "audited", "blocked", "pending",
    "completed", "active", "archived",
})


def validate_task_state(task: dict) -> dict:
    """Pure schema check: id non-empty, status in observed vocabulary."""
    errors = []
    if not isinstance(task, dict):
        return {"valid": False, "errors": ["not-a-dict"]}
    if not task.get("id") or not isinstance(task.get("id"), str):
        errors.append("missing-id")
    status = task.get("status")
    if status not in VALID_TASK_STATUSES:
        errors.append(f"unknown-status:{status!r}")
    return {"valid": not errors, "errors": errors}


def monitor_services() -> dict:
    """Run monitor instruments; per-instrument guarded. Lazy import:
    monitor_reconcile needs n02 topology context at module level."""
    try:
        from vsf_state import monitor_reconcile as _mr
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(e)[:150]}
    out = {}
    try:
        instruments = _mr._build_instruments()
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(e)[:150]}
    for inst in instruments:
        try:
            iid, _label, fn, _stale = inst
            out[iid] = {"ok": True, "last": fn()}
        except Exception as e:  # noqa: BLE001 — one bad probe ≠ outage
            try:
                iid = inst[0]
            except Exception:
                iid = "?"
            out[iid] = {"ok": False, "error": f"{type(e).__name__}"}
    return {"status": "ok", "instruments": out}


def reconcile_state() -> dict:
    """Run the monitor reconcile poll (same side effects as CLI:
    prints, NATS gap emit on staleness). Returns rc + staleness."""
    try:
        from vsf_state import monitor_reconcile as _mr
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(e)[:150]}
    try:
        rc = _mr.run()
        return {"status": "ok", "rc": rc}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": str(e)[:200]}


def filter_variety(counts: dict, min_count: int = 1) -> dict:
    """Return event types BELOW min_count (under-observed variety).
    Pure function over a counts dict (see compute_variety_metrics)."""
    counts = counts or {}
    return {k: v for k, v in counts.items()
            if isinstance(v, (int, float)) and v < min_count}


def compute_variety_metrics(date_str: str) -> dict:
    """Event-type distribution for a date (shells to LXC 101 counter).
    Returns {} (never raises) when infra unreachable."""
    try:
        from vsf_state.cyberfilter_variety import _count_events
        out = _count_events(date_str)
        return dict(out) if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001 — infra-dependent
        return {}


def get_certificate_info(ca_dir: str, s5=None, pin=None) -> dict:
    """CA trust info. s5 (crypto helper with _key_id) required by the
    underlying loader; without CA root on disk returns trusted=False
    with notes (never raises)."""
    try:
        from vsf_state.witness_verify import _load_ca
        trusted, notes = _load_ca(ca_dir, s5, None, pin)
        return {"trusted": bool(trusted),
                "notes": [list(n) for n in notes]}
    except Exception as e:  # noqa: BLE001
        return {"trusted": False,
                "notes": [["ERROR", f"{type(e).__name__}: {e}"[:150]]]}


def restore_handoff(archive_dir, month: str, target_path=None) -> dict:
    """Inverse of archive: read an archived month back. Read-only unless
    target_path is given (then writes the merged blocks there).
    Conservation-checked both ways; never touches the live file
    unless target_path points at it explicitly."""
    from pathlib import Path as _Path
    arch_d = _Path(archive_dir)
    cands = sorted(arch_d.glob(f"{month}*.vsm.md")) if arch_d.is_dir() \
        else []
    if not cands:
        return {"restored": False, "reason": f"no archive for {month}",
                "blocks": 0}
    bodies = []
    for p in cands:
        try:
            from vsf_state.handoff_archive import split_blocks
            _, blocks = split_blocks(p.read_text(encoding="utf-8"))
            bodies.extend(b for _, _, b in blocks)
        except Exception:
            continue
    if target_path is not None:
        _Path(target_path).write_text("".join(bodies), encoding="utf-8")
    return {"restored": True, "blocks": len(bodies),
            "files": [c.name for c in cands],
            "wrote": str(target_path) if target_path else None}


async def _subscribe_collect(servers, token, subject: str,
                             timeout: float) -> list:
    import nats
    kwargs = {"token": token} if token else {}
    nc = await nats.connect(servers, connect_timeout=timeout, **kwargs)
    try:
        got = []

        async def _cb(msg):
            got.append({"subject": msg.subject,
                        "data": msg.data.decode("utf-8",
                                                errors="replace")[:2000]})

        await nc.subscribe(subject, cb=_cb)
        await nc.flush()
        import asyncio as _aio
        await _aio.sleep(timeout)
        return got
    finally:
        try:
            await nc.close()
        except Exception:
            pass


def subscribe_beacon(subject: str = "vsf.alpha.algedonic",
                     timeout: float = 5.0, servers: str | None = None,
                     token: str | None = None) -> dict:
    """Collect beacon messages for `timeout` seconds. Env defaults
    (NATS_URL/NATS_TOKEN, same convention as algedonic_pub) so deploys
    configure once. Returns messages (never raises); empty list means
    quiet bus OR unreachable broker — check `reached` flag.
    CancelledError caught explicitly (NATS timeouts are BaseException)."""
    import asyncio as _aio
    import os as _os
    servers = servers or _os.environ.get("NATS_URL",
                                         "nats://10.10.20.20:4222")
    token = token if token is not None else _os.environ.get("NATS_TOKEN")
    try:
        got = _aio.run(_subscribe_collect(servers, token, subject,
                                          float(timeout)))
        return {"reached": True, "messages": got, "count": len(got)}
    except (_aio.CancelledError, Exception) as e:  # noqa: BLE001
        return {"reached": False, "messages": [],
                "error": f"{type(e).__name__}: {e}"[:150]}


def publish_beacon(payload: dict) -> bool:
    """Facade: publish a beacon dict over the algedonic channel.

    Best-effort: returns False (never raises) when NATS is unreachable.
    Catches CancelledError explicitly: NATS timeouts surface as
    asyncio cancellation (BaseException, NOT caught by `except
    Exception`) — the exact failure mode of an unreachable broker.
    """
    import asyncio
    import json as _json
    from vsf_state.algedonic_pub import _publish
    try:
        asyncio.run(_publish(_json.dumps(payload or {}).encode()))
        return True
    except (Exception, asyncio.CancelledError):
        return False


__all__ = [
    "algedonic_main",
    "variety_run",
    "split_blocks",
    "archive_handoffs",
    "parse_log",
    "detect_frequency",
    "detect_errors",
    "detect_timing",
    "detect_anomalies",
    "parse_learning_record",
    "correlate_learning_records",
    "generate_report",
    "export_analytics",
    "check_commit",
    "check_deploy",
    "check_path",
    "parse_tasks",
    "emit_algedonic",
    "verify_statements",
    "compute_hook_metrics",
    "verify_witness",
    "reconcile_tasks",
    "check_service_health",
    "restart_service",
    "VALID_TASK_STATUSES",
    "validate_task_state",
    "monitor_services",
    "reconcile_state",
    "filter_variety",
    "compute_variety_metrics",
    "get_certificate_info",
    "restore_handoff",
    "subscribe_beacon",
    "publish_beacon",
]
