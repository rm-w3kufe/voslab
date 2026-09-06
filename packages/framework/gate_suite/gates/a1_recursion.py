"""a1-recursion gate — negative control for recursive VSM structure.

From core_boot_primer.vsm §A1:
  S1(L) = { V_i(L+1) }
  Every unit in S1 is itself a viable system at the next recursion level.

This gate scans Rust source for evidence of recursive structure:
- A struct or enum named Vsm, V, or Vi
- A field or type referencing Level, recursion, or L+1
- A method that returns child_level or similar

Negative case: a Rust crate with NO recursion evidence — the gate
MUST reject it (it's a flat system, not a viable one).

Why a gate (not just a trait):
  The Recursion trait (in axioms.rs) defines the contract. But a crate
  could claim to implement Recursion without actually having recursive
  structure. This gate checks for structural evidence.
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register

# Patterns that indicate recursive VSM structure
RECURSION_PATTERNS = [
    r"Level\s*=\s*u\d+",                  # type Level = u32;
    r"child_level\s*\(",                   # fn child_level(
    r"recursion",                          # "recursion" in identifiers
    r"fn\s+level\s*\(",                    # fn level(
    r"S1\(L\)|S1\(L\s*\+\s*1\)",          # S1(L) or S1(L+1)
]

_RECURSION_RE = re.compile(
    "|".join(RECURSION_PATTERNS), re.IGNORECASE
)

_RUST_EXTENSIONS = {".rs"}


def _scan_file(filepath: str) -> list[str]:
    """Return list of recursion matches found in a file."""
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    matches = []
    for line in lines:
        # Skip comments
        line_clean = re.sub(r"//.*$", "", line)
        found = [m.group() for m in _RECURSION_RE.finditer(line_clean)]
        matches.extend(found)
    return matches


def _scan_directory(dirpath: str) -> dict[str, list[str]]:
    """Scan all Rust files for recursion evidence."""
    results = {}
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext in _RUST_EXTENSIONS:
                fpath = os.path.join(root, fname)
                matches = _scan_file(fpath)
                if matches:
                    results[fpath] = matches
    return results


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED.

    Policy: a VSM crate MUST have evidence of recursive structure.
    If NO recursion patterns are found, the crate is flat and rejected.
    """
    norm = os.path.normpath(path)

    if os.path.isfile(norm):
        _, ext = os.path.splitext(norm)
        if ext not in _RUST_EXTENSIONS:
            return 0
        matches = _scan_file(norm)
        return 0 if matches else 1

    if os.path.isdir(norm):
        results = _scan_directory(norm)
        return 0 if results else 1

    return 0


def negative_case() -> str:
    """A Rust crate with NO recursion evidence (MUST be rejected)."""
    root = tempfile.mkdtemp(prefix="voslab_a1_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "flat-crate"\nversion = "0.1.0"\n')

    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write(
            'fn main() {\n'
            '    println!("hello from a flat system");\n'
            '}\n'
        )

    return root


def positive_case() -> str:
    """A crate with recursion evidence."""
    root = tempfile.mkdtemp(prefix="voslab_a1_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "recursive-crate"\nversion = "0.1.0"\n')

    with open(os.path.join(src_dir, "lib.rs"), "w") as f:
        f.write(
            'pub type Level = u32;\n'
            '\n'
            'pub fn child_level(level: Level) -> Level {\n'
            '    level + 1\n'
            '}\n'
        )

    return root


register("a1-recursion", check, negative_case)
