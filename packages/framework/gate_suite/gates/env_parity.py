"""env-parity gate — D-01 (backlog system_backlog.vsm, 2026-10-01).

Declared-vs-observed parity for the execution environment: the python
version this tree is pinned to, plus the critical imports the kernel needs.
Origin: the 2026-10-01 incident where an `apt graphviz` flipped python
3.13 -> 3.14 and silently broke every user-site editable install — 41
modules drifted before any test noticed (epistemic cost: a full repair
session). An environment nobody checks is a memory that lies.

Semantics (boot_ontology pattern):
  - check(path): if path is a JSON fixture manifest, validate ITS declared
    env against the observed one; otherwise validate the embedded live
    declaration (EXPECTED_PYTHON + REQUIRED_IMPORTS).
  - negative_case(): temp JSON declaring python "9.99" and a module that
    cannot exist — must ALWAYS be rejected (exit != 0).
  - Live invocation: system/kernel/tests/test_env_parity.py calls
    check("") on every suite run, so drift goes loud in <= one test run.

Run by the harness: register("env-parity", check, negative_case).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile

from gate_suite.harness import register

# Deliberate pin: bump this (committed, visible) when the tree upgrades
# python — that is the whole point: environment changes become events.
EXPECTED_PYTHON = "3.14"
REQUIRED_IMPORTS = ("socratic_engine", "vos_kernel", "networkx")


def _observed_python() -> str:
    return ".".join(map(str, sys.version_info[:2]))


def _observed_imports(modules: list[str]) -> list[str]:
    missing: list[str] = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 — any failure is a drift
            missing.append(f"{mod} ({exc.__class__.__name__})")
    return missing


def check(path: str) -> int:
    """Return 0 if the declared environment matches the observed one."""
    declared = {"python": EXPECTED_PYTHON, "imports": list(REQUIRED_IMPORTS)}
    if path and path.endswith(".json") and os.path.exists(path):
        try:
            with open(path) as fh:
                declared = json.load(fh)
        except (OSError, ValueError):
            sys.stderr.write(f"env-parity: unreadable manifest {path}\n")
            return 1

    fails: list[str] = []
    observed = _observed_python()
    if declared.get("python") != observed:
        fails.append(f"python declared={declared.get('python')} observed={observed}")
    fails.extend(f"import {_m}" for _m in _observed_imports(declared.get("imports", [])))
    if fails:
        sys.stderr.write("env-parity drift: " + "; ".join(fails) + "\n")
        return 1
    return 0


def negative_case() -> str:
    """A manifest declaring an env that can never match reality."""
    fd, p = tempfile.mkstemp(prefix="env_parity.", suffix=".json",
                             dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as fh:
        json.dump({"python": "9.99",
                   "imports": ["definitely_missing_module_xyz"]}, fh)
    return p


register("env-parity", check, negative_case)
