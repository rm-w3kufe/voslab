#!/usr/bin/env python3
"""distill_triage.py — batch triage of state/distill/candidates.jsonl.

# design: docs/plans/refs_optimization_proposal.vsm
route: cli/manual — batch triage (no plugin entry_point); applying any
       adopted candidate still requires S5 ratification.

Task: DISTILL-BATCH-TRIAGE-1-2026-10-12 (S5 decision 2026-10-12).
Design §6.2 of the design source above (distill O-6 family).
SEMI-AUTOMATIC BY DESIGN: log_distill.py PROPOSES; this tool TRIAGES
(status + reason per candidate); applying any
adopted candidate still requires S5 ratification (K5: this script writes
ONLY candidates.jsonl, same write-set as log_distill).

Vocabulary per kind (task done_when):
  tool_pattern -> adopted (alias/batch path chosen) | rejected | proposed
  error_pattern-> adopted (real signal, root-cause work owner named)
                  | rejected (noise/expected/historic, reason fed)
                  | proposed (undecided, review_by date)
Batch-1 rules are deterministic functions of (kind, key, count) — R10.

Usage:
  python3 scripts/state/monitoring/distill_triage.py           # apply + report
  python3 scripts/state/monitoring/distill_triage.py --dry-run # report only
Exit: 0 ok, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_VOS_ROOT = Path(__file__).resolve().parents[3]
WRITE_ALLOWED = {"candidates.jsonl"}  # K5 hard limit (mirrors log_distill)

# --- tool_pattern families (order matters: first match wins) ---------------
_TOOL_VERIFY = re.compile(r"pytest|run_gates\.py|validator/check\.py")
_TOOL_SSH = re.compile(r"^(ssh |timeout # (ssh|grep))")
# everything else in cd/heredoc/inline/loop/date/git space is agent-idiom
_TOOL_IDIOM = re.compile(
    r"^(cd |python# <<|python# \"|python# .?import|for (f|i) in |date \+|git )"
)

# --- error_pattern families ------------------------------------------------
_REASON_REJECTED_K4 = "K4: truth=FALSE es outcome normal, no breakage"
_RULES_ERROR: list[tuple[re.Pattern, callable] ] = [
    (re.compile(r"truth=FALSE cert=True"),
     lambda k, c: ("rejected", _REASON_REJECTED_K4)),
    (re.compile(r"^live:child-boot-state-archive-gates"),
     lambda k, c: ("rejected", "check retirado (child archive legacy 2026-10-13)")),
    (re.compile(r"^live:zz-fake-cacheable"),
     lambda k, c: ("rejected", "NC fixture by design (zz-fake es control)")),
    (re.compile(r"^live:(classification-valid|dir-schema-valid)"),
     lambda k, c: ("rejected", "fixed 2026-10-16 (classification batch in-process)")),
    (re.compile(r"^live:instrument-set-valid"),
     lambda k, c: ("rejected", "fixed 2026-10-16 (checks_manifest regen)")),
    (re.compile(r"^live:"),
     lambda k, c: ("rejected", "suite live 84/84 PASS 2026-10-16 (histórico rotado)")),
    (re.compile(r"tool:rsi-approve|tool:rsi-threshold-set"),
     lambda k, c: ("rejected", "rbac_deny = enforcement working; histórico sep, sin recurrencia en muestra oct")),
    (re.compile(r"gap-resolver\|decision=\? certified=false"),
     lambda k, c: ("rejected", "expected: certified=false es salida semi-auto normal (UNKNOWN)")),
    (re.compile(r"^broken-noop-gate"),
     lambda k, c: ("rejected", "NC suite 25/25 PASS 2026-10-16 (histórico sep)")),
    (re.compile(r"E2BIG"),
     lambda k, c: ("adopted", "fix candidato: bridge payload via stdin (E2BIG argv) — dueño vos-kernel")),
    (re.compile(r"^state-reconcile\|reconcile failed: n02 is not defined"),
     lambda k, c: ("rejected", "no reproducido: state_reconcile OK en onboard 2026-10-16")),
    (re.compile(r"^state-reconcile\|monitoring_gap.*s3star"),
     lambda k, c: ("rejected", "FP certificado 2026-10-08 (s3star buffer/disk out-of-phase)")),
    (re.compile(r"^state-reconcile\|"),
     lambda k, c: ("rejected", "no reproducido: reconcile OK 2026-10-16")),
    (re.compile(r"^pattern-runner\|.*dep-graph"),
     lambda k, c: ("rejected", "resuelto: cycles→handoff (second-order-loop F, 2026-10-14)")),
    (re.compile(r"^tool-bridge\|"),
     lambda k, c: ("rejected", "histórico pipeline pre-fix classification + bridge estable en sesión 2026-10-16")),
    (re.compile(r"^tool-integration\|BLOCKED"),
     lambda k, c: ("rejected", "no reproducido: risk-assess bridge operativo 2026-10-16")),
    (re.compile(r"^learning-cycle-scan\|"),
     lambda k, c: ("rejected", "no reproducido: scan OK 2026-10-16")),
    (re.compile(r"^vsf-scripts-manifest-updater\|"),
     lambda k, c: ("rejected", "no reproducido: manifest updater OK 2026-10-16 (regen)")),
    (re.compile(r"^rsi-cycle\|"),
     lambda k, c: ("rejected", "no reproducido: rsi-cycle sanos (streak evaluate 283, queue consumed PASS)")),
]


def triage_tool(key: str, count: int) -> tuple[str, str]:
    if _TOOL_VERIFY.search(key):
        return ("adopted",
                "batch adoptado: grupo verify-runner (pytest/run_gates/check) — "
                "implementación pendiente OK S5")
    if _TOOL_SSH.search(key):
        return ("adopted",
                "batch adoptado: grupo ssh/timeout defaults (Host defaults / wrapper) — "
                "implementación pendiente OK S5")
    if _TOOL_IDIOM.match(key):
        return ("rejected", "agent-idiom (workdir/inline/loop/git), alias no aplica")
    return ("rejected", "agent-idiom misc, sin ganancia de ergonomía")


def triage_error(key: str, count: int) -> tuple[str, str]:
    for pat, fn in _RULES_ERROR:
        if pat.search(key):
            return fn(key, count)
    return ("proposed", "sin diagnóstico en batch-1")


def triage(rows: list[dict]) -> tuple[list[dict], dict]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for r in rows:
        kind = r.get("kind")
        key = r.get("key", "")
        count = r.get("count", 0)
        if r.get("status") != "proposed":
            out.append(r)  # already triaged — preserve
            continue
        if kind == "tool_pattern":
            status, reason = triage_tool(key, count)
        elif kind == "error_pattern":
            status, reason = triage_error(key, count)
        elif kind == "caution_signal":
            status, reason = (
                "rejected",
                "flood probe deliberado 2026-10-08 (G-36), no señal real")
        else:
            status, reason = ("proposed", "kind desconocido — conservar")
        r = dict(r)
        r["status"] = status
        r["triage"] = {"batch": 1, "ts": now, "by": "vos-kernel", "reason": reason}
        if status == "proposed":
            r["review_by"] = "2026-11-01"
        out.append(r)
    summary: dict = {}
    for r in out:
        k = (r.get("kind"), r.get("status"))
        summary["|".join(k)] = summary.get("|".join(k), 0) + 1
    return out, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path = _VOS_ROOT / "state" / "distill" / "candidates.jsonl"
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    triaged, summary = triage(rows)
    proposed = sum(v for k, v in summary.items() if k.endswith("|proposed"))
    print(f"total={len(triaged)} proposed={proposed} (target <20)")
    for k in sorted(summary):
        print(f"  {k}: {summary[k]}")
    if not args.dry_run:
        # K5: single permitted write target
        assert path.name in WRITE_ALLOWED
        with path.open("w", encoding="utf-8") as f:
            for r in triaged:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
