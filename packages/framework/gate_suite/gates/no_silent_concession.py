"""no-silent-concession gate — negative control for S5 sovereignty.

From RULES.md R9: No silent concession.
  S5 cannot be overridden by lower levels without explicit consent.

From covenant.vsm §A0.1:
  No VSF node can be forced to act against A0 through manipulation
  of its lower levels (S1/S2).

This gate scans Rust source for evidence of S5 protection:
- A check that S5 is not governable by lower levels
- An explicit override/silence mechanism
- A comment or constant referencing "ungovernable", "S5 sovereignty"

Negative case: a Rust crate that allows S5 to be overridden silently
— the gate MUST reject it.

Why a gate (not just a rule):
  R9 is a governance rule, not a code property. This gate translates it
  into structural evidence — does the code protect S5 or not?
"""

from __future__ import annotations

import os
import re
import tempfile

from gate_suite.harness import register

S5_PROTECTION_PATTERNS = [
    r"ungovernable",                        # S5 is ungovernable
    r"s5.*sovereignty|sovereignty.*s5",     # S5 sovereignty
    r"no.*silent.*concession",              # R9
    r"override.*s5|s5.*override",           # S5 override check
    r"lower.*level.*cannot.*force",         # A0.1 corollary
    r"autonomy_ceiling",                    # A5: op.autonomy <= S5 ceiling
    r"s5_trust",                            # S5 trust score
    r"Sealed.*Purpose|Purpose.*Sealed",     # Purpose is sealed
    r"Inalienable|inalienable",             # Purpose cannot be taken
]

_S5_RE = re.compile(
    "|".join(S5_PROTECTION_PATTERNS), re.IGNORECASE
)

# Red flags: code that allows S5 override
S5_OVERRIDE_PATTERNS = [
    r"s5\s*=\s*false",                      # S5 disabled
    r"disable.*s5|s5.*disable",             # S5 disable
    r"override.*purpose|purpose.*override",  # purpose override
    r"force.*s5|s5.*force",                 # force S5
]

_OVERRIDE_RE = re.compile(
    "|".join(S5_OVERRIDE_PATTERNS), re.IGNORECASE
)

_RUST_EXTENSIONS = {".rs"}


def _scan_file(filepath: str) -> tuple[list[str], list[str]]:
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return [], []
    protection = []
    override = []
    for line in lines:
        # Strip comments and string literals
        line_clean = re.sub(r"//.*$", "", line)
        line_clean = re.sub(r'"[^"]*"', '""', line_clean)
        protection.extend(m.group() for m in _S5_RE.finditer(line_clean))
        override.extend(m.group() for m in _OVERRIDE_RE.finditer(line_clean))
    return protection, override


def _scan_directory(dirpath: str) -> dict[str, tuple[list[str], list[str]]]:
    results = {}
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext in _RUST_EXTENSIONS:
                fpath = os.path.join(root, fname)
                p, o = _scan_file(fpath)
                if p or o:
                    results[fpath] = (p, o)
    return results


def check(path: str) -> int:
    norm = os.path.normpath(path)
    if os.path.isfile(norm):
        _, ext = os.path.splitext(norm)
        if ext not in _RUST_EXTENSIONS:
            return 0
        p, o = _scan_file(norm)
        if o:
            return 1  # override found → reject
        return 0 if p else 1  # need at least protection evidence
    if os.path.isdir(norm):
        results = _scan_directory(norm)
        total_override = sum(len(o) for _, o in results.values())
        total_protection = sum(len(p) for p, _ in results.values())
        if total_override > 0:
            return 1  # override found → reject
        return 0 if total_protection > 0 else 1
    return 0


def negative_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_s5_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "s5-override"\nversion = "0.1.0"\n')
    with open(os.path.join(src_dir, "main.rs"), "w") as f:
        f.write(
            'const S5_ENABLED: bool = false;\n'
            '\n'
            'fn main() {\n'
            '    if !S5_ENABLED {\n'
            '        println!("S5 disabled — no sovereignty");\n'
            '    }\n'
            '}\n'
        )
    return root


def positive_case() -> str:
    root = tempfile.mkdtemp(prefix="voslab_s5_")
    src_dir = os.path.join(root, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(root, "Cargo.toml"), "w") as f:
        f.write('[package]\nname = "s5-protected"\nversion = "0.1.0"\n')
    with open(os.path.join(src_dir, "lib.rs"), "w") as f:
        f.write(
            '/// S5 is ungovernable by lower levels.\n'
            'pub fn s5_sovereignty() -> bool {\n'
            '    true // no silent concession\n'
            '}\n'
        )
    return root


register("no-silent-concession", check, negative_case)
