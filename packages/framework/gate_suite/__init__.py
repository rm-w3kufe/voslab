"""gate-suite — the NERVES of vOSLAB (P0.1).

Policy enforcement with a negative-control harness. NO gate is admitted
without a failing test that fails when the gate is absent.
"""

from .harness import Gate, register, run_negative_controls, GATES

__all__ = ["Gate", "register", "run_negative_controls", "GATES"]
