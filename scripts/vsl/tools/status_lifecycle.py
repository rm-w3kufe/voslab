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

STATES = ("proposed", "active", "ratified", "archived")

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
    print(__doc__.split("Usage:")[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
