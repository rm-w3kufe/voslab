#!/usr/bin/env python3
"""viability_check.py — Omega(RSI-vOSlab) measurement CLI (thin wrapper).

Core lives in system/kernel/vsm_viability.py (importable + tested).
This CLI adds the drill run for the accuracy dim and prints the verdict.

Usage: viability_check.py [--json]
Exit codes: 0 inside Omega, 1 degraded input, 2 CAUTION.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOSLAB / "system" / "kernel"))

from vsm_viability import degraded_mode, measure, write_mode  # noqa: E402


def _cert_results():
    p = subprocess.run(
        [sys.executable, "scripts/vsl/tools/autonomy_cert.py", "--json"],
        capture_output=True, text=True, timeout=180, cwd=str(VOSLAB))
    if p.returncode not in (0, 1):
        return None
    try:
        out = json.loads(p.stdout.strip())
        return out if isinstance(out, list) else None
    except Exception:
        return None


def main(argv: list[str]) -> int:
    m = measure(cert_results=_cert_results())
    if "--write-mode" in argv:
        # Persist the ladder mode from the measured margin. Contracting
        # is automatic; EXPANDING back requires human clear (asymmetry):
        # only write when strictly more restrictive than stored.
        from vsm_viability import read_mode
        order = ["nominal", "shed", "quiesce", "halt"]
        mode = degraded_mode(m["margin"], caution_active=False)
        current = read_mode()
        if order.index(mode) > order.index(current):
            write_mode(mode)
            m["mode_written"] = mode
        else:
            m["mode_written"] = current + " (kept; expansion needs human)"
    if "--json" in argv:
        print(json.dumps(m, indent=2))
    else:
        d = m["dims"]
        print(f"Omega(RSI): accuracy={d['accuracy']} | drift={d['drift']} | "
              f"stability={d['stability']} | margin={m['margin']} -> "
              f"{'VIABLE' if m['inside'] else 'CAUTION'} "
              f"[{m['series_points']} points]")
    if d["accuracy"] is None:
        return 1
    return 0 if m["inside"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
