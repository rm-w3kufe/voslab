#!/usr/bin/env python3
"""prose_glyph_gate.py — deterministic glyph-in-prose gate (VSL-GRAMMAR-REINFORCE).

REFUERZO DETERMINISTA (decisión S5 rmw3, 2026-08-14): mathematical operators
declared by the ontology (boot/ canon glyph tables) are LEGAL as operators.
When the SAME glyph is used as PROSE_AMB shorthand it is blocked on staged
.vsm under docs/spec_revision/.

TERRENO PREPARADO, UN GLIFO ACTIVO (rmw3 S5): ¬ is the pilot. Validation with
the agents (the users) drives which glyphs join — if a sign causes real
confusion, consider it; prose signs that HELP comprehension are valued, not
blocked. Expanding too early would drown the gate in false positives.

DISCRIMINADOR VERIFICADO R4 (censo 2026-08-14):
  - PROSE_AMB patterns BLOCK: verb-shorthand (does ¬have), sentence-final
    (SOURCES, ¬), quote-token (¬'x'), digit (¬3), symbol-prose (¬σ), 
    paren-in-prose (¬(a)) — these are prose-abuse, same taxonomy as the
    universe census (not_census v0.4).
  - AFFIX (¬word, ¬viable(V), ¬conflict(V_i,V_j), ¬BOM) is NOT blocked: it is
    the canon's DELIBERATE prefix notation (core_boot_primer ratified uses it
    throughout; the capa-2 cleanup reported "0 prose ¬" in boot/). Blocking
    it would false-positive the ratified canon.
  - LOGICAL/TABLE stay legal: ¬(formula), ¬∃, ¬{…}, ¬Δ in formula context,
    glyph declaration tables.

VERIFIED (R4): boot/ ratified → 0 false positives; system/ → 28/63 files
carry PROSE_AMB ¬ (the cleanup debt the system/ arc addresses at its end —
the gate only blocks NEW prose ¬ on staged files, never the existing corpus).

USAGE: prose_glyph_gate.py <file...>
  rc=0  no prose-glyph abuse introduced
  rc=1  abuse found — block
  rc=2  usage error / instrument missing

EXTENSIBLE: GLYPH_ACTIVE + PROSE_PATTERN_RE are the seam for future glyphs.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..', '..'))
_TOOLS = os.path.join(_ROOT, 'child/sandbox/vsl-notation-review/tools')
sys.path.insert(0, _TOOLS)

try:
    import not_census as nc
except ImportError as e:
    print(f"✗ prose_glyph_gate: cannot import not_census ({e}) — "
          f"instrument missing at {_TOOLS}", file=sys.stderr)
    sys.exit(2)


# ── THE EXTENSIBLE SEAM (rmw3 S5: one glyph active, terrain prepared) ──────
GLYPH_ACTIVE = {'¬'}

# PROSE_AMB abuse patterns (line-level context). NOT AFFIX — the canon's
# deliberate prefix notation is legal (verified R4).
PROSE_PATTERN_RE = {
    'verb-shorthand': re.compile(r'\b(do|does|did)\s+¬'),
    'sentence-final': re.compile(r'¬\s*(?:[.,)\]]|$)'),
    'quote-token':    re.compile(r'¬\s*(?:["\'`])'),
    'digit':          re.compile(r'¬\s*\d'),
    'symbol-prose':   re.compile(r'¬\s*[σΩεφ↓.]'),
    'paren-in-prose': re.compile(r'¬\s*\(\s*[a-z]\s*\)'),
}


def _is_glyph_table(line):
    return nc.is_glyph_table(line)


def _is_legal_logical(line):
    return bool(
        re.search(r'¬\s*\([^)]{0,60}(∘|∈|=|@)', line)
        or re.search(r'¬\s*\(\s*(build|deploy|state|parse|H\b)', line)
        or '¬∃' in line
        or re.search(r'¬\{', line)
        or (re.search(r'¬Δ', line) and nc.FORMULA_RE.search(line))
    )


def _abuse_kind(line):
    """First matching PROSE_AMB abuse name, or None. Guards first."""
    if _is_glyph_table(line):
        return None
    if _is_legal_logical(line):
        return None
    for name, rx in PROSE_PATTERN_RE.items():
        if rx.search(line):
            return name
    return None


def scan_file(path):
    """Return list of (lineno, abuse_kind, ctx) or None if clean."""
    try:
        txt = open(path, encoding='utf-8').read()
    except OSError:
        return None
    lines = txt.split('\n')
    hits = []
    for ch in GLYPH_ACTIVE:
        for ln, line in enumerate(lines, 1):
            if ch not in line:
                continue
            kind = _abuse_kind(line)
            if kind:
                hits.append((ln, kind, line.strip()[:90]))
    return hits if hits else None


def main(argv):
    if not argv:
        print("usage: prose_glyph_gate.py <file...>", file=sys.stderr)
        return 2
    bad = []
    for f in argv:
        if not os.path.isfile(f):
            continue
        hits = scan_file(f)
        if hits:
            for ln, kind, ctx in hits:
                bad.append((os.path.relpath(f), ln, kind, ctx))
    if bad:
        print("✗ PROSE-GLYPH gate: prose use of a mathematical operator "
              "(VSL NOTATION — glyphs are operators, not prose shorthand)",
              file=sys.stderr)
        for p, ln, kind, ctx in sorted(set(bad)):
            print(f"      [{kind}] {p}:{ln}  {ctx}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))