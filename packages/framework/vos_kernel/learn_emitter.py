"""learn emitter (EP-3) — round-close R5 of plan EPISTEMIC-CERT-001.

The learning hooks already exist (bridge `learn-from-action` /
`run_learn_pipeline` on session.idle); what did not exist is the round-close
emitter that parses the epistemic ledgers and actually fires them (plan §4:
"the hooks EXISTED and nobody called them").

Round close (plan §6, step R5):
  1. parse the ledgers — live findings (guard_status=live) plus the plan's
     §9 retro-learning matrix (rows L*/E*, the retro ledger that carries
     byte-for-byte, workspace-ciego, ...)
  2. emit one learn event per source through the integration bridge
     (learn-from-action → scenario_memory.record + unified log
      event_type=learn)
  3. audit F→G (EP-1 audit_guards): a fixed finding without a resolvable
     guard makes the round close YELLOW — never a silent green
  4. report metric M1 (learn events emitted this round; plan baseline 0,
     round-close rule needs M1 > 0)

Everything here is deterministic (R10): fixed ledgers, fixed parse rules,
fixed emission order (findings first, retro rows second). The bridge is
imported, not shelled — record_pattern is record-only (milliseconds).

CLI:
  python3 -m vos_kernel.learn_emitter [--plan P] [--root D] [--dry-run]
  vsctl learn-round [--dry-run]        (wrapper scripts/vsl/vsctl)

Exit: 0 green (or dry-run), 1 yellow (guard audit failed or M1=0).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from importlib import util as importlib_util
from pathlib import Path

from vos_kernel.epistemic import EpicStore, audit_guards, repo_root, store_dir

BRIDGE_REL = Path(".opencode/plugins/operational/tool_integration_bridge.py")
PLAN_REL = Path("docs/plans/epistemic_certification_plan.vsm")
LOG_REL = Path("logs/agent_plugin.jsonl")

# §9 matrix of the plan: rows start right after the section marker with
# exactly three spaces then an id (L0..L6 / E1..E6); wrapped cell text
# continues on lines indented with seven spaces.
_SECTION_START = "// \u2550\u2550\u2550 9."
_SECTION_END = "// \u2550\u2550\u2550 10."
_ROW_RE = re.compile(r"^// {3}([LE]\d) (.+)$")
_CONT_RE = re.compile(r"^// {7}(\S.*)$")


def _now_iso() -> str:
    """UTC timestamp with milliseconds (log/round bookkeeping, not a doc)."""
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- sources

def load_live_findings(store: EpicStore) -> list[dict]:
    """Ledger findings with guard_status=live, ledger order preserved."""
    return [f for f in store.load("findings")
            if f.get("guard_status") == "live"]


def load_retro_learnings(plan_path: Path) -> list[dict]:
    """Parse the plan §9 matrix rows (L*/E*) — the retro learning ledger.

    Fails loud (ValueError) if the section or its rows are missing: a
    silent empty source would masquerade as a healthy round (R9).
    """
    path = Path(plan_path)
    if not path.exists():
        raise ValueError(f"plan not found: {path}")
    rows: list[dict] = []
    cur: dict | None = None
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not in_section:
            if line.startswith(_SECTION_START):
                in_section = True
            continue
        if line.startswith(_SECTION_END):
            break
        m = _ROW_RE.match(line)
        if m:
            cur = {"id": m.group(1), "text": m.group(2).strip()}
            rows.append(cur)
            continue
        c = _CONT_RE.match(line)
        if c and cur is not None:
            cur["text"] += " " + c.group(1).strip()
    if not rows:
        raise ValueError(f"plan §9 matrix rows not found in {path}")
    return rows


def build_sources(store: EpicStore, plan_path: Path) -> list[tuple[str, str, str]]:
    """(tool, file, outcome) triples in deterministic emission order."""
    sources: list[tuple[str, str, str]] = []
    for f in load_live_findings(store):
        sources.append(("round-finding", str(f.get("id")),
                        f"guarded:{f.get('guard', '')}"))
    for row in load_retro_learnings(plan_path):
        sources.append(("retro-learning", row["id"], "retro-learned"))
    return sources


# ---------------------------------------------------------------- bridge

def load_bridge(root: Path):
    """Import the integration bridge module (importable: main is guarded)."""
    path = Path(root) / BRIDGE_REL
    if not path.exists():
        raise ValueError(f"bridge not found: {path}")
    spec = importlib_util.spec_from_file_location("tool_integration_bridge", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load bridge: {path}")
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bridge_emit(mod):
    """learn-from-action adapter: one learn event, fail loud on no-confirm."""
    def _emit(tool: str, file: str, outcome: str) -> dict:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_learn_from_action([tool, file, outcome])
        out = buf.getvalue().strip()
        try:
            payload = json.loads(out) if out else {}
        except ValueError:
            payload = {}
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        if payload.get("ok") is not True:
            raise RuntimeError(f"bridge did not confirm: {out[:120]}")
        return payload
    return _emit


def count_learn_events(log_path: Path, since) -> int:
    """Unified-log learn events at or after `since` (datetime)."""
    path = Path(log_path)
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("event_type") != "learn":
            continue
        ts = _parse_ts(rec.get("ts", ""))
        if ts is not None and since is not None and ts >= since:
            n += 1
    return n


# ---------------------------------------------------------------- round close

def round_close(root: Path | None = None,
                plan_path: Path | None = None,
                dry_run: bool = False,
                emit_fn=None,
                summary_fn=None) -> dict:
    """Run R5: emit learn events, audit guards, report status.

    emit_fn/summary_fn are injectable for tests; by default both come from
    the integration bridge (learn-from-action + unified-log summary).
    """
    root = Path(root) if root is not None else repo_root()
    plan = Path(plan_path) if plan_path is not None else root / PLAN_REL
    store = EpicStore(root)

    started_at = _now_iso()
    started_dt = _parse_ts(started_at)
    round_id = "ROUND-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")

    sources = build_sources(store, plan)

    if emit_fn is None and not dry_run:
        mod = load_bridge(root)
        emit_fn = bridge_emit(mod)
        if summary_fn is None:
            summary_fn = mod.log_integration

    emitted: list[dict] = []
    failed: list[dict] = []
    if not dry_run:
        for tool, file, outcome in sources:
            try:
                payload = emit_fn(tool, file, outcome)
                rsi = payload.get("rsi") if isinstance(payload, dict) else None
                recorded = bool(rsi.get("recorded")) if isinstance(rsi, dict) else False
                emitted.append({"tool": tool, "file": file, "outcome": outcome,
                                "rsi_recorded": recorded})
            except Exception as e:  # noqa: BLE001 — one bad source must not
                failed.append({        # hide the rest of the round (R9)
                    "tool": tool, "file": file,
                    "error": str(e)[:160],
                })

    m1 = len(emitted)
    m1_log = count_learn_events(root / LOG_REL, started_dt)
    live_n = sum(1 for s in sources if s[0] == "round-finding")
    retro_n = len(sources) - live_n

    audit = audit_guards(store)
    reasons: list[str] = []
    if not audit.get("ok"):
        reasons.append(
            "guard-audit: missing="
            f"{audit.get('missing')} errors={len(audit.get('errors', []))}")
    if m1 == 0:
        reasons.append("M1=0 (no learn events emitted)")
    if emitted and any(not e["rsi_recorded"] for e in emitted):
        reasons.append("scenario-record-failed (learn event logged, "
                       "scenario memory refused some records)")
    if failed:
        reasons.append(f"emit-failed={len(failed)}")
    status = "green" if not reasons else "yellow"

    if not dry_run and summary_fn is not None:
        summary_fn({
            "ts": _now_iso(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "round_close",
            "tool": "learn-emitter",
            "file": round_id,
            "outcome": status,
            "level": "summary",
            "evidence": {"round_id": round_id, "m1": m1,
                         "status": status, "guards_ok": bool(audit.get("ok")),
                         "reasons": reasons},
        })

    return {
        "round_id": round_id,
        "started_at": started_at,
        "dry_run": bool(dry_run),
        "sources": {"live_findings": live_n,
                    "retro_learnings": retro_n,
                    "total": len(sources)},
        "m1": m1,
        "m1_log": m1_log,
        "emitted": emitted,
        "failed": failed,
        "guard_audit": {"ok": bool(audit.get("ok")),
                        "coverage": audit.get("coverage"),
                        "missing": audit.get("missing"),
                        "errors": audit.get("errors", [])},
        "status": status,
        "reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="learn_emitter",
        description="R5 round close: emit learn events (M1) + guard audit")
    ap.add_argument("--plan", type=Path, default=None,
                    help="plan file with the §9 retro matrix")
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root (store, bridge, log)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report sources without emitting anything")
    args = ap.parse_args(argv)
    try:
        report = round_close(root=args.root, plan_path=args.plan,
                             dry_run=args.dry_run)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if args.dry_run:
        return 0
    return 0 if report["status"] == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
