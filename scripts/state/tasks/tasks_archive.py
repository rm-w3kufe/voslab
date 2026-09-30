#!/usr/bin/env python3
"""Keep TASKS.vsm readable in one pass, without losing a byte.

Why (2026-08-10 boot audit): TASKS.vsm had reached 1341 KB — 5x the agent's
256 KB read limit — so the backlog could only ever be read in fragments.
Measured composition, not guessed:

    session() blocks   521 KB   (39%)  <- DS logs its sessions HERE by
                                          convention; HANDOFF cross-references
                                          them as "TASKS.vsm <name>"
    done task bodies   346 KB
    unparseable status 143 KB          <- 108 tasks; see the C dispatch to DS
    actionable         89 KB   (open + partial)

Two independent passes, each verifiable on its own:

  --sessions  move session() blocks older than the kept window into
              docs/sessions/ds/<YYYY-MM>.vsm. DS keeps writing them
              into TASKS.vsm exactly as before; only the cold tail moves.
              KEEP = number of RECENT session blocks to keep live (default
              1). CRITERION REVISED 2026-08-19 (ARCHIVE-CRITERION-BY-COUNT):
              by COUNT, not by month — month-based keep failed once all
              live sessions landed in the same month (nothing archived,
              ≤5-live check stayed red). "Archive sessions with no active
              tasks" was evaluated and REJECTED: verified that zero live
              sessions reference open task ids — that criterion archives
              everything and loses the recent context window.

  --closed    move the BODY of done/closed tasks into
              docs/sessions/tasks_closed/, leaving a stub that keeps the name,
              status, date and a pointer. Stubs matter: 24 closed tasks have
              inbound references, and today a field from a CLOSED task was what
              corrected an already-committed error. Archive, never summarise.

Span rule for session blocks, validated against the data before use: a block
runs from its `session(` line to the next line starting `session(`, `task(` or
`//`. TASKS.vsm holds TWO session forms — `session("x") = {` closes with `}`,
but `session("x"):` has no closing brace at all (15 of 168), so a brace-based
rule would have swallowed neighbours. 0 blocks contain a column-0 `//`, so the
rule cannot truncate one.

Usage:
    python3 scripts/state/tasks_archive.py --sessions
    python3 scripts/state/tasks_archive.py --sessions --apply
    python3 scripts/state/tasks_archive.py --closed  --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Brace-depth helpers from the VSL tokenizer — reuse the canonical scanner
# rather than reimplementing string/comment handling (a naive `}`-count broke
# nested fact()/task() bodies, 2026-08-15).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vsl"))
from vslline import scan_line as _scan_line          # noqa: E402
from tokenizer import _brace_delta                   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "TASKS.vsm"
SESSION_DIR = ROOT / "docs/sessions/ds"
CLOSED_DIR = ROOT / "docs/sessions/tasks_closed"
LIMIT = 256 * 1024
TOP = re.compile(r'^(session\(|task[\("]|//)')


def session_spans(lines: list[str]) -> list[tuple[int, int, str]]:
    tops = [i for i, l in enumerate(lines) if TOP.match(l)]
    out = []
    for i, l in enumerate(lines):
        if not l.startswith("session("):
            continue
        nxt = next((j for j in tops if j > i), len(lines))
        name = re.match(r'session\("?([^")]*)"?', l).group(1)
        out.append((i, nxt, name))
    return out


def chunk(items: list[tuple[str, str]], stem: str) -> dict[str, list]:
    """Split into files that each stay under the read limit."""
    files, part, acc, n = {}, [], 0, 0
    for name, body in items:
        b = len(body.encode())
        if part and acc + b > LIMIT * 0.85:
            files[f"{stem}-{chr(97+n)}"] = part
            part, acc, n = [], 0, n + 1
        part.append((name, body))
        acc += b
    if part:
        files[stem if n == 0 else f"{stem}-{chr(97+n)}"] = part
    return files


def do_sessions(text: str, keep: int, apply: bool) -> str | None:
    lines = text.splitlines(keepends=True)
    spans = session_spans(lines)
    # CRITERION (REVISED 2026-08-19, ARCHIVE-CRITERION-BY-COUNT): keep the
    # LAST `keep` session blocks by POSITION (the most recent work), archive
    # everything older. Month-based keep (previous behavior) failed once all
    # live sessions landed in the same month — nothing ever archived and the
    # ≤5-live check stayed red (root-boot-state-archive FAIL). By-count is
    # stable: it bounds the live window the model must read regardless of
    # how many sessions pile up in a month. "Archive sessions with no active
    # tasks" was evaluated and REJECTED: verified 2026-08-19 that zero live
    # sessions reference open task ids (sessions reference tasks in
    # resolved:, i.e. already-closed ones) — that criterion archives
    # everything and loses the recent context window.
    move = spans[:-keep] if len(spans) > keep else []
    stay = len(spans) - len(move)
    months = sorted({m.group(1) for _, _, n in spans
                     if (m := re.match(r"(\d{4}-\d{2})", n))})
    keep_months = set(months)  # months kept live = all months that still have live blocks

    by: dict[str, list] = {}
    for i, j, n in move:
        mo = (m.group(1) if (m := re.match(r"(\d{4}-\d{2})", n)) else "undated")
        by.setdefault(mo, []).append((n, "".join(lines[i:j])))

    files: dict[str, list] = {}
    for mo, items in sorted(by.items()):
        files.update(chunk(items, mo))

    moved_bytes = sum(len(b.encode()) for v in by.values() for _, b in v)
    print(f"  session blocks: {len(spans)} total · {stay} stay live "
          f"(months {sorted(keep_months)}) · {len(move)} archived")
    for f in sorted(files):
        print(f"    {f}.vsm  {len(files[f]):3d} blocks  "
              f"{sum(len(b.encode()) for _, b in files[f])/1024:6.1f} KB")
    print(f"  removes {moved_bytes/1024:.1f} KB from TASKS.vsm")

    drop = set()
    for i, j, _ in move:
        drop.update(range(i, j))
    index = ["\n// ── Archived DS session blocks "
             + "─" * 44 + "\n",
             "// Moved by scripts/state/tasks_archive.py --sessions. DS keeps writing\n",
             "// session blocks here as before; only the cold tail is archived.\n",
             "// Full text, nothing summarised — grep these like any other file.\n"]
    for f in sorted(files):
        index.append(f"//   docs/sessions/ds/{f}.vsm  "
                     f"({len(files[f])} blocks)\n")
    index.append("\n")

    first = min((i for i, _, _ in move), default=None)
    new = []
    for k, l in enumerate(lines):
        if first is not None and k == first:
            new.extend(index)
        if k not in drop:
            new.append(l)
    new_text = "".join(new)

    if not apply:
        return None
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    for f, items in files.items():
        head = (f"// DS session archive — {f}\n"
                f"// Moved from TASKS.vsm by scripts/state/tasks_archive.py.\n"
                f"// {len(items)} blocks, full text, byte-identical to the original.\n\n")
        (SESSION_DIR / f"{f}.vsm").write_text(head + "".join(b for _, b in items),
                                              encoding="utf-8")
    return new_text


def task_spans(lines: list[str]) -> list[tuple[int, int, str, str, str]]:
    """-> [(start, end, name, form, status)]. Validated: 0 spans contain another
    task's start, and all 237 brace-form tasks close on a column-0 `}`."""
    tops = [i for i, l in enumerate(lines) if TOP.match(l)]
    out = []
    for i, l in enumerate(lines):
        if m := re.match(r"^task\(([A-Za-z0-9_.\-]+)\):", l):
            j = next((k for k in tops if k > i), len(lines))
            body = "".join(lines[i:j])
            st = (re.search(r"^\s+status\s*=\s*(\w+)\s*$", body, re.M) or [None, "?"])[1]
            out.append((i, j, m.group(1), "A", st))
        elif m := re.match(r'^task\("([^"]+)"', l):
            # Find the REAL closing brace: a body may contain nested blocks
            # (fact(), task()) that also close on a column-0 `}` — taking the
            # first one TRUNCATES the body and leaves the tail (nested
            # blocks) orphaned outside the stub. Count brace depth like the
            # tokenizer does, respecting strings. Found 2026-08-15: 2 bodies
            # with nested fact()/task() were truncated by the first `}` rule.
            j = i + 1
            depth = 1          # the header's `{` is on line i
            in_string = False
            while j < len(lines):
                code, in_string = _scan_line(lines[j], in_string)
                depth += _brace_delta(code)
                j += 1
                if depth <= 0:
                    break
            body = "".join(lines[i:j])
            st = (re.search(r'status\s*[:=]\s*"?(\w+)', body) or [None, "?"])[1]
            out.append((i, min(j, len(lines)), m.group(1), "B", st))
        elif m := re.match(r'^task\(([A-Za-z0-9_.\-]+)[^"]*\)\s*=\s*\{', l):
            # form_C — `task(NAME) = {` (no quotes, `= {`, status with `:`).
            # Created by the 2026-08-13..19 conventions (NAME-DATE ids).
            # Same brace-counting as form_B — the body may contain nested
            # fact()/task() blocks. Found 2026-08-19: 7 form_C done/closed
            # tasks evaded both the archive and the maintenance check because
            # neither instrument recognized this third form.
            j = i + 1
            depth = 1
            in_string = False
            while j < len(lines):
                code, in_string = _scan_line(lines[j], in_string)
                depth += _brace_delta(code)
                j += 1
                if depth <= 0:
                    break
            body = "".join(lines[i:j])
            st = (re.search(r'status\s*[:=]\s*"?(\w+)', body) or [None, "?"])[1]
            out.append((i, min(j, len(lines)), m.group(1), "C", st))
    return out


def do_closed(text: str, apply: bool) -> str | None:
    lines = text.splitlines(keepends=True)
    spans = task_spans(lines)
    # IDEMPOTENT (2026-08-19): a stub that already carries an archived=
    # pointer must NOT be re-archived — re-running --closed would rewrite
    # every stub every time. Only full bodies (no archived pointer) move.
    move = [s for s in spans
            if s[4] in ("done", "closed")
            and "archived" not in "".join(lines[s[0]:s[1]])]
    print(f"  tasks: {len(spans)} total · {len(move)} done/closed to stub")

    items = [(n, "".join(lines[i:j])) for i, j, n, _, _ in move]
    files = chunk(items, "closed")
    where = {n: f for f in files for n, _ in files[f]}

    stubs: dict[int, str] = {}
    for i, j, name, form, st in move:
        body = "".join(lines[i:j])
        ptr = f"docs/sessions/tasks_closed/{where[name]}.vsm"
        if form == "A":
            title = (re.search(r'^\s+title\s*=\s*"([^"]*)"', body, re.M) or [None, ""])[1]
            date = (re.search(r'^\s+date\s*=\s*"([^"]*)"', body, re.M) or [None, ""])[1]
            stubs[i] = (f"task({name}):\n"
                        f'  title    = "{title}"\n'
                        f"  status   = {st}\n"
                        + (f'  date     = "{date}"\n' if date else "")
                        + f'  archived = "{ptr}"\n\n')
        elif form == "C":
            # form_C — `task(NAME) = {` (no quotes). Reconstruct the header
            # like form_B (do not copy line i — attrs may wrap), emit the
            # what:/status: tokens so the stub stays readable to every parser.
            # The attr regex: form_C's NAME has NO quotes, so the `[^"]+?` of
            # form_B would eat the whole header — anchor on the name already
            # captured (group(1)) and take attrs up to the closing `)`.
            attrs = (re.search(r'^task\(' + re.escape(name) + r'((?:"[^"]*"|[^)])*)\)', body, re.S) or [None, ""])[1]
            attrs = " ".join(attrs.split())
            what = (re.search(r'^\s*(?:what|title)\s*:\s*"(.*?)"', body, re.S | re.M) or [None, ""])[1]
            what = " ".join(what.split())[:150].replace('"', "'")
            stubs[i] = (f"task({name}{attrs}) = {{\n"
                        f'  what: "{what}",\n'
                        f'  status: {st},\n'
                        f'  archived: "{ptr}",\n'
                        "}\n\n")
        else:
            # RECONSTRUCT the header; do NOT copy lines[i]. A form-B signature may
            # wrap across lines, and copying only the first line produced two
            # stubs with no `) = {` closer at all — invisible to the very parser
            # this script feeds. Found by DS, census 2026-08-10 §2.
            # And EMIT the status: the first version dropped it "because the
            # archive holds the truth", which made 28 stubs unreadable to every
            # parser. Archive-decidable must come from the token, not from the
            # shape of the block (R4).
            # Capture the attribute list up to the REAL `)` that closes the
            # signature. `[^)]*` breaks when a string attr (gate=, blocked_on=)
            # contains parentheses — the signature got cut mid-string, leaving
            # an open quote that unbalanced the whole file (found 2026-08-15,
            # 27/44 stubs corrupt). Match quoted strings atomically.
            attrs = (re.search(r'^task\("[^"]+"((?:"[^"]*"|[^)])*)\)', body, re.S) or [None, ""])[1]
            attrs = " ".join(attrs.split())
            what = (re.search(r'^\s*(?:what|title)\s*:\s*"(.*?)"', body, re.S | re.M) or [None, ""])[1]
            what = " ".join(what.split())[:150].replace('"', "'")
            stubs[i] = (f'task("{name}"{attrs}) = {{\n'
                        f'  what: "{what}",\n'
                        f'  status: {st},\n'
                        f'  archived: "{ptr}",\n'
                        "}\n\n")

    drop = set()
    for i, j, _, _, _ in move:
        drop.update(range(i, j))
    new = []
    for k, l in enumerate(lines):
        if k in stubs:
            new.append(stubs[k])
        if k not in drop:
            new.append(l)
    new_text = "".join(new)

    for f in sorted(files):
        print(f"    {f}.vsm  {len(files[f]):3d} tasks  "
              f"{sum(len(b.encode()) for _, b in files[f])/1024:6.1f} KB")
    print(f"  TASKS.vsm would be {len(new_text.encode())/1024:.1f} KB")

    if not apply:
        return None
    CLOSED_DIR.mkdir(parents=True, exist_ok=True)
    for f, its in files.items():
        head = (f"// Closed-task archive — {f}\n"
                f"// Bodies moved from TASKS.vsm by scripts/state/tasks_archive.py.\n"
                f"// {len(its)} tasks, full text. A one-line stub stays in TASKS.vsm so\n"
                f"// every inbound reference still resolves and the MCP still sees them.\n\n")
        (CLOSED_DIR / f"{f}.vsm").write_text(head + "".join(b for _, b in its), encoding="utf-8")
    return new_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", action="store_true")
    ap.add_argument("--closed", action="store_true")
    ap.add_argument("--keep", type=int, default=1,
                    help="trailing months of session blocks kept live (default 1)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.sessions or args.closed):
        sys.exit("pick --sessions and/or --closed")

    text = TASKS.read_text(encoding="utf-8")
    before = len(text.encode())
    print(f"  TASKS.vsm now: {before/1024:.1f} KB")

    if args.sessions:
        out = do_sessions(text, args.keep, args.apply)
        if out is not None:
            TASKS.write_text(out, encoding="utf-8")
            print(f"  ✓ TASKS.vsm now {len(out.encode())/1024:.1f} KB")

    if args.closed:
        text = TASKS.read_text(encoding="utf-8")
        out = do_closed(text, args.apply)
        if out is not None:
            TASKS.write_text(out, encoding="utf-8")
            print(f"  ✓ TASKS.vsm now {len(out.encode())/1024:.1f} KB")

    if not args.apply:
        print("\n  dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
