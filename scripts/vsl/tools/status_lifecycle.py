#!/usr/bin/env python3
"""status_lifecycle.py — Executable status lifecycle (F1 verification).

Implements prop_status_lifecycle: delta(status, event) as a total,
computable function. Forbidden transitions map to nothing (None).

  proposed --approve--> active --ratify--> ratified
      |                     |                    |
      |                     +--deprecate--> archived <--supersede--+
      +-- (no direct edges elsewhere)

Also validates a .vsm file's @status value (SR-1 assist).

Usage:
  status_lifecycle.py check-file <doc.vsm>   # rc=0 valid status
  status_lifecycle.py allowed <status> <event>  # prints target or NONE
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

STATES = ("proposed", "active", "ratified", "archived",
          # Non-transitional working states (scan 2026-09-10: real usage in
          # system/): templates and theoretical conjectures are governed
          # artifacts with fixed status — no delta edges leave them.
          "template", "conjecture")

_DELTA = {
    ("proposed", "approve"): "active",
    ("active", "ratify"): "ratified",
    ("active", "deprecate"): "archived",
    ("ratified", "supersede"): "archived",
}


def delta(status: str, event: str) -> str | None:
    """Next status or None if the transition is forbidden."""
    return _DELTA.get((status, event))


def read_status(path: Path) -> str | None:
    m = re.search(r"^@status\s+(\w+)", path.read_text(encoding="utf-8"),
                  re.M)
    return m.group(1) if m else None


def scan(root: Path):
    """Walk system/ reporting per-file status conformity (read-only).

    Returns (rows, violations): rows = [(relpath, status)], violations =
    files with missing/invalid @status or failing header check.
    The lifecycle instrument: what cannot be scanned cannot be governed.
    """
    import subprocess
    rows, violations = [], []
    for path in sorted(root.rglob("*.vsm")):
        rel = str(path.relative_to(root))
        st = read_status(path)
        if st not in STATES:
            violations.append((rel, f"bad-status:{st}"))
            rows.append((rel, st or "MISSING"))
        else:
            rows.append((rel, st))
    return rows, violations


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "allowed" and len(argv) == 3:
        nxt = delta(argv[1], argv[2])
        print(nxt if nxt else "NONE")
        return 0 if nxt else 1
    if len(argv) == 2 and argv[0] == "check-file":
        st = read_status(Path(argv[1]))
        if st in STATES:
            print(f"status: {st}")
            return 0
        print(f"invalid/missing @status in {argv[1]}", file=sys.stderr)
        return 1
    if len(argv) >= 1 and argv[0] == "scan":
        root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
        rows, violations = scan(root)
        by_status: dict = {}
        for _, st in rows:
            by_status[st or "MISSING"] = by_status.get(st or "MISSING", 0) + 1
        print(f"scanned={len(rows)} by_status={by_status} "
              f"violations={len(violations)}")
        for rel, why in violations[:20]:
            print(f"  VIOLATION {rel}: {why}")
        return 0 if not violations else 1
    print(__doc__.split("Usage:")[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
