"""The coupling protocol.

Every cross-package dependency in vOSLAB MUST be declared as a CouplingSpec and
validated by `validate()`. This is the ONLY sanctioned channel between
packages: no package may import another package's internals directly. The
protocol is generic (no vOS-specific logic) so other frameworks can reuse it.

Negative control: `validate()` REJECTS a spec that omits its registered
interface or carries a malformed version — proving the gate is not a no-op.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CouplingSpec:
    """Declaration of one cross-package coupling.

    name:      unique coupling id
    provider:  package that provides the capability
    consumer:  package that consumes it
    interface: the protocol/endpoint name (must be registered in
               integration/endpoints.json of the consuming system)
    version:   pinned version (semver: D.D.D)
    invariants: contract guarantees the coupling must preserve
    """

    name: str
    provider: str
    consumer: str
    interface: str
    version: str
    invariants: list[str] = field(default_factory=list)


def validate(spec: CouplingSpec) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED.

    Negative case: a coupling missing a registered interface, or with a
    malformed version, is rejected.
    """
    if not spec.name or not spec.provider or not spec.consumer:
        return 1
    if not spec.interface:
        return 1
    if not _valid_version(spec.version):
        return 1
    return 0


def _valid_version(version: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", version or ""))


def negative_case() -> CouplingSpec:
    """A coupling that omits its interface — MUST be rejected."""
    return CouplingSpec(
        name="bad-coupling",
        provider="x",
        consumer="y",
        interface="",  # missing interface -> invalid
        version="1.0.0",
    )


def positive_case() -> CouplingSpec:
    """A well-formed coupling — MUST be accepted."""
    return CouplingSpec(
        name="state-canon-bridge",
        provider="state-canon-mcp",
        consumer="state-canon-infra",
        interface="state.canon.mcp",
        version="0.1.0",
        invariants=["no_vos_leak"],
    )
