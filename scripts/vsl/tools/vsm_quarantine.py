#!/usr/bin/env python3
"""vsm_quarantine.py — Pre-write snapshots + restore for .vsm enforcement.

Closes HOOK-FAILOPEN-001: the write-time daemon runs AFTER the write, so
a bare block report neverReverts anything. With a pre-write snapshot, a
blocking gate can RESTORE the previous content (or quarantine a newly
created file) instead of merely complaining.

Safety rules (never violated):
  - RESTORE only writes back content captured by `stash` (no invention).
  - New files are NEVER deleted: `quarantine` MOVES them to state/.
  - Runner errors (gate crashed) must NOT trigger restore — only a gate
    verdict with a cause marker ([DEMONIO ...] / R18-BLOCK). The caller
    (vsl-check-on-write.ts) enforces that distinction, not this script.

Token = sha256(abspath)[:16]: deterministic, so the before-hook (stash)
and the after-hook (restore) rendezvous without shared memory.

Usage:
  vsm_quarantine.py stash <file.vsm>       # snapshot -> prints token
  vsm_quarantine.py restore <token>        # write back stashed content
  vsm_quarantine.py quarantine <file.vsm>  # move new file to state/
  vsm_quarantine.py list                   # show quarantine dir

Exit codes: 0 ok (+ token/path on stdout), 1 usage/IO error,
2 refused (restore without stash, quarantine of missing file).
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _qdir() -> Path:
    import os as _os
    env = _os.environ.get("VSM_QUARANTINE_DIR")
    return Path(env) if env else ROOT / "state" / "quarantine"


QDIR = _qdir()


def _token(path: str) -> str:
    abspath = str(Path(path).resolve())
    return hashlib.sha256(abspath.encode()).hexdigest()[:16]


def cmd_stash(path: str) -> int:
    p = Path(path)
    QDIR = _qdir()
    QDIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "path": str(p.resolve()),
        "existed": p.is_file(),
        "content_b64": (base64.b64encode(p.read_bytes()).decode()
                        if p.is_file() else None),
        "stashed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if p.is_file():
            p.read_bytes()  # readability probe before claiming success
    except OSError as e:
        print(f"vsm_quarantine: cannot read {path}: {e}", file=sys.stderr)
        return 1
    tok = _token(path)
    (QDIR / f"{tok}.json").write_text(json.dumps(entry))
    print(tok)
    return 0


def cmd_restore(token: str) -> int:
    snap_file = _qdir() / f"{token}.json"
    if not snap_file.is_file():
        print(f"vsm_quarantine: no stash for token {token} (refused)",
              file=sys.stderr)
        return 2
    entry = json.loads(snap_file.read_text())
    if not entry.get("existed"):
        print("vsm_quarantine: stashed as NEW file — use quarantine, "
              "not restore (refused)", file=sys.stderr)
        return 2
    Path(entry["path"]).write_bytes(base64.b64decode(entry["content_b64"]))
    print(f"vsm_quarantine: restored {entry['path']}")
    return 0


def cmd_quarantine(path: str) -> int:
    p = Path(path)
    if not p.is_file():
        print(f"vsm_quarantine: nothing to quarantine at {path}",
              file=sys.stderr)
        return 2
    QDIR = _qdir()
    QDIR.mkdir(parents=True, exist_ok=True)
    dest = QDIR / f"{p.stem}.{int(time.time())}.vsm"
    p.rename(dest)
    print(str(dest))
    return 0


def cmd_list() -> int:
    QDIR = _qdir()
    if not QDIR.exists():
        print("quarantine: empty")
        return 0
    for f in sorted(QDIR.glob("*")):
        print(f.name)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in (
            "stash", "restore", "quarantine", "list"):
        print(__doc__.split("Usage:")[1].split("Exit codes:")[0].strip(),
              file=sys.stderr)
        return 1
    if argv[0] == "list":
        return cmd_list()
    if len(argv) < 2:
        print(f"usage: vsm_quarantine.py {argv[0]} <arg>", file=sys.stderr)
        return 1
    return {"stash": cmd_stash, "restore": cmd_restore,
            "quarantine": cmd_quarantine}[argv[0]](argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
