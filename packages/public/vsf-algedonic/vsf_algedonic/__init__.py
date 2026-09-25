"""
vsf-algedonic — Scripts algedonic del sistema VSF.

Rehab 2026-09-24: this __init__ imported 8 names that never existed
(attest_beacon, verify_attestation, ...), making the package
unimportable. Now uses lazy binding (PEP 562): names resolve to real
submodule attributes on first use, so importing the package never
executes heavy third-party imports (nats) or checkout-coupled code.
Missing names raise AttributeError with the real inventory hint.
"""

from __future__ import annotations

__version__ = "0.1.0"

_LAZY = {
    # beacon_attestation (real surface, verified in source)
    "verify_node_cert": "beacon_attestation",
    "BeaconAttestation": "beacon_attestation",
    "write_registry_entry": "beacon_attestation",
    "build_kernel_payload": "beacon_attestation",
    # ac_algedonic (NATS publish paths)
    "_publish_algedonic": "ac_algedonic",
    "_publish_phi_down": "ac_algedonic",
    "parse_events": "ac_classifier",
    "classify": "ac_classifier",
    "classify_raw": "ac_classifier",
    # sink + subscriber entry points
    "render_line": "g6_algedonic_sink",
    "dedup_key": "g6_algedonic_sink",
    "load_policy_whitelist": "bbs_decisions_bridge",
    # decision auth
    "DecisionVerifier": "vsf_decision_auth",
    "generate_operational_key": "vsf_decision_auth",
}


def __getattr__(name: str):
    mod = _LAZY.get(name)
    if mod is None:
        raise AttributeError(
            f"vsf_algedonic has no {name!r}. Real surface: "
            f"{sorted(_LAZY)}")
    import importlib
    module = importlib.import_module(f"vsf_algedonic.{mod}")
    return getattr(module, name)


__all__ = sorted(set(_LAZY) | {"__version__"})
