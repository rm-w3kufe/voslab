#!/usr/bin/env python3
"""
socratic_engine.py — Wrapper for the real socratic engine.

This module imports from the real socratic engine and provides a wrapper
for backward compatibility.

The actual engine should be installed:
  pip install -e ~/socratic-engine/
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Try to import from the installed socratic engine package first
try:
    from socratic_engine import SocraticEngine as _RealEngine
    from socratic_engine import Truth, PredicateResult
    from socratic_engine.tree import load_tree
    _HAS_REAL_ENGINE = True
except ImportError:
    # Fall back to looking in common locations
    _SOCRATIC_ENGINE_DIR = Path(os.environ.get("SOCRATIC_ENGINE_DIR", Path.home() / "socratic-engine"))
    if _SOCRATIC_ENGINE_DIR.exists() and str(_SOCRATIC_ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(_SOCRATIC_ENGINE_DIR))

    try:
        from socratic_engine import SocraticEngine as _RealEngine
        from socratic_engine import Truth, PredicateResult
        from socratic_engine.tree import load_tree
        _HAS_REAL_ENGINE = True
    except ImportError:
        _HAS_REAL_ENGINE = False
        _RealEngine = None


def _create_engine(engine_path: Optional[str] = None) -> "SocraticEngine":
    """Create a socratic engine instance."""
    return SocraticEngine(engine_path)


class SocraticEngine:
    """Wrapper for the real socratic engine."""
    
    def __init__(self, engine_path: Optional[str] = None):
        self.engine_path = Path(engine_path) if engine_path else _SOCRATIC_ENGINE_DIR
        if _HAS_REAL_ENGINE:
            self._engine = _RealEngine()
        else:
            self._engine = None
    
    def evaluate_tree(self, tree: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Evaluate a socratic tree against context.
        
        Args:
            tree: Socratic tree structure
            context: Evaluation context
            
        Returns:
            Dict with truth, certified, and explanation
        """
        if self._engine is None:
            return {
                "truth": "UNKNOWN",
                "certified": False,
                "explanation": "Real socratic engine not available at ~/socratic-engine/",
                "source": "stub"
            }
        
        context = context or {}
        result = self._engine.evaluate(tree, context)
        
        return {
            "truth": str(result.truth),
            "certified": result.certified,
            "explanation": result.explain(),
            "source": result.source,
            "home": result.home,
            "unknown": result.unknown,
        }
    
    def parse_tree(self, tree_str: str) -> Dict[str, Any]:
        """Parse a VSL tree string."""
        try:
            return json.loads(tree_str)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON"}


# Module-level root for backward compatibility
_ROOT = Path(__file__).parent


if __name__ == "__main__":
    # Basic CLI for testing
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "parse-tree":
            content = sys.stdin.read()
            engine = _create_engine()
            result = engine.parse_tree(content)
            print(json.dumps(result))
        elif command == "eval-tree":
            content = sys.stdin.read()
            engine = _create_engine()
            result = engine.evaluate_tree({"raw": content})
            print(json.dumps(result))
        else:
            print(json.dumps({"error": f"Unknown command: {command}"}))
    else:
        print(json.dumps({"error": "No command provided"}))
