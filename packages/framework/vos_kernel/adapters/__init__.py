"""adapters — Framework adapters for state-canon integration.

Provides:
  - StateCanonInfra: infrastructure wiring (connection, retry, fallback)
  - StateCanonAgent: agent-facing wiring (focus, journal, drift)

Architecture:
  vos_kernel → adapters → canon_bridge → state-canon-mcp
"""

from vos_kernel.adapters.state_canon_infra import StateCanonInfra, InfraConfig
from vos_kernel.adapters.state_canon_agent import StateCanonAgent, AgentConfig

__all__ = [
    "StateCanonInfra",
    "InfraConfig",
    "StateCanonAgent",
    "AgentConfig",
]
