"""script_predicates.py — Script analysis predicates.

Ported from child/scripts/vsl/classifier/vsf_hooks_predicates.py
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict


# ═══════════════════════════════════════════════════════════════════════
# SCRIPT PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def script_analyze(content: str) -> Dict[str, Any]:
    """Analyze script content and return metadata."""
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", content or "", re.M)
    return {
        "imports": imports,
        "has_main": "if __name__" in (content or ""),
        "has_tree": "socratic(" in (content or ""),
        "size": len(content or ""),
    }


def script_has_tree(name: str, trees_dir: str | None = None) -> bool:
    """True if a socratic tree exists for this script."""
    if trees_dir is None:
        trees_dir = os.path.expanduser("~/.opencode/plugins/support/trees")
    tree_path = os.path.join(trees_dir, f"{name}.tree.vsm")
    return os.path.exists(tree_path)


def script_needs_integration(analysis: Dict[str, Any]) -> bool:
    """True if script needs integration (large or many imports)."""
    if not isinstance(analysis, dict):
        return False
    return analysis.get("size", 0) > 500 or len(analysis.get("imports", [])) > 5


def script_classify(analysis: Dict[str, Any]) -> str:
    """Classify script based on analysis."""
    if not isinstance(analysis, dict):
        return "UNKNOWN"
    if analysis.get("has_tree"):
        return "HAS_TREE"
    if analysis.get("has_main"):
        return "STANDALONE"
    return "MODULE"


def script_read(path: str) -> str:
    """Read script content from file."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
# STAGING PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def staging_has_scripts(staging_dir: str) -> bool:
    """True if staging directory contains Python scripts."""
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".py") for f in os.listdir(staging_dir))


def staging_has_docs(staging_dir: str) -> bool:
    """True if staging directory contains VSM documents."""
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".vsm") for f in os.listdir(staging_dir))


def staging_read_doc(path: str) -> str:
    """Read document content from staging."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
# VERSION / CHANGE PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def spec_changed(change_type: str) -> bool:
    """True if change type is spec/language/vsl."""
    return str(change_type).lower() in ("spec", "language", "vsl")


def version_bumped(file_path: str) -> bool:
    """True if file version > 1.2.1."""
    try:
        with open(file_path, encoding="utf-8") as fh:
            content = fh.read()
        m = re.search(r"@vsm\s+([\d.]+)", content)
        if not m:
            return False
        version = [int(x) for x in m.group(1).split(".")]
        return version > [1, 2, 1]
    except Exception:
        return False


def code_updated(change_type: str) -> bool:
    """True if change type is code/spec/language/parser."""
    return str(change_type).lower() in ("code", "spec", "language", "parser")


def plugins_updated(change_type: str) -> bool:
    """True if change type is plugins/code/spec/hook."""
    return str(change_type).lower() in ("plugins", "code", "spec", "hook")


def changelog_updated(file_path: str, date_str: str = "2026-09-06") -> bool:
    """True if changelog contains the given date string."""
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, encoding="utf-8") as fh:
            return date_str in fh.read()
    except Exception:
        return False
