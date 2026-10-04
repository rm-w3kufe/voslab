#!/usr/bin/env python3
"""
VSL task format validator — TASKS.vsm coordination-file checker.

Flags:
  (i)  any task() with a missing or non-standard status;
  (ii) DRIFT — any task ID marked done/resolved in a session() block whose
       task() block is NOT status=done/superseded/dropped;
  (iii) duplicate task IDs with conflicting status.

Canonical status enum (v2 of VSL-STANDARDIZATION, 2026-08-22):
  { open, in_progress, queued, seeded, partial, discovery, deployed,
    paused, deferred, reopened, closed, done }

Map from legacy:
  blocked → in_progress
  gated → deferred
  superseded → done
  dropped → done
  acked / resolved / audited → done

Usage:
    python3 scripts/tasks_validate.py [--verbose] [--n02] [--state-db PATH]

    --verbose   show all findings including OK statuses
    --n02       fetch live state.db for cross-reference (SSH to n02)
    --state-db  path to state.db (default: /var/lib/vsf-state/state.db)

Returns:
    0  ← no drift, all tasks valid (OK for session-close)
    1  ← drift found (session-close MUST NOT proceed until fixed)
    2  ← parse error / file not found
"""

from pathlib import Path
import argparse
import os
import re
import sys

# S5 containment 2026-10-04: workspace root default (VSF_ROOT env still
# wins for upstream/covenant workflows).
VSF_ROOT = os.environ.get("VSF_ROOT") or os.environ.get("VOSLAB_PATH") \
    or str(Path(__file__).resolve().parents[3])
TASKS_FILE = os.path.join(VSF_ROOT, "TASKS.vsm")

# ── Canonical status enum ──────────────────────────────────────────────────
CANONICAL_STATUS = {"open", "in_progress", "queued", "seeded", "partial",
                    "discovery", "deployed", "paused", "deferred", "reopened",
                    "closed", "done"}

LEGACY_MAP = {
    "blocked": "in_progress",
    "gated": "deferred",
    "superseded": "done",
    "dropped": "done",
    "acked": "done",
    "resolved": "done",
    "audited": "done",
}

NON_DONE_STATUSES = {"open", "in_progress", "queued", "seeded", "partial",
                     "discovery", "deployed", "paused", "deferred", "reopened"}

# ── Parser ─────────────────────────────────────────────────────────────────

class VSLTask:
    """Parsed representation of one task() block."""
    __slots__ = ("id", "status", "title", "line", "raw_block", "agents")

    def __init__(self):
        self.id = None
        self.status = None
        self.title = None
        self.line = 0
        self.raw_block = ""
        self.agents = set()


class VSLSession:
    """Parsed representation of one session() block."""
    __slots__ = ("id", "resolved_ids", "line")

    def __init__(self):
        self.id = None
        self.resolved_ids = set()
        self.line = 0


def _normalize_status(raw: str) -> str:
    """Normalize legacy status to canonical. Returns canonical or empty str."""
    s = raw.strip()
    if s in CANONICAL_STATUS:
        return s
    if s in LEGACY_MAP:
        return LEGACY_MAP[s]
    return ""


def _parse_vsl_tasks(path: str) -> (list, list):
    """
    Parse TASKS.vsm into lists of VSLTask and VSLSession.
    Returns (tasks, sessions). On error, prints and returns ([], []).
    """
    tasks = []
    sessions = []
    current_task = None
    current_session = None

    if not os.path.exists(path):
        print(f"ERROR: {path} not found", file=sys.stderr)
        return [], []

    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    for i, raw in enumerate(lines):
        line_num = i + 1
        line = raw.split("//")[0].rstrip()

        # --- task() block ---
        # Multi-line: task("ID", priority=P, agent=[..], status=enum) = {
        # Single-line: task(ID): ... status=done
        tm = re.match(r'task\s*\(\s*"([^"]+)"\s*', line)
        if not tm:
            tm = re.match(r'task\s*\(\s*(\w+)\s*\)', line)
        if tm:
            if current_task:
                tasks.append(current_task)
            if current_session:
                sessions.append(current_session)
                current_session = None
            current_task = VSLTask()
            current_task.id = tm.group(1)
            current_task.line = line_num
            current_task.raw_block = raw.rstrip()

            # Extract status from single-line
            sm = re.search(r'\bstatus\s*=\s*(\S+)', line)
            if sm:
                current_task.status = sm.group(1).rstrip(',})')
            am = re.search(r'agent\s*=\s*\[([^\]]+)\]', line)
            if am:
                current_task.agents = set(a.strip() for a in am.group(1).split(','))
            continue

        # --- session() block ---
        sm = re.match(r'session\s*\(\s*"([^"]+)"\s*\)', line)
        if sm:
            if current_task:
                tasks.append(current_task)
                current_task = None
            if current_session:
                sessions.append(current_session)
            current_session = VSLSession()
            current_session.id = sm.group(1)
            current_session.line = line_num
            continue

        if current_task:
            current_task.raw_block += "\n" + raw.rstrip()
            sm = re.search(r'\bstatus\s*=\s*(\S+)', line)
            if sm and current_task.status is None:
                current_task.status = sm.group(1).rstrip(',})')
            # multi-line format: status: <value>
            sm2 = re.search(r'status\s*:\s*(\S+)', line)
            if sm2 and current_task.status is None:
                current_task.status = sm2.group(1).rstrip(',})')
            am = re.search(r'agent\s*=\s*\[([^\]]+)\]', line)
            if am:
                current_task.agents = set(a.strip() for a in am.group(1).split(','))

        if current_session:
            # Extract resolved: ["ID1", "ID2"] entries
            rm = re.findall(r'"([A-Z][-A-Z0-9]*)"', line)
            for rid in rm:
                if not rid.startswith("2026") and not rid.startswith("config"):  # avoid date strings
                    current_session.resolved_ids.add(rid)

    # Flush last
    if current_task:
        tasks.append(current_task)
    if current_session:
        sessions.append(current_session)

    return tasks, sessions


def _build_task_index(tasks: list) -> dict:
    """Build a dict of task_id → list of VSLTask (for duplicate detection)."""
    idx = {}
    for t in tasks:
        idx.setdefault(t.id, []).append(t)
    return idx


# ── Validation ──────────────────────────────────────────────────────────────

def validate(path: str, verbose: bool = False) -> list:
    """
    Run all validations. Returns list of finding dicts.
    Each finding: { 'class': str, 'task_id': str, 'detail': str }
    """
    findings = []
    tasks, sessions = _parse_vsl_tasks(path)
    if not tasks and not sessions:
        print(f"ERROR: no tasks or sessions found in {path}", file=sys.stderr)
        return [{"class": "PARSE_ERROR", "task_id": "", "detail": f"Empty or unparseable {path}"}]

    task_idx = _build_task_index(tasks)
    session_resolved = {}
    for s in sessions:
        for rid in s.resolved_ids:
            session_resolved.setdefault(rid, []).append(s.id)

    if verbose:
        print(f"Parsed: {len(tasks)} tasks, {len(sessions)} sessions")

    # ── (i) Invalid / missing status ────────────────────────────────────────
    for tid, tlist in task_idx.items():
        for t in tlist:
            if t.status is None or t.status == "":
                findings.append({
                    "class": "MISSING_STATUS",
                    "task_id": tid,
                    "detail": f"Status not set (line {t.line})",
                })
            else:
                norm = _normalize_status(t.status)
                if not norm:
                    findings.append({
                        "class": "INVALID_STATUS",
                        "task_id": tid,
                        "detail": f"Status '{t.status}' not in canonical set (line {t.line})",
                    })
                elif t.status != norm:
                    findings.append({
                        "class": "LEGACY_STATUS",
                        "task_id": tid,
                        "detail": f"Status '{t.status}' should be canonical '{norm}' (line {t.line})",
                    })

    # ── (iii) Duplicate IDs with conflicting status ─────────────────────────
    for tid, tlist in task_idx.items():
        if len(tlist) < 2:
            continue
        statuses = {}
        for t in tlist:
            stat = t.status or "UNSET"
            statuses.setdefault(stat, []).append(t.line)
        if len(statuses) > 1:
            detail = "; ".join(f"{s} at L{lines}" for s, lines in statuses.items())
            findings.append({
                "class": "DUPLICATE_CONFLICT",
                "task_id": tid,
                "detail": f"Duplicate task ID with differing status: {detail}",
            })

    # ── (ii) DRIFT: session says done, task says not done ───────────────────
    for tid, tlist in task_idx.items():
        if tid in session_resolved:
            # Task is referenced in a session block's resolved list
            # Check the LATEST task block status
            t = tlist[-1]  # latest occurrence
            norm = _normalize_status(t.status) if t.status else ""
            if norm in NON_DONE_STATUSES or norm == "":
                session_ids = ", ".join(session_resolved[tid])
                findings.append({
                    "class": "DRIFT",
                    "task_id": tid,
                    "detail": f"Session(s) [{session_ids}] mark as resolved but task block status='{t.status}' — close it",
                })

    return findings


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv: list) -> int:
    p = argparse.ArgumentParser(description="VSL task format validator (VSL-STANDARDIZATION v1)")
    p.add_argument("--verbose", action="store_true", help="show all findings including OK")
    p.add_argument("--n02", action="store_true",
                   help="(NYI) fetch live state.db for cross-reference (SSH to n02)")
    p.add_argument("--state-db", default="/var/lib/vsf-state/state.db")
    p.add_argument("--tasks-file", default=TASKS_FILE, help="Path to TASKS.vsm")
    a = p.parse_args(argv[1:])

    if not os.path.exists(a.tasks_file):
        print(f"ERROR: {a.tasks_file} not found", file=sys.stderr)
        return 2

    findings = validate(a.tasks_file, a.verbose)

    # Print report
    if a.verbose:
        print(f"\n--- VSL Validation Report ({len(findings)} total) ---")

    drift = [f for f in findings if f["class"] == "DRIFT"]
    invalid = [f for f in findings if f["class"] in ("MISSING_STATUS", "INVALID_STATUS")]
    legacy = [f for f in findings if f["class"] == "LEGACY_STATUS"]
    duplicates = [f for f in findings if f["class"] == "DUPLICATE_CONFLICT"]
    errors = [f for f in findings if f["class"] == "PARSE_ERROR"]

    # Summary
    lines = ["VSL Validation:"]
    if errors:
        for f in errors:
            lines.append(f"  ❌ {f['detail']}")

    if drift:
        lines.append(f"  ❌ DRIFT: {len(drift)} task(s) resolved in session block but not closed in task block")
        for f in drift[:10]:
            lines.append(f"     task({f['task_id']}): {f['detail']}")
    else:
        lines.append("  ✅ No drift — all session-resolved tasks have matching task-block status")

    if invalid:
        lines.append(f"  ⚠ STATUS: {len(invalid)} task(s) with missing/invalid status")
        for f in invalid[:5]:
            lines.append(f"     task({f['task_id']}): {f['detail']}")
    elif legacy:
        lines.append(f"  🟡 STATUS: {len(legacy)} task(s) use legacy status (auto-mapped, OK)")
        if a.verbose:
            for f in legacy[:5]:
                lines.append(f"     task({f['task_id']}): {f['detail']}")
    else:
        lines.append("  ✅ All statuses canonical")

    if duplicates:
        lines.append(f"  ❌ DUPLICATE: {len(duplicates)} task ID(s) with conflicting status")
        for f in duplicates[:5]:
            lines.append(f"     task({f['task_id']}): {f['detail']}")
    else:
        lines.append("  ✅ No duplicate task ID conflicts")

    if a.verbose:
        for f in findings:
            if f["class"] not in ("DRIFT", "MISSING_STATUS", "INVALID_STATUS",
                                  "LEGACY_STATUS", "DUPLICATE_CONFLICT", "PARSE_ERROR"):
                lines.append(f"  {f['class']}: task({f['task_id']}): {f['detail']}")

    print("\n".join(lines))

    # Exit code
    if errors:
        return 2
    if drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
