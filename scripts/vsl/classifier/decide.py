#!/usr/bin/env python3
"""decide.py — CLI for evaluating decisions through socratic engine.

Usage:
    python3 scripts/vsl/classifier/decide.py --decision "..." [options]

Options:
    --decision TEXT       The decision to evaluate (required)
    --alternatives TEXT   Comma-separated alternatives
    --impact TEXT         Impact description
    --reversible BOOLEAN Whether decision is reversible (default: true)
    --prerequisites TEXT  Comma-separated prerequisites
    --skip-alternatives   Skip alternatives check
    --skip-impact         Skip impact check
    --skip-approval       Skip approval check (for reversible)
    --json                Output as JSON
    --help                Show this help

Examples:
    # Simple reversible decision
    python3 scripts/vsl/classifier/decide.py --decision "Use JSONL for logging"
    
    # Complex irreversible decision
    python3 scripts/vsl/classifier/decide.py \
        --decision "Restructure docs/ directory" \
        --alternatives "Keep as is,Reorganize by topic,Reorganize by date" \
        --impact "All documentation references" \
        --reversible false \
        --prerequisites "Backup created,User approved"
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Path setup — decide.py lives at scripts/vsl/classifier/decide.py
REPO_ROOT = Path(__file__).parent.parent.parent.parent  # → vOSlab/
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "vsl" / "classifier" / "eval_tree_vsf.py"
TREE_FILE = REPO_ROOT / ".opencode" / "plugins" / "support" / "trees" / "decide.tree.vsm"


def build_context(args: argparse.Namespace) -> dict:
    """Build evaluation context from CLI arguments."""
    ctx = {
        "decision": args.decision,
    }
    
    if args.alternatives:
        ctx["alternatives"] = args.alternatives.split(",")
    
    if args.impact:
        ctx["impact"] = args.impact
    
    if args.prerequisites:
        ctx["prerequisites"] = args.prerequisites.split(",")
    
    ctx["reversible"] = str(args.reversible).lower()
    
    if args.skip_alternatives:
        ctx["skip_alternatives"] = "true"
    
    if args.skip_impact:
        ctx["skip_impact"] = "true"
    
    if args.skip_approval:
        ctx["skip_approval"] = "true"
    
    return ctx


def evaluate_tree(ctx: dict) -> dict:
    """Evaluate the decide tree with the given context."""
    if not ENGINE_SCRIPT.exists():
        return {"error": f"Engine not found: {ENGINE_SCRIPT}"}
    
    if not TREE_FILE.exists():
        return {"error": f"Tree not found: {TREE_FILE}"}
    
    # Build command
    cmd = [
        "python3",
        str(ENGINE_SCRIPT),
        str(TREE_FILE),
        "--doc-type", "DECIDE",
    ]
    
    # Add context as environment variable
    env = os.environ.copy()
    env["SOCRATIC_CTX"] = json.dumps(ctx)
    # Ensure local site-packages is in PYTHONPATH for editable installs
    local_site = Path.home() / ".local" / "lib" / "python3.13" / "site-packages"
    if local_site.exists():
        current_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(local_site) + (f":{current_pp}" if current_pp else "")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(REPO_ROOT),
        )
        
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        
        return json.loads(result.stdout)
    
    except subprocess.TimeoutExpired:
        return {"error": "Evaluation timed out"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON output: {e}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate decisions through socratic engine"
    )
    parser.add_argument("--decision", required=True, help="The decision to evaluate")
    parser.add_argument("--alternatives", help="Comma-separated alternatives")
    parser.add_argument("--impact", help="Impact description")
    parser.add_argument("--reversible", type=bool, default=True, help="Whether reversible")
    parser.add_argument("--prerequisites", help="Comma-separated prerequisites")
    parser.add_argument("--skip-alternatives", action="store_true", help="Skip alternatives check")
    parser.add_argument("--skip-impact", action="store_true", help="Skip impact check")
    parser.add_argument("--skip-approval", action="store_true", help="Skip approval check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    # Build context
    ctx = build_context(args)
    
    # Evaluate
    result = evaluate_tree(ctx)
    
    # Output
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        truth = result.get("truth", "UNKNOWN")
        certified = result.get("certified", False)
        home = result.get("home", "unknown")
        
        if truth == "TRUE" and certified:
            print(f"✓ DECISION CERTIFIED: {home}")
            print(f"  Decision: {args.decision}")
        elif truth == "FALSE" and certified:
            print(f"✗ DECISION REJECTED: {home}")
            print(f"  Decision: {args.decision}")
            print(f"  Reason: {result.get('detail', 'No detail provided')}")
        else:
            print(f"? DECISION UNCERTAIN: {home}")
            print(f"  Decision: {args.decision}")
    
    # Exit code
    sys.exit(0 if result.get("truth") == "TRUE" else 1)


if __name__ == "__main__":
    main()
