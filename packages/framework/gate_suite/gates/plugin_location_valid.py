"""plugin-location-valid gate — REBUILT with real negative control.

vsf's original `checks/plugin-location-valid` had a BROKEN negative control:
it could not discriminate a violating plugin from a valid one, so it was a
no-op. This version is a genuine discriminator: a plugin MUST live under
`plugins/<category>/` where <category> ∈ {core, operational, manual, support}.
Any other location is rejected.

Run by the harness: its negative case is a plugin placed under a disallowed
category; the gate MUST reject it (exit != 0).
"""

from __future__ import annotations

import os
import tempfile

from gate_suite.harness import register

ALLOWED_CATEGORIES = {"core", "operational", "manual", "support"}


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED.

    Policy: only files under a `plugins/<category>/` tree are in scope, and
    <category> must be an allowed one.
    """
    norm = os.path.normpath(path)
    parts = norm.split(os.sep)
    if "plugins" not in parts:
        return 0  # not a plugin artifact; out of scope -> accept
    idx = parts.index("plugins")
    if idx + 1 >= len(parts):
        return 1  # plugins/ root with no category -> reject
    category = parts[idx + 1]
    return 0 if category in ALLOWED_CATEGORIES else 1


def negative_case() -> str:
    """A plugin mislocated under a disallowed category (WRONG)."""
    root = tempfile.mkdtemp(prefix="voslab_")
    bad_dir = os.path.join(root, "plugins", "WRONG")
    os.makedirs(bad_dir, exist_ok=True)
    p = os.path.join(bad_dir, "myplugin.ts")
    with open(p, "w") as f:
        f.write("export const handler = {};")
    return p


def positive_case() -> str:
    """A plugin correctly located under an allowed category (core)."""
    root = tempfile.mkdtemp(prefix="voslab_")
    good_dir = os.path.join(root, "plugins", "core")
    os.makedirs(good_dir, exist_ok=True)
    p = os.path.join(good_dir, "myplugin.ts")
    with open(p, "w") as f:
        f.write("export const handler = {};")
    return p


register("plugin-location-valid", check, negative_case)
