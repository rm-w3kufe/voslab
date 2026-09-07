"""bridge.py — RSI bridge for vOSlab.

Imports from the existing vsf-rsi package at ~/packages/public/vsf-rsi/
which contains the full RSI implementation (40+ modules).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Ensure vsf-rsi package is importable
_RSI_DIR = Path.home() / "packages" / "public" / "vsf-rsi"
if _RSI_DIR.exists() and str(_RSI_DIR) not in sys.path:
    sys.path.insert(0, str(_RSI_DIR))


def _import_rsi(module_name: str):
    """Lazy import from vsf-rsi package."""
    try:
        import importlib
        return importlib.import_module(f"vsf_rsi.{module_name}")
    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════════════
# GENETIC ALGORITHM
# ═══════════════════════════════════════════════════════════════════════

def genetic_algorithm_run(
    population_size: int = 50,
    generations: int = 100,
    mutation_rate: float = 0.1,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run genetic algorithm optimization."""
    mod = _import_rsi("rsi_genetic_algorithm")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    if hasattr(mod, "run"):
        return mod.run(population_size=population_size, generations=generations, **kwargs)
    return {"error": "rsi_genetic_algorithm.run not found"}


# ═══════════════════════════════════════════════════════════════════════
# FOREST GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def forest_generate(
    num_trees: int = 10,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Generate a forest of socratic trees."""
    mod = _import_rsi("rsi_forest_generator")
    if mod is None:
        return [{"error": "vsf-rsi not available"}]
    if hasattr(mod, "generate"):
        return mod.generate(num_trees=num_trees, **kwargs)
    return [{"error": "rsi_forest_generator.generate not found"}]


# ═══════════════════════════════════════════════════════════════════════
# TREE GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def tree_generate(
    spec: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Generate a socratic tree from specification."""
    mod = _import_rsi("rsi_tree_generator")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    if hasattr(mod, "generate"):
        return mod.generate(spec=spec, **kwargs)
    return {"error": "rsi_tree_generator.generate not found"}


# ═══════════════════════════════════════════════════════════════════════
# PREDICATE GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def predicate_generate(
    domain: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Generate predicates for a domain."""
    mod = _import_rsi("rsi_predicate_generator")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    if hasattr(mod, "generate"):
        return mod.generate(domain=domain, **kwargs)
    return {"error": "rsi_predicate_generator.generate not found"}


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def compute_metrics(
    data: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compute RSI metrics."""
    mod = _import_rsi("rsi_metrics")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    if hasattr(mod, "compute"):
        return mod.compute(data=data, **kwargs)
    return {"error": "rsi_metrics.compute not found"}


# ═══════════════════════════════════════════════════════════════════════
# GAP DETECTOR
# ═══════════════════════════════════════════════════════════════════════

def detect_gaps(
    state: Dict[str, Any],
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Detect gaps in system state."""
    mod = _import_rsi("rsi_gap_detector")
    if mod is None:
        return [{"error": "vsf-rsi not available"}]
    if hasattr(mod, "detect"):
        return mod.detect(state=state, **kwargs)
    return [{"error": "rsi_gap_detector.detect not found"}]


# ═══════════════════════════════════════════════════════════════════════
# PATTERN DETECTOR
# ═══════════════════════════════════════════════════════════════════════

def detect_patterns(
    data: List[Dict[str, Any]],
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Detect patterns in data."""
    mod = _import_rsi("rsi_pattern_detector")
    if mod is None:
        return [{"error": "vsf-rsi not available"}]
    if hasattr(mod, "detect"):
        return mod.detect(data=data, **kwargs)
    return [{"error": "rsi_pattern_detector.detect not found"}]


# ═══════════════════════════════════════════════════════════════════════
# FEEDBACK LOOP
# ═══════════════════════════════════════════════════════════════════════

def feedback_loop_step(
    state: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute one step of the feedback loop."""
    mod = _import_rsi("rsi_feedback_loop")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    if hasattr(mod, "step"):
        return mod.step(state=state, **kwargs)
    return {"error": "rsi_feedback_loop.step not found"}


# ═══════════════════════════════════════════════════════════════════════
# COMPONENT REGISTRY
# ═══════════════════════════════════════════════════════════════════════

def register_component(
    name: str,
    metadata: Dict[str, Any],
    **kwargs: Any,
) -> bool:
    """Register a component in the RSI registry."""
    mod = _import_rsi("rsi_component_registry")
    if mod is None:
        return False
    if hasattr(mod, "register"):
        return mod.register(name=name, metadata=metadata, **kwargs)
    return False


def list_components() -> List[str]:
    """List registered components."""
    mod = _import_rsi("rsi_component_registry")
    if mod is None:
        return []
    if hasattr(mod, "list_all"):
        return mod.list_all()
    return []


# ═══════════════════════════════════════════════════════════════════════
# AVAILABILITY CHECK
# ═══════════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Check if vsf-rsi package is available."""
    return _RSI_DIR.exists()


def get_version() -> str:
    """Get vsf-rsi version."""
    mod = _import_rsi("__init__")
    if mod and hasattr(mod, "__version__"):
        return mod.__version__
    return "unknown"
