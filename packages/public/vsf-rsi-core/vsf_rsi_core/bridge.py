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
    try:
        ga = mod.RSIGeneticAlgorithm(
            population_size=population_size,
            mutation_rate=mutation_rate,
        )
        # Create forest and evolve
        predicate_name = kwargs.get("predicate_name", "default")
        forest = ga.create_forest(predicate_name)
        for _ in range(generations):
            forest = ga.evolve_generation(forest, predicate_name)
        stats = ga.get_evolution_stats(predicate_name) if hasattr(ga, "get_evolution_stats") else {}
        return {
            "generations": generations,
            "status": "completed",
            "forest_size": len(forest) if forest else 0,
            "stats": stats,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# FOREST GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def forest_generate(
    num_trees: int = 10,
    predicate_name: str = "default",
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Generate a forest of socratic trees."""
    mod = _import_rsi("rsi_forest_generator")
    if mod is None:
        return [{"error": "vsf-rsi not available"}]
    try:
        if hasattr(mod, "RSIForestGenerator"):
            gen = mod.RSIForestGenerator()
            result = gen.generate_forest(predicate_name=predicate_name, population_size=num_trees)
            return [{"generated": True, "result": str(result)[:200]}]
        elif hasattr(mod, "generate"):
            return mod.generate(num_trees=num_trees, **kwargs)
        return [{"error": "no generate method found"}]
    except Exception as e:
        return [{"error": str(e)}]


# ═══════════════════════════════════════════════════════════════════════
# TREE GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def tree_generate(
    predicate_name: str = "default",
    gaps: Dict[str, Any] | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Generate a socratic tree from specification."""
    mod = _import_rsi("rsi_tree_generator")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSITreeGenerator"):
            gen = mod.RSITreeGenerator()
            tree = gen.generate_tree(predicate_name=predicate_name, gaps=gaps or {})
            return {"generated": True, "tree": str(tree)[:200]} if tree else {}
        elif hasattr(mod, "generate"):
            return mod.generate(predicate_name=predicate_name, gaps=gaps, **kwargs)
        return {"error": "no generate method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# PREDICATE GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def predicate_generate(
    pattern: Dict[str, Any],
    base_predicate: str | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Generate predicates for a domain."""
    mod = _import_rsi("rsi_predicate_generator")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIPredicateGenerator"):
            gen = mod.RSIPredicateGenerator()
            predicate = gen.generate_predicate(pattern=pattern, base_predicate=base_predicate)
            return {"generated": True, "predicate": str(predicate)[:200]} if predicate else {}
        elif hasattr(mod, "generate"):
            return mod.generate(pattern=pattern, base_predicate=base_predicate, **kwargs)
        return {"error": "no generate method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def compute_metrics(
    predicate_name: str = "default",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compute RSI metrics."""
    mod = _import_rsi("rsi_metrics")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIMetrics"):
            metrics = mod.RSIMetrics()
            summary = metrics.get_summary()
            accuracy = metrics.get_accuracy(predicate_name)
            coverage = metrics.get_coverage(predicate_name)
            return {
                "computed": True,
                "summary": summary,
                "accuracy": accuracy,
                "coverage": coverage,
            }
        elif hasattr(mod, "compute"):
            return mod.compute(predicate_name=predicate_name, **kwargs)
        return {"error": "no compute method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# GAP DETECTOR
# ═══════════════════════════════════════════════════════════════════════

def detect_gaps(
    predicate_name: str = "default",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect gaps in system state."""
    mod = _import_rsi("rsi_gap_detector")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIGapDetector"):
            detector = mod.RSIGapDetector()
            gaps = detector.detect_gaps(predicate_name=predicate_name)
            return {"detected": True, "gaps": gaps} if gaps else {"detected": False}
        elif hasattr(mod, "detect"):
            return mod.detect(predicate_name=predicate_name, **kwargs)
        return {"error": "no detect method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# PATTERN DETECTOR
# ═══════════════════════════════════════════════════════════════════════

def detect_patterns(
    predicate_name: str = "default",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect patterns in data."""
    mod = _import_rsi("rsi_pattern_detector")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIPatternDetector"):
            detector = mod.RSIPatternDetector()
            patterns = detector.detect_patterns(predicate_name=predicate_name)
            return {"detected": True, "patterns": patterns} if patterns else {"detected": False}
        elif hasattr(mod, "detect"):
            return mod.detect(predicate_name=predicate_name, **kwargs)
        return {"error": "no detect method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# FEEDBACK LOOP
# ═══════════════════════════════════════════════════════════════════════

def feedback_loop_step(
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute one step of the feedback loop."""
    mod = _import_rsi("rsi_feedback_loop")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIFeedbackLoop"):
            loop = mod.RSIFeedbackLoop()
            result = loop.adjust_thresholds()
            return {"stepped": True, "result": result}
        elif hasattr(mod, "adjust_thresholds"):
            return mod.adjust_thresholds(**kwargs)
        return {"error": "no adjust_thresholds method found"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# COMPONENT REGISTRY
# ═══════════════════════════════════════════════════════════════════════

def register_component(
    name: str,
    component_type: str = "generic",
    component_path: str = "",
    metadata: Dict[str, Any] | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Register a component in the RSI registry."""
    mod = _import_rsi("rsi_component_registry")
    if mod is None:
        return {"error": "vsf-rsi not available"}
    try:
        if hasattr(mod, "RSIComponentRegistry"):
            registry = mod.RSIComponentRegistry()
            result = registry.register_component(
                component_type=component_type,
                component_path=component_path,
                name=name,
                metadata=metadata,
            )
            return result
        elif hasattr(mod, "register"):
            return mod.register(name=name, metadata=metadata, **kwargs)
        return {"error": "no register method found"}
    except Exception as e:
        return {"error": str(e)}


def list_components() -> List[Dict[str, Any]]:
    """List registered components."""
    mod = _import_rsi("rsi_component_registry")
    if mod is None:
        return []
    try:
        if hasattr(mod, "RSIComponentRegistry"):
            registry = mod.RSIComponentRegistry()
            return registry.get_active_components() if hasattr(registry, "get_active_components") else []
        elif hasattr(mod, "list_all"):
            return mod.list_all()
        return []
    except Exception:
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
