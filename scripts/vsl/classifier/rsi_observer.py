#!/usr/bin/env python3
"""Thin wrapper — delegates to vsf-rsi package."""
# DELEGATION: this module is a thin wrapper for backwards compatibility.
# The canonical implementation lives in ~/packages/public/vsf-rsi/vsf_rsi/
# See: https://github.com/rm-w3kufe/vsf-rsi

import sys
from pathlib import Path

# Ensure vsf-rsi package is importable
_package_dir = Path.home() / "packages" / "public" / "vsf-rsi"
if _package_dir.exists() and str(_package_dir) not in sys.path:
    sys.path.insert(0, str(_package_dir))

# Re-export everything from the package module
from vsf_rsi.rsi_observer import *

# Also re-export module-level names for direct attribute access
import vsf_rsi.rsi_observer as _mod
for _name in dir(_mod):
    if not _name.startswith('_'):
        globals()[_name] = getattr(_mod, _name)
