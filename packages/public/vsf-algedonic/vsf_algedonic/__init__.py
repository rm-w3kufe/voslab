"""
vsf-algedonic — Scripts algedonic del sistema VSF.

Proporciona functions para el sistema algedonic.
"""

__version__ = "0.1.0"

# Key exports for common usage
from .beacon_attestation import attest_beacon, verify_attestation
from .ac_algedonic import process_algedonic_signal, route_algedonic
from .bbs_decisions_bridge import bridge_decisions, sync_decisions
from .vsf_algedonic_subscriber import subscribe_algedonic, unsubscribe_algedonic

__all__ = [
    "attest_beacon",
    "verify_attestation",
    "process_algedonic_signal",
    "route_algedonic",
    "bridge_decisions",
    "sync_decisions",
    "subscribe_algedonic",
    "unsubscribe_algedonic",
]
