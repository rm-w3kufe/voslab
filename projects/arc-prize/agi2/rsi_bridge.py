#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""rsi_bridge.py — Bridge: RSI-generated strategies → agent.py.

Carga estrategias generadas por el RSI loop (pattern_memory) y las
presenta como candidatos al agent. Stdlib-only, determinístico.

Usage:
    from rsi_bridge import rsi_propose
    candidates = rsi_propose(trains, test)
    # Returns list of {grid, key, dynamic, fn_name, loo_frac, prior}
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import numpy as np
import recognizer as R

# State directory for RSI patterns
_STATE_DIR = HERE.parent / "arc-agi3" / "state"
_MEMORY_FILE = _STATE_DIR / "pattern_memory.json"


def _load_rsi_patterns():
    """Load RSI-learned patterns from pattern_memory.json."""
    if not _MEMORY_FILE.exists():
        return {}
    try:
        with open(_MEMORY_FILE) as f:
            data = json.load(f)
        # Only return active, llm-generated patterns
        return {
            k: v for k, v in data.get("patterns", {}).items()
            if v.get("status") == "active"
            and v.get("source") in ("llm_proposed", "rsi_generated")
        }
    except Exception:
        return {}


def _try_rsi_strategy(code_str, trains, test):
    """Execute an RSI-generated strategy in a restricted sandbox."""
    safe_builtins = {
        "abs": abs, "all": all, "any": any, "bool": bool,
        "dict": dict, "enumerate": enumerate, "filter": filter,
        "float": float, "int": int, "isinstance": isinstance,
        "len": len, "list": list, "map": map, "max": max, "min": min,
        "print": print, "range": range, "round": round, "set": set,
        "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
        "type": type, "zip": zip,
    }

    def _safe_import(name, *args, **kwargs):
        mod = name.split(".")[0]
        if mod not in ("numpy", "math", "collections", "itertools"):
            raise ImportError(f"Import not allowed: {name}")
        import importlib
        return importlib.import_module(name)

    safe_builtins["__import__"] = _safe_import

    namespace = {"__builtins__": safe_builtins, "np": np, "numpy": np}
    try:
        compiled = compile(code_str, "<rsi_generated>", "exec")
        exec(compiled, namespace)
    except Exception:
        return None

    solve_fn = namespace.get("solve")
    if not callable(solve_fn):
        return None

    try:
        result = solve_fn(trains, test)
        if result is not None and isinstance(result, np.ndarray):
            return result
    except Exception:
        pass
    return None


def rsi_propose(trains, test, max_candidates=3):
    """Generate candidates from RSI-learned strategies.

    Returns list of dicts compatible with agent.py's propose() output:
        {grid, key, dynamic, fn_name, loo_frac, prior}
    """
    patterns = _load_rsi_patterns()
    if not patterns:
        return []

    candidates = []
    for name, info in list(patterns.items())[:max_candidates]:
        code = info.get("code", "")
        if not code:
            continue

        grid = _try_rsi_strategy(code, trains, test)
        if grid is None:
            continue

        try:
            key = tuple(tuple(r) for r in grid)
        except Exception:
            continue

        # Quick LOO check
        try:
            fn = lambda tr, t: _try_rsi_strategy(code, tr, t)
            loo_f = R.verify_loo_fraction(fn, trains)
        except Exception:
            loo_f = 0.0

        candidates.append({
            "grid": grid,
            "key": key,
            "dynamic": f"rsi:{name}",
            "fn_name": f"rsi_{name}",
            "loo_frac": loo_f,
            "prior": 0.5,  # RSI strategies start with neutral prior
        })

    return candidates


def has_rsi_strategies():
    """Check if any RSI strategies are available."""
    return bool(_load_rsi_patterns())
