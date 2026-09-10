"""vsm-version-enforcer gate — REBUILT with real negative control.

This gate enforces that ALL .vsm files use the canonical protocol version
vsm-1.2.1 (not vsm-1.2, vsm-1.0, or any other version).

The gate checks:
1. Header contains `| vsm-1.2.1 |` (not `| vsm-1.2 |`)
2. @vsm declaration is `@vsm 1.2.1` (not `@vsm 1.2`)
3. Timestamp includes seconds (ISO 8601 UTC with seconds)

Root cause: Documentation used `vsm-1.2` as shorthand, leading to incorrect
version in generated files. The canonical version is vsm-1.2.1 (core_boot_primer.vsm).

Run by the harness: its negative case is a .vsm file with vsm-1.2 (no .1);
the gate MUST reject it (exit != 0).
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED.

    Policy: any .vsm file must use vsm-1.2.1 as the protocol version.
    Files that are not .vsm are out of scope and accepted.
    """
    if not path.endswith(".vsm"):
        return 0  # not a .vsm file; out of scope -> accept

    try:
        with open(path, "r") as f:
            content = f.read()
    except (OSError, IOError):
        return 1  # can't read -> reject

    # Check header: must contain `| vsm-1.2.1 |`
    header_match = re.search(r"⟦\s*\w+\s*\|\s*\S+\s*\|\s*(\S+)\s*\|\s*\S+\s*⟧", content)
    if not header_match:
        return 1  # no valid header -> reject

    version = header_match.group(1)
    if version != "vsm-1.2.1":
        return 1  # wrong version in header -> reject

    # Check @vsm declaration: must be `@vsm 1.2.1`
    vsm_decl_match = re.search(r"^@vsm\s+([\d.]+)", content, re.MULTILINE)
    if not vsm_decl_match:
        return 1  # no @vsm declaration -> reject

    vsm_version = vsm_decl_match.group(1)
    if vsm_version != "1.2.1":
        return 1  # wrong version in @vsm declaration -> reject

    # Check timestamp includes seconds
    date_match = re.search(r"⟦\s*\w+\s*\|\s*\S+\s*\|\s*\S+\s*\|\s*(\S+)\s*⟧", content)
    if date_match:
        date_str = date_match.group(1)
        # Must match ISO 8601 UTC with seconds: YYYY-MM-DDTHH:MM:SSZ
        if not re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", date_str):
            return 1  # timestamp missing seconds -> reject

    return 0  # all checks passed -> accept


def negative_case() -> str:
    """A .vsm file with vsm-1.2 (missing .1) — MUST be rejected."""
    root = tempfile.mkdtemp(prefix="voslab_")
    p = os.path.join(root, "bad_version.vsm")
    with open(p, "w") as f:
        f.write("⟦ bad_version | TEST-v1 | vsm-1.2 | 2026-01-01T00:00:00Z ⟧\n")  # hardcoded-allow: detector guts
        f.write("@vsm 1.2\n")
        f.write("@status active\n")
        f.write("// This file uses the wrong version\n")
        f.write("⟦ /bad_version ⟧\n")
    return p


def positive_case() -> str:
    """A .vsm file correctly using vsm-1.2.1."""
    root = tempfile.mkdtemp(prefix="voslab_")
    p = os.path.join(root, "good_version.vsm")
    with open(p, "w") as f:
        f.write("⟦ good_version | TEST-v1 | vsm-1.2.1 | 2026-01-01T00:00:00Z ⟧\n")  # hardcoded-allow: detector guts
        f.write("@vsm 1.2.1\n")
        f.write("@status active\n")
        f.write("// This file uses the correct version\n")
        f.write("⟦ /good_version ⟧\n")
    return p


register("vsm-version-enforcer", check, negative_case)
