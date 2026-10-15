#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/learn-budget-v1/learn_budget_design.vsm
"""learn_budget — P-B envelope O2: learning investment budget with S5 envelope.

RATIFIED by S5 2026-10-15 (q1-q5, autonomy_ceiling_proposals.vsm
@ratificacion_P_B): cap 2/week, domains thresholds+scenario_memory,
cost unit = L3 samples, Omega gates at 0.7/0.1/0.8, baseline = the
standing pending signals ingested once.

Delegation, not self-concession (R10.1): the envelope is S5 signing a
perimeter ONCE; anything outside it stays a normal S5 queue item
(unacked alert), anything that corrupts the envelope itself refuses
to auto-approve (fail-CLOSED — the inverse of L3's fail-open cycle
budget, because this is a privilege, not a loop).

Precedents: rsi_cycle._l3_budget_ok (persistent counter + window),
vsm_viability.OMEGA (same frontiers), alert_triage NEEDS_S5_TYPES
(surface outside, unchanged).

Deterministic (R10): decide() takes now + injectable omega/ledger —
same inputs, same decision. No randomness, no reads of wall-clock
inside the scoring path.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VOSLAB = Path(__file__).resolve().parents[2]
STATE_RSI = Path(os.environ.get("RSI_STATE_DIR", VOSLAB / "state" / "rsi"))

ENVELOPE_PATH = Path(os.environ.get(
    "LEARN_BUDGET_FILE", STATE_RSI / "learn_budget.json"))
LEDGER_PATH = Path(os.environ.get(
    "LEARN_LEDGER_FILE", STATE_RSI / "learn_ledger.jsonl"))
THRESHOLDS_PATH = Path(os.environ.get(
    "LEARN_THRESHOLDS_FILE", STATE_RSI / "learn_thresholds.json"))
CONSOLIDATIONS_PATH = Path(os.environ.get(
    "LEARN_CONSOLIDATIONS_FILE", STATE_RSI / "learn_consolidations.jsonl"))

ALERT_TYPE = "learning_investment_pending"

# Ratified bounds (q2/q1): executor writes stay inside these.
THRESHOLD_BOUNDS = {"min_n": (2, 6), "window_days": (14, 60)}
DEFAULT_THRESHOLDS = {"min_n": 3, "window_days": 30}

# Cost unit = L3 samples (q4). What an approved investment spends:
COST = {"thresholds": 0, "scenario_memory": 1}


class EnvelopeError(RuntimeError):
    """Envelope missing/corrupt/sha-mismatched — never auto-approve."""


# ── C1: envelope sha ────────────────────────────────────────────────────────

def canonical_params(params: dict) -> str:
    """Canonical form of the ratified parameters (everything but the sha)."""
    body = {k: v for k, v in params.items() if k != "sha"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def envelope_sha(params: dict) -> str:
    return hashlib.sha256(canonical_params(params).encode("utf-8")).hexdigest()


def init_envelope(params: dict, path: Optional[Path] = None,
                  force: bool = False) -> dict:
    """Write the envelope (C1). Refuses to overwrite a live envelope:
    changing ratified parameters is an S5 ceremony, not a file edit."""
    path = path or ENVELOPE_PATH
    if path.exists() and not force:
        raise EnvelopeError(f"envelope exists ({path}); changing it "
                            "requires an S5 ceremony (force= explicitly)")
    doc = dict(params)
    doc["sha"] = envelope_sha(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return doc


def load_envelope(path: Optional[Path] = None) -> dict:
    """Load + verify (C1). Any mismatch raises: callers must route to S5."""
    path = path or ENVELOPE_PATH
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise EnvelopeError(f"envelope missing: {path}") from e
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"envelope unreadable: {e}") from e
    if envelope_sha(doc) != doc.get("sha"):
        raise EnvelopeError("envelope sha mismatch — parameters were "
                            "modified outside the S5 ceremony")
    return doc


# ── C2: ledger (append-only) ────────────────────────────────────────────────

def ledger_append(entry: dict, path: Optional[Path] = None) -> None:
    path = path or LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ledger_events(path: Optional[Path] = None) -> List[dict]:
    path = path or LEDGER_PATH
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn tail never poisons the read
    return out


def _week_key(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def weekly_approved(ledger: List[dict], now: datetime) -> int:
    """C4/q1: approvals already spent in the current ISO week."""
    wk = _week_key(now)
    return sum(1 for e in ledger
               if e.get("event") == "approved" and e.get("week") == wk)


# ── C3: Omega governor ──────────────────────────────────────────────────────

def _live_cert_results() -> Optional[list]:
    """Accuracy dim source: autonomy drill (fast — ~0.6s live)."""
    try:
        p = subprocess.run(
            [sys.executable, str(VOSLAB / "scripts" / "vsl" / "tools"
                                 / "autonomy_cert.py"), "--json"],
            capture_output=True, text=True, timeout=60, cwd=str(VOSLAB))
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode not in (0, 1):
        return None
    try:
        out = json.loads(p.stdout.strip())
        return out if isinstance(out, list) else None
    except (json.JSONDecodeError, ValueError):
        return None


def omega_ok(*,
             cert_runner: Optional[Callable[[], Optional[list]]] = None,
             measure_fn: Optional[Callable[..., dict]] = None,
             mode_reader: Optional[Callable[[], str]] = None
             ) -> Tuple[bool, dict]:
    """C3/q5: OMEGA frontiers (accuracy>=0.7 ^ drift<=0.1 ^ stability>=0.8)
    + persisted mode == nominal. FAIL-CLOSED: unknown dims => not ok."""
    if cert_runner is None:
        cert_runner = _live_cert_results
    if measure_fn is None:
        from vsm_viability import measure as _m
        measure_fn = _m
    if mode_reader is None:
        from vsm_viability import read_mode as _rm
        mode_reader = _rm
    try:
        mode = mode_reader()
    except Exception:
        mode = "unknown"
    try:
        m = measure_fn(cert_results=cert_runner())
    except Exception as e:
        return False, {"reason": "measure_failed", "error": str(e),
                       "mode": mode}
    dims = m.get("dims", {})
    evidence = {"dims": dims, "mode": mode, "inside": m.get("inside")}
    if mode != "nominal":
        evidence["reason"] = "mode_not_nominal"
        return False, evidence
    if m.get("inside") is None:
        evidence["reason"] = "omega_unknown"  # accuracy unmeasured: fail closed
        return False, evidence
    if not m["inside"]:
        evidence["reason"] = "omega_breached"
        return False, evidence
    return True, evidence


# ── decide (pure, R10) ──────────────────────────────────────────────────────

def decide(*, envelope: dict, domain: str, cost: int, now: datetime,
           ledger: List[dict], omega_pass: bool,
           omega_evidence: dict) -> Tuple[str, str]:
    """The envelope gate. Returns (decision, reason) — approved only if
    every ratified constraint holds. Order: sha already verified by caller
    (envelope dict came from load_envelope), then Omega, domain, cost, cap.
    """
    if domain not in envelope.get("domains", []):
        return "rejected_domain", f"domain {domain!r} outside envelope"
    if not omega_pass:
        return "rejected_omega", f"Omega suspended envelope: " \
                                 f"{omega_evidence.get('reason', '?')}"
    if cost > int(envelope.get("max_cost_l3_samples", 0)):
        return "rejected_cost", f"cost {cost} > max " \
                                f"{envelope.get('max_cost_l3_samples')}"
    n = weekly_approved(ledger, now)
    if n >= int(envelope.get("cap_per_week", 0)):
        return "rejected_cap", f"weekly cap reached ({n}/" \
                               f"{envelope.get('cap_per_week')})"
    return "approved", "inside envelope"


# ── executors (bounded, deterministic) ──────────────────────────────────────

def _week_trigger_count(alerts: Iterable[dict], now: datetime) -> int:
    """Triggers emitted in the current ISO week (evidence source for the
    thresholds rule — counts SIGNAL, ack state irrelevant)."""
    wk = _week_key(now)
    n = 0
    for a in alerts:
        if a.get("alert_type") != ALERT_TYPE:
            continue
        ts = str(a.get("ts", ""))
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if _week_key(t) == wk:
            n += 1
    return n


def exec_thresholds(*, alerts: Iterable[dict], now: datetime,
                    path: Optional[Path] = None,
                    cap: int = 2) -> dict:
    """thresholds executor: hysteresis on min_n inside ratified bounds.
    up when noise (triggers > 2*cap), down toward default when calm
    (triggers <= cap) — L3-style band, no flap at the middle.
    """
    path = path or THRESHOLDS_PATH
    caps = int(cap)
    try:
        cur = json.loads(path.read_text())
        min_n = int(cur.get("min_n", DEFAULT_THRESHOLDS["min_n"]))
        window = int(cur.get("window_days",
                             DEFAULT_THRESHOLDS["window_days"]))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        min_n, window = DEFAULT_THRESHOLDS["min_n"], \
            DEFAULT_THRESHOLDS["window_days"]
    triggers = _week_trigger_count(alerts, now)
    lo, hi = THRESHOLD_BOUNDS["min_n"]
    decision = "hold"
    if triggers > 2 * caps and min_n < hi:
        min_n += 1
        decision = "raise_min_n"
    elif triggers <= caps and min_n > lo:
        min_n -= 1
        decision = "restore_min_n"
    out = {"min_n": min_n, "window_days": window,
           "updated_at": now.isoformat().replace("+00:00", "Z"),
           "evidence": {"triggers_this_week": triggers,
                        "decision": decision}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out


def exec_scenario_memory(*, alerts: Iterable[dict], now: datetime,
                         path: Optional[Path] = None) -> dict:
    """scenario_memory executor v1: ORDER consolidation (append-only).
    The structural merge itself is future L4 work — the order is the
    investment; the live scenario store lives outside vOSlab (no writes
    outside ~/vOSlab)."""
    path = path or CONSOLIDATIONS_PATH
    ids = [str(a.get("alert_id")) for a in alerts
           if a.get("alert_type") == ALERT_TYPE]
    entry = {"ts": now.isoformat().replace("+00:00", "Z"),
             "status": "ordered", "signal_alerts": ids,
             "note": "consolidate novel patterns into scenario structure "
                     "(S4 trigger, envelope-approved)"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


EXECUTORS = {"thresholds": exec_thresholds,
             "scenario_memory": exec_scenario_memory}


# ── consume: the wiring entry point ─────────────────────────────────────────

def consume(*, alerts: List[dict], ack_many: Callable[[Iterable[str]], int],
            now: Optional[datetime] = None,
            envelope_path: Optional[Path] = None,
            ledger_path: Optional[Path] = None,
            omega_fn: Optional[Callable[[], Tuple[bool, dict]]] = None,
            domain: str = "scenario_memory",
            executor: Optional[Callable[..., dict]] = None
            ) -> dict:
    """One decision per standing signal (dedup), then route.

    approved  -> executor + ledger(approved) + ack the whole batch
    rejected  -> ledger(rejected_*) + alerts STAY unacked (normal S5 queue)
    no signal -> observe() only (no writes without an investment event)
    """
    now = now or datetime.now(timezone.utc)
    batch = [a for a in alerts
             if a.get("alert_type") == ALERT_TYPE and not a.get("acknowledged")]
    summary = {"signals": len(batch), "decision": None, "acked": 0,
               "reason": None}
    if not batch:
        return summary

    try:
        envelope = load_envelope(envelope_path)
    except EnvelopeError as e:
        summary.update(decision="rejected_sha", reason=str(e))
        return summary  # alerts stay unacked: envelope broken -> S5

    ledger = ledger_events(ledger_path)
    if omega_fn is None:
        omega_pass, omega_evidence = omega_ok()
    else:
        omega_pass, omega_evidence = omega_fn()
    cost = COST.get(domain, 999)
    decision, reason = decide(envelope=envelope, domain=domain, cost=cost,
                              now=now, ledger=ledger, omega_pass=omega_pass,
                              omega_evidence=omega_evidence)
    ids = [str(a.get("alert_id")) for a in batch]
    entry = {"ts": now.isoformat().replace("+00:00", "Z"),
             "week": _week_key(now), "event": decision, "domain": domain,
             "alert_ids": ids, "cost_samples_l3": cost,
             "envelope_sha": envelope.get("sha"), "reason": reason}
    if decision == "approved":
        ex = executor or EXECUTORS.get(domain)
        if ex is None:
            entry.update(event="rejected_domain",
                         reason=f"no executor for {domain!r}")
            ledger_append(entry, ledger_path)
            summary.update(decision="rejected_domain", reason=entry["reason"])
            return summary
        try:
            payload = ex(alerts=batch, now=now,
                         cap=int(envelope.get("cap_per_week", 2)))
        except TypeError:
            payload = ex(alerts=batch, now=now)  # executor w/o cap kwarg
        except Exception as e:
            # execution failed after approval: ledger the failure, leave
            # the signal unacked (S5 sees it — never ack what didn't run)
            entry.update(event="executor_failed", reason=str(e))
            ledger_append(entry, ledger_path)
            summary.update(decision="executor_failed", reason=str(e))
            return summary
        entry["execution"] = payload
        ledger_append(entry, ledger_path)
        summary["acked"] = ack_many(ids)
        summary.update(decision="approved", reason=reason)
        return summary

    ledger_append(entry, ledger_path)
    summary.update(decision=decision, reason=reason)
    return summary  # unacked = normal S5 queue (nothing silently conceded)


def baseline_ingest(*, alerts: List[dict],
                    ack_many: Callable[[Iterable[str]], int],
                    now: Optional[datetime] = None,
                    ledger_path: Optional[Path] = None) -> dict:
    """q3: the standing pending signals ratified ONCE as a baseline entry
    (idempotent — a ledger that already carries a baseline never re-runs)."""
    now = now or datetime.now(timezone.utc)
    ledger = ledger_events(ledger_path)
    if any(e.get("event") == "baseline" for e in ledger):
        return {"skipped": "baseline already recorded"}
    batch = [a for a in alerts
             if a.get("alert_type") == ALERT_TYPE and not a.get("acknowledged")]
    ids = [str(a.get("alert_id")) for a in batch]
    entry = {"ts": now.isoformat().replace("+00:00", "Z"),
             "week": _week_key(now), "event": "baseline",
             "domain": "scenario_memory", "alert_ids": ids,
             "cost_samples_l3": 0, "envelope_sha": None,
             "reason": "q3 S5: standing pending ratified as clean baseline"}
    ledger_append(entry, ledger_path)
    acked = ack_many(ids)
    return {"baseline_alerts": len(ids), "acked": acked}


# ── CLI (manual ops) ────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    from alerting import AlertMonitor
    monitor = AlertMonitor()
    if "--init" in argv:
        # Ratified params — S5 2026-10-15 (autonomy_ceiling_proposals.vsm
        # @ratificacion_P_B). First write only; later changes = ceremony.
        doc = init_envelope({
            "ratified_at": "2026-10-15T05:17:13Z",
            "ratification": "docs/plans/autonomy_ceiling_proposals.vsm"
                            "@ratificacion_P_B",
            "cap_per_week": 2,
            "domains": ["thresholds", "scenario_memory"],
            "max_cost_l3_samples": 2,
        })
        print(json.dumps(doc, indent=2))
        return 0
    if "--status" in argv:
        try:
            env = load_envelope()
        except EnvelopeError as e:
            print(f"envelope: BROKEN ({e})")
            return 1
        ledger = ledger_events()
        op, ev = omega_ok()
        print(json.dumps({"envelope_sha": env.get("sha"),
                          "week_approved": weekly_approved(
                              ledger, datetime.now(timezone.utc)),
                          "ledger_events": len(ledger),
                          "omega_ok": op, "omega": ev}, indent=2))
        return 0
    if "--baseline" in argv:
        alerts = monitor._read_alerts()
        r = baseline_ingest(alerts=alerts,
                            ack_many=monitor.acknowledge_many)
        print(json.dumps(r))
        return 0
    if "--consume" in argv:
        alerts = monitor._read_alerts()
        r = consume(alerts=alerts, ack_many=monitor.acknowledge_many)
        print(json.dumps(r))
        return 0
    print("usage: learn_budget.py --init|--status|--baseline|--consume")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
