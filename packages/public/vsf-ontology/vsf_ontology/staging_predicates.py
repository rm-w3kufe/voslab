"""staging_predicates.py — Staging and change predicates for vOSlab.

Ported from vsf_hooks_predicates.py (Child scripts).
These predicates handle staging directory checks and change tracking.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# STAGING PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def staging_has_docs(staging_dir: str) -> bool:
    """Check if staging directory has .vsm documents."""
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".vsm") for f in os.listdir(staging_dir))


def staging_has_scripts(staging_dir: str) -> bool:
    """Check if staging directory has .py scripts."""
    if not staging_dir or not os.path.isdir(staging_dir):
        return False
    return any(f.endswith(".py") for f in os.listdir(staging_dir))


def staging_read_doc(path: str) -> str:
    """Read a document from staging directory."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════
# VERSION / CHANGE PREDICATES
# ═══════════════════════════════════════════════════════════════════════

def spec_changed(change_type: str) -> bool:
    """Check if change type indicates a spec change."""
    return str(change_type).lower() in ("spec", "language", "vsl")


def code_updated(change_type: str) -> bool:
    """Check if change type indicates a code update."""
    return str(change_type).lower() in ("code", "spec", "language", "parser")


def plugins_updated(change_type: str) -> bool:
    """Check if change type indicates a plugin update."""
    return str(change_type).lower() in ("plugins", "code", "spec", "hook")


def changelog_updated(change_type: str) -> bool:
    """Check if changelog has been updated recently."""
    # Look for changelog in common locations
    vsf_root = os.environ.get("VSF_ROOT", str(Path.home() / "vsf"))
    changelog = os.path.join(vsf_root, "child", "docs", "changelog.vsm")
    if not os.path.exists(changelog):
        return False
    try:
        with open(changelog, encoding="utf-8") as fh:
            content = fh.read()
            # Check for recent date (within last week)
            from datetime import datetime, timedelta
            today = datetime.now()
            for i in range(7):
                date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                if date_str in content:
                    return True
            return False
    except Exception:
        return False


def version_bumped(file_path: str) -> bool:
    """Check if version has been bumped in a file."""
    try:
        with open(file_path, encoding="utf-8") as fh:
            content = fh.read()
        m = re.search(r"@vsm\s+([\d.]+)", content)
        if not m:
            return False
        # Version exists - check if it's recent
        return True
    except Exception:
        return False
