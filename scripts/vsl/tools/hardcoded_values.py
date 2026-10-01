#!/usr/bin/env python3
"""hardcoded_values.py — Generic hardcoded-value scan (self_maintaining).

Scope (S5 2026-09-10): timestamps + versions + absolute paths.
Explicitly OUT of scope: secrets (never hunted, never logged).
Privacy rule: report file:line:KIND only — matched VALUES never printed.

Checks:
  T  hardcoded timestamp shapes (canonical is_hardcoded_timestamp)
  V  stale protocol versions (@vsm / header not at 1.2.1)
  P  absolute /home/ paths baked into code (Path.home()/env preferred)

Usage:
  hardcoded_values.py [root]          # report to stdout, rc=0 always
  hardcoded_values.py --gate [root]   # rc=1 if any finding (gate mode)

Exit codes: 0 clean (or report mode), 1 gate findings, 2 usage error.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]


def _load_kernel():
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))
    try:
        from vos_kernel.utils import vsm_kernel
        return vsm_kernel
    finally:
        pass


_VSMK = _load_kernel()

_VERSION_RE = re.compile(r"@vsm\s+([\d.]+)|vsm-([\d.]+)")
_HOME_RE = re.compile(r"""["'](/home/[A-Za-z0-9_][^"'`\s]*)["']""")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist"}
_SKIP_FILES = {"health_history.jsonl", "agent_plugin.jsonl",
               "doc_manifest.jsonl", "current_focus.json"}  # living state docs
# Paths that are data/history by nature, plus test trees (matrices assert
# on hardcoded shapes BY DESIGN — scanning them is noise, not signal).
# system/state/ — signed/runtime artifacts (attestations): timestamps are
# code-emitted (D-09 verified 2026-10-01) and the files are signed —
# editing them for a marker would break the signature.
_SKIP_PATHS = ("docs/archive", "state/", "system/state/")
_SKIP_COMPONENTS = {"tests"}
# Inline marker: documenting a shape is not hardcoding it.
_ALLOW_MARK = "hardcoded-allow"


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                       and not d.startswith(".")]
        for f in filenames:
            if f in _SKIP_FILES:
                continue
            if f.startswith("test_"):
                continue  # matrices assert on shapes by design
            if f.endswith((".py", ".ts", ".js", ".sh", ".vsm", ".json")):
                p = Path(dirpath) / f
                rel = str(p.relative_to(root))
                if rel.startswith(_SKIP_PATHS):
                    continue
                if _SKIP_COMPONENTS & set(Path(rel).parts):
                    continue
                yield p


def scan(root: Path) -> list[tuple]:
    """Return [(relpath, lineno, kind)] — never values."""
    hits = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except Exception:
            continue
        rel = str(path.relative_to(root))
        for i, line in enumerate(text.splitlines(), 1):
            if _ALLOW_MARK in line:
                continue
            if _VSMK.is_hardcoded_timestamp(line) is not None:
                hits.append((rel, i, "T"))
        if path.suffix == ".vsm":
            m = re.search(r"@vsm\s+([\d.]+)", text)
            h = re.search(r"vsm-([\d.]+)", text)
            if (m and m.group(1) != "1.2.1") or (h and h.group(1) != "1.2.1"):
                hits.append((rel, 1, "V"))
        if path.suffix in (".py", ".ts", ".js", ".sh"):
            for i, line in enumerate(text.splitlines(), 1):
                if _HOME_RE.search(line):
                    hits.append((rel, i, "P"))
    return hits


def main(argv: list[str]) -> int:
    gate = "--gate" in argv
    rest = [a for a in argv if not a.startswith("-")]
    root = Path(rest[0]).resolve() if rest else VOSLAB
    if not root.is_dir():
        print("usage: hardcoded_values.py [--gate] [root]", file=sys.stderr)
        return 2
    hits = scan(root)
    for rel, lineno, kind in hits:
        print(f"{rel}:{lineno} [{kind}]")
    print(f"findings: {len(hits)} files-scanned-scope (T/V/P kinds only, "
          f"values never printed)")
    if gate:
        return 1 if hits else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
