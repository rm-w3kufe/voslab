"""state_canon_infra.py — Framework adapter for state-canon infrastructure wiring.

This adapter provides the kernel with a clean interface to state-canon,
handling infrastructure concerns:
  - Connection management
  - Retry logic
  - Fallback to local state
  - Health checks

Architecture:
  vos_kernel → state_canon_infra → canon_bridge → state-canon-mcp
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from vos_kernel.backbone.canon_bridge import CanonBridge
from vos_kernel.backbone.backbone import StepResult


@dataclass
class InfraConfig:
    """Configuration for infra adapter."""
    canon_path: str | Path | None = None
    retry_attempts: int = 3
    retry_delay_ms: int = 100
    health_check_interval_s: int = 60
    local_fallback: bool = True


class StateCanonInfra:
    """Infrastructure adapter for state-canon.

    Usage:
        infra = StateCanonInfra()
        infra.connect()
        result = infra.record_status("component.py", {"status": "ok"})
        result = infra.query_status("component.py")
        health = infra.health_check()
    """

    def __init__(self, config: InfraConfig | None = None):
        self.config = config or InfraConfig()
        self.bridge: CanonBridge | None = None
        self._connected = False
        self._last_health_check: float = 0
        self._health_status: dict = {}

    def connect(self) -> StepResult:
        """Establish connection to state-canon.

        Returns:
            StepResult with connection evidence.
        """
        try:
            self.bridge = CanonBridge(canon_path=self.config.canon_path)
            self._connected = True

            # Run initial health check
            health = self.health_check()

            return StepResult(
                success=True,
                evidence={
                    "connected": True,
                    "healthy": health.get("healthy", False),
                },
            )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"connected": False},
                error=str(e),
            )

    def record_status(
        self,
        component: str,
        status: dict,
    ) -> StepResult:
        """Record component status with retry logic.

        Args:
            component: component identifier
            status: status dict

        Returns:
            StepResult with recording evidence.
        """
        if not self._connected:
            return StepResult(
                success=False,
                evidence={},
                error="Not connected. Call connect() first.",
            )

        last_error = None
        for attempt in range(self.config.retry_attempts):
            try:
                result = self.bridge.record_status(component, status)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)

            # Wait before retry
            if attempt < self.config.retry_attempts - 1:
                time.sleep(self.config.retry_delay_ms / 1000)

        # All retries failed
        if self.config.local_fallback:
            return self._record_status_local(component, status)

        return StepResult(
            success=False,
            evidence={"component": component, "attempts": self.config.retry_attempts},
            error=f"All {self.config.retry_attempts} attempts failed: {last_error}",
        )

    def query_status(self, component: str) -> dict | None:
        """Query component status.

        Args:
            component: component identifier

        Returns:
            Status dict or None.
        """
        if not self._connected:
            return None

        try:
            result = self.bridge.query_events(component=component, limit=1)
            if result:
                return result[-1]
            return None
        except Exception:
            return None

    def health_check(self) -> dict:
        """Check health of state-canon connection.

        Returns:
            Health status dict with latency measurement.
        """
        now = time.time()

        # Skip if recently checked
        if now - self._last_health_check < self.config.health_check_interval_s:
            return self._health_status

        self._last_health_check = now

        try:
            # Measure actual latency
            start_time = time.time()
            result = self.bridge.query_events(limit=1)
            latency_ms = int((time.time() - start_time) * 1000)

            self._health_status = {
                "healthy": True,
                "timestamp": now,
                "latency_ms": latency_ms,
                "query_result": len(result) if result else 0,
            }
        except Exception as e:
            self._health_status = {
                "healthy": False,
                "timestamp": now,
                "error": str(e),
            }

        return self._health_status

    def reconcile(self) -> StepResult:
        """Reconcile declared vs observed state.

        Returns:
            StepResult with reconciliation evidence.
        """
        if not self._connected:
            return StepResult(
                success=False,
                evidence={},
                error="Not connected.",
            )

        return self.bridge.reconcile()

    def _record_status_local(self, component: str, status: dict) -> StepResult:
        """Fallback: record status to local JSON file."""
        status_file = Path(self.config.canon_path or Path.home() / "state-canon-mcp") / "backbone_status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if status_file.exists():
            try:
                with open(status_file) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        existing[component] = status

        with open(status_file, "w") as f:
            json.dump(existing, f, indent=2)

        return StepResult(
            success=True,
            evidence={
                "component": component,
                "recorded": True,
                "local_fallback": True,
            },
        )
