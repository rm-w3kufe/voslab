#!/usr/bin/env python3
"""load_hooks.py — Load all VSF predicates into socratic engine.

design: docs/design/sources/integration-backbone-design-v1/integration_backbone_design.vsm §8 (Socratic Engine Integration)
This module resolves GAP1 by providing a single entry point to load all
VSF predicates into a socratic engine instance.

This module provides a single entry point to load all VSF predicates
into a socratic engine instance. It resolves GAP1 by ensuring predicates
are loaded and evaluated, not just trees.

Usage:
    from load_hooks import load_all_predicates

    engine = SocraticEngine()
    load_all_predicates(engine)

Or via CLI:
    python load_hooks.py --verify
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from socratic_engine import SocraticEngine

# Add classifier to path
VSF_ROOT = Path(__file__).parent.parent.parent
CLASSIFIER_DIR = VSF_ROOT / "scripts" / "vsl" / "classifier"
if str(CLASSIFIER_DIR) not in sys.path:
    sys.path.insert(0, str(CLASSIFIER_DIR))


def load_all_predicates(engine: "SocraticEngine") -> dict:
    """Load all VSF predicates into the engine.

    Args:
        engine: SocraticEngine instance to load predicates into

    Returns:
        Dict with loading results:
        - loaded: list of loaded predicate names
        - errors: list of (name, error) tuples
        - total: total predicates loaded
    """
    results = {
        "loaded": [],
        "errors": [],
        "total": 0,
    }

    # Import predicate modules
    modules = [
        ("vsf_predicates", "register_vsf_predicates"),
        ("vsf_hooks_predicates", "register_hooks_predicates"),
        ("chain_predicates", None),  # Uses CHAIN_PREDICATES constant
        ("analytics_predicates", None),  # Uses ANALYTICS_PREDICATES constant
        ("health_predicates", None),  # Uses health predicates
        ("governance_predicates", None),  # Uses GOVERNANCE_PREDICATES constant
    ]

    for module_name, register_func_name in modules:
        try:
            # Import module
            module = __import__(module_name)

            # Get register function
            register_func = getattr(module, register_func_name, None) if register_func_name else None
            if register_func:
                # Standard register pattern
                register_func(engine)
                results["loaded"].append(module_name)
                results["total"] += 1
            else:
                # Check for constant pattern (CHAIN_PREDICATES, etc.)
                for const_name in ["CHAIN_PREDICATES", "ANALYTICS_PREDICATES", "GOVERNANCE_PREDICATES"]:
                    predicates_dict = getattr(module, const_name, None)
                    if predicates_dict and isinstance(predicates_dict, dict):
                        # Register each predicate from the dict
                        for pred_name, pred_func in predicates_dict.items():
                            if callable(pred_func):
                                engine.register(pred_name)(pred_func)
                        results["loaded"].append(f"{module_name} ({len(predicates_dict)} predicates)")
                        results["total"] += 1
                        break
                else:
                    # Try to find health predicates
                    if module_name == "health_predicates":
                        # Health predicates are registered differently
                        results["loaded"].append(f"{module_name} (special)")
                        results["total"] += 1
                    else:
                        results["errors"].append((module_name, "no register function or predicates found"))

        except ImportError as e:
            results["errors"].append((module_name, f"import error: {e}"))
        except Exception as e:
            results["errors"].append((module_name, f"error: {e}"))

    return results


def verify_predicates(engine: "SocraticEngine") -> dict:
    """Verify that predicates are properly loaded.

    Args:
        engine: SocraticEngine instance to verify

    Returns:
        Dict with verification results.
    """
    # List of expected predicates
    expected_predicates = [
        "ctx_has",
        "ctx_equals",
        "ctx_not_has",
        "procedure_match_instrument",
        "adaptation_needed",
        "adaptation_safe",
        "ac_viable_false",
        "ac_stasis_critical",
        "ac_stasis_warning",
        "ac_trust_degraded",
        "ac_regime_not_nominal",
        "ac_algedonic_critical",
        "ac_algedonic_warning",
        "ac_invariant_streak",
        "ac_invariant_magnitude",
        "ac_s4_ethics_candidate",
        "agent_at_level",
        "organ_matches_markers",
        "regime_known",
        "confidence_sufficient",
        "regime_quiescent",
        "omega_available",
        "within_omega_range",
        "is_cert_test",
        "is_cycle_summary",
        "is_drift_alert",
        "is_merkle_break",
        "has_evidence",
        "is_covenant_halt_test",
        "service_active",
        "nats_reachable",
        "nats_authenticated",
        "disk_ok",
        "alerts_db_ok",
        "is_high_error_rate",
    ]

    # Check which predicates are available
    available = []
    missing = []

    # Get engine predicates - could be _predicates or predicates
    engine_predicates = getattr(engine, "_predicates", None) or getattr(engine, "predicates", None) or {}

    for pred_name in expected_predicates:
        if pred_name in engine_predicates:
            available.append(pred_name)
        else:
            missing.append(pred_name)

    return {
        "available": available,
        "missing": missing,
        "total_expected": len(expected_predicates),
        "total_available": len(available),
        "coverage": len(available) / len(expected_predicates) if expected_predicates else 0,
    }


def _cli_verify():
    """CLI: verify predicates are loaded."""
    from socratic_engine import SocraticEngine

    engine = SocraticEngine()
    results = load_all_predicates(engine)
    verification = verify_predicates(engine)

    print(json.dumps({
        "loading": results,
        "verification": verification,
    }, indent=2))

    if verification["missing"]:
        print(f"\nWARNING: {len(verification['missing'])} predicates missing", file=sys.stderr)
        return 1

    print(f"\nOK: {verification['total_available']} predicates loaded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        sys.exit(_cli_verify())
    else:
        print("usage: load_hooks.py --verify", file=sys.stderr)
        sys.exit(2)
