#!/usr/bin/env python3
"""
VSL reference parser — VSL v1.0
Validates .vsm files against the canonical grammar: docs/spec/vsm_notation_spec.md Part IV (BNF).

The BNF's REQUIRED start is `@vsm version` (spec rule line 5: "`@vsm <version>` mandatory in every
.vsm file"); `system ::= "@vsm" version NL mode_comment? domain_context? declaration+`. The ⟦…⟧
header/footer is an OPTIONAL wrapping convention used by experiment/seed files — its ABSENCE is NOT a
grammar error (only a mismatched header≠footer pair is). This parser checks the BNF essentials
(@vsm + version int.int, domain_context well-formedness, V(id,L=int) system_def shape, bracket
balance) and lints conventions (hypothesis-label uniqueness, @ref existence) as warnings. A full
recursive-descent AST over every production is VSL v2.0 (the interpreter, task U).

Usage:
    python3 scripts/vsl/vsl_parser.py file.vsm          # validate, print summary
    python3 scripts/vsl/vsl_parser.py file.vsm --json   # emit parsed AST as JSON
    python3 scripts/vsl/vsl_parser.py file.vsm --strict # treat warnings as errors
    python3 scripts/vsl/vsl_parser.py --corpus DIR      # conformance sweep over all .vsm under DIR

Exit codes: 0=valid  1=invalid  2=parse_error
"""

import sys, re, json, os
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent / "vsl"))
from dataclasses import dataclass, field
from typing import Any

# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    valid: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    ast: dict = field(default_factory=dict)

    def error(self, msg, line=None):
        self.valid = False
        self.errors.append(f"ERROR{f' L{line}' if line else ''}: {msg}")

    def warn(self, msg, line=None):
        self.warnings.append(f"WARN{f' L{line}' if line else ''}: {msg}")


# ── Patterns ──────────────────────────────────────────────────────────────────

RE_HEADER  = re.compile(r'⟦\s*([^/\s]\S*)\s*\|\s*(\S+)\s*\|\s*vsm-([\d.]+)\s*\|\s*([\dT:\-.]+Z?)\s*⟧')
# VSM 1.1 (D2): header date field accepts date-only (2026-08-16) OR ISO 8601
# UTC timestamp (2026-08-16T17:40:00Z). Backward compatible — date-only files
# still parse. (Promoted 2026-08-16, VSM11-PROMOTE-PRIMER.)
RE_FOOTER  = re.compile(r'⟦\s*/(\S+)\s*(?:\|[^⟧]*)?⟧')   # name-only OR legacy full-repeat
RE_FOOTER_FIELDS = re.compile(r'⟦\s*/\S+\s*\|')            # legacy form carries | fields
RE_VERSION = re.compile(r'^@vsm\s+([\d.]+)')
RE_COMMENT = re.compile(r'^\s*//')
RE_BLANK   = re.compile(r'^\s*$')
RE_KV      = re.compile(r'^(\s*)([a-zA-Z_][a-zA-Z0-9_.]*)\s*[:=]\s*(.*)')
RE_BLOCK_O = re.compile(r'\{\s*$')
RE_BLOCK_C = re.compile(r'^\s*\}')
RE_ARRAY_O = re.compile(r'\[\s*$')
RE_ARRAY_C = re.compile(r'^\s*\]')
RE_HYPO    = re.compile(r'^\s*([A-Z]\d+)\s*:\s*"([^"]*)"')
RE_REF     = re.compile(r'@ref\s+(\S+)')
RE_DATE    = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RE_TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z$')
# VSM 1.1 (D2): timestamp ::= date "T" hh ":" mm [":" ss ["." frac]] "Z" — UTC.
RE_NUMBER  = re.compile(r'^-?\d+(\.\d+)?$')
# ── BNF Part IV productions ─────────────────────────────────────────────────────
RE_SEMVER  = re.compile(r'^\d+\.\d+(\.\d+)*$')               # version ::= int ("." int)+  (1.2 / 1.2.1)
RE_DOMCTX  = re.compile(r'domain_context:\s*\{([^}]*)\}')     # domain_context ::= "{" dc_field* "}"
RE_SYSDEF  = re.compile(r'V\(\s*("?[\w.-]+"?)\s*,\s*L\s*=\s*(\d+)\s*\)')  # V(id, L=int)
RE_STATUS  = re.compile(r'@status\s*=\s*(\w+)')
# @status carries TWO vocabularies and the enum depends on WHERE it sits.
# Declared in boot/vsl_language 2026-08-09 after the document half had drifted
# to 13 values against 7 declared, unchecked.
VALID_STATUS = {"design", "planned", "onboarding", "iterating",
                "testing", "production", "deprecated"}                        # lifecycle of a V(...)
VALID_DOC_STATUS = {"active", "ratified", "proposed", "conjecture",
                    "developing", "template", "historical_record"}

# `layer` is a LOCUS, not a subsystem. The old enum was narrower than the
# canon: the corpus writes S1, L+3, L..L+2 and S4<->S4 in that slot, and 7 of
# 11 --strict failures were this production being wrong about its own corpus.
SUBSYS = r"S[1-5]|S3_star"
LOCUS = re.compile(
    rf"^(?:{SUBSYS}"                       # subsystem
    rf"|L(?:\d+|[+−]\d+)"             # level: L0 / L+2 / L−1
    rf"(?:\.\.L(?:\d+|[+−]\d+))?"     # level span: L1..L4 / L..L+2
    rf"|L\.\.L(?:\d+|[+−]\d+)"        # open-left span: L..L+2
    rf"|(?:{SUBSYS})\u2194(?:{SUBSYS}))$")   # channel: S4<->S4


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_file(path: str, strict_refs: bool = False) -> ParseResult:
    result = ParseResult()

    try:
        with open(path, encoding='utf-8') as f:
            raw = f.read()
    except OSError as e:
        result.error(f"cannot open file: {e}")
        return result

    lines = raw.splitlines()
    result.ast['path'] = path
    result.ast['lines'] = len(lines)

    # ── §13.1 Header check ────────────────────────────────────────────────────
    header_name = footer_name = vsm_version = None

    for i, line in enumerate(lines, 1):
        m = RE_HEADER.search(line)
        if m:
            header_name = m.group(1)
            result.ast['id']      = m.group(1)
            result.ast['exp_id']  = m.group(2)
            result.ast['version'] = m.group(3)
            result.ast['date']    = m.group(4)
            vsm_version = m.group(3)
            if not (RE_DATE.match(m.group(4)) or RE_TIMESTAMP.match(m.group(4))):
                result.warn(f"date '{m.group(4)}' not ISO 8601 (date-only or UTC timestamp)", i)
            break

    if not header_name:
        # ⟦…⟧ is an OPTIONAL convention (experiment/seed files); the BNF requires @vsm, not this.
        result.warn("no ⟦…⟧ header (optional convention; @vsm is the required grammar start)")

    # ── @vsm version declaration ───────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if RE_BLANK.match(line) or RE_COMMENT.match(line):
            continue
        if RE_HEADER.search(line):
            continue
        m = RE_VERSION.match(line)
        if m:
            result.ast['vsm_decl'] = m.group(1)
            if m.group(1) != vsm_version and vsm_version:
                result.warn(f"@vsm {m.group(1)} differs from header version {vsm_version}", i)
        break

    if '@vsm' not in raw:
        result.error("missing @vsm version declaration")
    elif result.ast.get('vsm_decl') and not RE_SEMVER.match(result.ast['vsm_decl']):
        # version ::= int "." int  (BNF Part IV)
        result.error(f"@vsm version '{result.ast['vsm_decl']}' is not int.int (BNF: version ::= int \".\" int)")

    # ── BNF: domain_context (optional; well-formed if present) ──────────────────
    mdc = RE_DOMCTX.search(raw)
    if mdc:
        fields = {}
        for part in mdc.group(1).split(','):
            if '=' in part:
                k, v = part.split('=', 1)
                fields[k.strip()] = v.strip()
        result.ast['domain_context'] = fields
        layer = fields.get('layer')
        if layer and not LOCUS.match(layer):
            result.warn(f"domain_context layer '{layer}' is not a LOCUS "
                        f"(subsystem | level | level_span | channel) — "
                        f"BNF vsl_language §grammar locus")

    # ── BNF: system_def V(id, L=int) [@status=...] ─────────────────────────────
    systems = []
    for i, line in enumerate(lines, 1):
        for m in RE_SYSDEF.finditer(line):
            systems.append({'id': m.group(1).strip('"'), 'L': int(m.group(2))})
        ms = RE_STATUS.search(line)
        if ms and ms.group(1) not in (VALID_STATUS | VALID_DOC_STATUS):
            result.warn(f"@status '{ms.group(1)}' in neither vocabulary — "
                        f"V-lifecycle {sorted(VALID_STATUS)} nor document "
                        f"{sorted(VALID_DOC_STATUS)}", i)
    result.ast['systems'] = systems

    # ── Footer check ─────────────────────────────────────────────────────────
    footer_has_fields = False
    for line in reversed(lines):
        m = RE_FOOTER.search(line)
        if m:
            footer_name = m.group(1)
            footer_has_fields = bool(RE_FOOTER_FIELDS.search(line))
            break

    if header_name and footer_name and header_name != footer_name:
        result.error(f"header/footer name mismatch: '{header_name}' ≠ '{footer_name}'")

    # VSM 1.2.1 closure policy (ratified rmw3 S5): the closing footer MUST be
    # name-only ⟦ /name ⟧ — no | id | version | date repeat. The header keeps the
    # full 4-field form; the footer is the canonical closure. A full-repeat footer
    # is a HARD ERROR for vsm-1.2.1+ (enforced in the kernel); pre-1.2.1 docs keep
    # their legacy form silently, so existing --strict gates on vsm-1.2 operational
    # docs (TASKS.vsm / HANDOFF) are not broken by this change.
    if footer_has_fields:
        try:
            vtuple = tuple(int(x) for x in vsm_version.split(".")) if vsm_version else ()
        except ValueError:
            vtuple = ()
        if vtuple >= (1, 2, 1):
            result.error(
                f"footer must be ⟦ /{footer_name} ⟧ for vsm-{vsm_version} "
                f"(no | fields; see vsl_language_primer §closure)")

    if not footer_name:
        # covenant.vsm waives the FOOTER only — it closes with the
        # constitutional SEAL ⟦ VSF ✸ 2026 | Valparaíso, Chile ⟧ instead.
        # Ratified rmw3 (S5) 2026-08-07 and declared in
        # docs/spec_revision/design-sources/vsf-cert-rubric-v1/certification_rubric.vsm §exceptions. The parser
        # did not know, so the ONE ratified exception in the corpus read as
        # the corpus's only unfixable failure — which is how a real exception
        # becomes the reason a gate stays switched off.
        if os.path.basename(path) != "covenant.vsm":
            result.warn("missing ⟦ /name ⟧ footer")

    # ── Delimiter balance — DELEGATED to scripts/vsl/tokenizer.py ──────────
    # This was a hand-rolled string-aware scanner and it was wrong in exactly
    # one way: an ESCAPED quote closed the string. vsl_language's BNF section
    # writes literals as \" and the state desynchronised there, so a balanced
    # document reported "brace depth 1 at EOF" — one of the 11 remaining
    # --strict failures was this scanner, not the corpus.
    # The tokenizer answers the question once, for every tool, and it is
    # negative-tested: an unterminated string blocks, an unclosed block
    # blocks, and math literals {x : L(x) ≤ τ} / [a,b) pass.
    try:
        from tokenizer import tokenize          # scripts/vsl on sys.path
        _doc = tokenize(path)
        _brace = sum(l.code.count("{") - l.code.count("}") for l in _doc.lines)
        _brack = sum(l.code.count("[") - l.code.count("]") for l in _doc.lines)
        if _doc.lines and _doc.lines[-1].opens_string:
            _at = ""
            if getattr(_doc, "string_open_line", None):
                _at = f" — opened at line {_doc.string_open_line}"
            result.error("a string is still OPEN at EOF — an unterminated "
                         f"value silently absorbs whatever follows it{_at}")
        if _brace:
            result.error(f"brace depth {_brace} at EOF (block nesting)")
        if _brack:
            result.warn(f"bracket depth {_brack} at EOF (array or math "
                        f"interval e.g. [a,b))")
    except Exception as _e:                     # tokenizer absent → say so
        result.warn(f"delimiter balance NOT CHECKED — tokenizer unavailable "
                    f"({_e.__class__.__name__}). This is a gap, not a pass.")

    # ── Hypothesis labels — a CONVENTION lint, not BNF (Part IV has no hypothesis production).
    #    Reusing H1/A5 across blocks (declaration vs results) is legitimate → WARN, never fail. ──
    # SCOPED BY BLOCK, ¬by document. `Q1: "DONE — convex polytope"` and
    # `Q1: "PENDING — define Ω_banking"` are the SAME field name in two SIBLING
    # domain blocks, which is exactly what a field name is for. Document-wide
    # scope reported 6 of these as reused labels, all legitimate.
    # The tokenizer carries block depth, so the check can ask the question it
    # actually meant: is this label reused WITHIN one block?
    hypo_labels: dict[tuple[int, str], int] = {}   # (block identity, label)
    try:
        from tokenizer import tokenize
        _depths = [l.block for l in tokenize(path).lines]
    except Exception:
        _depths = [0] * len(lines)          # degrade to document scope
    for i, line in enumerate(lines, 1):
        m = RE_HYPO.match(line)
        if m:
            label = m.group(1)
            key = (_depths[i - 1] if i - 1 < len(_depths) else 0, label)
            if key in hypo_labels:
                result.warn(f"reused label '{label}' in the SAME block "
                            f"(first at L{hypo_labels[key]})", i)
            hypo_labels[key] = i
    result.ast['hypotheses'] = sorted({lb for _, lb in hypo_labels})

    # ── @ref extraction + existence check ────────────────────────────────────
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    # R_ref_resolution: a ref in system/ is SYMBOLIC — `@ref @var`, bound in
    # system/instance/instance.vsm. The parser resolved refs as filesystem
    # paths and knew nothing about bindings, so the CORRECT form failed and
    # the forbidden form (a literal path) passed. A checker that rewards the
    # thing its own rule forbids is worse than no checker.
    _bind: dict[str, str] = {}
    try:
        _inst = os.path.join(repo_root,
                             "docs/spec_revision/system/instance/vsf-instance-v1/instance.vsm")
        if os.path.exists(_inst):
            with open(_inst, encoding="utf-8") as _fh:
                for _l in _fh:
                    _m = re.match(r'\s*([a-z_][a-z_0-9]*)\s*:\s*"([^"]+)"', _l)
                    if _m:
                        _bind[_m.group(1)] = _m.group(2).replace("*/", "", 1)
    except Exception:
        pass

    refs = []
    # Read @ref from CODE, ¬from the raw line. Every one of the 13 false
    # positives in this class was a MENTION, not a use: `// @ref resolves
    # relative to *`, `all @ref targets resolve`, and the BNF production
    # `ref(@ref <subdir>/<file>.vsm)` quoted inside vsl_language's own grammar
    # block. A document that DESCRIBES a directive was being audited as if it
    # were USING it — the same "rule applied outside its object" the rubric
    # already names for the D7 sweep over the ledger.
    # tokenizer.code blanks comment text AND string bodies, so both vanish and
    # the real refs (which sit in code positions) survive.
    try:
        from tokenizer import tokenize
        _scan = [l.code for l in tokenize(path).lines]
    except Exception:
        _scan = lines               # degrade to raw; over-reports, ¬under
    for i, line in enumerate(_scan, 1):
        for m in RE_REF.finditer(line):
            ref_target = m.group(1).split('#')[0]
            refs.append(ref_target)
            _t = ref_target
            if _t.startswith(("http://", "https://")):
                # A URL is a legitimate ref target and is NOT a filesystem
                # path. Checking it as one made covenant.vsm report its own
                # public repo as a missing file. Existence of a remote is a
                # NETWORK question and this parser does not ask it (R10: no
                # egress in a gate) — so it says nothing rather than lying.
                continue
            if _t.startswith("@"):
                _t = _bind.get(_t[1:], _t)      # unresolved stays unresolved
            ref_path = os.path.join(repo_root, _t)
            if strict_refs and not os.path.exists(ref_path):
                result.error(f"@ref target not found: {ref_target}", i)
            elif not os.path.exists(ref_path):
                result.warn(f"@ref target not found: {ref_target}", i)
    result.ast['refs'] = refs

    # ── Key extraction (top-level) ────────────────────────────────────────────
    keys = []
    for line in lines:
        m = RE_KV.match(line)
        if m and m.group(1) == '':
            keys.append(m.group(2))
    result.ast['top_level_keys'] = keys

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def corpus_sweep(root: str, strict: bool = False) -> int:
    """Validate every .vsm / .vsm.md under `root` against the BNF. Prints a conformance summary +
    the offending files (real findings only). Exit 0 iff every file is valid."""
    import os
    files = []
    for dirpath, _, names in os.walk(root):
        if '/target/' in dirpath + '/' or '/.git/' in dirpath + '/':
            continue
        for n in names:
            if n.endswith('.vsm') or n.endswith('.vsm.md'):
                files.append(os.path.join(dirpath, n))
    files.sort()
    invalid = []
    for f in files:
        r = parse_file(f, strict_refs=strict)
        if not r.valid:
            invalid.append((f, r.errors))
    print(f"# VSL v1.0 corpus conformance — {root}")
    print(f"## {len(files) - len(invalid)}/{len(files)} valid; {len(invalid)} invalid")
    for f, errs in invalid:
        print(f"  ✗ {f}")
        for e in errs[:3]:
            print(f"      {e}")
    return 0 if not invalid else 1


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)

    if args[0] == '--corpus':
        root = args[1] if len(args) > 1 else '.'
        sys.exit(corpus_sweep(root, strict='--strict' in args))

    path = args[0]
    emit_json = '--json' in args
    strict    = '--strict' in args

    result = parse_file(path, strict_refs=strict)

    if strict and result.warnings:
        for w in result.warnings:
            result.errors.append(w.replace('WARN', 'ERROR'))
        result.valid = False

    if emit_json:
        out = {'valid': result.valid, 'errors': result.errors,
               'warnings': result.warnings, 'ast': result.ast}
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        status = "✓ VALID" if result.valid else "✗ INVALID"
        print(f"{status}  {path}")
        print(f"  id={result.ast.get('id','?')}  version={result.ast.get('version','?')}  "
              f"date={result.ast.get('date','?')}")
        sysrepr = ", ".join(f"V({s['id']},L={s['L']})" for s in result.ast.get('systems', [])) or "—"
        print(f"  @vsm={result.ast.get('vsm_decl','?')}  systems: {sysrepr}  "
              f"domain_context: {result.ast.get('domain_context', {}) or '—'}")
        print(f"  hypotheses: {result.ast.get('hypotheses', [])}  "
              f"refs: {len(result.ast.get('refs', []))}  "
              f"keys: {result.ast.get('top_level_keys', [])}")
        for e in result.errors:   print(f"  {e}")
        for w in result.warnings: print(f"  {w}")

    sys.exit(0 if result.valid else 1)


if __name__ == '__main__':
    main()
