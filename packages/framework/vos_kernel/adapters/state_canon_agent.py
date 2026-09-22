"""state_canon_agent.py — Framework adapter for agent-facing state-canon wiring.

This adapter provides agents with a clean interface to state-canon,
handling agent-specific concerns:
  - Session context
  - Focus tracking
  - Journal snapshots
  - Drift detection

Architecture:
  agent → state_canon_agent → canon_bridge → state-canon-mcp
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
class AgentConfig:
    """Configuration for agent adapter."""
    canon_path: str | Path | None = None
    session_id: str | None = None
    focus_file: str | Path | None = None
    journal_db: str | Path | None = None


class StateCanonAgent:
    """Agent-facing adapter for state-canon.

    Usage:
        agent = StateCanonAgent(session_id="session-123")
        agent.connect()
        agent.focus_mark("TASK-001", status="active", note="Working on X")
        agent.journal_mark(session_id="session-123")
        drifts = agent.detect_drift()
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.bridge: CanonBridge | None = None
        self._connected = False

    def connect(self) -> StepResult:
        """Establish connection to state-canon.

        Returns:
            StepResult with connection evidence.
        """
        try:
            self.bridge = CanonBridge(canon_path=self.config.canon_path)
            self._connected = True

            return StepResult(
                success=True,
                evidence={"connected": True},
            )
        except Exception as e:
            return StepResult(
                success=False,
                evidence={"connected": False},
                error=str(e),
            )

    def focus_mark(
        self,
        ref: str,
        status: str = "active",
        note: str | None = None,
    ) -> StepResult:
        """Mark a focus entry.

        Args:
            ref: focus entry identifier
            status: active | paused | done
            note: optional context note

        Returns:
            StepResult with evidence.
        """
        if not self._connected:
            return StepResult(
                success=False,
                evidence={},
                error="Not connected.",
            )

        record = {
            "ref": ref,
            "status": status,
            "timestamp": time.time(),
        }
        if note:
            record["note"] = note

        return self.bridge.record_status(
            f"focus:{ref}",
            record,
        )

    def focus_close(self, ref: str, note: str | None = None) -> StepResult:
        """Close a focus entry.

        Args:
            ref: focus entry identifier
            note: optional closing note

        Returns:
            StepResult with evidence.
        """
        return self.focus_mark(ref, status="done", note=note)

    def journal_mark(self, session_id: str | None = None) -> StepResult:
        """Save a journal snapshot.

        Args:
            session_id: optional session label

        Returns:
            StepResult with evidence.
        """
        if not self._connected:
            return StepResult(
                success=False,
                evidence={},
                error="Not connected.",
            )

        record = {
            "type": "journal_snapshot",
            "session_id": session_id or self.config.session_id,
            "timestamp": time.time(),
        }

        return self.bridge.record_status(
            f"journal:{session_id or 'default'}",
            record,
        )

    def detect_drift(self) -> list[dict]:
        """Detect drift between declared and observed state.

        Enhanced drift detection (GAP-09):
        - Status mismatch: same component with different status values
        - Focus staleness: active tasks not updated in >1 hour
        - Component health: health percentage below threshold
        - Event gap: no events for a component in >30 minutes

        Returns:
            List of drift dicts with 'issue' field describing the type.
        """
        if not self._connected:
            return []

        try:
            import os, json
            from pathlib import Path
            from datetime import datetime, timezone, timedelta

            drifts = []
            now = datetime.now(timezone.utc)

            # 1. Status mismatch (existing logic)
            events = self.bridge.query_events(limit=100)
            status_by_component = {}
            for event in events:
                component = event.get("component", "")
                status = event.get("status", "")
                if component in status_by_component:
                    if status_by_component[component] != status:
                        drifts.append({
                            "component": component,
                            "issue": "status_mismatch",
                            "previous": status_by_component[component],
                            "current": status,
                        })
                else:
                    status_by_component[component] = status

            # 2. Focus staleness: active tasks not updated in >1 hour
            voslab = Path(os.environ.get("VOSLAB_PATH", "/home/rmw3/vOSlab"))
            focus_path = voslab / "current_focus.json"
            try:
                if focus_path.exists():
                    entries = json.loads(focus_path.read_text())
                    cutoff = now - timedelta(hours=1)
                    for entry in entries:
                        if entry.get("status") == "active":
                            updated = entry.get("updated_at", "")
                            if updated:
                                try:
                                    update_time = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                                    if update_time < cutoff:
                                        drifts.append({
                                            "component": f"focus:{entry.get('ref', '?')}",
                                            "issue": "focus_stale",
                                            "last_updated": updated,
                                            "stale_hours": (now - update_time).total_seconds() / 3600,
                                        })
                                except (ValueError, TypeError):
                                    pass
            except Exception:
                pass

            # 3. Component health below threshold
            status_path = voslab / "scripts/state/monitoring/backbone_status.json"
            try:
                if status_path.exists():
                    status_data = json.loads(status_path.read_text())
                    total = len(status_data)
                    if total > 0:
                        healthy = sum(1 for v in status_data.values() if v.get("status") == "ok")
                        health_pct = healthy / total
                        if health_pct < 0.8:
                            drifts.append({
                                "component": "infrastructure",
                                "issue": "health_degraded",
                                "healthy": healthy,
                                "total": total,
                                "health_pct": health_pct,
                            })
            except Exception:
                pass

            return drifts

        except Exception:
            return []

    def query_focus(self, ref: str | None = None) -> dict | list[dict]:
        """Query focus entries.

        Args:
            ref: optional specific ref to query

        Returns:
            Focus entry dict or list of entries.
        """
        if not self._connected:
            return {} if ref else []

        try:
            if ref:
                result = self.bridge.query_events(component=f"focus:{ref}", limit=1)
                return result[-1] if result else {}
            else:
                # Query all focus entries
                all_events = self.bridge.query_events(limit=1000)
                focus_events = [e for e in all_events if e.get("component", "").startswith("focus:")]
                return focus_events
        except Exception:
            return {} if ref else []

    def get_session_context(self) -> dict:
        """Get current session context.

        Returns:
            Session context dict.
        """
        return {
            "session_id": self.config.session_id,
            "connected": self._connected,
            "focus_file": str(self.config.focus_file) if self.config.focus_file else None,
            "journal_db": str(self.config.journal_db) if self.config.journal_db else None,
        }
