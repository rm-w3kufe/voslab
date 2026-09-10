"""VENDORED 2026-09-10 from ~/vsf/child/sandbox/vsl-notation-review/tools/not_census.py v0.6 (verbatim body; only this header added).
Reason: not_prose_gate.py had a live runtime import across repos;
child/ is read-only reference and may move (gate died rc=2).
Upstream fixes flow by re-vendoring + parity test below.
"""
#!/usr/bin/env python3
"""VSL universe-first ¬ census (reverse census), v0.6 — VERSIONED INSTRUMENT.

Per parent dispatch UNIVERSE-PURE-VSL-NOTATION-2026-08-13 (58cae91, rmw3 S5
Option A — CANON PURO):
  - the agreed universe is 1,404 ¬ = system 949 + sandbox 138 + ledger 76 +
    child_docs 57 + child_sandbox canon 184 (vsl-language-rev + README).
  - EXCLUDED from the COUNT: self-census artifacts (child/sandbox/
    vsl-notation-review/* — audit, proposals, TASK_SPEC = 513 ¬) and the
    census-defining dispatch itself (universe_pure, 6 ¬ — self-exclusion:
    the census must not count the document that defines it, same fix-point
    principle the parent flagged: "el censo se mide a sí mismo"). agent_layer/
    is retired (rmw3 commit 8f264822) and absent — scanning it is a no-op.
  - the 5 PRE-universe_pure dispatches (57 ¬) ARE counted: the parent's
    DONE_WHEN arithmetic (1404 = 949+138+76+57+184) includes child_docs 57,
    so child_docs/deploy/* counts except the current census-defining file.
  - DEFAULT output is canon-puro (1,404). Flag --include-self switches to
    the FULL live universe (v0.5 mode, everything incl. vsl-notation-review).
  - classify every ¬ with the SAME mechanical v0.4 rules (no new rules).

NOTE ON THE PARENT-DISPATCH CONTRADICTION (documented in φ↑ 2026-08-13):
  The dispatch body lists "dispatches child/docs/deploy/*" under EXCLUIDOS,
  yet the DONE_WHEN sum explicitly includes child_docs 57. Resolution: the
  EXCLUIDOS list applies to the CLEANUP SET (gate 2: 0 rows pointing at
  vsl-notation-review or dispatches — cleanup targets, not count). The COUNT
  follows the DONE_WHEN literal: 57. Without the self-exclusion of the
  defining dispatch, child_docs would read 63 and the universe would drift
  with every new dispatch.

TAXONOMY (v0.4, mechanical rules — every ¬ classified once):
  LOGICAL    ¬ operator over a formula: ¬(…formula…), ¬∃, ¬{…}, ¬Δ in a
             line carrying formula markers (⟹ or ∧).
  TABLE      ¬ as a glyph inside an alphabet/notation declaration line
             (8+ distinct math glyphs on the same line).
  PROSE_AMB  ¬ structurally ambiguous in prose:
               verb-shorthand   : do/does/did + space + ¬ (do-not), ANY
                                  following char (¬touch, ¬., ¬ re-declare)
               sentence-final   : ¬ followed by . , ) ] \n or space+EOF
                                  (covers is/was/are + ¬ at EOL)
               quote/code-token : ¬ then ' or ` or space+'/`
               digit            : ¬ then 0-9
               symbol-prose     : ¬ then σ Ω ε φ ↓ or . (non-formula)
               paren-in-prose   : ¬(a) with a single letter, no formula ops
  AFFIX      ¬ glued to a word (¬word) or ¬ + space + word — prose prefix
             for NOT-word shorthand; includes old AFFIX_SPACE + OTHER (fold).

Output: per-class counts + per-domain breakdown + the FULL PROSE_AMB and
LOGICAL row lists with source:line and context. Re-run to reproduce; do
not hand-edit the output.
CWD-INDEPENDENT: resolves the shared repo root from this file's own path,
so the same census prints from /home/rmw3/vsf or /home/rmw3/vsf/child.

NOTE ON v0.1/v0.2/v0.3 bugs (fixed in v0.4, preserved in v0.5/v0.6):
  - old verb regex r'\\n?' required a literal backslash, so 'do ¬touch',
    'did ¬,', 'does ¬,' etc. were misclassified as AFFIX/OTHER — the audit
    lists them as prose P4/P5/P6/P11/P12. Fixed: real-space do-family pattern.
  - v0.3 restricted verb-shorthand to ¬ followed by space/EOL, dropping
    P4 (h_rest:20 'do ¬touch') and P6 (conformance:15 '4 do ¬count').
    Fixed: do-family + space + ¬ => PROSE_AMB regardless of what follows.
  - v0.3 used line.find('¬') so a line with TWO ¬ (s4_ant:959 '¬one ... ¬σ,')
    classified only the first; P28 (¬σ,) was dropped. Fixed: every ¬ on the
    line is evaluated at its own column.
  - '¬(a) alone' matched the LOGICAL paren regex via \\b between a and ) —
    now excluded (paren-in-prose rule).
  - the audit's T4 (child/sandbox/vsl-language-rev/...) was OUTSIDE the
    parent-defined universe; v0.4 scanned system+sandbox and counted 3
    glyph-table lines (vsl_language:33/:37, core_boot_primer:38). v0.5
    scans the full agreed universe including ledger + child/; TABLE count
    may grow only via real glyph tables in those new dirs.
"""
import os, re, collections

# The script lives at child/sandbox/vsl-notation-review/tools/not_census.py;
# the census universe is the agreed SHARED-repo set: docs/spec_revision/
# (system+sandbox+ledger, EXCLUDING retired agent_layer/) + child/docs/ +
# child/sandbox/ (self-census). Resolve root from this file's own path so the
# script is reproducible from ANY cwd (parent runs it from the shared repo
# root, or from child/ — same result).
_SHARED_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
)

# ── CANON-PURO EXCLUSIONS (v0.6) ───────────────────────────────────────────
# Self-census artifacts — NOT canon, NOT counted (parent dispatch 58cae91).
#  1. child/sandbox/vsl-notation-review/  (audit, proposals, TASK_SPEC, tools)
#  2. the census-defining dispatch itself: child/docs/deploy/2026-08-13_
#     parent_dispatch_vsl_notation_universe_pure.vsm (6 ¬) — self-exclusion
#     so child_docs counts exactly the 57 ¬ of the 5 pre-existing dispatches
#     that the parent's DONE_WHEN arithmetic includes.
_EXCLUDE_DIRS = [
    os.path.join(_SHARED_ROOT, 'child/sandbox/vsl-notation-review'),
]
_EXCLUDE_FILES = [
    os.path.join(_SHARED_ROOT,
                 'child/docs/deploy/2026-08-13_parent_dispatch_vsl_notation_universe_pure.vsm'),
]

# (label, path) — each domain is counted and reported separately
UNIVERSE = [
    ('system',       os.path.join(_SHARED_ROOT, 'docs/spec_revision/system/')),
    ('sandbox',      os.path.join(_SHARED_ROOT, 'docs/spec_revision/sandbox/')),
    ('ledger',       os.path.join(_SHARED_ROOT, 'docs/spec_revision/ledger/')),
    ('child_docs',   os.path.join(_SHARED_ROOT, 'child/docs/')),
    ('child_sandbox', os.path.join(_SHARED_ROOT, 'child/sandbox/')),
]
MATH_GLYPHS = set('∀∃∄∧∨⟹⟺∈∉⊂⊆⊄⊃∪∩∅≠≡≢≈≤≥⊤⊥Σ')
# do-family only: "do ¬" is the canonical do-not negation; is/was/are + ¬ is
# handled by sentence-final rules (¬ at EOL / before . , ) ]).
DO_VERB_RE = re.compile(r'\b(do|does|did)\s+¬')
# formula-context markers that make ¬Δ a real logical operator
FORMULA_RE = re.compile(r'[⟹∧]')
# glyph-declaration line: 8+ distinct math glyphs
def is_glyph_table(line):
    return len(set(ch for ch in line if ch in MATH_GLYPHS)) >= 8


def scan(label, root):
    rows = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if os.path.join(dp, d) not in _EXCLUDE_DIRS]
        for fn in fns:
            if not fn.endswith('.vsm'):
                continue
            p = os.path.join(dp, fn)
            if p in _EXCLUDE_FILES:
                continue
            try:
                txt = open(p, encoding='utf-8').read()
            except Exception:
                continue
            lines = txt.split('\n')
            for m in re.finditer('¬', txt):
                i = m.start()
                ln = txt.count('\n', 0, i) + 1
                line = lines[ln - 1] if ln <= len(lines) else ''
                line_start = txt.rfind('\n', 0, i) + 1
                col = i - line_start            # column of THIS ¬ within line
                s = max(0, i - 42)
                e = min(len(txt), i + 48)
                ctx = txt[s:e].replace('\n', '\\n')
                rows.append((label, os.path.relpath(p), ln, line, col, ctx))
    return rows


def classify(rows):
    cls = collections.Counter()
    by_domain = collections.defaultdict(collections.Counter)
    amb = []
    logical = []
    tables = []
    for label, p, ln, line, col, ctx in rows:
        # THIS ¬ is at column col of the line (not line.find — multi-¬ lines)
        after = line[col + 1:]
        nxt = after[0] if after else ''
        nxt2 = after.lstrip(' ')[0] if after.lstrip(' ') else ''
        # do-family verb + space + ¬ immediately before THIS ¬ (do-not)
        # anchored to the END of the prefix so it only fires for the ¬ that
        # directly follows the verb, not for a later ¬ on the same line.
        before_verb = bool(re.search(r'\b(do|does|did)\s+¬\s*$', line[:col + 1]))
        line_is_formula = bool(FORMULA_RE.search(line))
        line_is_glyph_table = is_glyph_table(line)

        if line_is_glyph_table:
            c = 'TABLE'
            tables.append((label, p, ln, line.strip()))
        elif (re.search(r'¬\s*\([^)]{0,60}(∘|∈|=|@)', line)
              or re.search(r'¬\s*\(\s*(build|deploy|state|parse|H\b)', line)
              or '¬∃' in line
              or re.search(r'¬\{', line)
              or (re.search(r'¬Δ', line) and line_is_formula)):
            c = 'LOGICAL'
            logical.append((label, p, ln, line.strip()))
        elif before_verb:
            # do/does/did + space + ¬ : "do ¬touch", "does ¬.", "do ¬ re-declare"
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'verb-shorthand', ctx))
        elif nxt in ('.', ',', ')', ']'):
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'sentence-final', ctx))
        elif nxt == '' or (nxt == ' ' and nxt2 == ''):
            # ¬ at end of line
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'sentence-final', ctx))
        elif nxt in ("'", '"', '`') or (nxt == ' ' and nxt2 in ("'", '"', '`')):
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'quote/code-token', ctx))
        elif nxt.isdigit() or (nxt == ' ' and nxt2.isdigit()):
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'digit', ctx))
        elif nxt in 'σΩεφ↓.':
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'symbol-prose', ctx))
        elif re.search(r'¬\s*\(\s*[a-z]\s*\)', line) and not line_is_formula:
            c = 'PROSE_AMB'
            amb.append((label, p, ln, 'paren-in-prose', ctx))
        else:
            c = 'AFFIX'
        cls[c] += 1
        by_domain[label][c] += 1
    return cls, by_domain, amb, logical, tables


def main():
    import argparse
    ap = argparse.ArgumentParser(description='VSL ¬ census (canon-puro default)')
    ap.add_argument('--include-self', action='store_true',
                    help='count the FULL live universe incl. vsl-notation-review/ '
                         'and the defining dispatch (v0.5 mode)')
    args = ap.parse_args()
    if args.include_self:
        # v0.5 full-universe mode: no artifact exclusion
        global _EXCLUDE_DIRS, _EXCLUDE_FILES
        _EXCLUDE_DIRS = []
        _EXCLUDE_FILES = []
    rows = []
    for label, root in UNIVERSE:
        rows += scan(label, root)
    cls, by_domain, amb, logical, tables = classify(rows)
    total = sum(cls.values())
    # per-domain totals (derived from the scan, never hardcoded)
    dom_totals = {label: sum(by_domain[label].values()) for label, _ in UNIVERSE}
    dom_str = ' + '.join(f'{label} {dom_totals[label]}' for label, _ in UNIVERSE)
    mode = 'FULL UNIVERSE (--include-self)' if args.include_self else 'CANON-PURO (excl. vsl-notation-review + defining dispatch)'
    print(f'mode: {mode}')
    print(f'UNIVERSE ¬: {total}  ({dom_str} = {total})')
    for k in ('LOGICAL', 'TABLE', 'PROSE_AMB', 'AFFIX'):
        print(f'  {k:12s} {cls[k]:5d}  {100*cls[k]/total:5.1f}%')
    print()
    print('=== per-domain by class ===')
    for label, _ in UNIVERSE:
        c = by_domain[label]
        parts = ' '.join(f'{k}={c[k]}' for k in ('LOGICAL', 'TABLE', 'PROSE_AMB', 'AFFIX'))
        print(f'  {label:15s} {dom_totals[label]:5d}  {parts}')
    print()
    print(f'=== GLYPH TABLES ({len(tables)}) ===')
    for label, p, ln, line in sorted(tables):
        print(f'  [{label}] {p}:{ln}  {line[:70]}')
    print()
    print(f'=== LOGICAL rows ({len(logical)}) ===')
    for label, p, ln, line in sorted(logical, key=lambda x: (x[1], x[2])):
        print(f'  [{label}] {p}:{ln}  {line[:80]}')
    print()
    print(f'=== FULL PROSE_AMB CLEANUP SET ({len(amb)}) — reverse census ===')
    for label, p, ln, kind, ctx in sorted(amb, key=lambda x: (x[1], x[2])):
        print(f'  [{label}] [{kind}] {p}:{ln}  {ctx[:90]}')


if __name__ == '__main__':
    main()
