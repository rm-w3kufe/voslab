"""alert_triage.py — Algedonic Urgency Score (AUS) + triage.
design: docs/spec_revision/design-sources/algedonic-triage-v1/algedonic_triage.vsm

Scores unacked algedonic alerts by urgency and triages them into
NOW / DEFER / ACCUMULATE so the kernel (and S5) decide WHEN to fix:
fundamental for the main task vs postponable vs batchable by origin.

Integration route: registered via the algedonic consumer —
.opencode/plugins/operational/tool_integration_bridge.py
`_alert_consume_stage` imports + calls `triage()` on session.created
(read-only report; auto-remediation is a slow-path follow-up on idle).

Deterministic (R10): pure functions of (alert, context) — no randomness,
no wall-clock reads inside scoring (caller passes `now`).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

# ── impact class → type_w (S5-ratified 2026-10-14) ──────────────────────────
IMPACT_W = {
    "BLOCKING": 1.0,       # frena la tarea principal / espera decisión S5
    "HEALTH": 0.6,         # salud del sistema, gate rojo
    "OPERACIONAL": 0.4,    # componente fallando, degrada pero no frena
    "NOISE": 0.2,          # rendimiento, test-leak
}
DEFAULT_IMPACT = "OPERACIONAL"  # tipo nuevo no declarado

# alert_type → impact class (default propuesto, S5 2026-10-14)
TYPE_IMPACT = {
    "handoff_needs_nod": "BLOCKING",
    "learning_investment_pending": "BLOCKING",
    "gates_weekly_fail": "HEALTH",
    "attestation_fail": "HEALTH",
    "health_degradation": "HEALTH",
    # monitoring runners fail-loud (T4/T7, S5 ok rmw3 2026-10-21):
    # fails diarios/de drill de la flota de timers vsf = salud del sistema
    "gates_daily_fail": "HEALTH",
    "docs_reconcile_fail": "HEALTH",
    "restore_drill_fail": "HEALTH",
    # Delta A (hardening-gaps-2026-10, R16 post-detector): external-job pain
    "external_job_stall": "HEALTH",
    "no_progress": "HEALTH",
    "resource_waste": "HEALTH",
    "reality_score_shock": "HEALTH",
    # Shadow S2 (shadow-inventory-2026-10, R16 post-detector): covered ≠ actuado
    "error_burst": "HEALTH",
    "pattern_runner_fail": "OPERACIONAL",
    "bridge_call_failed": "OPERACIONAL",
    "relocate_unparsed": "OPERACIONAL",
    "failure_burst": "OPERACIONAL",
    "latency_spike": "NOISE",
}

LEVEL_W = {"critical": 1.0, "error": 0.7, "warning": 0.3, "warn": 0.3, "info": 0.1}
DEFAULT_LEVEL_W = 0.3

AGE_WINDOW_H = 48.0   # matches the algedonic-queue-consumed 48h check window
BURST_REF = 10.0      # same-type unacked count that saturates burst_w
DEFER_THRESHOLD = 0.4

# Dynamic NOW cutoff (S5 2026-10-14, hybrid): threshold = max(absolute floor,
# p90 of the current cohort). The floor keeps absolute semantics across
# sessions (a fresh critical is never called calm); the percentile adapts to
# the live score distribution so a uniformly-mid cohort still surfaces its
# worst (fixes "0 NOW at a fixed 0.75"). Deterministic (R10): sort-based
# nearest-rank percentile, no randomness, no wall-clock.
NOW_FLOOR = 0.62         # absolute floor — below this is never NOW
NOW_PERCENTILE = 0.90    # surface the top decile of the cohort
PERCENTILE_MIN = 5       # cohort guard: <5 alerts → floor only (no self-p90)

# NOW action (S5 2026-10-14): auto-fix ONLY if non-destructive (R17).
# These types are re-verified + acked-if-resolved (stale-alert cleanup).
REVERIFY_TYPES = {"gates_weekly_fail", "bridge_call_failed"}
# These types' "fix" IS an S5 decision — surface, never auto-fix.
NEEDS_S5_TYPES = {"handoff_needs_nod", "learning_investment_pending"}


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def level_w(level: str) -> float:
    return LEVEL_W.get(str(level).lower(), DEFAULT_LEVEL_W)


def classify_impact(alert_type: str) -> str:
    return TYPE_IMPACT.get(str(alert_type), DEFAULT_IMPACT)


def age_w(ts, now: datetime) -> float:
    t = _parse_ts(ts)
    if t is None:
        return 0.0
    age_h = max(0.0, (now - t).total_seconds() / 3600.0)
    return min(age_h / AGE_WINDOW_H, 1.0)


def burst_w(count: int) -> float:
    return min(max(0, count) / BURST_REF, 1.0)


def origin_key(alert: dict) -> tuple:
    """Group key for ACCUMULATE: same source + same type = same origin."""
    return (str(alert.get("source", "?")), str(alert.get("alert_type", "?")))


def _norm(s: str) -> set:
    """Normalize to a set of tokens: lowercase, non-alnum → space, split.
    'pattern-runner(S3)' → {'pattern', 'runner', 's3'}."""
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(s))
    return set(cleaned.split())


def matches_focus(source: str, active_focus: Iterable[dict]) -> bool:
    """True if the alert's origin matches a component the ACTIVE task touches.
    Deterministic (R10): normalized token-substring match of `source` against
    each active focus entry's ref + note."""
    src_tokens = _norm(source)
    if not src_tokens:
        return False
    for entry in active_focus or []:
        haystack = _norm(entry.get("ref", "")) | _norm(entry.get("note", ""))
        # a source token of length>=4 appearing in the focus text = a match
        if any(tok in haystack for tok in src_tokens if len(tok) >= 4):
            return True
    return False


def type_w(alert_type: str, source: str, active_focus: Iterable[dict]) -> float:
    """Impact weight WITH focus elevation (S5 2026-10-14): origin that matches
    the active task is elevated to BLOCKING (1.0)."""
    if matches_focus(source, active_focus):
        return IMPACT_W["BLOCKING"]
    return IMPACT_W[classify_impact(alert_type)]


def aus_score(alert: dict, active_focus: Iterable[dict],
              same_type_unacked: int, now: datetime) -> float:
    """AUS in 0..1 = (level_w + type_w + age_w + burst_w) / 4. Deterministic."""
    lw = level_w(alert.get("level"))
    tw = type_w(alert.get("alert_type"), alert.get("source", ""), active_focus)
    aw = age_w(alert.get("ts"), now)
    bw = burst_w(same_type_unacked)
    return (lw + tw + aw + bw) / 4.0


def now_threshold(scores: List[float]) -> float:
    """Dynamic NOW cutoff = max(absolute floor, nearest-rank p90 of cohort).
    Cohort guard: <PERCENTILE_MIN scores → floor only (a lone alert must not
    become its own p90 → false urgency). Deterministic (R10): sort-based."""
    if len(scores) < PERCENTILE_MIN:
        return float(NOW_FLOOR)
    ordered = sorted(scores)
    idx = min(len(ordered) - 1, int(round(NOW_PERCENTILE * (len(ordered) - 1))))
    return max(float(NOW_FLOOR), ordered[idx])


def triage_class(score: float, now_cutoff: float = NOW_FLOOR) -> str:
    if score >= now_cutoff:
        return "NOW"
    if score >= DEFER_THRESHOLD:
        return "DEFER"
    return "ACCUMULATE"


def triage(alerts: List[dict], active_focus: Iterable[dict],
           now: Optional[datetime] = None) -> dict:
    """Score + triage a list of UNACKED alerts. Returns:
      {now: [...], defer: [...], accumulate: {origin: {group_score, alerts}},
       cutoff: dynamic NOW threshold applied, counts: {...}}
    Each alert gets `_aus` + `_triage` annotations. ACCUMULATE groups by
    origin_key; the group's triage is driven by max(AUS) in the group."""
    now = now or datetime.now(timezone.utc)
    unacked = [a for a in alerts if not a.get("acknowledged")]
    # burst denominator = same-type unacked count
    type_counts: dict = {}
    for a in unacked:
        type_counts[a.get("alert_type", "?")] = type_counts.get(a.get("alert_type", "?"), 0) + 1

    # pass 1: score everything
    raw = []
    for a in unacked:
        s = aus_score(a, active_focus, type_counts.get(a.get("alert_type", "?"), 1), now)
        raw.append((a, s))
    # pass 2: dynamic cutoff from the cohort, then classify
    cutoff = now_threshold([s for _, s in raw])
    scored = []
    for a, s in raw:
        a = dict(a)
        a["_aus"] = round(s, 4)
        a["_triage"] = triage_class(s, cutoff)
        a["_impact"] = ("BLOCKING" if type_w(a.get("alert_type"), a.get("source", ""), active_focus) == IMPACT_W["BLOCKING"]
                        else classify_impact(a.get("alert_type")))
        scored.append(a)

    now_list = [a for a in scored if a["_triage"] == "NOW"]
    defer_list = [a for a in scored if a["_triage"] == "DEFER"]
    acc_raw = [a for a in scored if a["_triage"] == "ACCUMULATE"]

    accumulate: dict = {}
    for a in acc_raw:
        k = origin_key(a)
        g = accumulate.setdefault(k, {"group_score": 0.0, "alerts": []})
        g["alerts"].append(a)
        g["group_score"] = max(g["group_score"], a["_aus"])
    # group triage = class of max AUS (against the same dynamic cutoff)
    for k, g in accumulate.items():
        g["_triage"] = triage_class(g["group_score"], cutoff)

    return {
        "now": sorted(now_list, key=lambda a: -a["_aus"]),
        "defer": sorted(defer_list, key=lambda a: -a["_aus"]),
        "accumulate": {f"{k[0]}|{k[1]}": v for k, v in sorted(accumulate.items())},
        "cutoff": round(cutoff, 4),
        "counts": {
            "unacked": len(unacked),
            "now": len(now_list),
            "defer": len(defer_list),
            "accumulate_groups": len(accumulate),
            "accumulate_alerts": len(acc_raw),
        },
    }


def auto_remediate(alert: dict) -> dict:
    """Attempt a NON-DESTRUCTIVE fix for a NOW alert (S5 2026-10-14, R17).
    Whitelist only — destructive or unknown types are NOT auto-fixed.
    Returns {attempted, destructive, result} where result ∈
    {"reverify", "needs_s5", "no_autorem"}."""
    at = str(alert.get("alert_type"))
    if at in NEEDS_S5_TYPES:
        # the fix IS an S5 decision — surface, never auto-fix
        return {"attempted": False, "destructive": False, "result": "needs_s5"}
    if at in REVERIFY_TYPES:
        # non-destructive: re-verify the condition; caller re-runs + acks if resolved
        return {"attempted": True, "destructive": False, "result": "reverify"}
    # everything else: no known non-destructive remediation → defer
    return {"attempted": False, "destructive": False, "result": "no_autorem"}


# ── retryable bridge commands (slow-path; R17 safety) ───────────────────────
# bridge_call_failed detail embeds the failed command, but we NEVER re-run an
# arbitrary shell line parsed out of an alert (injection risk). Only these
# READ-ONLY bridge commands may be retried; the retry re-invokes the bridge
# with the command NAME (not the raw shell line).
SAFE_RETRY_COMMANDS = frozenset({
    "log-distill", "session-report", "rsi-status",
    "socratic-canon", "alert-consume",
})


def parse_failed_command(detail: str) -> Optional[str]:
    """Extract the bridge command name from a bridge_call_failed detail.
    detail format: 'callBridge(<cmd>) error: Command failed: python3 ... <cmd>'
    Deterministic (R10): regex on the callBridge(...) prefix only."""
    import re
    m = re.match(r"callBridge\(([^)\s]+)\)", str(detail or ""))
    return m.group(1) if m else None


def retry_command_for(alert: dict) -> Optional[str]:
    """Safe command name to retry for a bridge_call_failed alert, or None.
    Whitelist check — never returns an unlisted/arbitrary command."""
    if str(alert.get("alert_type")) != "bridge_call_failed":
        return None
    cmd = parse_failed_command(alert.get("detail", ""))
    return cmd if cmd in SAFE_RETRY_COMMANDS else None


def is_throttled(marker: Path, hours: float,
                 now: Optional[datetime] = None) -> bool:
    """True if `marker` was written less than `hours` ago (reverify throttle).
    Deterministic given `now`; wall-clock only at the call site."""
    if not marker.exists():
        return False
    try:
        last = _parse_ts(marker.read_text(encoding="utf-8").strip())
        if last is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - last).total_seconds() < hours * 3600.0
    except OSError:
        return False


def load_active_focus(root: Path) -> List[dict]:
    """Read current_focus.json entries with status == 'active' (read-only)."""
    p = root / "current_focus.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [e for e in data if e.get("status") == "active"]
    except (json.JSONDecodeError, OSError):
        return []


def triage_repo(root: Path, alerts_path: Optional[Path] = None,
                now: Optional[datetime] = None) -> dict:
    """Convenience: load repo alerts + active focus, then triage (read-only)."""
    alerts_path = alerts_path or (root / "state" / "rsi" / "alerts.jsonl")
    alerts = []
    if alerts_path.exists():
        for line in alerts_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    alerts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    focus = load_active_focus(root)
    return triage(alerts, focus, now=now)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AUS triage of algedonic alerts")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true", help="emit full JSON")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    result = triage_repo(root)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        c = result["counts"]
        print(f"unacked={c['unacked']} NOW={c['now']} DEFER={c['defer']} "
              f"ACCUMULATE={c['accumulate_alerts']} in {c['accumulate_groups']} origins "
              f"(cutoff={result['cutoff']})")
        for a in result["now"][:10]:
            print(f"  NOW  AUS={a['_aus']:.3f} [{a['_impact']}] {a.get('alert_type')} "
                  f"({a.get('source')}) ts={str(a.get('ts'))[:16]}")
