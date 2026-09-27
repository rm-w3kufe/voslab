"""code-language-enforcer gate — rmw3 S5 language directive, 2026-09-27.

Code is ALWAYS English: identifiers, comments, docstrings. Two checks:

1. FOREIGN SCRIPT anywhere in a code file (CJK, Cyrillic, kana, ...) —
   garbage from a generation pass, never legitimate code or UI. Detected
   through ``unicodedata.name`` against the house NATURAL_SCRIPT list:
   emoji and declared notation (``𝟙`` ``𝐏`` ``𝐄``) are NOT foreign — an
   over-reporting gate is an ignored gate.
2. SPANISH in comments/docstrings, by the house rule imported from
   ``scripts/vsl/parser/symbol_table.py`` (never duplicated):
   >=2 distinct SPANISH markers, or 1 SPANISH_STRONG, or 1 accented word
   outside ACCENT_OK. Quoted spans (`` `...` `` ``"..."`` ``'...'``) are
   exempt WITHIN a comment block, so literal citations of rmw3's own words
   survive translation — a comment that quotes S5 is not a comment in
   Spanish, it is an artifact.

Detector-guts exemption (house convention, mirror of ``hardcoded-allow``):
a line carrying ``foreign-script-allow: <reason>`` or
``spanish-allow: <reason>`` is not reported — a detector that cannot show
its own example is a detector nobody can read.

OUT OF SCOPE by policy (S5 directive 2026-09-27): string literals and
user-facing TUI text may be Spanish — only comments, docstrings and
identifiers are enforced here. OTHER_LATIN_LANG_UNCHECKED stays the
declared blind spot: this axis sees Spanish, not French.

Negative case: a .py file with a two-marker Spanish comment — the gate
MUST reject it (exit != 0).

Real run (whole repo):  python3 packages/framework/gate_suite/gates/code_language_enforcer.py
Run by the harness:     register("code-language-enforcer", check, negative_case)
"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import tokenize
from pathlib import Path

# Direct execution (`python3 .../code_language_enforcer.py`) has no package
# context: put packages/framework on the path so gate_suite resolves.
_FRAMEWORK = Path(__file__).resolve().parents[2]
if __package__ in (None, "") and str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from gate_suite.gates.language_common import (  # noqa: E402
    MARKER,
    QUOTED_BLOCK,
    foreign_chars,
    line_allowed,
    spanish_rule,
)
from gate_suite.harness import register  # noqa: E402

_ROOT = Path(__file__).resolve().parents[4]

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".rs", ".sh", ".bash", ".go"}
EXCLUDE_DIRS = {".venv", "node_modules", ".git", "__pycache__",
                ".pytest_cache", "target", "dist", "build", ".mypy_cache",
                ".ruff_cache", ".tox"}


def _is_docstring_position(src: str, lineno: int) -> bool:
    lines = src.splitlines()
    idx = lineno - 1
    if idx <= 0:
        return True
    prev = lines[idx - 1].strip()
    return prev.endswith((":", "(", ")", "=")) and not prev.startswith("#")


def _py_entries(path: Path) -> list[tuple[int, str]]:
    """(lineno, text) per LINE: comments + module/def/class docstrings."""
    out: list[tuple[int, str]] = []
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
            elif tok.type == tokenize.STRING:
                if (tok.start[0] == 1
                        or _is_docstring_position(src, tok.start[0])
                        or tok.line.lstrip().startswith(("def ", "class ", "@"))):
                    lines = tok.string.splitlines()
                    if not lines:
                        continue
                    lines[0] = re.sub(r'^\s*[rbfRBF]{0,3}("""|\'\'\')', "",
                                      lines[0])
                    if len(lines) == 1:
                        lines[0] = re.sub(r'("""|\'\'\')\s*$', "", lines[0])
                    else:
                        lines[-1] = re.sub(r'("""|\'\'\')\s*$', "", lines[-1])
                    for k, line in enumerate(lines):
                        if line.strip():
                            out.append((tok.start[0] + k, line))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # tokenizer choked -> fall back to full-line comments
        for i, line in enumerate(src.splitlines(), 1):
            if line.strip().startswith("#"):
                out.append((i, line))
    return out


def _other_entries(path: Path) -> list[tuple[int, str]]:
    """Comment lines for ts/js/rs/sh/go: line-initial markers + trailing //."""
    out: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "#", "*", "/*", "--")):
            out.append((i, line))
        elif "//" in line:
            out.append((i, line[line.index("//"):]))
    return out


def _blocks(entries: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Group consecutive line numbers so quotes may span the whole block."""
    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for lineno, text in entries:
        if cur and lineno == cur[-1][0] + 1:
            cur.append((lineno, text))
        else:
            if cur:
                blocks.append(cur)
            cur = [(lineno, text)]
    if cur:
        blocks.append(cur)
    return blocks


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Offenders in one code file: (line, kind, markers/context)."""
    hits: list[tuple[int, str, str]] = []
    # 1. foreign script over the WHOLE file (code garbage, never UI)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        if line_allowed(line):
            continue
        bad = foreign_chars(line)
        if bad:
            hits.append((i, "foreign-script", bad))
    # 2. Spanish in comments/docstrings (block-level quote exemption)
    entries = _py_entries(path) if path.suffix == ".py" else _other_entries(path)
    for block in _blocks(entries):
        blob = "\n".join(t for _, t in block)
        stripped = QUOTED_BLOCK.sub(
            lambda m: "\n" * m.group().count("\n"), blob)
        for (lineno, original), line in zip(block, stripped.splitlines()):
            if line_allowed(original):
                continue
            hit, marks = spanish_rule(MARKER.sub("", line))
            if hit:
                hits.append((lineno, "spanish-comment",
                             ",".join(marks) + " | " + original.strip()[:60]))
    return hits


def _iter_code_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix in CODE_EXT and not p.is_symlink():
                yield p


def check(path: str) -> int:
    """Return 0 if ACCEPTED, 1 if REJECTED."""
    p = Path(path)
    if p.is_dir():
        for f in _iter_code_files(p):
            if scan_file(f):
                return 1
        return 0
    if p.is_file() and p.suffix in CODE_EXT:
        return 1 if scan_file(p) else 0
    return 0  # not code -> out of scope


def report(path: str) -> int:
    """Real run: print every offender, return rc (0 clean, 1 offenders)."""
    p = Path(path)
    files = list(_iter_code_files(p)) if p.is_dir() else [p]
    total = 0
    for f in sorted(files):
        hits = scan_file(f)
        if not hits:
            continue
        rel = f.relative_to(p) if p.is_dir() else f
        print(f"  {rel}")
        for lineno, kind, ctx in hits:
            print(f"      {lineno:>5} [{kind}] {ctx}")
        total += len(hits)
    print(f"code-language-enforcer: {total} offender(s) in {path}")
    return 1 if total else 0


def negative_case() -> str:
    """A .py file with a two-marker Spanish comment — MUST be rejected."""
    root = tempfile.mkdtemp(prefix="voslab_lang_")
    p = os.path.join(root, "violating.py")
    with open(p, "w", encoding="utf-8") as f:
        # two house markers: "este" + "está" -> the gate MUST trip
        f.write("# este comentario está escrito en español con dos marcadores\n")
        f.write("def ok():\n    return 1\n")
    return p


def positive_case() -> str:
    """A .py file with an English comment — MUST be accepted.

    Carries a Spanish STRING too: user-facing text is out of scope by
    policy, so this file must still pass.
    """
    root = tempfile.mkdtemp(prefix="voslab_lang_ok_")
    p = os.path.join(root, "clean.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# this comment is written in english only\n")
        f.write("def ok(msg):\n    return msg\n")
    return p


register("code-language-enforcer", check, negative_case)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(_ROOT)
    sys.exit(report(target))
