"""hook_metrics.py — Hook execution metrics.

Ported from child/scripts/hook_metrics.py
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


class HookMetrics:
    """Collect and report hook execution metrics."""

    def __init__(self, metrics_dir: str | None = None):
        if metrics_dir is None:
            _base = os.environ.get("VOSLAB_PATH", os.path.expanduser("~/vOSlab"))
            metrics_dir = os.path.join(_base, "state", "hook_metrics")
        self.metrics_dir = metrics_dir
        os.makedirs(metrics_dir, exist_ok=True)
        self.metrics_file = os.path.join(metrics_dir, "hook_metrics.jsonl")

    def record(
        self,
        hook_name: str,
        duration_ms: float,
        success: bool,
        error: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """Record a hook execution event."""
        entry = {
            "timestamp": time.time(),
            "hook_name": hook_name,
            "duration_ms": duration_ms,
            "success": success,
            "error": error,
            "metadata": metadata or {},
        }
        with open(self.metrics_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_metrics(self, hook_name: str | None = None) -> List[Dict[str, Any]]:
        """Get recorded metrics, optionally filtered by hook name."""
        if not os.path.exists(self.metrics_file):
            return []
        metrics = []
        with open(self.metrics_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if hook_name is None or entry.get("hook_name") == hook_name:
                        metrics.append(entry)
                except json.JSONDecodeError:
                    continue
        return metrics

    def summary(self, hook_name: str | None = None) -> Dict[str, Any]:
        """Get summary statistics for hooks."""
        metrics = self.get_metrics(hook_name)
        if not metrics:
            return {"count": 0}

        durations = [m["duration_ms"] for m in metrics]
        successes = sum(1 for m in metrics if m["success"])
        failures = len(metrics) - successes

        return {
            "count": len(metrics),
            "successes": successes,
            "failures": failures,
            "success_rate": successes / len(metrics) if metrics else 0,
            "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
            "min_duration_ms": min(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
        }

    def clear(self, older_than_seconds: float | None = None) -> int:
        """Clear metrics, optionally only older than given seconds."""
        if not os.path.exists(self.metrics_file):
            return 0

        if older_than_seconds is None:
            # Clear all
            os.unlink(self.metrics_file)
            return -1

        # Clear old entries
        cutoff = time.time() - older_than_seconds
        kept = 0
        removed = 0
        with open(self.metrics_file) as f:
            lines = f.readlines()

        with open(self.metrics_file, "w") as f:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("timestamp", 0) >= cutoff:
                        f.write(line + "\n")
                        kept += 1
                    else:
                        removed += 1
                except json.JSONDecodeError:
                    continue

        return removed
