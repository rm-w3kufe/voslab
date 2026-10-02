"""EP-5 — round protocol runner (PRC): R0–R7 as a registered backbone step.

One round = route the whole claim store through the claim-gate (step R1 via
``router.route_all``), audit guards, then emit metrics M1–M8 and close with a
GREEN / NOT_GREEN verdict (plan ``epistemic_certification_plan.vsm`` §9/EP-5):

  M1 learn_events in window            >= 1      (baseline 0)
  M2 new tree traces >= new decisions  and  > 0   (baseline 0)
  M3 % claims with route + status      == 1.0    (baseline ~0)
  M4 guard coverage (fix -> guard)     == 1.0    (baseline: only F16)
  M5 manual digest rituals in window   == 0      (baseline 8+)
  M6 silent errors (errors w/o consumer in window) == 0 (baseline 99/day)
  M7 UNDECLARED external writes        == 0      (baseline 756 blind skips)
  M8 substrate nouns in CORE           == 0      (§7 noun list; the exact
        nouns live only in _NOUNS below, literal-split so this file cannot
        match itself — prose here refers to §7 instead of spelling them out)

Closure rule (plan): no green round without M1>0 and M2>0 (and M6=0 when
there were alerts). Negative control (plan EP-5): a round without learn
(M1=0) must NOT close green — pass ``--simulate-no-learn`` to witness it.

M8 CORE scope (§7 "ontología, árboles, protocolo de ronda, schemas"):
the round-protocol implementation (this file, router, epistemic), the
decision trees, and the JSON schemas. Broader artifact lists belong to the
EP-6 ``substrate-agnostic.valid`` gate. The noun list is written with
literal concatenation (``"note" "book"``) so this file — which is itself
CORE — cannot match its own scanner (R10: same input, same output).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]  # vos_kernel/ -> <vOSlab>

#: §7 substrate nouns — literal-split so the scanner cannot self-match.
_NOUNS: tuple[str, ...] = (
    "note" "book", "jup" "yter", "n" "02", "l" "xc", "prox" "mox",
    "/" "tmp", "/" "root", "m" "d5",
)

#: CORE artifact set for M8 (§7 scope; EP-6 gate widens this later).
#: NB: workspaces.json is NOT scanned — it is a data registry whose content
#: IS workspace paths (an input, not an ontology/schema artifact); the EP-6
#: ``substrate-agnostic.valid`` gate owns the final CORE artifact list.
CORE_PATTERNS: tuple[str, ...] = (
    ".opencode/plugins/support/trees/*.vsm",
    "packages/framework/vos_kernel/round_runner.py",
    "packages/framework/vos_kernel/router.py",
    "packages/framework/vos_kernel/epistemic.py",
    "state/epistemic/*.json",
    "state/autonomy_classes.json",
)

MANUAL_RITUAL_RE = re.compile(r"\bmd5(sum)?\b")


# ---------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: object) -> datetime | None:
    """Parse ISO-8601 (Z or offset) to aware UTC datetime; None if bogus."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _in_window(value: object, start: datetime) -> bool:
    dt = _ts(value)
    return dt is not None and dt >= start


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_event(event: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


# ------------------------------------------------------------ collectors


def collect_log_metrics(start: datetime, log_path: Path) -> dict:
    """M1, M5, M6, M7 inputs from the canonical agent log."""
    learn = errors = consumers = md5_rituals = undeclared = declared = 0
    for rec in _read_jsonl(log_path) if log_path.exists() else []:
        if not _in_window(rec.get("ts"), start):
            continue
        et = rec.get("event_type", "")
        if et == "learn":
            learn += 1
        if et in ("learn", "evaluate.l3_audit"):
            consumers += 1
        if rec.get("level") == "error":
            errors += 1
        action = str(rec.get("action", ""))
        if rec.get("source") == "tool-integration" and MANUAL_RITUAL_RE.search(action):
            md5_rituals += 1
        blob = action + " " + str(rec.get("detail", ""))
        if "UNDECLARED external write" in blob:
            undeclared += 1
        if "declared workspace" in blob:
            declared += 1
    # silent = emitted errors with no consumer (learn/audit) in the window
    silent = errors if (errors > 0 and consumers == 0) else 0
    return {
        "M1": learn,
        "errors": errors,
        "consumers": consumers,
        "M5": md5_rituals,
        "M6": silent,
        "M7": undeclared,
        "M7_declared": declared,
    }


def collect_window_events(start: datetime, workspace: Path) -> dict:
    """M2 inputs: new traces vs new persisted decisions in the window."""
    traces = _read_jsonl(workspace / "state" / "rsi" / "tree_traces.jsonl")
    decisions = _read_jsonl(workspace / "state" / "epistemic" / "decisions.jsonl")
    return {
        "M2_traces": sum(1 for t in traces if _in_window(t.get("ts"), start)),
        "M2_decisions": sum(1 for d in decisions if _in_window(d.get("ts"), start)),
    }


def scan_substrate(workspace: Path) -> list[dict]:
    """M8: forbidden substrate nouns in CORE artifacts (§7)."""
    hits: list[dict] = []
    files: list[Path] = []
    for pattern in CORE_PATTERNS:
        files.extend(p for p in workspace.glob(pattern) if p.is_file())
    for path in sorted(set(files)):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(workspace))
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for noun in _NOUNS:
                if noun.startswith("/"):
                    found = noun in low
                else:
                    found = re.search(r"\b" + re.escape(noun) + r"\b", low) is not None
                if found:
                    hits.append(
                        {"file": rel, "line": lineno, "noun": noun,
                         "text": line.strip()[:100]}
                    )
    return hits


def collect_claims_metrics(store, routed: int) -> dict:
    """M3: claims with a route this round and a non-empty status."""
    claims = store.load("claims")
    total = len(claims)
    with_status = sum(1 for c in claims if str(c.get("status", "")).strip())
    coverage = 1.0 if total == 0 else min(routed, with_status) / total
    return {"M3": round(coverage, 4), "claims_total": total,
            "claims_with_status": with_status, "routed": routed}


def guards_metrics(audit: dict) -> dict:
    """M4: guard coverage for fixed findings (+ liveness when run)."""
    live = audit.get("liveness") or {}
    dead = sorted(g for g, v in live.items() if v != "live")
    ok = audit.get("coverage") == 1.0 and not dead
    return {"M4": audit.get("coverage", 0.0), "liveness_run": bool(live),
            "guards_dead": dead, "guards_ok": ok,
            "guard_errors": audit.get("errors", [])}


# --------------------------------------------------------------- verdict


def build_metrics(logm: dict, win: dict, clm: dict, grd: dict,
                  substrate_hits: list[dict], simulate_no_learn: bool) -> dict:
    m1 = 0 if simulate_no_learn else logm["M1"]
    m2_ok = win["M2_traces"] > 0 and win["M2_traces"] >= win["M2_decisions"]
    metrics = {
        "M1": {"value": m1, "target": ">=1", "ok": m1 >= 1},
        "M2": {"value": win["M2_traces"], "target": ">0 and >=decisions",
               "ok": m2_ok, "decisions": win["M2_decisions"]},
        "M3": {"value": clm["M3"], "target": "==1.0", "ok": clm["M3"] >= 1.0,
               "claims_total": clm["claims_total"],
               "routed": clm["routed"]},
        "M4": {"value": grd["M4"], "target": "==1.0", "ok": grd["guards_ok"],
               "liveness_run": grd["liveness_run"],
               "dead": grd["guards_dead"]},
        "M5": {"value": logm["M5"], "target": "==0", "ok": logm["M5"] == 0},
        "M6": {"value": logm["M6"], "target": "==0", "ok": logm["M6"] == 0,
               "errors": logm["errors"], "consumers": logm["consumers"]},
        "M7": {"value": logm["M7"], "target": "==0", "ok": logm["M7"] == 0,
               "declared": logm["M7_declared"]},
        "M8": {"value": len(substrate_hits), "target": "==0",
               "ok": not substrate_hits, "hits": substrate_hits[:10]},
    }
    return metrics


def verdict(metrics: dict) -> tuple[str, list[str]]:
    reasons = [f"{k}: value={v['value']!r} fails target {v['target']}"
               for k, v in metrics.items() if not v["ok"]]
    # plan closure rule: no green without M1>0 and M2>0
    if metrics["M1"]["value"] <= 0 and "M1" not in "".join(reasons):
        reasons.append("M1: no learn events in round")
    if metrics["M2"]["value"] <= 0 and "M2" not in "".join(reasons):
        reasons.append("M2: no traces in round")
    return ("GREEN", []) if not reasons else ("NOT_GREEN", reasons)


# ------------------------------------------------------------------ emit


def _round_id(now: datetime) -> str:
    return "ROUND-" + now.strftime("%Y%m%dT%H%M%S%fZ")


def emit(record: dict, workspace: Path, log_path: Path | None = None) -> None:
    rounds_dir = workspace / "state" / "epistemic" / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)
    # D-06 FASE C3: write a sealed COPY chained to the previous sealed
    # round (additive prev_hash/record_hash keys; the caller's record
    # and the closure event below stay unsealed and unmutated).
    from vos_kernel.hash_chain import last_sealed_hash, seal
    sealed = seal(record, last_sealed_hash(rounds_dir))
    out = rounds_dir / f"{record['round_id']}.json"
    out.write_text(json.dumps(sealed, indent=1, ensure_ascii=False) + "\n")
    green = record["verdict"] == "GREEN"
    event = {
        "ts": record["closed_at"],
        "pid": os.getpid(),
        "level": "info" if green else "warn",
        "source": "round-runner",
        "event_type": "round.closure",
        "event_id": f"round-runner:round.closure:{record['round_id']}",
        "action": (f"round {record['round_id']} verdict={record['verdict']} "
                   + " ".join(f"{k}={v['value']}"
                              for k, v in record["metrics"].items())),
        "result": "green" if green else "not_green",
        "detail": {"round_id": record["round_id"],
                   "reasons": record["reasons"],
                   "metrics": {k: v["value"] for k, v in record["metrics"].items()},
                   "artifact": str(out.relative_to(workspace))},
    }
    _append_event(event, log_path or workspace / "logs" / "agent_plugin.jsonl")


# ------------------------------------------------------------- the round


def run_round(window_hours: float = 24.0, *, simulate_no_learn: bool = False,
              run_guards: bool = True, emit_round: bool = True,
              workspace: Path | None = None,
              route_fn=None, guards_fn=None) -> dict:
    """Execute one protocol round: R1 route -> guards -> M1-M8 -> closure."""
    from vos_kernel.epistemic import EpicStore, audit_guards
    from vos_kernel.router import route_all

    ws = workspace or WORKSPACE
    start = _now() - timedelta(hours=window_hours)
    store = EpicStore(root=ws)

    route_fn = route_fn or (lambda: route_all(store=store))
    # fixtures may hand in ready-made dicts; callables are the live path
    step_route = route_fn() if callable(route_fn) else dict(route_fn)
    if guards_fn is None:
        step_guards = audit_guards(store, run=run_guards)
    else:
        step_guards = guards_fn() if callable(guards_fn) else dict(guards_fn)

    logm = collect_log_metrics(start, ws / "logs" / "agent_plugin.jsonl")
    win = collect_window_events(start, ws)
    clm = collect_claims_metrics(store, routed=int(step_route.get("routed", 0)))
    grd = guards_metrics(step_guards)
    hits = scan_substrate(ws)
    metrics = build_metrics(logm, win, clm, grd, hits, simulate_no_learn)
    verdict_str, reasons = verdict(metrics)

    now = _now()
    record = {
        "round_id": _round_id(now),
        "window_hours": window_hours,
        "started_at": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "closed_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "steps": {
            "R1_route": {"routed": step_route.get("routed"),
                         "routes": step_route.get("routes"),
                         "route_failed": step_route.get("failed", [])},
            "guards": {"coverage": step_guards.get("coverage"),
                       "run": bool(step_guards.get("liveness")),
                       "errors": step_guards.get("errors", [])},
        },
        "metrics": metrics,
        "verdict": verdict_str,
        "reasons": reasons,
        "simulated_no_learn": simulate_no_learn,
    }
    if emit_round:
        emit(record, ws)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="round_runner",
        description="EP-5: run one epistemic round (R0-R7 + metrics M1-M8)")
    ap.add_argument("--window-hours", type=float, default=24.0)
    ap.add_argument("--simulate-no-learn", action="store_true",
                    help="negative control: force M1=0 (must NOT be green)")
    ap.add_argument("--skip-guards", action="store_true",
                    help="coverage only (skip live guard execution)")
    ap.add_argument("--no-emit", action="store_true",
                    help="do not persist round record / log event")
    args = ap.parse_args(argv)
    try:
        record = run_round(
            window_hours=args.window_hours,
            simulate_no_learn=args.simulate_no_learn,
            run_guards=not args.skip_guards,
            emit_round=not args.no_emit,
        )
    except Exception as exc:  # fail loud: rc2 + detail
        print(f"round_runner ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "round_id": record["round_id"],
        "verdict": record["verdict"],
        "reasons": record["reasons"],
        "metrics": {k: v["value"] for k, v in record["metrics"].items()},
    }, indent=1))
    return 0 if record["verdict"] == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
