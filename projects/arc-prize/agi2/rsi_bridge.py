#!/usr/bin/env python3
# design: projects/arc-prize/knowledge/viarc_covenant.vsm
"""rsi_bridge.py — RSI runtime bridge (M2): pattern memory + tool certify.

Loads RSI-learned strategies from pattern_memory.json and presents them
as candidates to agent.py. M2 additions:
  * path resolution: /kaggle/working (kernel) first, then local fallbacks
  * certify_tool(): LOO-certify candidate code BEFORE it enters memory
    (certify-first applies to the toolbox, not just grids — covenant I1)
  * append_pattern(): write-back of certified tools (cross-run memory)
  * propose_tools(): execute+certify raw code strings -> candidates
Stdlib + numpy only, deterministic (R10).
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import recognizer as R  # noqa: E402

# ── Pattern memory resolution (kernel-first) ───────────────────────────

MEMORY_CANDIDATES = [
    Path("/kaggle/working/pattern_memory.json"),      # kernel working dir
    HERE / "pattern_memory.json",                      # beside the code
    HERE.parent / "arc-agi3" / "state" / "pattern_memory.json",  # legacy
]


def _memory_path() -> Path:
    for p in MEMORY_CANDIDATES:
        if p.exists():
            return p
    return MEMORY_CANDIDATES[0]  # default write target: kernel working


def _load_rsi_patterns():
    """Load active RSI/LLM-proposed patterns from pattern memory."""
    path = _memory_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            k: v for k, v in data.get("patterns", {}).items()
            if v.get("status") == "active"
            and v.get("source") in ("llm_proposed", "rsi_generated",
                                    "tool_certified")
        }
    except Exception:
        return {}


def append_pattern(name: str, code: str, source: str = "tool_certified",
                   extra: dict = None) -> bool:
    """Write-back a certified tool into pattern memory (append, atomic-ish).

    Memory persists in kernel working dir (exported post-run) and locally
    (cross-version library growth). Never raises.
    """
    path = _memory_path()
    try:
        data = {}
        if path.exists():
            with open(path) as f:
                data = json.load(f)
        pats = data.setdefault("patterns", {})
        entry = {"code": code, "status": "active", "source": source,
                 "certified_at": round(time.time(), 1)}
        if extra:
            entry.update(extra)
        pats[name] = entry
        data["updated_at"] = entry["certified_at"]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ── Sandbox execution (restricted builtins + whitelisted imports) ──────

def _try_rsi_strategy(code_str, trains, test):
    """Execute RSI-generated strategy in a restricted sandbox."""
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
        if result is None:
            return None
        if isinstance(result, np.ndarray):
            return result.tolist()
        if isinstance(result, (list, tuple)) and result:
            return [list(row) for row in result]
    except Exception:
        pass
    return None


def certify_tool(code_str, trains, min_loo=0.5) -> float:
    """Covenant I1 for tools: LOO fraction of proposed code (0.0 if dead)."""
    if not code_str:
        return 0.0
    try:
        fn = lambda tr, t: _try_rsi_strategy(code_str, tr, t)  # noqa: E731
        # safe_apply path: verify_loo_fraction calls fn on held-outs
        return float(R.verify_loo_fraction(fn, trains))
    except Exception:
        return 0.0


def propose_tools(trains, test, code_strs, min_loo=0.5, max_tools=2):
    """Execute+certify candidate code strings -> agent-compatible cands.

    Only tools with LOO >= min_loo are returned (uncertified code never
    competes). Best-first, deterministic order.
    """
    out = []
    for ci, code in enumerate(code_strs or []):
        if len(out) >= max_tools:
            break
        grid = _try_rsi_strategy(code, trains, test)
        if grid is None:
            continue
        try:
            loo = certify_tool(code, trains, min_loo)
        except Exception:
            loo = 0.0
        if loo < min_loo:
            continue
        try:
            key = tuple(tuple(r) for r in grid)
        except Exception:
            continue
        out.append({"grid": grid, "key": key,
                    "dynamic": f"rsi:tool{ci}",
                    "fn_name": f"rsi_tool{ci}",
                    "loo_frac": loo, "prior": 0.5,
                    "code": code})
    out.sort(key=lambda c: -c["loo_frac"])
    return out


def rsi_propose(trains, test, max_candidates=3):
    """Generate candidates from stored RSI-learned patterns.

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

        # Quick LOO check (stored prior does not waive re-verification)
        try:
            loo_f = certify_tool(code, trains)
        except Exception:
            loo_f = 0.0

        candidates.append({
            "grid": grid,
            "key": key,
            "dynamic": f"rsi:{name}",
            "fn_name": f"rsi_{name}",
            "loo_frac": loo_f,
            "prior": 0.5,
        })

    return candidates


def has_rsi_strategies():
    """Check if any RSI strategies are available."""
    return bool(_load_rsi_patterns())


if __name__ == "__main__":  # pragma: no cover
    print("memory path:", _memory_path(),
          "| patterns:", len(_load_rsi_patterns()))
