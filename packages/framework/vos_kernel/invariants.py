"""invariants.py — Invariant checking for pre/post conditions.

Provides declarative invariant checking for operations:
  - Pre-conditions: must hold before action
  - Post-conditions: must hold after action
  - Invariants: must hold throughout

Usage:
    from vos_kernel.invariants import InvariantChecker, CheckResult

    checker = InvariantChecker()
    result = checker.check_preconditions(
        action="write",
        file="/home/rmw3/vsf/covenant.vsm",
        trust=0.8,
    )
    if not result.passed:
        print(f"Pre-conditions failed: {result.failures}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class InvariantCheck:
    name: str
    check: Callable[..., bool]
    message: str = ""
    severity: str = "HIGH"


class InvariantChecker:
    """Checks pre/post conditions and invariants for operations.

    Provides built-in checks for common VSF invariants:
      - A0 compliance (no prohibited content)
      - Trust bounds (autonomy <= trust)
      - File criticality (protection of key files)
      - Rate limits (write frequency)
    """

    def __init__(self):
        self._pre_checks: dict[str, list[InvariantCheck]] = {}
        self._post_checks: dict[str, list[InvariantCheck]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default invariant checks."""
        # A0 compliance check
        self.register_pre("write", InvariantCheck(
            name="a0_no_prohibited",
            check=self._check_a0_compliance,
            message="file must not contain prohibited content",
            severity="CRITICAL",
        ))

        # Trust bounds check
        self.register_pre("write", InvariantCheck(
            name="trust_bounds",
            check=self._check_trust_bounds,
            message="operational autonomy must not exceed S5 trust",
            severity="HIGH",
        ))

        # File protection check
        self.register_pre("write", InvariantCheck(
            name="file_protection",
            check=self._check_file_protection,
            message="critical files require explicit approval",
            severity="HIGH",
        ))

    def register_pre(self, action: str, check: InvariantCheck) -> None:
        """Register a pre-condition check for an action."""
        if action not in self._pre_checks:
            self._pre_checks[action] = []
        self._pre_checks[action].append(check)

    def register_post(self, action: str, check: InvariantCheck) -> None:
        """Register a post-condition check for an action."""
        if action not in self._post_checks:
            self._post_checks[action] = []
        self._post_checks[action].append(check)

    def check_preconditions(
        self,
        action: str,
        **kwargs: Any,
    ) -> CheckResult:
        """Check all pre-conditions for an action.

        Args:
            action: action name (write, edit, bash, etc.)
            **kwargs: context for checks (file, trust, content, etc.)

        Returns:
            CheckResult with passed=True/False and any failures.
        """
        checks = self._pre_checks.get(action, [])
        return self._run_checks(checks, **kwargs)

    def check_postconditions(
        self,
        action: str,
        **kwargs: Any,
    ) -> CheckResult:
        """Check all post-conditions for an action."""
        checks = self._post_checks.get(action, [])
        return self._run_checks(checks, **kwargs)

    def _run_checks(
        self,
        checks: list[InvariantCheck],
        **kwargs: Any,
    ) -> CheckResult:
        """Run a list of checks and aggregate results."""
        failures = []
        details = {}

        for check in checks:
            try:
                passed = check.check(**kwargs)
                if not passed:
                    failures.append(f"{check.name}: {check.message}")
                details[check.name] = {
                    "passed": passed,
                    "severity": check.severity,
                }
            except Exception as e:
                failures.append(f"{check.name}: check error: {e}")
                details[check.name] = {
                    "passed": False,
                    "error": str(e),
                    "severity": check.severity,
                }

        return CheckResult(
            passed=len(failures) == 0,
            failures=failures,
            details=details,
        )

    # ─── Built-in Checks ────────────────────────────────────────────────

    def _check_a0_compliance(self, **kwargs) -> bool:
        """Check that file content doesn't contain prohibited keywords."""
        content = kwargs.get("content", "")
        if not content:
            return True  # no content to check

        prohibited = [
            "warfare", "weapon", "surveillance", "oppression",
            "authoritarian", "censorship", "propaganda",
        ]

        content_lower = content.lower()
        for keyword in prohibited:
            if keyword in content_lower:
                return False
        return True

    def _check_trust_bounds(self, **kwargs) -> bool:
        """Check that operational autonomy doesn't exceed S5 trust."""
        trust = kwargs.get("trust", 0.7)
        autonomy = kwargs.get("autonomy", 0.5)
        return autonomy <= trust

    def _check_file_protection(self, **kwargs) -> bool:
        """Check that critical files are protected.

        Critical files require explicit approval or higher trust level.
        """
        file = kwargs.get("file", "")
        trust = kwargs.get("trust", 0.7)

        # Critical files that require elevated trust
        critical_files = {
            "covenant.vsm": 0.9,      # System 5 identity
            "hard_rules.vsm": 0.9,    # Non-negotiable rules
            "RULES.md": 0.8,          # Rules documentation
            "instance.vsm": 0.8,      # Instance configuration
            "boot.vsm": 0.8,          # Boot sequence
            "backbone.py": 0.7,       # Core orchestrator
            "covenant.py": 0.7,       # Covenant enforcement
            "regulation.py": 0.7,     # Regulation layer
        }

        # Check if file is critical
        file_name = Path(file).name if file else ""
        if file_name in critical_files:
            required_trust = critical_files[file_name]
            if trust < required_trust:
                return False

        # Check if file is in protected directories
        protected_dirs = [".git", ".opencode", "state"]
        for part in Path(file).parts:
            if part in protected_dirs:
                return False

        return True
