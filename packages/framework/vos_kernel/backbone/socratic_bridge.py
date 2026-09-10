"""socratic_bridge.py — Integration with socratic-engine.

Provides:
  - load_tree: parse and validate VSL trees
  - register_predicate: import and register predicates
  - evaluate: run evaluation through socratic engine

Architecture:
  backbone → socratic_bridge → socratic-engine (via subprocess)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from vos_kernel.backbone.backbone import StepResult


class SocraticBridge:
    """Bridge between backbone and socratic-engine.

    Usage:
        bridge = SocraticBridge(engine_path="~/socratic-engine")
        result = bridge.load_tree("/path/to/tree.vsm")
        result = bridge.evaluate_tree(tree, context)
    """

    def __init__(self, engine_path: str | Path | None = None):
        if engine_path:
            self.engine_path = Path(engine_path)
        else:
            # Default location
            self.engine_path = Path.home() / "socratic-engine"

        self.engine_script = self.engine_path / "socratic_engine" / "engine.py"

    def load_tree(self, path: str | Path) -> StepResult:
        """Load and validate a VSL tree file.

        Args:
            path: path to the .vsm tree file

        Returns:
            StepResult with validation evidence.
        """
        path = Path(path)

        if not path.exists():
            return StepResult(
                success=False,
                evidence={"path": str(path)},
                error=f"File not found: {path}",
            )

        try:
            content = path.read_text()

            # Check VSL structure
            if "⟦" not in content or "⟧" not in content:
                return StepResult(
                    success=False,
                    evidence={"path": str(path), "has_vsl_structure": False},
                    error="Missing VSL structure (⟦ ⟧)",
                )

            # Try to parse with socratic engine
            result = self._run_engine("parse-tree", content)
            if result.get("error"):
                return StepResult(
                    success=False,
                    evidence={"path": str(path), "parse_error": result["error"]},
                    error=f"Parse error: {result['error']}",
                )

            return StepResult(
                success=True,
                evidence={
                    "path": str(path),
                    "has_vsl_structure": True,
                    "parsed": True,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"path": str(path)},
                error=str(e),
            )

    def register_predicate(self, path: str | Path) -> StepResult:
        """Import and register a predicate file.

        Args:
            path: path to the predicate .py file

        Returns:
            StepResult with registration evidence.
        """
        path = Path(path)

        if not path.exists():
            return StepResult(
                success=False,
                evidence={"path": str(path)},
                error=f"File not found: {path}",
            )

        try:
            # Check syntax
            content = path.read_text()
            compile(content, str(path), "exec")

            # Try to import and check for predicate function
            import importlib.util
            spec = importlib.util.spec_from_file_location("predicate", str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            has_predicate = hasattr(module, "predicate")

            return StepResult(
                success=True,
                evidence={
                    "path": str(path),
                    "syntax_ok": True,
                    "has_predicate": has_predicate,
                },
            )

        except SyntaxError as e:
            return StepResult(
                success=False,
                evidence={"path": str(path), "syntax_error": str(e)},
                error=f"Syntax error: {e}",
            )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"path": str(path)},
                error=str(e),
            )

    def evaluate_tree(
        self,
        tree: dict | str,
        context: dict | None = None,
    ) -> StepResult:
        """Evaluate a tree through the socratic engine.

        Args:
            tree: tree dict or VSL string
            context: evaluation context

        Returns:
            StepResult with evaluation evidence.
        """
        try:
            if isinstance(tree, str):
                tree_str = tree
            else:
                tree_str = json.dumps(tree)

            result = self._run_engine("eval-tree", tree_str, context)

            if result.get("error"):
                return StepResult(
                    success=False,
                    evidence={"tree": tree_str[:100], "error": result["error"]},
                    error=f"Evaluation error: {result['error']}",
                )

            return StepResult(
                success=True,
                evidence={
                    "truth": result.get("truth"),
                    "certified": result.get("certified"),
                    "source": result.get("source"),
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"tree": str(tree)[:100]},
                error=str(e),
            )

    def _run_engine(
        self,
        command: str,
        *args: Any,
    ) -> dict:
        """Run socratic engine command.

        Args:
            command: engine command (parse-tree, eval-tree, etc.)
            *args: command arguments

        Returns:
            Parsed JSON result.
        """
        try:
            cmd = ["python3", str(self.engine_script), command] + list(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.engine_path),
            )

            if result.returncode != 0:
                return {"error": result.stderr.strip() or "Engine command failed"}

            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            return {"error": "Engine command timed out"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON from engine: {e}"}
        except Exception as e:
            return {"error": str(e)}
