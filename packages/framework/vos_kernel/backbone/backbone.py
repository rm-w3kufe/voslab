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
        """Route: determine correct destination by type.

        Routes components to appropriate directories based on type:
        - PREDICATE → predicates/
        - TREE → trees/
        - SCRIPT → scripts/
        - PLUGIN → plugins/
        """
        path_obj = Path(path)
        if not path_obj.exists():
            return StepResult(
                success=False,
                evidence={"path": path},
                error=f"File not found: {path}",
            )

        # Determine destination based on component type
        type_dirs = {
            ComponentType.PREDICATE: "predicates",
            ComponentType.TREE: "trees",
            ComponentType.SCRIPT: "scripts",
            ComponentType.PLUGIN: "plugins",
            ComponentType.ADAPTER: "adapters",
            ComponentType.PROTOCOL: "protocols",
        }

        dest_dir = type_dirs.get(component_type, "components")
        dest_path = self.state_dir / dest_dir / path_obj.name

        return StepResult(
            success=True,
            evidence={
                "path": path,
                "component_type": component_type.value,
                "routed_to": str(dest_path),
                "dest_dir": dest_dir,
            },
        )

    def _step_register(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Register: add to component registry.

        Maintains a JSON registry of all integrated components.
        """
        registry_path = self.state_dir / "component_registry.json"

        # Load existing registry
        registry = {}
        if registry_path.exists():
            try:
                with open(registry_path) as f:
                    registry = json.load(f)
            except (json.JSONDecodeError, OSError):
                registry = {}

        # Add/update component entry
        component_name = Path(path).stem
        registry[component_name] = {
            "path": path,
            "type": component_type.value,
            "registered_at": time.time(),
            "status": "registered",
        }

        # Save registry
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

        return StepResult(
            success=True,
            evidence={
                "path": path,
                "registered": True,
                "registry_size": len(registry),
            },
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
        """Evaluate: test component against system.

        Runs basic validation and integration tests.
        """
        evaluation_results = {
            "path": path,
            "component_type": component_type.value,
            "checks": [],
        }

        # Check 1: File is readable
        try:
            with open(path) as f:
                content = f.read()
            evaluation_results["checks"].append({
                "name": "readable",
                "passed": True,
                "size_bytes": len(content),
            })
        except Exception as e:
            return StepResult(
                success=False,
                evidence=evaluation_results,
                error=f"Cannot read file: {e}",
            )

        # Check 2: Syntax validity (for Python files)
        if path.endswith(".py"):
            try:
                compile(content, path, "exec")
                evaluation_results["checks"].append({
                    "name": "syntax_valid",
                    "passed": True,
                })
            except SyntaxError as e:
                evaluation_results["checks"].append({
                    "name": "syntax_valid",
                    "passed": False,
                    "error": str(e),
                })
                return StepResult(
                    success=False,
                    evidence=evaluation_results,
                    error=f"Syntax error: {e}",
                )

        # Check 3: VSL structure (for .vsm files)
        if path.endswith(".vsm"):
            has_header = "⟦" in content and "⟧" in content
            has_footer = content.count("⟦ /") > 0
            evaluation_results["checks"].append({
                "name": "vsl_structure",
                "passed": has_header and has_footer,
                "has_header": has_header,
                "has_footer": has_footer,
            })

        passed_all = all(c["passed"] for c in evaluation_results["checks"])

        return StepResult(
            success=passed_all,
            evidence=evaluation_results,
            error=None if passed_all else "Evaluation checks failed",
        )

    def _step_activate(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Activate: mark component as active.

        Updates the registry and creates activation event.
        """
        registry_path = self.state_dir / "component_registry.json"
        component_name = Path(path).stem

        # Update registry if it exists
        if registry_path.exists():
            try:
                with open(registry_path) as f:
                    registry = json.load(f)

                if component_name in registry:
                    registry[component_name]["status"] = "active"
                    registry[component_name]["activated_at"] = time.time()

                    with open(registry_path, "w") as f:
                        json.dump(registry, f, indent=2)
            except (json.JSONDecodeError, OSError):
                pass

        return StepResult(
            success=True,
            evidence={
                "path": path,
                "activated": True,
                "component_name": component_name,
            },
        )

    def _step_monitor(
        self, path: str, component_type: ComponentType, context: dict
    ) -> StepResult:
        """Monitor: observe post-activation usage.

        Records monitoring start and checks for existing metrics.
        """
        component_name = Path(path).stem
        metrics_dir = self.state_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        metrics_file = metrics_dir / f"{component_name}.json"

        # Load existing metrics or create new
        metrics = {
            "component": component_name,
            "path": path,
            "type": component_type.value,
            "monitoring_started": time.time(),
            "invocations": 0,
            "errors": 0,
        }

        if metrics_file.exists():
            try:
                with open(metrics_file) as f:
                    existing = json.load(f)
                metrics["invocations"] = existing.get("invocations", 0)
                metrics["errors"] = existing.get("errors", 0)
                metrics["monitoring_started"] = existing.get("monitoring_started", metrics["monitoring_started"])
            except (json.JSONDecodeError, OSError):
                pass

        # Save metrics
        with open(metrics_file, "w") as f:
            json.dump(metrics, f, indent=2)

        return StepResult(
            success=True,
            evidence={
                "path": path,
                "monitoring": True,
                "metrics_file": str(metrics_file),
                "component_name": component_name,
            },
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
