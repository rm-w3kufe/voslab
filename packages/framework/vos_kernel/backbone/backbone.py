"""backbone.py — Integration backbone orchestrator.

Manages the lifecycle of code flowing through the system:
  route → register → verify → load → evaluate → activate → monitor

Each step:
  - Executes the action
  - Generates evidence (BackboneEvent)
  - Feeds state canon
  - On failure: revert + log

Step handlers are in backbone_steps.py for better modularity.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vos_kernel.backbone.backbone_event import (
    BackboneEvent,
    BackboneEventLogger,
    ComponentType,
    EventStatus,
    Step,
)
from vos_kernel.backbone.backbone_steps import (
    StepResult,
    step_route,
    step_register,
    step_verify,
    step_load,
    step_evaluate,
    step_activate,
    step_monitor,
)


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
            Step.ROUTE: lambda p, ct, ctx: step_route(p, ct, ctx, self.state_dir),
            Step.REGISTER: lambda p, ct, ctx: step_register(p, ct, ctx, self.state_dir),
            Step.VERIFY: lambda p, ct, ctx: step_verify(p, ct, ctx, self.state_dir),
            Step.LOAD: lambda p, ct, ctx: step_load(p, ct, ctx, self.state_dir),
            Step.EVALUATE: lambda p, ct, ctx: step_evaluate(p, ct, ctx, self.state_dir),
            Step.ACTIVATE: lambda p, ct, ctx: step_activate(p, ct, ctx, self.state_dir),
            Step.MONITOR: lambda p, ct, ctx: step_monitor(p, ct, ctx, self.state_dir),
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
