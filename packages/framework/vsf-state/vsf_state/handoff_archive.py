#!/usr/bin/env python3
"""Split HANDOFF.vsm.md by month so the live file stays readable in one pass.

Why this exists (2026-08-10 boot audit): HANDOFF.vsm.md had grown to 755 KB /
169 session blocks / 11 433 lines. The agent's Read tool caps at 256 KB, so the
primary continuity document could NOT be read whole — every consultation was a
partial read, and reasoning from truncated reads produced two false findings in
a single session. Mass is a correctness problem here, not a tidiness one.

Rule: the live file keeps the header plus the CURRENT and PREVIOUS month.
Everything older moves to docs/sessions/handoff/<YYYY-MM>.vsm.md, one file per
month, full text preserved. Nothing is deleted, nothing is summarised — a
grep or a targeted Read still finds every word. (Today's session needed a field
from a *closed* task to correct an error; compressing history away would have
destroyed exactly that. Archive, never compress.)

Usage:
    python3 scripts/state/handoff_archive.py            # dry run, prints the plan
    python3 scripts/state/handoff_archive.py --apply
    python3 scripts/state/handoff_archive.py --keep 3 --apply   # keep 3 months
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "HANDOFF.vsm.md"
ARCHIVE_DIR = ROOT / "docs/sessions/handoff"
BLOCK_RE = re.compile(r"^session\(", re.M)
NAME_RE = re.compile(r'session\("?([^")]*)"?')
READ_LIMIT_KB = 256


def split_blocks(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """-> (header, [(month, name, body), ...]) preserving byte-exact bodies."""
    starts = [m.start() for m in BLOCK_RE.finditer(text)]
    if not starts:
        sys.exit("no session() blocks found — refusing to touch the file")
    header = text[: starts[0]]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        body = text[s:e]
        name = NAME_RE.match(body).group(1)
        m = re.match(r"(\d{4}-\d{2})", name)
        out.append((m.group(1) if m else "undated", name, body))
    return header, out


def archive_handoffs(live_path=None, archive_dir=None, keep: int = 2,
                     apply: bool = False) -> dict:
    """Archive old handoff months out of the live file (facade).

    Extracted from main() without behavior change: same split, same
    conservation accounting, same chunking. Paths default to the module
    LIVE/ARCHIVE_DIR constants; override for tests. dry-run (default)
    writes nothing. Returns stats dict; raises ValueError on accounting
    failure (main() converts to sys.exit).
    """
    from pathlib import Path as _Path
    live_p = _Path(live_path) if live_path else LIVE
    arch_d = _Path(archive_dir) if archive_dir else ARCHIVE_DIR

    original = live_p.read_text(encoding="utf-8")
    header, blocks = split_blocks(original)

    months = sorted({m for m, _, _ in blocks if m != "undated"})
    keep_months = set(months[-keep:]) | {"undated"}
    live = [b for b in blocks if b[0] in keep_months]
    arch = [b for b in blocks if b[0] not in keep_months]

    if len(live) + len(arch) != len(blocks):
        raise ValueError("block accounting failed — aborting")

    by_month: dict[str, list] = {}
    for m, n, b in arch:
        by_month.setdefault(m, []).append((n, b))

    files: dict[str, list] = {}
    for m in sorted(by_month):
        items, part, acc = by_month[m], [], 0
        for name, body in items:
            b = len(body.encode())
            if acc + b > READ_LIMIT_KB * 1024 * 0.85 and part:
                files[f"{m}-{chr(97 + len([k for k in files if k.startswith(m)])) }"] = part
                part, acc = [], 0
            part.append((name, body)); acc += b
        if part:
            suffix = "" if not any(k.startswith(m) for k in files) else \
                     f"-{chr(97 + len([k for k in files if k.startswith(m)]))}"
            files[f"{m}{suffix}"] = part

    new_live = header.rstrip("\n") + "\n"
    index = ["", "## Archived sessions", "",
             f"Split by archive_handoffs — the live file keeps the last "
             f"{keep} months so it stays under the {READ_LIMIT_KB} KB read limit.",
             "Full text, nothing summarised. Every file below is itself under the limit,",
             "so any of them can be read in one pass. Grep them like any other file.", ""]
    for f in sorted(files):
        index.append(f"- `{f}.vsm.md` — {len(files[f])} blocks")
    index.append("")
    new_live += "\n".join(index) + "\n" + "".join(b for _, _, b in live)
    if not apply:
        return {"live_blocks": len(live), "archived_blocks": len(arch),
                "archive_files": sorted(files),
                "months_kept": sorted(keep_months - {"undated"}),
                "applied": False}

    arch_d.mkdir(parents=True, exist_ok=True)
    for f, items in files.items():
        head = (f"# HANDOFF archive — {f}\n\n"
                f"{len(items)} session blocks, full text, byte-identical.\n\n")
        (arch_d / f"{f}.vsm.md").write_text(
            head + "".join(b for _, b in items), encoding="utf-8")
    live_p.write_text(new_live, encoding="utf-8")

    total = sum(len(v) for v in files.values()) + len(live)
    if total != len(blocks):
        raise ValueError("post-write accounting failed")
    return {"live_blocks": len(live), "archived_blocks": len(arch),
            "archive_files": sorted(files),
            "months_kept": sorted(keep_months - {"undated"}),
            "applied": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=2,
                    help="how many trailing months stay live (default 2)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    original = LIVE.read_text(encoding="utf-8")
    header, blocks = split_blocks(original)

    months = sorted({m for m, _, _ in blocks if m != "undated"})
    keep_months = set(months[-args.keep:]) | {"undated"}
    live = [b for b in blocks if b[0] in keep_months]
    arch = [b for b in blocks if b[0] not in keep_months]

    # conservation check BEFORE writing anything
    if len(live) + len(arch) != len(blocks):
        sys.exit("block accounting failed — aborting")

    by_month: dict[str, list] = {}
    for m, n, b in arch:
        by_month.setdefault(m, []).append((n, b))

    # A month can itself exceed the read limit (2026-06 held 97 blocks / 374 KB).
    # An archive nobody can Read whole reproduces the defect this script exists to
    # remove, one directory down. Chunk oversized months into -a, -b, … parts.
    files: dict[str, list] = {}
    for m in sorted(by_month):
        items, part, acc = by_month[m], [], 0
        for name, body in items:
            b = len(body.encode())
            if acc + b > READ_LIMIT_KB * 1024 * 0.85 and part:
                files[f"{m}-{chr(97 + len(
                    [k for k in files if k.startswith(m)])) }"] = part
                part, acc = [], 0
            part.append((name, body)); acc += b
        if part:
            suffix = "" if not any(k.startswith(m) for k in files) else \
                     f"-{chr(97 + len([k for k in files if k.startswith(m)]))}"
            files[f"{m}{suffix}"] = part

    index = ["", "## Archived sessions", "",
             f"Split by `scripts/state/handoff_archive.py` — the live file keeps the last "
             f"{args.keep} months so it stays under the {READ_LIMIT_KB} KB read limit.",
             "Full text, nothing summarised. Every file below is itself under the limit,",
             "so any of them can be read in one pass. Grep them like any other file.", ""]
    for f in sorted(files):
        index.append(f"- `docs/sessions/handoff/{f}.vsm.md` — {len(files[f])} blocks")
    index.append("")

    new_live = header.rstrip("\n") + "\n" + "\n".join(index) + "\n" + "".join(b for _, _, b in live)

    kb = lambda s: len(s.encode()) / 1024
    print(f"  live now : {kb(original):7.1f} KB  {len(blocks)} blocks")
    print(f"  live after: {kb(new_live):7.1f} KB  {len(live)} blocks  (months {sorted(keep_months - {'undated'})})")
    for m in sorted(by_month):
        print(f"    archive  {m}: {len(by_month[m]):3d} blocks")
    if kb(new_live) > READ_LIMIT_KB:
        print(f"  ⚠ still over {READ_LIMIT_KB} KB — rerun with a smaller --keep")

    if not args.apply:
        print("\n  dry run — pass --apply to write")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for f, items in files.items():
        head = (f"# HANDOFF archive — {f}\n\n"
                f"Archived from `HANDOFF.vsm.md` by `scripts/state/handoff_archive.py`.\n"
                f"{len(items)} session blocks, full text, byte-identical to the original.\n"
                f"The live HANDOFF keeps only recent months; this is where the rest lives.\n\n")
        (ARCHIVE_DIR / f"{f}.vsm.md").write_text(head + "".join(b for _, b in items), encoding="utf-8")

    LIVE.write_text(new_live, encoding="utf-8")

    # verify round-trip: every archived block is findable, live count matches
    total = sum(len(v) for v in files.values()) + len(live)
    assert total == len(blocks), "post-write accounting failed"
    print(f"\n  ✓ written · {len(by_month)} archive files · {total} blocks accounted for")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
