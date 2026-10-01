"""focus-format gate — A-7 / D-03 (backlog system_backlog.vsm, 2026-10-01).

current_focus.json notes used to be walls (>2000 chars, truncated by any
reader) — LCC-07/CYCLE-CLOSE/EPISTEMIC entries were unreadable at a
glance. A focus file is a signal surface: short structured fields, long
detail archived by reference.

Contract (docs/specs/focus_format.vsm):
  - top level: JSON array of entries
  - required per entry: ref (non-empty, unique), status in
    {active, paused, done}, note (non-empty, <= MAX_NOTE_CHARS),
    started_at / updated_at (ISO-8601 UTC with Z)
  - optional: detail (reference to an archived note file), agent_id
  - long notes live in state/focus_details/<ref>.md (runtime, local)

Semantics (boot_ontology / env_parity pattern):
  - check(path): validate the JSON at path; empty path -> live
    current_focus.json at the workspace root.
  - negative_case(): a focus entry whose note exceeds MAX_NOTE_CHARS —
    must ALWAYS be rejected (exit != 0).
  - Live invocation: gate_suite/tests/test_focus_format.py checks the
    schema helpers on every suite run.

Run by the harness: register("focus-format", check, negative_case).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

from gate_suite.harness import register

#: Notes longer than this are archived to state/focus_details/<ref>.md.
MAX_NOTE_CHARS = 500
STATUSES = ("active", "paused", "done")
REQUIRED_FIELDS = ("ref", "status", "note", "started_at", "updated_at")
OPTIONAL_FIELDS = ("detail", "agent_id")
ALLOWED_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)


def _looks_iso_z(value: object) -> bool:
    """ISO-8601 UTC ending in Z (YYYY-MM-DDTHH:MM:SSZ), string only."""
    if not isinstance(value, str) or len(value) < 20:
        return False
    if not value.endswith("Z"):
        return False
    # date T time : seconds Z
    return (
        len(value) == 20
        and value[4] == "-"
        and value[10] == "T"
        and value[13] == ":"
        and value[16] == ":"
        and value[19] == "Z"
    )


def validate_focus(data: object) -> list[str]:
    """Return a list of violations (empty = valid). Deterministic (R10)."""
    fails: list[str] = []
    if not isinstance(data, list):
        return ["focus must be a JSON array of entries"]
    seen_refs: set[str] = set()
    for i, entry in enumerate(data):
        where = f"[{i}]"
        if not isinstance(entry, dict):
            fails.append(f"{where}: entry must be an object")
            continue
        ref = entry.get("ref")
        if isinstance(ref, str) and ref:
            where = f"[{i}]({ref})"
            if ref in seen_refs:
                fails.append(f"{where}: duplicate ref")
            seen_refs.add(ref)
        else:
            fails.append(f"{where}: missing or empty ref")
        for field in REQUIRED_FIELDS:
            if field not in entry:
                fails.append(f"{where}: missing field {field}")
        for field in entry:
            if field not in ALLOWED_FIELDS:
                fails.append(f"{where}: unknown field {field}")
        status = entry.get("status")
        if "status" in entry and status not in STATUSES:
            fails.append(f"{where}: status {status!r} not in {list(STATUSES)}")
        note = entry.get("note")
        if "note" in entry:
            if not isinstance(note, str) or not note.strip():
                fails.append(f"{where}: note must be a non-empty string")
            elif len(note) > MAX_NOTE_CHARS:
                fails.append(
                    f"{where}: note {len(note)} chars > {MAX_NOTE_CHARS} — "
                    f"archive the detail and keep a short summary"
                )
        for field in ("started_at", "updated_at"):
            if field in entry and not _looks_iso_z(entry[field]):
                fails.append(f"{where}: {field} not ISO-8601 UTC with Z")
        detail = entry.get("detail")
        if "detail" in entry and (not isinstance(detail, str) or not detail):
            fails.append(f"{where}: detail must be a non-empty string")
    return fails


def _default_focus_path() -> str:
    # Workspace root: this file lives in packages/framework/gate_suite/gates/
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", "..", "..", "current_focus.json")


def check(path: str) -> int:
    """Return 0 if the focus file honours the short-note contract."""
    target = path or _default_focus_path()
    if not os.path.exists(target):
        if not path:
            # No live focus file: nothing to signal (clones start empty).
            return 0
        sys.stderr.write(f"focus-format: no such file {target}\n")
        return 1
    try:
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"focus-format: unreadable {target}: {exc}\n")
        return 1
    fails = validate_focus(data)
    if fails:
        for fail in fails:
            sys.stderr.write(f"focus-format: {fail}\n")
        return 1
    return 0


def negative_case() -> str:
    """A focus entry whose note is too long — must always be rejected."""
    fd, p = tempfile.mkstemp(prefix="focus_format.", suffix=".json",
                             dir=tempfile.gettempdir())
    entry = {
        "ref": "wall-note",
        "status": "active",
        "note": "x" * (MAX_NOTE_CHARS + 1),
        "started_at": "2026-10-01T12:00:00Z",
        "updated_at": "2026-10-01T12:00:00Z",
    }
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump([entry], fh)
    return p


register("focus-format", check, negative_case)
