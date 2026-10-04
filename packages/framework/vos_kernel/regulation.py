"""regulation.py — Regulation layer for invariant monitoring.

Monitors system invariants at runtime and triggers responses
when invariants are violated.

Architecture:
  Invariant → RegulationLayer → monitor() → InvariantResult
                                          → response (if violated)

Default invariants implement what boot/regulation_layer.vsm declares
(Ax_S5CautionVeto fail-safe: caution mode must never outlive its
expiry — a phantom veto would suspend S3 decisions indefinitely).
G-31 closed 2026-10-04: RegulationLayer() previously registered zero
invariants, so the boot doc's monitoring promise had no behavior.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional


class InvariantStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    VIOLATED = "violated"
    UNKNOWN = "unknown"


@dataclass
class Invariant:
    name: str
    description: str
    check: Callable[[], bool]  # returns True if invariant holds
    severity: str = "HIGH"  # CRITICAL, HIGH, MEDIUM, LOW
    auto_halt: bool = False  # if True, halt operations on violation


@dataclass
class InvariantResult:
    name: str
    status: InvariantStatus
    message: str
    details: dict = field(default_factory=dict)


def caution_state_db() -> str:
    """Path of the s5_policy state DB (VSF_STATE_DB override for fixtures)."""
    return os.environ.get("VSF_STATE_DB", "/var/lib/vsf-state/state.db")


def check_caution_expiry(db_path: Optional[str] = None) -> bool:
    """Ax_S5CautionVeto fail-safe (boot/regulation_layer.vsm).

    Returns True (holds) when no phantom veto is possible:
      - absent DB or inactive mode -> nothing to veto
      - active within its expiry   -> legitimate caution window
    Returns False when caution is active past its expiry (phantom —
    would suppress S3 decisions with no clock to clear it) or active
    with no expiry set (cannot auto-clear).
    """
    path = db_path or caution_state_db()
    if not os.path.exists(path):
        return True
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT value FROM s5_policy WHERE key='s5.caution_mode'"
        ).fetchone()
        if not row or row[0] != "true":
            return True
        exp = conn.execute(
            "SELECT value FROM s5_policy WHERE key='s5.caution_expires'"
        ).fetchone()
        if not exp or not exp[0]:
            return False  # active with no expiry: no auto-clear possible
        expires = datetime.fromisoformat(exp[0].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) <= expires
    finally:
        conn.close()


def default_invariants() -> list[Invariant]:
    """Invariants declared by boot/regulation_layer.vsm (ratified).

    G-31: these are what RegulationLayer() registers by default — the
    boot doc's monitoring promise as executable checks.
    """
    return [
        Invariant(
            name="caution_mode_expiry",
            description=(
                "s5.caution_mode must not outlive s5.caution_expires "
                "(Ax_S5CautionVeto, CAUTION_DURATION_S=1800)"
            ),
            check=check_caution_expiry,
            severity="HIGH",
            auto_halt=False,
        ),
    ]


class RegulationLayer:
    """Monitors invariants and triggers responses.

    Usage:
        layer = RegulationLayer()          # registers default invariants
        results = layer.monitor()
        for r in results:
            if r.status != InvariantStatus.HEALTHY:
                print(f"ALERT: {r.name} — {r.message}")

    Extra invariants register the same way (R10: check must be a
    deterministic callable — same input, same result).
    """

    def __init__(self, register_defaults: bool = True):
        self._invariants: list[Invariant] = []
        self._history: list[list[InvariantResult]] = []
        if register_defaults:
            for inv in default_invariants():
                self._invariants.append(inv)

    def register(self, invariant: Invariant) -> None:
        """Register an invariant for monitoring."""
        self._invariants.append(invariant)

    def monitor(self) -> list[InvariantResult]:
        """Check all registered invariants.

        Returns:
            List of InvariantResult for each invariant.
        """
        results = []
        for inv in self._invariants:
            try:
                holds = inv.check()
                status = InvariantStatus.HEALTHY if holds else InvariantStatus.VIOLATED
                message = "invariant holds" if holds else f"invariant violated: {inv.description}"
            except Exception as e:
                status = InvariantStatus.UNKNOWN
                message = f"check failed: {e}"

            results.append(InvariantResult(
                name=inv.name,
                status=status,
                message=message,
                details={"severity": inv.severity, "auto_halt": inv.auto_halt},
            ))

        self._history.append(results)
        return results

    def get_history(self) -> list[list[InvariantResult]]:
        """Get monitoring history."""
        return self._history

    def get_violations(self) -> list[InvariantResult]:
        """Get only violated invariants from last check."""
        if not self._history:
            return []
        return [r for r in self._history[-1] if r.status == InvariantStatus.VIOLATED]

    def should_halt(self) -> bool:
        """Check if any invariant with auto_halt=True is violated."""
        if not self._history:
            return False
        for r in self._history[-1]:
            if r.status == InvariantStatus.VIOLATED and r.details.get("auto_halt"):
                return True
        return False
