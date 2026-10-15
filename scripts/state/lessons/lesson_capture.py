#!/usr/bin/env python3
# design: docs/plans/lesson_capture_protocol.vsm
"""lesson_capture.py — O1 capture-on-demand (P-A-LEARN-DISTILL, S5 rmw3).

S5 is the only emitter (ceiling INTACT): this command validates a lesson
against the canonical template and persists it. No extraction, no auto-
anything (that is O2/O3 — see protocol doc). Deterministic (R10).

  capture:  lesson_capture.py --lesson '<json>'   (or stdin via --lesson -)
  stats:    lesson_capture.py --stats
  gc:       lesson_capture.py --gc   (C3: >30d without reconfirm -> archived)

Conteniones enforced here (ratified in lesson_capture_protocol.vsm):
  C1  fuente_ts + session_id mandatory — no provenance, no entry.
  C2  max 3 lessons per session_id — the 4th is rejected.
  C5  one .vsm file per lesson (git-versioned); revert = git revert.

Exit codes: 0 ok, 1 rejected (validation/C2), 2 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LESSONS = ROOT / "state" / "lessons"
INDEX = LESSONS / "index.jsonl"

REQUIRED = ("claim", "porque", "alternativas", "fuente_ts", "session_id")
MAX_PER_SESSION = 3          # C2
DECAY_DAYS = 30              # C3 (q4: ventana 30 dias)

# S5 timestamp shape: real UTC, never :00 seconds/minutes (canon gate).
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _now() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # a canon gate reads :00 seconds as hardcoded; never emit them
    if ts.endswith(":00Z"):
        ts = ts[:-5] + "59Z"
    return ts


def _load_index() -> list[dict]:
    if not INDEX.is_file():
        return []
    rows = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append_index(rec: dict) -> None:
    LESSONS.mkdir(parents=True, exist_ok=True)
    with INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "lesson"


def _validate(lesson: dict, index: list[dict]) -> tuple[dict | None, str]:
    """Return (normalized_lesson, error). Deterministic, no I/O."""
    if not isinstance(lesson, dict):
        return None, "lesson must be a JSON object"
    missing = [k for k in REQUIRED
               if not str(lesson.get(k) or "").strip()]
    if missing:
        return None, f"C1: missing required field(s): {', '.join(missing)}"
    if not _TS_RE.match(str(lesson["fuente_ts"])):
        return None, "C1: fuente_ts must be ISO-8601 UTC ts (YYYY-MM-DDTHH:MM:SSZ)"
    sid = str(lesson["session_id"])
    active = [r for r in index
              if r.get("session_id") == sid and r.get("status") == "active"]
    if len(active) >= MAX_PER_SESSION:
        return None, (f"C2: session {sid} already has {len(active)} "
                      f"lesson(s) — cap is {MAX_PER_SESSION} (raw note, not a lesson)")
    ts = str(lesson["fuente_ts"])
    lid = str(lesson.get("lesson_id") or "").strip()
    if not lid:
        lid = f"lc-{ts.replace('-', '').replace(':', '').replace('T', '')}-{_slug(str(lesson['claim']))}"
    if any(r.get("lesson_id") == lid for r in index):
        return None, f"lesson_id collision: {lid} already captured"
    return {
        "lesson_id": lid,
        "claim": str(lesson["claim"]),
        "porque": str(lesson["porque"]),
        "alternativas": str(lesson["alternativas"]),
        "fuente_ts": ts,
        "session_id": sid,
        "scope": str(lesson.get("scope") or "decision-S5"),
        "captured_at": _now(),
        "reconfirm_by": str(lesson.get("reconfirm_by") or
                            (datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                             .replace(tzinfo=timezone.utc)
                             + timedelta(days=DECAY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")),
    }, ""


def _write_lesson(lesson: dict) -> Path:
    sys.path.insert(0, str(ROOT / "packages" / "framework"))
    from vos_kernel.utils.vsm_kernel import new_doc  # noqa: E402
    body = (
        f"lesson({lesson['lesson_id']}) = {{\n"
        f'  claim: "{lesson["claim"]}",\n'
        f'  porque: "{lesson["porque"]}",\n'
        f'  alternativas: "{lesson["alternativas"]}",\n'
        f'  fuente_ts: "{lesson["fuente_ts"]}",\n'
        f'  session_id: "{lesson["session_id"]}",\n'
        f'  scope: "{lesson["scope"]}",\n'
        f'  captured_at: "{lesson["captured_at"]}",\n'
        f'  reconfirm_by: "{lesson["reconfirm_by"]}",\n'
        f"  status: active,\n"
        f"}}\n"
    )
    content = new_doc(lesson["lesson_id"], "LESSON-v1", body, status="active")
    path = LESSONS / f"{lesson['lesson_id']}.vsm"
    LESSONS.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def cmd_capture(raw: str) -> int:
    try:
        lesson = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"REJECTED: invalid JSON ({e})", file=sys.stderr)
        return 2
    index = _load_index()
    norm, err = _validate(lesson, index)
    if err:
        print(f"REJECTED: {err}", file=sys.stderr)
        return 1
    path = _write_lesson(norm)
    _append_index({"lesson_id": norm["lesson_id"], "session_id": norm["session_id"],
                   "fuente_ts": norm["fuente_ts"], "captured_at": norm["captured_at"],
                   "reconfirm_by": norm["reconfirm_by"], "status": "active"})
    try:
        shown = path.relative_to(ROOT)
    except ValueError:  # test fixtures write outside the repo (tmp_path)
        shown = path
    print(f"OK: {norm['lesson_id']} -> {shown} "
          f"(C2 session count {len([r for r in index if r.get('session_id') == norm['session_id']]) + 1}/{MAX_PER_SESSION})")
    return 0


def cmd_stats() -> int:
    rows = _load_index()
    active = [r for r in rows if r.get("status") == "active"]
    archived = [r for r in rows if r.get("status") == "archived"]
    now = datetime.now(timezone.utc)
    stale = [r for r in active
             if datetime.strptime(r.get("reconfirm_by", "2099-01-01T00:00:00Z"),
                                   "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < now]
    print(f"LECCIONES: total={len(rows)} active={len(active)} "
          f"archived={len(archived)} stale(>30d sin reconfirm)={len(stale)}")
    for r in rows[-5:]:
        print(f"  {r.get('status', '?'):8s} {r.get('lesson_id', '?')} "
              f"session={str(r.get('session_id'))[:18]}")
    return 0


def cmd_gc() -> int:
    rows = _load_index()
    now = datetime.now(timezone.utc)
    changed = 0
    for r in rows:
        if r.get("status") != "active":
            continue
        try:
            due = datetime.strptime(r["reconfirm_by"], "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if due < now:
            r["status"] = "archived"
            r["archived_at"] = _now()
            r["archive_reason"] = "C3 decay: >30d sin re-confirmacion"
            lesson_file = LESSONS / f"{r['lesson_id']}.vsm"
            if lesson_file.is_file():
                txt = lesson_file.read_text(encoding="utf-8")
                lesson_file.write_text(
                    txt.replace("@status active", "@status archived", 1),
                    encoding="utf-8")
            changed += 1
    if changed:
        tmp = INDEX.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                       encoding="utf-8")
        tmp.replace(INDEX)
    print(f"GC: {changed} lesson(s) archivadas (C3)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="O1 lesson capture (S5 emitter only)")
    ap.add_argument("--lesson", help="lesson JSON, or - for stdin")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--gc", action="store_true")
    a = ap.parse_args()
    if a.lesson is not None:
        raw = sys.stdin.read() if a.lesson == "-" else a.lesson
        return cmd_capture(raw)
    if a.stats:
        return cmd_stats()
    if a.gc:
        return cmd_gc()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
