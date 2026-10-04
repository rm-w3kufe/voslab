"""regulation-monitor gate — G-31 (backlog system_backlog.vsm, 2026-10-04).

boot/regulation_layer.vsm (ratified) promises runtime monitoring:
  Invariant -> RegulationLayer -> monitor() -> response.
The framework existed but registered zero invariants and had zero
callers — the promise had no behavior (G-31). This gate closes it:
RegulationLayer() now registers the Ax_S5CautionVeto fail-safe
(caution mode must not outlive its expiry) and the gate refuses a
workspace whose caution state is a phantom veto.

Contract:
  - check(path): run the default layer; "" -> live workspace state DB.
    A path to a *.db fixture is used as the state DB instead
    (negative control). exit 0 = no VIOLATED invariant; 1 = a proven
    phantom veto (monitor() maps check errors to UNKNOWN, which does
    not reject — only real evidence of violation fails).
  - negative_case(): a temp state.db with caution_mode=true and an
    expiry in the past — must ALWAYS be rejected (exit != 0).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from gate_suite.harness import register

# framework root (packages/framework) — vos_kernel lives beside gate_suite
_FRAMEWORK = Path(__file__).resolve().parents[2]


def _run_layer(db_path: str | None) -> int:
    if str(_FRAMEWORK) not in sys.path:
        sys.path.insert(0, str(_FRAMEWORK))
    from vos_kernel.regulation import RegulationLayer, InvariantStatus

    saved = os.environ.get("VSF_STATE_DB")
    if db_path:
        os.environ["VSF_STATE_DB"] = db_path
    try:
        layer = RegulationLayer()
        if not layer._invariants:
            sys.stderr.write(
                "regulation-monitor: no invariants registered (G-31 regression)\n"
            )
            return 1
        results = layer.monitor()
    finally:
        if db_path:
            if saved is None:
                os.environ.pop("VSF_STATE_DB", None)
            else:
                os.environ["VSF_STATE_DB"] = saved
    violated = [r for r in results if r.status == InvariantStatus.VIOLATED]
    for r in results:
        sys.stderr.write(
            f"regulation-monitor: {r.status.value} {r.name} — {r.message}\n"
        )
    return 1 if violated else 0


def check(path: str) -> int:
    """0 = default regulation layer reports no violated invariant.

    Empty path = live workspace state DB (absent DB holds: no phantom
    veto can exist without state). A .db path is a fixture.
    """
    if path:
        if not os.path.exists(path):
            sys.stderr.write(f"regulation-monitor: no such state db {path}\n")
            return 1
        return _run_layer(path)
    return _run_layer(None)


def negative_case() -> str:
    """Phantom caution: mode=true, expiry long past — must be rejected."""
    fd, p = tempfile.mkstemp(prefix="regulation_monitor.", suffix=".db",
                             dir=tempfile.gettempdir())
    os.close(fd)
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE s5_policy(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_mode', 'true')")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_expires', '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()
    return p


register("regulation-monitor", check, negative_case)
