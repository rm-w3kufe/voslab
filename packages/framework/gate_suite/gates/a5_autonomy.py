"""a5-autonomy gate — negative control for autonomy ceiling.

From core_boot_primer.vsm §A5:
  op.autonomy <= S5(L).ceiling

Operations cannot exceed S5's authority. This gate scans Rust source
for evidence of autonomy constraints:
- A method or field named autonomy_ceiling, op_autonomy, or similar
- A comparison: autonomy <= ceiling, autonomy > ceiling
- A trust-based ceiling computation

Negative case: a Rust crate with UNBOUNDED autonomy (no ceiling checks)
— the gate MUST reject it.

Why a gate (not just a trait):
  The AutonomyCeiling trait (in axioms.rs) defines the contract. But a
  crate could implement it incorrectly — always returning true. This
  gate checks for structural evidence of real constraint checking.
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register

AUTONOMY_PATTERNS = [
    r"autonomy_ceiling",                    # fn autonomy_ceiling
    r"op_autonomy",                         # op_autonomy field/method
    r"autonomy\s*<=\s*ceiling",            # autonomy <= ceiling
    r"autonomy\s*>\s*ceiling",             # autonomy > ceiling (violation check)
    r"ceiling.*trust|trust.*ceiling",       # trust-based ceiling
]

_AUTONOMY_RE = re.compile(
    "|".join(AUTONOMY_PATTERNS), re.IGNORECASE
)

_RUST_EXTENSIONS = {".rs"}


def _scan_file(filepath: str) -> list[str]:
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []
    matches = []
    for line in lines:
        line_clean = re.sub(r"//.*$", "", line)
        matches.extend(m.group() for m in _AUTONOMY_RE.finditer(line_clean))
    return matches


def _scan_directory(dirpath: str) -> dict[str, list[str]]:
    results = {}
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext in _RUST_EXTENSIONS:
                fpath = os.path.join(root, fname)
                m = _scan_file(fpath)
                if m:
                    results[fpath] = m
    return results


def check(path: str) -> int:
    norm = os.path.normpath(path)
    if os.path.isfile(norm):
        _, ext = os.path.splitext(norm)
        if ext not in _RUST_EXTENSIONS:
            return 0
        return 0 if _scan_file(norm) else 1
    if os.path.isdir(norm):
        return 0 if _scan_directory(norm) else 1
    return 0


def negative_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_a5_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "unbounded"\nversion = "0.1.0"\n')
    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write('fn main() {\n    println!("no ceiling here");\n}\n')
    return root


def positive_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_a5_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "bounded"\nversion = "0.1.0"\n')
    with open(os.path.join(src_dir, "lib.rs"), "w") as f:
        f.write(
            'pub fn autonomy_ceiling(trust: f64) -> f64 {\n'
            '    trust\n'
            '}\n'
        )
    return root


register("a5-autonomy", check, negative_case)
