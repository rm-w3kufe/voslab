"""regulation.py — Regulation layer for invariant monitoring.

Monitors system invariants at runtime and triggers responses
when invariants are violated.

Architecture:
  Invariant → RegulationLayer → monitor() → InvariantResult
                                          → response (if violated)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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


class RegulationLayer:
    """Monitors invariants and triggers responses.

    Usage:
        layer = RegulationLayer()
        layer.register(Invariant(
            name="trust_bounds",
            description="S5 trust must be >= 0.3",
            check=lambda: get_trust() >= 0.3,
            severity="HIGH",
        ))
        results = layer.monitor()
        for r in results:
            if r.status != InvariantStatus.HEALTHY:
                print(f"ALERT: {r.name} — {r.message}")
    """

    def __init__(self):
        self._invariants: list[Invariant] = []
        self._history: list[list[InvariantResult]] = []

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
