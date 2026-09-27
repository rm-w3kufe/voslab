#!/usr/bin/env python3
"""
vsf_socratic_engine.py — VSF shim delegating to socratic-engine package.

All logic lives in the installed socratic-engine package (0.2.4+).
Custom VSF predicates are registered via vsf_predicates.py.

Benefits:
  - DIALECTICAL_AND operator available
  - PredicateCache with TTL
  - More builtins (type_glob, type_prefix, trend_up/down, etc.)
  - Single source of truth (~/socratic-engine)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Import from installed package
from socratic_engine import (
    Evaluation,
    FailureTrace,
    PredicateResult,
    SocraticEngine,
    Truth,
    find_failure_traces,
    parse_socratic_block,
    tree_home,
)

# Register VSF custom predicates
from vsf_predicates import register_vsf_predicates


def _create_engine() -> SocraticEngine:
    """Create engine with VSF custom predicates registered."""
    engine = SocraticEngine()
    register_vsf_predicates(engine)
    return engine


def _clean_tree(node):
    """Remove VSL comments (// ...) from parsed tree.
    
    The VSM parser splits comments into individual words. We filter out
    any string nodes that are not valid socratic nodes (dict with 'op' or 'predicate').
    """
    if isinstance(node, str):
        # Filter out any string (comment fragments)
        return None
    if isinstance(node, bool):
        return node
    if isinstance(node, dict):
        cleaned = {}
        for k, v in node.items():
            if k == "children":
                cleaned_children = []
                for child in v:
                    cleaned_child = _clean_tree(child)
                    if cleaned_child is not None:
                        cleaned_children.append(cleaned_child)
                cleaned[k] = cleaned_children
            else:
                cleaned[k] = v
        return cleaned
    return node


# ============================================================
# CLI
# ============================================================

def _eval_tree_cli(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: vsf_socratic_engine.py eval-tree <tree.vsm|tree.json> "
              "[--context <json>] [--doc-type <TYPE>]", file=sys.stderr)
        return 2
    tree_path = Path(argv[0])
    if not tree_path.exists():
        print(f"tree not found: {tree_path}", file=sys.stderr)
        return 2
    ctx: dict = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--context" and i + 1 < len(argv):
            try:
                ctx = json.loads(argv[i + 1])
            except json.JSONDecodeError as e:
                print(f"context is not valid JSON: {e}", file=sys.stderr)
                return 2
            i += 2
        elif argv[i] == "--doc-type" and i + 1 < len(argv):
            ctx["type"] = argv[i + 1]
            i += 2
        else:
            i += 1
    # tree: .json → direct dict; .vsm → parse_socratic_block
    if tree_path.suffix == ".json":
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    else:
        tree = parse_socratic_block(tree_path.read_text(encoding="utf-8"))
    if tree is None:
        print("no socratic(...) block found in tree file", file=sys.stderr)
        return 2
    # Clean VSL comments from tree
    tree = _clean_tree(tree)
    eng = _create_engine()
    try:
        ev = eng.evaluate(tree, ctx)
    except (ValueError, KeyError, TypeError) as e:
        print(f"evaluation error: {e}", file=sys.stderr)
        return 1
    out: dict = {
        "truth": ev.truth.name if hasattr(ev.truth, "name") else str(ev.truth),
        "certified": ev.certified,
        "unknown": ev.is_unknown,
        "home": tree_home(tree, ctx.get("type", ""), eng, ctx),
        "explain": ev.explain(),
        "diagnose": [t.to_dict() if hasattr(t, "to_dict") else str(t)
                     for t in eng.diagnose(tree, ctx)],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ============================================================
# Selftest (R4.1)
# ============================================================

def _run_selftest():
    """Quick selftest: verify engine loads and basic evaluation works."""
    eng = _create_engine()
    # Test basic AND evaluation
    tree = {"op": "AND", "children": [
        {"predicate": "ctx_has", "args": ["$ctx", "test"]},
    ]}
    ev = eng.evaluate(tree, {"test": "value"})
    assert ev.truth == Truth.TRUE, f"selftest failed: expected TRUE, got {ev.truth}"
    assert ev.certified, "selftest failed: expected certified"
    # Test DIALECTICAL_AND
    tree_dialectical = {"op": "DIALECTICAL_AND", "children": [
        {"predicate": "ctx_has", "args": ["$ctx", "a"]},
        {"predicate": "ctx_equals", "args": ["$ctx", "b", "wrong"]},
    ]}
    ev_d = eng.evaluate(tree_dialectical, {"a": "yes", "b": "other"})
    assert ev_d.truth == Truth.UNKNOWN, f"DIALECTICAL_AND test failed: expected UNKNOWN, got {ev_d.truth}"
    print("selftest passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "eval-tree":
        sys.exit(_eval_tree_cli(sys.argv[2:]))
    # quick selftest (R4.1: the instrument verifies itself)
    _run_selftest()
