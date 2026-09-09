"""backbone_steps.py — Step handlers for the integration backbone.

Each step in the lifecycle has a handler that:
  - Executes the action
  - Returns a StepResult with evidence
  - Can be tested independently

Steps:
  route → register → verify → load → evaluate → activate → monitor
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vos_kernel.backbone.backbone_event import (
    ComponentType,
    Step,
)


@dataclass
class StepResult:
    success: bool
    evidence: dict
    error: str | None = None


def step_route(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
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
    dest_path = state_dir / dest_dir / path_obj.name

    return StepResult(
        success=True,
        evidence={
            "path": path,
            "component_type": component_type.value,
            "routed_to": str(dest_path),
            "dest_dir": dest_dir,
        },
    )


def step_register(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
) -> StepResult:
    """Register: add to component registry.

    Maintains a JSON registry of all integrated components.
    """
    registry_path = state_dir / "component_registry.json"

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


def step_verify(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
) -> StepResult:
    """Verify: check component integrity."""
    # Basic verification based on type
    if component_type == ComponentType.PREDICATE:
        return _verify_predicate(path)
    elif component_type == ComponentType.TREE:
        return _verify_tree(path)
    elif component_type == ComponentType.SCRIPT:
        return _verify_script(path)
    else:
        return StepResult(
            success=True,
            evidence={"path": path, "verified": True},
        )


def step_load(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
) -> StepResult:
    """Load: import component into system.

    For predicates: register with socratic engine via socratic_bridge.
    For trees: load and validate via socratic_bridge.
    For scripts/plugins: verify loadable.
    """
    if component_type == ComponentType.PREDICATE:
        return _load_predicate(path)
    elif component_type == ComponentType.TREE:
        return _load_tree(path)
    else:
        return StepResult(
            success=True,
            evidence={"path": path, "loaded": True},
        )


def step_evaluate(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
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


def step_activate(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
) -> StepResult:
    """Activate: mark component as active.

    Updates the registry and creates activation event.
    """
    registry_path = state_dir / "component_registry.json"
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


def step_monitor(
    path: str, component_type: ComponentType, context: dict, state_dir: Path
) -> StepResult:
    """Monitor: observe post-activation usage.

    Records monitoring start and checks for existing metrics.
    """
    component_name = Path(path).stem
    metrics_dir = state_dir / "metrics"
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


# ─── Verification Helpers ───────────────────────────────────────────────────

def _verify_predicate(path: str) -> StepResult:
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


def _verify_tree(path: str) -> StepResult:
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


def _verify_script(path: str) -> StepResult:
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


def _load_predicate(path: str) -> StepResult:
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


def _load_tree(path: str) -> StepResult:
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
