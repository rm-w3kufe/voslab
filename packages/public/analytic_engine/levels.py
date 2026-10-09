"""levels.py — Analysis levels (L1-L5), scalable plug-in registry.

Levels are lazy-loaded to keep core fast.

L1: claim extraction + routing (claim_ingest) - ALWAYS RUNS
L2: theorem parsing (hypothesis → conclusion)
L3: symbolic verification (SymPy/Z3)
L4: theory-experiment correlation
L5: cross-source reasoning

Each level is a callable: level(text, context) -> dict
"""

from __future__ import annotations
from typing import Callable, Any

# Registry: level_name -> loader function
_LEVEL_REGISTRY: dict[str, Callable[[], Callable]] = {}

# Analysis result type
AnalysisResult = dict[str, Any]


def register_level(name: str, loader: Callable[[], Callable]) -> None:
    """Register a level loader.
    
    Args:
        name: Level name (e.g., "L1", "L2")
        loader: Callable that returns the level function
    """
    _LEVEL_REGISTRY[name] = loader


def get_level(name: str) -> Callable:
    """Get level function by name (lazy load).
    
    Args:
        name: Level name (e.g., "L1")
        
    Returns:
        Level function: fn(text, context) -> AnalysisResult
        
    Raises:
        KeyError: If level not registered
    """
    if name not in _LEVEL_REGISTRY:
        raise KeyError(f"Level not registered: {name}. Available: {list(_LEVEL_REGISTRY)}")
    
    # Lazy load and cache
    level_fn = _LEVEL_REGISTRY[name]()
    _LEVEL_REGISTRY[name] = lambda: level_fn  # Cache
    return level_fn


def available_levels() -> list[str]:
    """List available level names."""
    return list(_LEVEL_REGISTRY.keys())


# ─── Built-in L1 ──────────────────────────────────────────────────────────────

def _load_l1() -> Callable:
    """Load L1: claim extraction + routing via claim_ingest."""
    def l1(text: str, context: dict) -> AnalysisResult:
        """Extract claims and route them.
        
        Returns:
            {
                "claims": [...],
                "routes": [...],
                "coverage": {...},
                "internal": {...},
                "ledger": "...",
            }
        """
        # Import here to avoid circular dependencies
        import sys
        from pathlib import Path
        
        # Add packages/framework to path (file -> analytic_engine -> public
        # -> packages; parents[2] == packages)
        framework_path = str(Path(__file__).resolve().parents[2] / "framework")
        if framework_path not in sys.path:
            sys.path.insert(0, framework_path)
        
        from claim_ingest.pipeline import ingest_text
        from claim_ingest.ledger.ledger import repo_root as _repo_root
        
        name = context.get("name", "unnamed")
        subject = context.get("subject")
        risk = context.get("risk", "exploratory")
        register = context.get("register", False)
        route = context.get("route", True)
        ledger_path = context.get("ledger_path")
        
        # persist: read -> EXPLICIT ledger (claim_ingest proposal line 9).
        # Central sidecar named by the raw stem — find_sidecar() looks for
        # `sidecars/<stem>.claims.vsm` with the artifact's original case.
        if ledger_path is None and context.get("persist"):
            ledger_path = (
                Path(_repo_root()) / "state" / "epistemic" / "sidecars"
                / f"{Path(name).stem}.claims.vsm"
            )
        
        result = ingest_text(
            text,
            name=name,
            subject=subject,
            risk=risk,
            register=register,
            route=route,
            ledger_path=ledger_path,
        )
        
        return {
            "level": "L1",
            "claims": result["claims"],
            "routes": result["routes"],
            "coverage": result["coverage"],
            "internal": result["internal"],
            "ledger": result["ledger"],
            "ledger_path": result["ledger_path"],
            "ledger_status": result["ledger_status"],
            "source_id": result["source_id"],
            "fingerprint": result["fingerprint"],
        }
    
    return l1


# Register built-in levels
register_level("L1", _load_l1)

# L2-L5: placeholders for future implementation
# register_level("L2", _load_l2)  # theorem parsing
# register_level("L3", _load_l3)  # symbolic verification
# register_level("L4", _load_l4)  # theory-experiment correlation
# register_level("L5", _load_l5)  # cross-source reasoning
