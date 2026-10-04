"""The chassis: wires agents + endpoints + the coupling protocol.

Contains NO agent logic, NO policies, NO plugins. It is the assembly mechanism
that any vOS agent is built upon. Depends only on vsf-common (the coupling
protocol) to validate every cross-package coupling.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from vsf_common import CouplingSpec, validate


@dataclass
class WiringResult:
    agents: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    couplings: list[CouplingSpec] = field(default_factory=list)


class Chassis:
    """Loads the endpoint registry and validates couplings through vsf-common."""

    def __init__(self, root: str):
        self.root = root

    def load_endpoints(self, path: str | None = None) -> list[dict]:
        """Negative control: missing/empty registry fails the wire."""
        p = path or os.path.join(self.root, "integration", "endpoints.json")
        if not os.path.exists(p):
            raise FileNotFoundError(f"endpoints registry missing: {p}")
        with open(p) as f:
            data = json.load(f)
        endpoints = data.get("endpoints", []) if isinstance(data, dict) else data
        if not endpoints:
            raise ValueError("endpoints registry is empty")
        return endpoints

    def register_couplings(self, specs: list[CouplingSpec]) -> list[CouplingSpec]:
        """Negative control: a coupling vsf-common rejects is refused."""
        accepted: list[CouplingSpec] = []
        for s in specs:
            if validate(s) != 0:
                raise ValueError(f"coupling rejected by vsf-common: {s.name}")
            accepted.append(s)
        return accepted

    def wire(
        self, endpoints_path: str | None = None, couplings: list[CouplingSpec] | None = None
    ) -> WiringResult:
        eps = self.load_endpoints(endpoints_path)
        accepted = self.register_couplings(couplings or [])
        return WiringResult(
            agents=[],
            endpoints=[e.get("name", "?") for e in eps],
            couplings=accepted,
        )
