#!/usr/bin/env python3
"""
eval_tree_vsf.py — VSF wrapper around socratic-engine eval-tree.

Loads VSF-specific predicates (vsf_predicates.register_predicates) before
evaluating a tree, so socratic-engine stays domain-agnostic.

Usage (mirrors engine eval-tree):
  python3 eval_tree_vsf.py <tree.vsm|tree.json> [--doc-type TYPE] [--context JSON]

Context can also be passed via SOCRATIC_CTX environment variable (JSON string).
This is used by decide.py to pass context without shell escaping.

Returns JSON: {"decision": bool, "certified": bool, "source": str, ...}
Exit code: 0 if tree evaluated, 1 on error.
"""

import json
import sys
import os
from pathlib import Path

# socratic-engine is installed as a package — no sys.path hack needed
from socratic_engine import SocraticEngine

# Add scripts dir to path for local predicate modules
SCRIPTS_DIR = Path(__file__).parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# vsl_tree_loader: strips VSL `//` comments before parse (errors.txt
# 2026-10-03: inline comments in classify.tree.vsm children parsed as
# nodos "//" → ValueError en evaluate con doc-types sin short-circuit).
# Path-tolerant: gap-resolver code-classification may relocate the
# module (classifier/ ↔ tools/) — both homes are searched.
try:
    from vsl_tree_loader import load_tree_file
except ModuleNotFoundError:
    _tools_dir = Path(__file__).resolve().parents[1] / "tools"
    if str(_tools_dir) not in sys.path:
        sys.path.insert(0, str(_tools_dir))
    from vsl_tree_loader import load_tree_file

# Load VSF predicates (classifier + hook-specific)
import vsf_predicates
import vsf_hooks_predicates


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: eval_tree_vsf.py <tree> [--doc-type TYPE] [--context JSON]", file=sys.stderr)
        return 1

    tree_path = argv[0]
    doc_type = None
    context = {}

    i = 1
    while i < len(argv):
        if argv[i] == "--doc-type" and i + 1 < len(argv):
            doc_type = argv[i + 1]
            i += 2
        elif argv[i] == "--context" and i + 1 < len(argv):
            try:
                context = json.loads(argv[i + 1])
            except json.JSONDecodeError as e:
                print(f"invalid --context JSON: {e}", file=sys.stderr)
                return 1
            i += 2
        else:
            i += 1

    # Context from environment variable (used by decide.py)
    ctx_env = os.environ.get("SOCRATIC_CTX")
    if ctx_env:
        try:
            env_ctx = json.loads(ctx_env)
            context = {**env_ctx, **context}  # CLI overrides env
        except json.JSONDecodeError:
            pass

    if doc_type:
        context.setdefault("type", doc_type)

    engine = SocraticEngine()
    vsf_predicates.register_vsf_predicates(engine)
    vsf_hooks_predicates.register_hooks_predicates(engine)

    tree = load_tree_file(tree_path)
    if tree is None:
        print(f"ERROR: failed to load tree: {tree_path}", file=sys.stderr)
        return 1

    result = engine.evaluate(tree, context)
    out = {
        "decision": result.is_true,
        "certified": result.certified,
        "source": result.source,
        "truth": str(result.truth),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
