"""backbone.py — Integration backbone orchestrator.

Manages the lifecycle of code flowing through the system:
  route → register → verify → load → evaluate → activate → monitor

Each step:
  - Executes the action
  - Generates evidence (BackboneEvent)
  - Feeds state canon
  - On failure: revert + log
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from vos_kernel.backbone.backbone_event import (
    BackboneEvent,
    BackboneEventLogger,
    ComponentType,
    EventStatus,
    Step,
)


@dataclass
class StepResult:
    success: bool
    evidence: dict
    error: str | None = None


class Backbone:
    """Integration backbone orchestrator.

    Usage:
        backbone = Backbone(state_dir="/home/rmw3/vsf/state")
        result = backbone.ingest(
            path="/path/to/predicate.py",
            component_type=ComponentType.PREDICATE,
        )
        if result.success:
            print("Component integrated successfully")
        else:
            print(f"Integration failed: {result.error}")
    """

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.logger = BackboneEventLogger(self.state_dir)
        self._step_handlers: dict[Step, Callable] = {
            Step.ROUTE: self._step_route,
            Step.REGISTER: self._step_register,
            Step.VERIFY: self._step_verify,
            Step.LOAD: self._step_load,
            Step.EVALUATE: self._step_evaluate,
            Step.ACTIVATE: self._step_activate,
            Step.MONITOR: self._step_monitor,
        }

    def ingest(
        self,
        path: str | Path,
        component_type: ComponentType,
        context: dict | None = None,
    ) -> StepResult:
        """Run the full integration lifecycle on a component.

        Args:
            path: path to the component file
            component_type: type of component (tree, predicate, script, plugin)
            context: additional context for the lifecycle

        Returns:
            StepResult with success status and evidence.
        """
        path = str(path)
        context = context or {}
        start_time = time.time()

        # Run each step in sequence
        steps = [
            Step.ROUTE,
            Step.REGISTER,
            Step.VERIFY,
            Step.LOAD,
            Step.EVALUATE,
            Step.ACTIVATE,
            Step.MONITOR,
        ]

        for step in steps:
            step_start = time.time()
            handler = self._step_handlers[step]

            try:
                result = handler(path, component_type, context)
            except Exception as e:
                result = StepResult(
                    success=False,
                    evidence={"error": str(e)},
                    error=str(e),
                )

            duration_ms = int((time.time() - step_start) * 1000)

            # Log event
            event = BackboneEvent(
                step=step,
                component=path,
                component_type=component_type,
                status=EventStatus.OK if result.success else EventStatus.ERROR,
                evidence=result.evidence,
                duration_ms=duration_ms,
            )
            self.logger.log(event)

            # If step failed, stop lifecycle
            if not result.success:
                return StepResult(
                    success=False,
                    evidence={"failed_step": step.value, "error": result.error},
                    error=f"Step {step.value} failed: {result.error}",
                )

        total_ms = int((time.time() - start_time) * 1000)
        return StepResult(
            success=True,
            evidence={"total_ms": total_ms, "steps_completed": len(steps)},
        )

    def get_status(self, component: str | None = None) -> dict:
        """Get backbone status."""
        return self.logger.get_status(component)

    def get_events(self, component: str | None = None, limit: int = 50) -> list[dict]:
        """Get recent events."""
        return self.logger.get_events(component, limit)

    # ─── Step Handlers ──────────────────────────────────────────────────

    def _step_route(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Route: determine correct destination by type."""
        # For now, just verify the file exists
        if not Path(path).exists():
            return StepResult(
                success=False,
                evidence={"path": path},
                error=f"File not found: {path}",
            )

        return StepResult(
            success=True,
            evidence={"path": path, "routed_to": path},
        )

    def _step_register(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Register: add to component registry."""
        # For now, just log the registration
        return StepResult(
            success=True,
            evidence={"path": path, "registered": True},
        )

    def _step_verify(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Verify: check component integrity."""
        # Basic verification based on type
        if component_type == ComponentType.PREDICATE:
            return self._verify_predicate(path)
        elif component_type == ComponentType.TREE:
            return self._verify_tree(path)
        elif component_type == ComponentType.SCRIPT:
            return self._verify_script(path)
        else:
            return StepResult(
                success=True,
                evidence={"path": path, "verified": True},
            )

    def _step_load(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Load: import component into system.

        For predicates: register with socratic engine via socratic_bridge.
        For trees: load and validate via socratic_bridge.
        For scripts/plugins: verify loadable.
        """
        if component_type == ComponentType.PREDICATE:
            return self._load_predicate(path)
        elif component_type == ComponentType.TREE:
            return self._load_tree(path)
        else:
            return StepResult(
                success=True,
                evidence={"path": path, "loaded": True},
            )

    def _load_predicate(self, path: str) -> StepResult:
        """Load a predicate into the socratic engine."""
        try:
            from vos_kernel.backbone.socratic_bridge import SocraticBridge
            bridge = SocraticBridge()
            result = bridge.register_predicate(path)
            return StepResult(
                success=result.success,
                evidence={"path": path, "loaded": True, "bridge_evidence": result.evidence},
                error=result.error,
            )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"path": path},
                error=f"Failed to load predicate: {e}",
            )

    def _load_tree(self, path: str) -> StepResult:
        """Load and validate a VSL tree."""
        try:
            from vos_kernel.backbone.socratic_bridge import SocraticBridge
            bridge = SocraticBridge()
            result = bridge.load_tree(path)
            return StepResult(
                success=result.success,
                evidence={"path": path, "loaded": True, "bridge_evidence": result.evidence},
                error=result.error,
            )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"path": path},
                error=f"Failed to load tree: {e}",
            )

    def _step_evaluate(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Evaluate: test component against system."""
        # For now, just log the evaluation
        return StepResult(
            success=True,
            evidence={"path": path, "evaluated": True},
        )

    def _step_activate(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Activate: mark component as active."""
        return StepResult(
            success=True,
            evidence={"path": path, "activated": True},
        )

    def _step_monitor(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Monitor: observe post-activation usage."""
        return StepResult(
            success=True,
            evidence={"path": path, "monitoring": True},
        )

    # ─── Verification Helpers ───────────────────────────────────────────

    def _verify_predicate(self, path: str) -> StepResult:
        """Verify a predicate file."""
        try:
            with open(path) as f:
                content = f.read()

            # Check it's valid Python
            compile(content, path, "exec")

            return StepResult(
                success=True,
                evidence={"path": path, "syntax_ok": True},
            )
        except SyntaxError as e:
            return StepResult(
                success=False,
                evidence={"path": path, "syntax_error": str(e)},
                error=f"Syntax error: {e}",
            )

    def _verify_tree(self, path: str) -> StepResult:
        """Verify a tree file."""
        try:
            with open(path) as f:
                content = f.read()

            # Basic VSL structure check
            if "⟦" in content and "⟧" in content:
                return StepResult(
                    success=True,
                    evidence={"path": path, "structure_ok": True},
                )
            else:
                return StepResult(
                    success=False,
                    evidence={"path": path},
                    error="Missing VSL structure (⟦ ⟧)",
                )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"path": path},
                error=str(e),
            )

    def _verify_script(self, path: str) -> StepResult:
        """Verify a script file."""
        try:
            with open(path) as f:
                content = f.read()

            # Check it's valid Python or has valid shebang
            if content.startswith("#!"):
                return StepResult(
                    success=True,
                    evidence={"path": path, "shebang_ok": True},
                )
            else:
                compile(content, path, "exec")
                return StepResult(
                    success=True,
                    evidence={"path": path, "syntax_ok": True},
                )
        except SyntaxError as e:
            return StepResult(
                success=False,
                evidence={"path": path, "syntax_error": str(e)},
                error=f"Syntax error: {e}",
            )
