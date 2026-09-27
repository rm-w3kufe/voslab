"""Gate registry for vOSLAB gate-suite.

Each gate module registers itself on import. Import this package to load all
gates, then call `gate_suite.run_negative_controls()`.
"""

from gate_suite.harness import register
from gate_suite.gates import plugin_location_valid  # noqa: F401  (registers gate)
from gate_suite.gates import a0_compliance  # noqa: F401  (registers gate)
from gate_suite.gates import a1_recursion  # noqa: F401  (registers gate)
from gate_suite.gates import trust_composable  # noqa: F401  (registers gate)
from gate_suite.gates import a5_autonomy  # noqa: F401  (registers gate)
from gate_suite.gates import no_silent_concession  # noqa: F401  (registers gate)
from gate_suite.gates import vsm_version_enforcer  # noqa: F401  (registers gate)
from gate_suite.gates import timestamp_no_hardcoded  # noqa: F401  (registers gate)
from gate_suite.gates import guard_coverage  # noqa: F401  (registers gate, EP-1)
from gate_suite.gates import claim_audit      # noqa: F401  (registers gate, EP-1)
