"""backbone_event.py — BackboneEvent dataclass + logger.

Each step in the integration lifecycle generates a BackboneEvent.
Events are stored in backbone_events.jsonl (append-only log).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class Step(str, Enum):
    ROUTE = "route"
    REGISTER = "register"
    VERIFY = "verify"
    LOAD = "load"
    EVALUATE = "evaluate"
    ACTIVATE = "activate"
    MONITOR = "monitor"


class ComponentType(str, Enum):
    TREE = "tree"
    PREDICATE = "predicate"
    SCRIPT = "script"
    PLUGIN = "plugin"
    ADAPTER = "adapter"
    PROTOCOL = "protocol"


class EventStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    REVERTED = "reverted"


@dataclass
class BackboneEvent:
    """A single event in the integration lifecycle."""
    step: Step
    component: str
    component_type: ComponentType
    status: EventStatus
    evidence: dict = field(default_factory=dict)
    duration_ms: int = 0
    parent_id: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class BackboneEventLogger:
    """Append-only logger for BackboneEvents.

    Events are stored in:
      - backbone_events.jsonl (append-only log)
      - backbone_status.json (current state per component)
    """

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.state_dir / "backbone_events.jsonl"
        self.status_file = self.state_dir / "backbone_status.json"

    def log(self, event: BackboneEvent) -> None:
        """Append event to log and update status."""
        # Append to events log
        with open(self.events_file, "a") as f:
            f.write(event.to_json() + "\n")

        # Update status
        self._update_status(event)

    def _update_status(self, event: BackboneEvent) -> None:
        """Update component status from event."""
        status = self._load_status()
        component = event.component

        if component not in status:
            status[component] = {
                "type": event.component_type.value,
                "current_step": None,
                "status": None,
                "last_event_id": None,
                "last_timestamp": None,
                "history": [],
            }

        comp_status = status[component]
        comp_status["current_step"] = event.step.value
        comp_status["status"] = event.status.value
        comp_status["last_event_id"] = event.id
        comp_status["last_timestamp"] = event.timestamp
        comp_status["history"].append({
            "step": event.step.value,
            "status": event.status.value,
            "timestamp": event.timestamp,
            "id": event.id,
        })

        # Keep only last 20 history entries
        comp_status["history"] = comp_status["history"][-20:]

        self._save_status(status)

    def _load_status(self) -> dict:
        """Load current status from file."""
        if self.status_file.exists():
            try:
                with open(self.status_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_status(self, status: dict) -> None:
        """Save status to file."""
        with open(self.status_file, "w") as f:
            json.dump(status, f, indent=2)

    def get_status(self, component: str | None = None) -> dict:
        """Get status for a component or all components."""
        status = self._load_status()
        if component:
            return status.get(component, {})
        return status

    def get_events(self, component: str | None = None, limit: int = 100) -> list[dict]:
        """Get recent events, optionally filtered by component."""
        if not self.events_file.exists():
            return []

        events = []
        with open(self.events_file) as f:
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

    def get_component_history(self, component: str) -> list[dict]:
        """Get event history for a specific component."""
        status = self._load_status()
        comp = status.get(component, {})
        return comp.get("history", [])
