"""Gate registry for vOSLAB gate-suite.

Each gate module registers itself on import. Import this package to load all
gates, then call `gate_suite.run_negative_controls()`.
"""

from gate_suite.harness import register
from gate_suite.gates import plugin_location_valid  # noqa: F401  (registers gate)
