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
from vsf_state.handoff_archive import split_blocks
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
    "parse_log",
    "detect_frequency",
    "detect_errors",
    "detect_timing",
    "detect_anomalies",
    "parse_learning_record",
    "correlate_learning_records",
    "generate_report",
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
    "publish_beacon",
]
