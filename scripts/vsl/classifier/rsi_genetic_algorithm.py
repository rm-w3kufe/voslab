#!/usr/bin/env python3
"""Thin wrapper — delegates to vsf-rsi package, defaults from ga_config."""
# DELEGATION: this module is a thin wrapper for backwards compatibility.
# The canonical implementation lives in ~/packages/public/vsf-rsi/vsf_rsi/
# See: https://github.com/rm-w3kufe/vsf-rsi
#
# D-06 FASE C2: constructor/evolution defaults are NOT literals here —
# they read ga_config.GA_PARAMS (single source of truth) at call time.

import sys
from pathlib import Path

# Ensure vsf-rsi package is importable
_package_dir = (Path(__file__).resolve().parents[3] / "packages" / "public" / "vsf-rsi")
if _package_dir.exists() and str(_package_dir) not in sys.path:
    sys.path.insert(0, str(_package_dir))

# Re-export everything from the package module
from vsf_rsi.rsi_genetic_algorithm import *

# Also re-export module-level names for direct attribute access
import vsf_rsi.rsi_genetic_algorithm as _mod
for _name in dir(_mod):
    if not _name.startswith('_'):
        globals()[_name] = getattr(_mod, _name)

# ga_config sits next to this file; register it under one shared module
# name so shims, tests and the vsf-rsi-core bridge share ONE GA_PARAMS dict.
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import ga_config  # noqa: E402


class RSIGeneticAlgorithm(_mod.RSIGeneticAlgorithm):
    """Canonical GA whose default parameters come from ga_config.GA_PARAMS.

    All defaults are read at construction/evolution time (not bound at
    import), so replacing a GA_PARAMS entry is immediately observable.
    Explicit constructor arguments always win over the declaration.
    """

    def __init__(self, population_size: int | None = None,
                 mutation_rate: float | None = None):
        params = ga_config.GA_PARAMS
        super().__init__(
            population_size=(params["population_size"]
                             if population_size is None else population_size),
            mutation_rate=(params["mutation_rate"]
                           if mutation_rate is None else mutation_rate),
        )

    def evolve_forest(self, predicate_name, generations=None, patience=None,
                      convergence_threshold=None, **kwargs):
        params = ga_config.GA_PARAMS
        call = dict(kwargs)
        call["generations"] = (params["generation_window"]
                               if generations is None else generations)
        call["patience"] = (params["patience_window"]
                            if patience is None else patience)
        if convergence_threshold is not None:
            call["convergence_threshold"] = convergence_threshold
        return super().evolve_forest(predicate_name, **call)
