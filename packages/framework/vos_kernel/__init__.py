"""vos_kernel — covenant, regulation, invariant-checking.

The kernel is the runtime substrate for covenant enforcement.
It wraps vsl-core (Rust) via PyO3 and provides Python APIs for:
  - Covenant evaluation (A0/A0.1 checks)
  - Regulation layer (invariant monitoring)
  - Invariant checking (pre/post conditions)

Architecture:
  vsl-core (Rust) → PyO3 bindings → vos_kernel (Python) → bridge → plugin
"""

from vos_kernel.covenant import CovenantEnforcer, Verdict
from vos_kernel.regulation import RegulationLayer, Invariant
from vos_kernel.invariants import InvariantChecker, CheckResult

__version__ = "0.1.0"

__all__ = [
    "CovenantEnforcer",
    "Verdict",
    "RegulationLayer",
    "Invariant",
    "InvariantChecker",
    "CheckResult",
]
