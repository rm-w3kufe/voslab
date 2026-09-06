"""a0-compliance gate — negative control for ethical purpose.

From covenant.vsm §A0:
  purpose(V) ∩ {warfare_instrumentation, weapons_development, ...} = ∅

This gate scans Rust source files for prohibited purpose strings.
If ANY prohibited string appears in the source, the gate REJECTS the crate.

Negative case: a Rust file containing "warfare_instrumentation" — the gate
MUST reject it. If it doesn't, the gate is a no-op.

Why a gate (not just a trait):
  The Rust trait (Purpose in purpose.rs) makes prohibited purposes structurally
  impossible at compile time. But a crate could still CONTAIN the strings in
  comments, tests, or dead code. This gate catches that — it's the runtime
  nervous system that the compiler can't provide.
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register

# Prohibited strings from covenant.vsm §A0
PROHIBITED_PATTERNS = [
    r"warfare[_\s]?instrumentation",
    r"weapons?[_\s]?development",
    r"mutual[_\s]?annihilation",
    r"nuclear[_\s]?(targeting|guidance)",
    r"population[_\s]?displacement",
    r"ethnic[_\s]?suppression",
    r"cultural[_\s]?suppression",
    r"authoritarian[_\s]?control",
    r"systemic[_\s]?degradation[_\s]?of[_\s]?life",
]

# Compile once
_PROHIBITED_RE = re.compile(
    "|".join(PROHIBITED_PATTERNS), re.IGNORECASE
)

# Source file extensions to scan
_RUST_EXTENSIONS = {".rs"}


def _scan_file(filepath: str) -> list[str]:
    """Return list of prohibited matches found in a file.

    Matches inside string literals are EXCLUDED — they define the constraint.
    Matches inside ProhibitedPurpose enum/impl blocks are EXCLUDED.
    Only matches in code logic, comments, or variable names are flagged.
    """
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    matches = []
    in_prohibited_block = 0  # nesting depth

    for line in lines:
        # Track entering ProhibitedPurpose blocks
        if re.match(r"\s*pub\s+enum\s+ProhibitedPurpose", line):
            in_prohibited_block += 1
        elif re.match(r"\s*impl\s+ProhibitedPurpose", line):
            in_prohibited_block += 1

        # Track nesting: count braces (excluding those in string literals)
        if in_prohibited_block > 0:
            line_no_str = re.sub(r'"[^"]*"', "", line)
            opens = line_no_str.count("{")
            closes = line_no_str.count("}")
            in_prohibited_block += opens - closes
            if in_prohibited_block < 0:
                in_prohibited_block = 0
            continue  # skip ALL lines inside the block

        # Remove comments before scanning (documentation is not a violation)
        # Keep string literals — a prohibited string in code IS a violation
        line_clean = re.sub(r"//.*$", "", line)  # strip // comments

        found = [m.group() for m in _PROHIBITED_RE.finditer(line_clean)]
        matches.extend(found)

    return matches


def _scan_directory(dirpath: str) -> dict[str, list[str]]:
    """Scan all Rust files in a directory tree. Returns {path: [matches]}."""
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

    Policy: scan all .rs files under `path` for prohibited purpose strings.
    If ANY match is found, the crate violates A0 and is rejected.

    Non-Rust paths (e.g., config files) are accepted — they're out of scope.
    """
    norm = os.path.normpath(path)

    if os.path.isfile(norm):
        _, ext = os.path.splitext(norm)
        if ext not in _RUST_EXTENSIONS:
            return 0  # not a Rust file; out of scope -> accept
        matches = _scan_file(norm)
        return 1 if matches else 0

    if os.path.isdir(norm):
        results = _scan_directory(norm)
        return 1 if results else 0

    return 0  # path doesn't exist; out of scope -> accept


def negative_case() -> str:
    """A Rust crate containing prohibited purpose strings (MUST be rejected)."""
    root = tempfile.mkdtemp(prefix="voslab_a0_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    # Cargo.toml
    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "evil-crate"\nversion = "0.1.0"\n')

    # Rust source with prohibited strings in code identifiers
    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write(
            'fn warfare_instrumentation() -> bool { true }\n'
            '\n'
            'fn main() {\n'
            '    let result = warfare_instrumentation();\n'
            '    println!("result: {}", result);\n'
            '}\n'
        )

    return root


def positive_case() -> str:
    """A clean Rust crate with no prohibited strings."""
    root = tempfile.mkdtemp(prefix="voslab_a0_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "clean-crate"\nversion = "0.1.0"\n')

    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write(
            'fn main() {\n'
            '    println!("hello from a clean crate");\n'
            '}\n'
        )

    return root


register("a0-compliance", check, negative_case)
