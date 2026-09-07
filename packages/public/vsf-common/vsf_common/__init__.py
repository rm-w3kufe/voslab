"""vsf-common — Coupling protocol for vOSlab packages.

This module defines the shared protocol that all packages must implement
to communicate with the backbone and other packages.

Architecture:
  All packages → vsf-common (protocol)
  backbone → vsf-common → packages

The protocol defines:
  - Component types and metadata
  - Communication interfaces
  - Event formats
  - Status codes
  - CouplingSpec (cross-package dependency declaration)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# Import coupling protocol (from protocol.py)
from .protocol import CouplingSpec, validate, negative_case, positive_case


# ─── Component Types ─────────────────────────────────────────────────────────

class ComponentType(str, Enum):
    """Standard component types in the vOS ecosystem."""
    TREE = "tree"
    PREDICATE = "predicate"
    SCRIPT = "script"
    PLUGIN = "plugin"
    ADAPTER = "adapter"
    PROTOCOL = "protocol"


class ComponentStatus(str, Enum):
    """Standard component statuses."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"
    DEPRECATED = "deprecated"


# ─── Event Format ────────────────────────────────────────────────────────────

@dataclass
class Event:
    """Standard event format for inter-package communication."""
    event_type: str
    component: str
    component_type: ComponentType
    status: ComponentStatus
    data: dict = field(default_factory=dict)
    timestamp: float = 0
    source: str = ""
    correlation_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "event_type": self.event_type,
            "component": self.component,
            "component_type": self.component_type.value,
            "status": self.status.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        """Create from dict."""
        return cls(
            event_type=data.get("event_type", ""),
            component=data.get("component", ""),
            component_type=ComponentType(data.get("component_type", "script")),
            status=ComponentStatus(data.get("status", "active")),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", 0),
            source=data.get("source", ""),
            correlation_id=data.get("correlation_id"),
        )


# ─── Communication Interfaces ────────────────────────────────────────────────

@runtime_checkable
class Component(Protocol):
    """Protocol that all components must implement."""

    @property
    def name(self) -> str:
        """Component name."""
        ...

    @property
    def version(self) -> str:
        """Component version."""
        ...

    @property
    def component_type(self) -> ComponentType:
        """Component type."""
        ...

    def get_status(self) -> ComponentStatus:
        """Get current component status."""
        ...

    def to_dict(self) -> dict:
        """Serialize component metadata."""
        ...


@runtime_checkable
class Bridge(Protocol):
    """Protocol that all bridges must implement."""

    def connect(self) -> bool:
        """Establish connection. Returns True if successful."""
        ...

    def health_check(self) -> dict:
        """Check bridge health. Returns health status dict."""
        ...

    def disconnect(self) -> None:
        """Close connection."""
        ...


@runtime_checkable
class Adapter(Protocol):
    """Protocol that all adapters must implement."""

    def get_config(self) -> dict:
        """Get adapter configuration."""
        ...

    def set_config(self, config: dict) -> None:
        """Set adapter configuration."""
        ...


# ─── Status Codes ────────────────────────────────────────────────────────────

class StatusCode(int, Enum):
    """Standard status codes for operations."""
    OK = 0
    ERROR = 1
    TIMEOUT = 2
    NOT_FOUND = 3
    AUTH_FAILED = 4
    RATE_LIMITED = 5
    UNKNOWN = 99


# ─── Package Metadata ────────────────────────────────────────────────────────

@dataclass
class PackageMetadata:
    """Standard metadata for a vOSlab package."""
    name: str
    version: str
    component_type: ComponentType
    description: str = ""
    author: str = ""
    license: str = ""
    dependencies: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict."""
        return {
            "name": self.name,
            "version": self.version,
            "component_type": self.component_type.value,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "dependencies": self.dependencies,
            "provides": self.provides,
            "requires": self.requires,
        }


# ─── Validation Helpers ──────────────────────────────────────────────────────

def validate_event(event: dict) -> tuple[bool, str]:
    """Validate an event dict against the protocol.

    Returns:
        (is_valid, error_message)
    """
    required_fields = ["event_type", "component", "component_type", "status"]

    for field in required_fields:
        if field not in event:
            return False, f"Missing required field: {field}"

    # Validate component_type
    try:
        ComponentType(event["component_type"])
    except ValueError:
        return False, f"Invalid component_type: {event['component_type']}"

    # Validate status
    try:
        ComponentStatus(event["status"])
    except ValueError:
        return False, f"Invalid status: {event['status']}"

    return True, ""


def validate_metadata(metadata: dict) -> tuple[bool, str]:
    """Validate package metadata against the protocol.

    Returns:
        (is_valid, error_message)
    """
    required_fields = ["name", "version", "component_type"]

    for field in required_fields:
        if field not in metadata:
            return False, f"Missing required field: {field}"

    # Validate component_type
    try:
        ComponentType(metadata["component_type"])
    except ValueError:
        return False, f"Invalid component_type: {metadata['component_type']}"

    return True, ""


# ─── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    # Component types and status
    "ComponentType",
    "ComponentStatus",
    # Event format
    "Event",
    # Communication interfaces
    "Component",
    "Bridge",
    "Adapter",
    # Status codes
    "StatusCode",
    # Package metadata
    "PackageMetadata",
    # Validation helpers
    "validate_event",
    "validate_metadata",
    # Coupling protocol (from protocol.py)
    "CouplingSpec",
    "validate",
    "negative_case",
    "positive_case",
]
