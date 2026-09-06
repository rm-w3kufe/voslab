"""backbone — Integration backbone for the vOS ecosystem.

Manages the lifecycle of code flowing through the system:
  route → register → verify → load → evaluate → activate → monitor

Components:
  - Backbone: orchestrator (backbone.py)
  - BackboneEvent: event dataclass (backbone_event.py)
  - SocraticBridge: integration with socratic-engine (socratic_bridge.py)
  - CanonBridge: integration with state-canon (canon_bridge.py)
  - RSIBridge: integration with vsf-rsi (rsi_bridge.py)
"""

from vos_kernel.backbone.backbone import Backbone
from vos_kernel.backbone.backbone_event import (
    BackboneEvent,
    BackboneEventLogger,
    ComponentType,
    EventStatus,
    Step,
)
from vos_kernel.backbone.socratic_bridge import SocraticBridge
from vos_kernel.backbone.canon_bridge import CanonBridge
from vos_kernel.backbone.rsi_bridge import RSIBridge

__all__ = [
    "Backbone",
    "BackboneEvent",
    "BackboneEventLogger",
    "ComponentType",
    "EventStatus",
    "Step",
    "SocraticBridge",
    "CanonBridge",
    "RSIBridge",
]
