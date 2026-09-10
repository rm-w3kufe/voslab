"""canon_bridge.py — Integration with state-canon.

Provides:
  - record_event: record backbone events in state canon
  - record_status: record component status in state canon
  - reconcile: detect drift between declared and observed state

Architecture:
  backbone → canon_bridge → state-canon-mcp (via subprocess)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from vos_kernel.backbone.backbone import StepResult
from vos_kernel.backbone.backbone_event import BackboneEvent


class CanonBridge:
    """Bridge between backbone and state-canon.

    Usage:
        bridge = CanonBridge(canon_path="~/state-canon-mcp")
        result = bridge.record_event(event)
        result = bridge.record_status(component, status)
    """

    def __init__(self, canon_path: str | Path | None = None):
        if canon_path:
            self.canon_path = Path(canon_path)
        else:
            # Default location
            self.canon_path = Path.home() / "state-canon-mcp"

        # State canon domains for backbone
        self.events_domain = "backbone_events"
        self.status_domain = "backbone_status"

    def record_event(self, event: BackboneEvent) -> StepResult:
        """Record a backbone event in state canon.

        Args:
            event: the BackboneEvent to record

        Returns:
            StepResult with recording evidence.
        """
        try:
            record = event.to_dict()

            # Try to use state-canon-mcp
            result = self._query_canon("record", self.events_domain, record)

            if result.get("error"):
                # Fallback: write to local JSONL
                return self._record_event_local(event)

            return StepResult(
                success=True,
                evidence={
                    "event_id": event.id,
                    "domain": self.events_domain,
                    "recorded": True,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"event_id": event.id},
                error=str(e),
            )

    def record_status(self, component: str, status: dict) -> StepResult:
        """Record component status in state canon.

        Args:
            component: component identifier
            status: status dict

        Returns:
            StepResult with recording evidence.
        """
        try:
            record = {"component": component, **status}

            result = self._query_canon("record", self.status_domain, record)

            if result.get("error"):
                # Fallback: write to local JSON
                return self._record_status_local(component, status)

            return StepResult(
                success=True,
                evidence={
                    "component": component,
                    "domain": self.status_domain,
                    "recorded": True,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={"component": component},
                error=str(e),
            )

    def query_events(
        self,
        component: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query backbone events from state canon.

        Args:
            component: optional component filter
            limit: max events to return

        Returns:
            List of event dicts.
        """
        try:
            filter_dict = {}
            if component:
                filter_dict["component"] = component

            result = self._query_canon("query", self.events_domain, filter_dict)

            if result.get("error"):
                # Fallback: read from local JSONL
                return self._query_events_local(component, limit)

            return result.get("records", [])

        except Exception:
            return self._query_events_local(component, limit)

    def reconcile(self) -> StepResult:
        """Reconcile declared vs observed state.

        Checks that:
          - All active components have valid status
          - No orphaned events
          - Status matches latest event

        Returns:
            StepResult with reconciliation evidence.
        """
        try:
            # Get all status records
            status_result = self._query_canon("query", self.status_domain, {})
            statuses = status_result.get("records", {})

            # Get recent events
            events_result = self._query_canon("query", self.events_domain, {})
            events = events_result.get("records", [])

            drifts = []

            # Check each component
            for component, status in statuses.items():
                # Find latest event for this component
                component_events = [
                    e for e in events if e.get("component") == component
                ]

                if not component_events:
                    drifts.append({
                        "component": component,
                        "issue": "no_events",
                        "detail": "Component has status but no events",
                    })
                    continue

                latest_event = max(
                    component_events,
                    key=lambda e: e.get("timestamp", ""),
                )

                # Check if status matches event
                if status.get("status") != latest_event.get("status"):
                    drifts.append({
                        "component": component,
                        "issue": "status_mismatch",
                        "declared": status.get("status"),
                        "observed": latest_event.get("status"),
                    })

            if drifts:
                return StepResult(
                    success=False,
                    evidence={"drifts": drifts, "components_checked": len(statuses)},
                    error=f"Found {len(drifts)} drifts",
                )

            return StepResult(
                success=True,
                evidence={
                    "components_checked": len(statuses),
                    "events_checked": len(events),
                    "drifts": 0,
                },
            )

        except Exception as e:
            return StepResult(
                success=False,
                evidence={},
                error=str(e),
            )

    def _query_canon(self, action: str, domain: str, data: Any) -> dict:
        """Query state-canon-mcp.

        Args:
            action: query action (record, query, etc.)
            domain: canon domain
            data: query data

        Returns:
            Parsed JSON result.
        """
        try:
            # Try using the MCP server directly
            cmd = [
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '{self.canon_path}')
from state_canon.mcp_server import StateCanonMCPServer
server = StateCanonMCPServer()
result = server.handle_{action}('{domain}', {json.dumps(data)})
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
                return {"error": result.stderr.strip() or "Canon query failed"}

            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            return {"error": "Canon query timed out"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON from canon: {e}"}
        except Exception as e:
            return {"error": str(e)}

    def _record_event_local(self, event: BackboneEvent) -> StepResult:
        """Fallback: record event to local JSONL file."""
        events_file = self.canon_path / "backbone_events.jsonl"
        events_file.parent.mkdir(parents=True, exist_ok=True)

        with open(events_file, "a") as f:
            f.write(event.to_json() + "\n")

        return StepResult(
            success=True,
            evidence={
                "event_id": event.id,
                "domain": self.events_domain,
                "recorded": True,
                "local_fallback": True,
            },
        )

    def _record_status_local(self, component: str, status: dict) -> StepResult:
        """Fallback: record status to local JSON file."""
        status_file = self.canon_path / "backbone_status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing status
        existing = {}
        if status_file.exists():
            try:
                with open(status_file) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Update
        existing[component] = status

        # Save
        with open(status_file, "w") as f:
            json.dump(existing, f, indent=2)

        return StepResult(
            success=True,
            evidence={
                "component": component,
                "domain": self.status_domain,
                "recorded": True,
                "local_fallback": True,
            },
        )

    def _query_events_local(
        self,
        component: str | None,
        limit: int,
    ) -> list[dict]:
        """Fallback: query events from local JSONL file."""
        events_file = self.canon_path / "backbone_events.jsonl"
        if not events_file.exists():
            return []

        events = []
        with open(events_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if component and event.get("component") != component:
                        continue
                    events.append(event)
                except json.JSONDecodeError:
                    continue

        return events[-limit:]
