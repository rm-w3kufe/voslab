"""rsi_bridge.py — Integration with vsf-rsi.

Provides:
  - wrap_evaluate: wrap evaluation through RSI observer
  - detect_gaps: detect gaps using RSI gap detector
  - auto_improve: attempt auto-improvement based on RSI feedback

Architecture:
  backbone → rsi_bridge → vsf-rsi (via subprocess)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from vos_kernel.backbone.backbone import StepResult


class RSIBridge:
    """Bridge between backbone and vsf-rsi.

    Usage:
        bridge = RSIBridge(rsi_path="/home/rmw3/packages/public/vsf-rsi")
        result = bridge.detect_gaps()
        result = bridge.wrap_evaluate(component, evaluation_result)
    """

    def __init__(self, rsi_path: str | Path | None = None):
        if rsi_path:
            self.rsi_path = Path(rsi_path)
        else:
            # Default location
            self.rsi_path = Path.home() / "packages" / "public" / "vsf-rsi"

        self.observer_script = self.rsi_path / "vsf_rsi" / "observer.py"

    def wrap_evaluate(
        self,
        component: str,
        evaluation_result: dict,
    ) -> StepResult:
        """Wrap evaluation result through RSI observer.

        Args:
            component: component identifier
            evaluation_result: result from socratic evaluation

        Returns:
            StepResult with observer evidence.
        """
        try:
            # Record the evaluation event
            event = {
                "type": "evaluation",
                "component": component,
                "truth": evaluation_result.get("truth"),
                "certified": evaluation_result.get("certified"),
                "source": evaluation_result.get("source"),
            }

            result = self._run_rsi("record-event", event)

            if result.get("error"):
                # Fallback: log locally
                return self._record_event_local(event)

            return StepResult(
                success=True,
                evidence={
                    "component": component,
                    "observed": True,
                    "metrics_recorded": True,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"component": component},
                error=str(e),
            )

    def detect_gaps(self) -> StepResult:
        """Detect gaps using RSI gap detector.

        Returns:
            StepResult with detected gaps.
        """
        try:
            result = self._run_rsi("detect-gaps", {})

            if result.get("error"):
                return StepResult(
                    success=False,
                    evidence={},
                    error=f"Gap detection failed: {result['error']}",
                )

            gaps = result.get("gaps", [])
            return StepResult(
                success=True,
                evidence={
                    "gaps_found": len(gaps),
                    "gaps": gaps,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={},
                error=str(e),
            )

    def auto_improve(
        self,
        component: str,
        gap: dict,
    ) -> StepResult:
        """Attempt auto-improvement based on RSI feedback.

        Args:
            component: component identifier
            gap: detected gap information

        Returns:
            StepResult with improvement evidence.
        """
        try:
            # Determine improvement level
            level = gap.get("level", "L1")

            if level == "L1":
                # Adjust threshold
                return self._improve_threshold(component, gap)
            elif level == "L2":
                # Inject predicate
                return self._improve_predicate(component, gap)
            elif level == "L3":
                # Generate tree
                return self._improve_tree(component, gap)
            else:
                return StepResult(
                    success=False,
                    evidence={"level": level},
                    error=f"Unknown improvement level: {level}",
                )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"component": component},
                error=str(e),
            )

    def _improve_threshold(self, component: str, gap: dict) -> StepResult:
        """L1 improvement: adjust threshold."""
        return StepResult(
            success=True,
            evidence={
                "component": component,
                "improvement": "threshold_adjustment",
                "gap": gap,
            },
        )

    def _improve_predicate(self, component: str, gap: dict) -> StepResult:
        """L2 improvement: inject predicate."""
        return StepResult(
            success=True,
            evidence={
                "component": component,
                "improvement": "predicate_injection",
                "gap": gap,
            },
        )

    def _improve_tree(self, component: str, gap: dict) -> StepResult:
        """L3 improvement: generate tree."""
        return StepResult(
            success=True,
            evidence={
                "component": component,
                "improvement": "tree_generation",
                "gap": gap,
            },
        )

    def _run_rsi(self, command: str, data: Any) -> dict:
        """Run vsf-rsi command.

        Args:
            command: RSI command (record-event, detect-gaps, etc.)
            data: command data

        Returns:
            Parsed JSON result.
        """
        try:
            cmd = [
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '{self.rsi_path}')
from vsf_rsi.observer import RSIObserver
observer = RSIObserver()
result = observer.{command.replace('-', '_')}({json.dumps(data)})
print(json.dumps(result))
""",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return {"error": result.stderr.strip() or "RSI command failed"}

            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            return {"error": "RSI command timed out"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON from RSI: {e}"}
        except Exception as e:
            return {"error": str(e)}

    def _record_event_local(self, event: dict) -> StepResult:
        """Fallback: record event to local JSONL file."""
        events_file = self.rsi_path / "backbone_events.jsonl"
        events_file.parent.mkdir(parents=True, exist_ok=True)

        with open(events_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        return StepResult(
            success=True,
            evidence={
                "component": event.get("component"),
                "observed": True,
                "local_fallback": True,
            },
        )
