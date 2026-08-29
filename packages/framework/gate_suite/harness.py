"""Negative-control harness for gate-suite.

The defect we found in vsf's `checks/plugin-location-valid` was a BROKEN
negative control: it could not discriminate a violating artifact from a valid
one, so the gate was effectively a no-op. This harness makes that impossible
to ship unnoticed.

Each gate registers:
  - name:           unique gate id
  - check(path):    runs the gate on an artifact; returns 0 if ACCEPTED,
                    nonzero if REJECTED
  - negative_case:  builds an artifact the gate MUST reject, returns its path

`run_negative_controls()` proves every gate is NECESSARY: it feeds each gate
its own negative case and asserts the gate REJECTS it. If a gate accepts its
negative case (exit 0), the harness fails — exactly catching the vsf defect.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass


@dataclass
class Gate:
    name: str
    check: "callable[[str], int]"          # path -> exit code (0 accept, !=0 reject)
    negative_case: "callable[[], str]"     # () -> path to artifact that MUST be rejected


GATES: list[Gate] = []


def register(name: str, check, negative_case) -> None:
    """Register a gate with its negative-control case."""
    GATES.append(Gate(name, check, negative_case))


def _cleanup(path: str) -> None:
    if path.startswith(tempfile.gettempdir()):
        try:
            os.remove(path)
        except OSError:
            pass


def run_negative_controls() -> int:
    """Return 0 if ALL gates reject their negative cases; else 1.

    A nonzero return means at least one gate is a no-op (broken negative
    control) and must not ship.
    """
    failed: list[str] = []
    for g in GATES:
        path = g.negative_case()
        rc = g.check(path)
        _cleanup(path)
        if rc == 0:
            failed.append(g.name)
    if failed:
        print(
            "NEGATIVE CONTROL FAIL — gates that do NOT catch their own "
            f"negative case (no-op defect): {failed}"
        )
        return 1
    print(f"NEGATIVE CONTROL PASS — {len(GATES)} gates verified necessary")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_negative_controls())
