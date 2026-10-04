#!/usr/bin/env python3
"""system_topology_view — view-module #2: the system's declared self-model + recent algedonic activity.

Reads `state.db` (RO bind-mount) for the Sn-function topology (lxcs / components / coupling_registry) and
the chain-verified `events.jsonl` tail for recent algedonic/drift activity. This is what SCADA covered —
re-materialized as a clean declared module on the same host, proving the modularity law (the view-host
takes N modules). The state.db is the canonical model (R9, model≡reality kept by the S3* reconcile); a
LIVE state.db attestation to verify is PROD-A1a. Authoring WSL; runs on the view-host LXC (109).
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cybernetic_rag_view as crv  # reuse _read_events_tail / _chain_ok / _now_iso  # noqa: E402

SCHEMA = "system-topology-view/0.1"
MODULE_ID = "system-topology"
SYSTEM_ID = "alpha"
STATE_DB = os.environ.get("STATE_DB", "/mnt/state/state.db")
EVENTS_PATH = os.environ.get("EVENTS_PATH", "/mnt/telemetry/events.jsonl")
ALGEDONIC_TYPES = ("algedonic_emit", "drift_alert", "signal_escalated", "signal_deferred")


def _read_state():
    """The declared self-model from state.db (read-only)."""
    out = {"lxcs": [], "components": [], "couplings": []}
    try:
        # immutable=1: robust cross-mount RO (the SCADA pattern) — avoids WAL/-shm mapping issues across
        # containers. Reads the checkpointed main db (eventually-consistent; fine for a topology view).
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro&immutable=1", uri=True)
        out["lxcs"] = [{"id": i, "role": r, "ip": ip}
                       for i, r, ip in con.execute("SELECT id, role, ip FROM lxcs ORDER BY id")]
        out["components"] = [{"name": n, "lxc": d}
                             for n, d in con.execute(
                                 "SELECT name, deploy_target_lxc FROM components ORDER BY deploy_target_lxc, name")]
        out["couplings"] = [{"resource": res, "kind": k, "status": s}
                            for res, k, s in con.execute(
                                "SELECT resource, kind, status FROM coupling_registry ORDER BY kind, resource")]
        con.close()
    except Exception as e:
        out["error"] = str(e)
    return out


def _activity():
    """Recent algedonic/drift activity from the chain-verified events.jsonl tail."""
    events = crv._read_events_tail(EVENTS_PATH, 5000)
    chain_ok = crv._chain_ok(events)
    counts, last = {}, None
    for e in events:
        et = e.get("event_type", "")
        if et in ALGEDONIC_TYPES:
            counts[et] = counts.get(et, 0) + 1
            last = e.get("ts", last)
    return {"counts": counts, "last_signal_ts": last, "window_events": len(events)}, chain_ok


def build_tick():
    state = _read_state()
    act, chain_ok = _activity()
    view = {
        "lxcs": state["lxcs"],
        "components": state["components"],
        "couplings": state["couplings"],
        "activity": act,
        "summary": {
            "lxcs": len(state["lxcs"]),
            "services": len(state["components"]),
            "couplings": len(state["couplings"]),
            "couplings_active": sum(1 for c in state["couplings"] if c["status"] == "active"),
        },
    }
    if "error" in state:
        view["error"] = state["error"]
    return {
        "schema": SCHEMA, "ts": crv._now_iso(), "system_id": SYSTEM_ID, "module_id": MODULE_ID,
        "source": "state.db + events.jsonl",
        "view": view,
        "source_ref": {"state_db": STATE_DB, "events": EVENTS_PATH},
        "certified": bool(chain_ok),
        "cert_basis": "events.jsonl merkle-chain (activity); state.db = canonical model (live-attest = PROD-A1a)",
        "cert_findings": [] if chain_ok else ["CHAIN_BREAK"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_tick(), indent=2))
