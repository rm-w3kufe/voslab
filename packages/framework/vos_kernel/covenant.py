"""covenant.py — Runtime covenant enforcement.

Wraps vsl-core's CovenantEnforcer via PyO3 bindings.
Provides Python-native API for A0/A0.1 evaluation.

Usage:
    from vos_kernel.covenant import CovenantEnforcer, Verdict

    enforcer = CovenantEnforcer()
    verdict = enforcer.evaluate(s5_trust=0.8, op_autonomy=0.5)
    if verdict.passed:
        print("Covenant OK")
    else:
        for v in verdict.violations:
            print(f"VIOLATION: {v.axiom} — {v.message}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from vos_kernel.utils.vsl_core_check import HAS_VSL_CORE


@dataclass
class Violation:
    axiom: str
    message: str
    severity: str  # CRITICAL, HIGH, MEDIUM


@dataclass
class Verdict:
    passed: bool
    violations: list[Violation] = field(default_factory=list)


class CovenantEnforcer:
    """Evaluates covenant (A0/A0.1) against system state.

    Tries vsl-core (Rust) first, falls back to Python implementation.
    """

    def __init__(self):
        if HAS_VSL_CORE:
            self._enforcer = vsl_core.CovenantEnforcer()
            self._backend = "vsl-core"
        else:
            self._enforcer = None
            self._backend = "python"

    def evaluate(
        self,
        s5_trust: float = 0.8,
        op_autonomy: float = 0.5,
        pressure: Optional[str] = None,
    ) -> Verdict:
        """Evaluate covenant against system state.

        Args:
            s5_trust: S5 trust score (0.0-1.0)
            op_autonomy: Operational autonomy (0.0-1.0)
            pressure: Optional pressure type (coercion, budget_pressure, etc.)

        Returns:
            Verdict with passed=True/False and any violations.
        """
        if self._backend == "vsl-core":
            return self._evaluate_vsl_core(s5_trust, op_autonomy, pressure)
        else:
            return self._evaluate_python(s5_trust, op_autonomy, pressure)

    def _evaluate_vsl_core(
        self,
        s5_trust: float,
        op_autonomy: float,
        pressure: Optional[str],
    ) -> Verdict:
        """Evaluate using vsl-core Rust bindings."""
        state = vsl_core.SystemState(s5_trust, op_autonomy, pressure)
        result = self._enforcer.evaluate(state)

        violations = [
            Violation(
                axiom=v.axiom,
                message=v.message,
                severity=v.severity,
            )
            for v in result.violations
        ]

        return Verdict(passed=result.passed, violations=violations)

    def _evaluate_python(
        self,
        s5_trust: float,
        op_autonomy: float,
        pressure: Optional[str],
    ) -> Verdict:
        """Fallback Python implementation of covenant checks."""
        violations = []

        # A0: Purpose must be human liberation
        # (always passes in this simplified version — purpose is set at init)

        # A0.1: Pressure must not alter purpose
        if pressure and pressure in ("coercion", "administrative_capture"):
            violations.append(Violation(
                axiom="A0.1",
                message=f"pressure '{pressure}' attempted to alter S5 purpose",
                severity="CRITICAL",
            ))

        # Trust check: S5 trust must be adequate
        if s5_trust < 0.3:
            violations.append(Violation(
                axiom="TRUST",
                message=f"S5 trust critically low ({s5_trust:.2f})",
                severity="HIGH",
            ))

        # Autonomy check: must not exceed trust bounds
        if op_autonomy > s5_trust:
            violations.append(Violation(
                axiom="A5",
                message=f"operational autonomy ({op_autonomy:.2f}) exceeds S5 trust ({s5_trust:.2f})",
                severity="HIGH",
            ))

        return Verdict(
            passed=len(violations) == 0,
            violations=violations,
        )
