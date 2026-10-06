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
from gate_suite.gates import code_language_enforcer  # noqa: F401  (S5-language, code)
from gate_suite.gates import docs_language           # noqa: F401  (S5-language, docs)
from gate_suite.gates import boot_ontology          # noqa: F401  (boot-ontology, promoted 2026-09-30)
from gate_suite.gates import env_parity             # noqa: F401  (env-parity, D-01 2026-10-01)
from gate_suite.gates import focus_format           # noqa: F401  (focus-format, A-7/D-03 2026-10-01)
from gate_suite.gates import substrate_agnostic     # noqa: F401  (substrate-agnostic.valid, EP-6 2026-10-02)
from gate_suite.gates import regulation_monitor  # noqa: F401  (regulation-monitor, G-31 2026-10-04)
from gate_suite.gates import l0_memo             # noqa: F401  (l0-memo, F1 §7.1 2026-10-06)
from gate_suite.gates import l1_cache            # noqa: F401  (l1-cache, F2 §7.1 2026-10-06)
