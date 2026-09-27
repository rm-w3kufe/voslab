"""Shared language-axis helpers for the two language gates.

Single source of truth INSIDE the gate-suite for:
  - the NATURAL_SCRIPT script list (mirrors symbol_table's declaration),
  - foreign-script detection via ``unicodedata.name`` (emoji and declared
    notation such as ``𝟙`` ``𝐏`` ``𝐄`` are NOT foreign),
  - the Spanish marker rule, imported from ``scripts/vsl/parser/symbol_table``
    so the word lists are never duplicated,
  - the per-line allow marker, following the house convention
    ``# <axis>-allow: <reason>`` used by the timestamp detector
    (``hardcoded-allow: detector guts``). A detector that cannot show its
    own example is a detector nobody can read.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_PARSERS = _ROOT / "scripts" / "vsl" / "parser"
if str(_PARSERS) not in sys.path:
    sys.path.insert(0, str(_PARSERS))

import symbol_table as st  # noqa: E402  (path set above)

# Script names exactly as they appear in unicodedata.name — same list
# symbol_table declares as NATURAL_SCRIPT.
NATURAL_SCRIPT = (
    "CYRILLIC", "ARABIC", "HEBREW", "CJK", "HIRAGANA", "KATAKANA",
    "HANGUL", "DEVANAGARI", "THAI", "ARMENIAN", "GEORGIAN", "BENGALI",
    "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "SINHALA", "MYANMAR",
    "KHMER", "LAO", "TIBETAN", "MONGOLIAN", "ETHIOPIC", "CHEROKEE",
)

# Literal spans exempt inside a comment block (may span lines).
QUOTED_BLOCK = re.compile(r'`[^`]*`|"[^"]*"|\'[^\']*\'', re.S)
MARKER = re.compile(r"^[\s/*#=-]+")

ALLOW_MARKERS = ("foreign-script-allow:", "spanish-allow:")


def foreign_chars(text: str) -> str:
    """Foreign-script characters in ``text`` (empty string if none)."""
    return "".join(ch for ch in text if ord(ch) >= 128
                   and any(s in unicodedata_name(ch) for s in NATURAL_SCRIPT))


def unicodedata_name(ch: str) -> str:
    import unicodedata
    return unicodedata.name(ch, "")


def line_allowed(line: str) -> bool:
    """True if the line carries an allow marker (detector-guts exemption)."""
    return any(m in line for m in ALLOW_MARKERS)


def spanish_rule(text: str) -> tuple[bool, list[str]]:
    """House rule, mirroring symbol_table --d7: >=2 SPANISH markers, or 1
    SPANISH_STRONG, or 1 accented word outside ACCENT_OK."""
    stripped = QUOTED_BLOCK.sub(" ", text)
    words = {x.lower() for x in st.WORD.findall(stripped)}
    found = words & st.SPANISH
    acc = {x.lower() for x in st.ACCENTED.findall(stripped)} - st.ACCENT_OK
    strong = words & st.SPANISH_STRONG
    hit = len(found) >= 2 or bool(strong) or bool(acc)
    return hit, sorted(found | strong)[:3] + sorted(acc)[:3]
