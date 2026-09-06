"""trust-composable gate — negative control for composable trust.

From definitions_core.vsm (D5-D13):
  trust(t+1) = (1-lambda)*decay(trust(t), lambda) + lambda*observation(t)

From definitions_theory.vsm (D18):
  trust_parent = min(sum(w_i * trust_i), min_i(trust_i) + epsilon)

This gate scans Rust source for evidence of composable trust:
- A struct or function named TrustScore, trust_score, or similar
- A function that accepts multiple trust values (composition)
- A configurable lambda/epsilon parameter (not hardcoded)
- A trust update function

Negative case: a Rust crate with hardcoded trust values (0.6, 0.8, etc.)
and NO composable trust structure — the gate MUST reject it.

Why a gate (not just a trait):
  The TrustScore type (in trust.rs) defines the contract. But a crate
  could hardcode trust values instead of computing them. This gate
  catches that — it's the "trust is not a magic number" guard.
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register

# Patterns that indicate composable trust structure
TRUST_COMPOSABLE_PATTERNS = [
    r"TrustScore\s*\{",                    # TrustScore { ... }
    r"fn\s+compose",                       # fn compose
    r"fn\s+update\s*\(",                   # fn update(
    r"lambda|lambda\s*[=<>]",              # lambda parameter
    r"epsilon|epsilon\s*[=<>]",            # epsilon parameter
    r"weighted.*sum|sum.*weighted",         # weighted sum
    r"min.*trust|trust.*min",              # min(trust_i)
]

# Hardcoded trust values (sign of non-composable trust)
HARDCODED_TRUST_PATTERNS = [
    r"trust\s*=\s*0\.\d+",                # trust = 0.6
    r"THRESHOLD\s*=\s*0\.\d+",            # THRESHOLD = 0.3
    r"const.*TRUST.*=\s*0\.\d+",          # const TRUST: f64 = 0.8
]

_COMPOSABLE_RE = re.compile(
    "|".join(TRUST_COMPOSABLE_PATTERNS), re.IGNORECASE
)
HARDCODED_RE = re.compile(
    "|".join(HARDCODED_TRUST_PATTERNS), re.IGNORECASE
)

_RUST_EXTENSIONS = {".rs"}


def _scan_file(filepath: str) -> tuple[list[str], list[str]]:
    """Return (composable_matches, hardcoded_matches)."""
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return [], []

    composable = []
    hardcoded = []
    for line in lines:
        line_clean = re.sub(r"//.*$", "", line)
        composable.extend(m.group() for m in _COMPOSABLE_RE.finditer(line_clean))
        hardcoded.extend(m.group() for m in HARDCODED_RE.finditer(line_clean))
    return composable, hardcoded


def _scan_directory(dirpath: str) -> dict[str, tuple[list[str], list[str]]]:
    """Scan all Rust files for trust patterns."""
    results = {}
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext in _RUST_EXTENSIONS:
                fpath = os.path.join(root, fname)
                comp, hard = _scan_file(fpath)
                if comp or hard:
                    results[fpath] = (comp, hard)
    return results


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED.

    Policy: a VSM crate MUST have composable trust (not hardcoded).
    If ONLY hardcoded values are found (no composable structure), rejected.
    If composable structure is found, accepted — even if hardcoded values
    exist (they might be defaults in tests).
    """
    norm = os.path.normpath(path)

    if os.path.isfile(norm):
        _, ext = os.path.splitext(norm)
        if ext not in _RUST_EXTENSIONS:
            return 0
        comp, hard = _scan_file(norm)
        # Accept if composable structure exists
        return 0 if comp else (1 if hard else 1)

    if os.path.isdir(norm):
        results = _scan_directory(norm)
        total_comp = sum(len(c) for c, _ in results.values())
        total_hard = sum(len(h) for _, h in results.values())
        # Accept if composable structure exists
        return 0 if total_comp > 0 else (1 if total_hard > 0 else 1)

    return 0


def negative_case() -> str:
    """A Rust crate with hardcoded trust, no composable structure."""
    root = tempfile.mkdtemp(prefix="voslab_trust_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "hardcoded-trust"\nversion = "0.1.0"\n')

    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write(
            'const TRUST: f64 = 0.6;\n'
            'const THRESHOLD: f64 = 0.3;\n'
            '\n'
            'fn main() {\n'
            '    if TRUST > THRESHOLD {\n'
            '        println!("trusted");\n'
            '    }\n'
            '}\n'
        )

    return root


def positive_case() -> str:
    """A crate with composable trust structure."""
    root = tempfile.mkdtemp(prefix="voslab_trust_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "composable-trust"\nversion = "0.1.0"\n')

    with open(os.path.join(src_dir, "lib.rs"), "w") as f:
        f.write(
            'pub struct TrustScore {\n'
            '    score: f64,\n'
            '}\n'
            '\n'
            'impl TrustScore {\n'
            '    pub fn update(&mut self, observation: f64, lambda: f64) {\n'
            '        let decay = 1.0 - lambda;\n'
            '        self.score = decay * self.score + lambda * observation;\n'
            '    }\n'
            '\n'
            '    pub fn compose(children: &[(f64, f64)]) -> f64 {\n'
            '        children.iter().map(|(t, w)| t * w).sum()\n'
            '    }\n'
            '}\n'
        )

    return root


register("trust-composable", check, negative_case)
