#!/usr/bin/env python3
"""check_nats_connect.py — repo check: no raw nats.connect(literal_url) in the codebase.

NATS-SHARED-HELPER mandate (docs/spec/nats_auth_remediation/spec.vsm §systemic):
  - Rust:  vsf_agent::nats::connect  (mandate; no raw async_nats::connect(url))
  - Python: vsf_nats.connect()       (mandate; no raw nats.connect(hardcoded_url))

A future auth change must touch ONE place. Raw literal connects silently
bypass the token and recreate the auth-muted failure class (2026-07-11).

Exit 0 = clean, 1 = violations found (with file:line listing).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root

# nats.connect("<literal>") — a string literal (not a variable like NATS_URL)
# Allowed exception: localhost one-off audit scripts may connect locally.
PATTERN = re.compile(r"nats\.connect\(\s*['\"]")


def main() -> int:
    violations = []
    for py in ROOT.rglob("*.py"):
        if ".git" in py.parts or "node_modules" in py.parts or "worktrees" in py.parts:
            continue
        for i, line in enumerate(py.read_text(errors="ignore").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):  # comment — not a connect call
                continue
            if PATTERN.search(line):
                # localhost literal is a local broker, not a bypass of remote auth
                if "localhost" in line or "127.0.0.1" in line:
                    continue
                violations.append(f"{py.relative_to(ROOT)}:{i}: {line.strip()}")

    if violations:
        print(f"[check_nats_connect] {len(violations)} raw literal NATS connect(s):")
        for v in violations:
            print(f"  {v}")
        print("[check_nats_connect] FAIL — use vsf_nats.connect() (reads NATS_URL from env)")
        return 1
    print("[check_nats_connect] OK — no raw literal NATS connect (all use vsf_nats or env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
