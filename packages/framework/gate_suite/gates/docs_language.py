"""docs-language gate — rmw3 S5 language directive, 2026-09-27.

Docs are language-persistent, not language-agnostic: the persistent
system/ layer is ENGLISH (D7), transient and local layers may be Spanish.
Two checks:

1. FOREIGN SCRIPT in any .vsm/.md (CJK, Cyrillic, kana, ...) — generation
   garbage, on the same NATURAL_SCRIPT axis symbol_table declares. Emoji
   and declared notation are NOT foreign. A line carrying
   ``foreign-script-allow: <reason>`` is exempt (house ``*-allow``
   convention, mirror of ``hardcoded-allow``).
2. SPANISH in ``system/**/*.vsm`` — the D7 rule by the house marker sets
   imported from ``scripts/vsl/parser/symbol_table.py`` (never
   duplicated): >=2 SPANISH markers, or 1 SPANISH_STRONG, or 1 accented
   word outside ACCENT_OK. ``covenant.vsm`` is D7_EXEMPT (house rule).

OUT OF SCOPE by policy (S5 directive 2026-09-27): docs OUTSIDE system/
(docs/, .opencode/, archive/) may be Spanish — transient and local layers.
The blind spot OTHER_LATIN_LANG_UNCHECKED (French et al.) stays declared.

Negative case: a .vsm carrying a CJK character — MUST be rejected.

Real run:          python3 packages/framework/gate_suite/gates/docs_language.py
Run by the harness: register("docs-language", check, negative_case)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Direct execution has no package context: put packages/framework on the path.
_FRAMEWORK = Path(__file__).resolve().parents[2]
if __package__ in (None, "") and str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from gate_suite.gates.language_common import (  # noqa: E402
    foreign_chars,
    line_allowed,
    spanish_rule,
)
from gate_suite.harness import register  # noqa: E402

_ROOT = Path(__file__).resolve().parents[4]
_SYSTEM = _ROOT / "system"

DOC_EXT = {".vsm", ".md"}
EXCLUDE_DIRS = {".venv", "node_modules", ".git", "__pycache__",
                ".pytest_cache", "target", "dist", "build", ".mypy_cache",
                ".ruff_cache", ".tox"}
# House D7 exemption (symbol_table.D7_EXEMPT) — kept as the name, not the
# content, so the single source of truth stays in symbol_table.
_D7_EXEMPT_NAMES = {"covenant.vsm"}


def _iter_doc_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix in DOC_EXT and not p.is_symlink():
                yield p


def scan_file(path: Path, root: Path | None = None) -> list[tuple[int, str, str]]:
    """Offenders: (line, kind, context). root marks the system/ scope."""
    hits: list[tuple[int, str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return hits

    # 1. foreign script anywhere in the doc
    for i, line in enumerate(lines, 1):
        if line_allowed(line):
            continue
        bad = foreign_chars(line)
        if bad:
            hits.append((i, "foreign-script", bad))

    # 2. D7 English, only for files inside the system/ tree
    in_system = path.name not in _D7_EXEMPT_NAMES and (
        (root is not None and path.is_relative_to(root))
        or (root is None and str(path).startswith(str(_SYSTEM) + os.sep)))
    if in_system and path.suffix == ".vsm":
        for i, line in enumerate(lines, 1):
            if line_allowed(line):
                continue
            hit, marks = spanish_rule(line)
            if hit:
                hits.append((i, "d7-spanish",
                             ",".join(marks) + " | " + line.strip()[:60]))
    return hits


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED."""
    p = Path(path)
    if p.is_dir():
        # only the docs inside this dir are in scope; system/ D7 applies
        # when the dir itself is (or contains) system/
        for f in _iter_doc_files(p):
            if scan_file(f, root=p if "system" in p.parts else None):
                return 1
        return 0
    if p.is_file() and p.suffix in DOC_EXT:
        return 1 if scan_file(p) else 0
    return 0  # not a doc -> out of scope


def report(path: str) -> int:
    """Real run: print every offender, return rc (0 clean, 1 offenders)."""
    p = Path(path)
    files = list(_iter_doc_files(p)) if p.is_dir() else [p]
    total = 0
    for f in sorted(files):
        hits = scan_file(f, root=p if p.is_dir() and "system" in p.parts
                         else _SYSTEM)
        if not hits:
            continue
        rel = f.relative_to(p) if p.is_dir() else f
        print(f"  {rel}")
        for lineno, kind, ctx in hits:
            print(f"      {lineno:>5} [{kind}] {ctx}")
        total += len(hits)
    print(f"docs-language: {total} offender(s) in {path}")
    return 1 if total else 0


def negative_case() -> str:
    """A .vsm carrying a CJK character — MUST be rejected."""
    root = tempfile.mkdtemp(prefix="voslab_docs_lang_")
    p = os.path.join(root, "violating.vsm")
    with open(p, "w", encoding="utf-8") as f:
        f.write("⟦ violating | SPEC-v1 | vsm-1.2.1 | 2026-09-27T09:15:00Z ⟧\n")
        f.write("\n@vsm 1.2.1\n@status active\n\n")
        # generation garbage: CJK inside a system doc line
        f.write("// This fills the gap. 填补空白\n")  # foreign-script-allow: negative fixture for docs-language gate
        f.write("\n⟦ /violating ⟧\n")
    return p


def positive_case() -> str:
    """An English .vsm with a Spanish sentence OUTSIDE system/ — accepted
    (transient/local layers are language-persistent in Spanish)."""
    root = tempfile.mkdtemp(prefix="voslab_docs_ok_")
    p = os.path.join(root, "notes.vsm")
    with open(p, "w", encoding="utf-8") as f:
        f.write("// Notas de sesión: esta revisión quedó pendiente de\n")
        f.write("// validar con rmw3 antes del siguiente ciclo.\n")
    return p


register("docs-language", check, negative_case)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(_ROOT)
    sys.exit(report(target))
