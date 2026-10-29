#!/usr/bin/env python3
"""tokenizer.py — one structural read of a VSL document, shared by every tool.

WHY THIS EXISTS
---------------
Five open items in the conformance attenuator had ONE root cause: the tools
counted CHARACTERS where they had to read STRUCTURE. None of them knew where a
string began or ended, nor where a block did.

What that cost, all of it measured on this corpus:

  * brace depth flagged math literals — {x : L(x) ≤ τ} and intervals [a,b) —
    as unbalanced blocks. 4 false positives across certified documents.
  * label scope did not exist, so Q1..Q3 used as field names in three sibling
    blocks read as reused labels. 6 false positives.
  * definition-vs-citation was POSITIONAL — "an identifier opening a line is a
    definition" — and could not separate `Ax_QuasiStationary: "∃ π …"`, a real
    declaration inside a quoted block, from `D6: removing the LLM`, wrapped
    prose that happens to carry a colon. Rewritten THREE times; each rewrite
    traded one error class for another.
  * quote parity was tried as a fix and desynchronises on any line with an odd
    number of quotes, then poisons every line after it.
  * the orphan-line metric was abandoned because "short line" cannot be told
    from "dense notation" without knowing what CONTINUES.

Each was attacked with a regex, and each regex was wrong in a new way. This
module answers the questions those regexes were guessing at, once, structurally.

WHAT IT PRODUCES
----------------
A Line record per physical line, carrying the facts a checker actually needs:

    in_string     the line BEGINS inside an unterminated string
    opens_string  a string is still open when the line ends
    code          the line with comments and string BODIES blanked out, so a
                  delimiter counter sees only structural delimiters
    depth         block nesting BEFORE this line, braces in strings excluded
    kind          declaration | continuation | comment | blank | structural
    name          for a declaration, the identifier being declared

VSL SPECIFICS this had to get right, each learned from a real defect:
  * `//` opens a comment, but `://` inside a URL does not
  * a string may span many lines and carries prose, notation and braces
  * a declaration is `ident:` or `ident =` at the START of a line, OUTSIDE a
    string — and inside a quoted BLOCK a declaration is still a declaration,
    because in VSL a quoted block is a container for declarations, not only
    prose (boot/regulation_layer writes `Ax_TraceabilityClosure:` inside
    `boundary: "…"`)

Deterministic, stdlib-only. No LLM in this path (R10).
Self-test:  python3 scripts/vsl/tokenizer.py --selftest
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# vslline.py lives in this same directory (scripts/vsl/) — make it
# importable whether tokenizer runs as a script or as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vslline import brace_delta as _brace_delta  # noqa: E402
from vslline import scan_line as _scan_line      # noqa: E402

# `ident:` or `ident =` opening a line. The identifier may carry dots and
# hyphens (D6.tactical, D4-L2). `::=` and `==` are NOT declarations.
# Greek belongs in an identifier: Ax_ψ_Preserve, Ax_Ω_Closure, Def_Adaptiveτ,
# Def_SeqLockσ. The charset excluded it, so four DECLARATIONS in the canon's
# own notation section read as continuations — and boot/ read as leaking
# them. symbol_table's identifier patterns were widened for exactly this on
# 2026-08-09; the tokenizer was not. One fix, two places, one applied.
DECL = re.compile(r"^([A-Za-z_][A-Za-z_0-9.\-\u0370-\u03ff\u1f00-\u1fff]*)\s*(?::(?!:)|=(?!=))")
# A block opener that is also a declaration: `name(args) = {` / `name = {`
BLOCK_OPEN = re.compile(r"^([A-Za-z_][A-Za-z_0-9.\-]*)\s*(?:\([^)]*\))?\s*=?\s*\{")
# Structural-only lines: closers, separators.
STRUCTURAL = re.compile(r"^[\}\]\),;]+$")
# `ident <statement>` — the canon's juxtaposition form, no adjacent operator.
EXTRA_DECL = re.compile(
    r"(?<![\w.\-])([A-Za-z_][A-Za-z_0-9.\-Ͱ-Ͽἀ-῿]*)\s*:(?!:)\s*(?=\S)")
JUXT = re.compile(r"^([A-Za-z_][A-Za-z_0-9.\-\u0370-\u03ff\u1f00-\u1fff]*)\s+\S")
# Operators that make what follows a STATEMENT rather than a sentence.
# Derivation arrows included: core_boot_primer declares corollaries as
# `A5.Cor1  ⟸  A5 ∧ transitive(≤, L)`. Kept to operators that are NEVER
# prose punctuation — `<` and `>` are deliberately absent.
# ORDER RELATIONS included 2026-08-09. The canon states axioms as
# INEQUALITIES — `A2   B(child) ≤ B(parent)` — and without ≤ the primer's
# own axioms did ¬index as declared, so the dependency graph read the
# PRIMER as depending on vsl_language for A2, A6 and D4. A false edge
# straight through the canon's root.
# The TYPOGRAPHIC forms only: ASCII `<` and `>` stay out, because
# `D6 (no LLM at L<2) gated…` is prose and would declare D6.
DEF_OPS = set("=:≜∈→⟹⟺⊆≡⟸⟵←≔↦⊨⊢≤≥≠≜⊂⊃")


@dataclass
class Line:
    n: int                    # 1-indexed
    raw: str
    in_string: bool           # begins inside an unterminated string
    opens_string: bool        # a string is open when the line ends
    code: str                 # comments stripped, string BODIES blanked
    depth: int                # block depth BEFORE this line
    kind: str                 # declaration|continuation|comment|blank|structural
    name: str = ""            # declared identifier, when kind == declaration
    names: tuple[str, ...] = ()   # ALL identifiers declared on this line.
                              # vsl_language writes `D16 adaptive_τ:
                              # Def_Adaptiveτ: τ : Lifecycle → …` — a canon id,
                              # a human name and a formal name, three
                              # declarations in one line. `name` held the first,
                              # so Def_Adaptiveτ/Def_VRComplex/Def_SeqLockσ read
                              # as CITED and boot/ read as leaking them.
    block: int = 0            # IDENTITY of the innermost enclosing block.
                              # ¬the same as depth: two SIBLING blocks share a
                              # depth. Scoping labels by depth still reported
                              # `Q1` in vsf_nucleus and `Q1` in vsf_banking as
                              # one reuse — they are the same field name in two
                              # different domains, which is what a field name
                              # is for. Identity separates them; depth cannot.


@dataclass
class Doc:
    path: Path
    lines: list[Line] = field(default_factory=list)
    # Line (1-indexed) where the string that is STILL OPEN at EOF was
    # opened. None when no string is open at EOF. This is the diagnosis
    # that "brace depth N at EOF" hides: an unterminated string silently
    # absorbs every `}` after it, so the report blamed innocent braces.
    string_open_line: int | None = None

    def declarations(self) -> list[Line]:
        return [l for l in self.lines if l.kind == "declaration"]

    def depth_at_eof(self) -> int:
        return self.lines[-1].depth if self.lines else 0

    def unbalanced(self) -> int:
        """Block depth left open at EOF, counting only structural braces."""
        d = 0
        for l in self.lines:
            d += _brace_delta(l.code)
        return d

    def first_negative_depth(self) -> tuple[int, str] | None:
        """First line where a `}` closes WITHOUT a matching `{` (depth < 0).

        The net depth at EOF can be 0 ACCIDENTALLY: a stray `}` (delta -1)
        cancels an unclosed `{` elsewhere (delta +1) — the 2026-08-15
        TASKS.vsm incident (THERMAL-WATCHDOG-MISSING vs THEORY-FUSE-REMAINDER).
        This surfaces the FIRST intermediate negative: the exact line where
        the extra closer happens, BEFORE any structural operation relies on
        the (accidentally zero) net balance.
        """
        d = 0
        for l in self.lines:
            d += _brace_delta(l.code)
            if d < 0:
                return (l.n, l.raw.strip()[:64])
        return None


def tokenize(path: Path | str) -> Doc:
    path = Path(path)
    doc = Doc(path=path)
    in_string = False
    string_open_line: int | None = None   # where the currently-open string opened
    depth = 0
    stack: list[int] = [0]        # innermost-last; 0 = document scope
    next_id = 1
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        began_in_string = in_string
        code, in_string = _scan_line(raw, in_string)
        # Track where the string that is STILL OPEN at the end of this line
        # was opened. A string that spans lines keeps its opener line; a
        # line that starts inside a string and closes it (then possibly
        # re-opens) moves the marker to this line.
        if in_string and not began_in_string:
            string_open_line = n          # a quote opened on this line
        elif in_string and began_in_string:
            pass                           # continuation — opener unchanged
        elif began_in_string and not in_string:
            string_open_line = None        # the open string closed here
        # A string that closes AND re-opens within one line: the marker
        # moves to this line only when a NEW quote is present after the
        # close. _scan_line blanks string bodies, so `code` carries only
        # structural quotes; two structural quotes on one in-string line
        # mean close-then-reopen.
        if not in_string and began_in_string and code.count('"') >= 2:
            string_open_line = n
        stripped = raw.strip()
        body = code.strip()

        if not stripped:
            kind, name = "blank", ""
        elif stripped.startswith("//"):
            kind, name = "comment", ""
        elif STRUCTURAL.match(body):
            kind, name = "structural", ""
        else:
            # A declaration is `ident:` / `ident =` at the start of the line.
            # It counts INSIDE a quoted block too: VSL quoted blocks contain
            # declarations. What it must NOT count is a line that begins in the
            # MIDDLE of a wrapped sentence — and that is exactly the case where
            # the line began in a string AND carries no definition operator at
            # its own start.
            m = DECL.match(stripped) or JUXT.match(stripped)
            if m and _looks_declarative(stripped):
                kind, name = "declaration", m.group(1)
            elif m and not began_in_string and DECL.match(stripped):
                # Outside a string an adjacent operator declares outright:
                # nothing can be a wrapped sentence there.
                kind, name = "declaration", m.group(1)
            else:
                kind, name = "continuation", ""

        names: tuple[str, ...] = (name,) if name else ()
        if kind == "declaration":
            # A SECOND `ident:` after the first is another declaration on the
            # same line. Narrow by construction: it must be followed by ':' and
            # then a value, so prose with a colon does ¬qualify.
            for m2 in EXTRA_DECL.finditer(stripped[len(name):]):
                if m2.group(1) not in names:
                    names += (m2.group(1),)
        doc.lines.append(Line(n=n, raw=raw, in_string=began_in_string,
                              opens_string=in_string, code=code,
                              depth=depth, kind=kind, name=name,
                              names=names, block=stack[-1]))
        for ch in code:
            if ch == "{":
                stack.append(next_id); next_id += 1
            elif ch == "}" and len(stack) > 1:
                stack.pop()
        depth += _brace_delta(code)
    doc.string_open_line = string_open_line if in_string else None
    return doc


def _looks_declarative(stripped: str) -> bool:
    """Inside a string, tell a declaration from prose carrying a colon.

    `Ax_QuasiStationary: "∃ π s.t. …"`  → declaration: the value is quoted or
                                          the identifier is notation-shaped
    `D6: removing the LLM`              → prose: lowercase words follow, and
                                          the identifier is a bare canon id
    The rule is the SHAPE OF THE VALUE, not the identifier: a declaration's
    value opens a string, a block, a list, or a number. Prose does not.
    """
    m = DECL.match(stripped)
    if m:
        rest = stripped[m.end():].strip()
        if not rest:
            return True                   # `name:` then a block on the next line
        if rest[0] in '"[{0123456789-+.⟨(':
            return True
        # A FORMULA is a declaration too, and it opens with a VARIABLE:
        #   Def_SplitOperator: x(t+1) = f₀(x(t)) + σ(t)·η(t)
        #   Def_TrustUpdate:   trust(t+1) = (1−λ)·trust(t) + λ·obs
        #   Def_Adaptiveτ:     τ : Lifecycle → [0.05, 1]
        # The value-shape test rejected all of them for opening with a
        # lowercase letter, so vsl_language read as CITING 17 identifiers it
        # DECLARES — and boot/ read as UNCLOSED. I was one step from trimming
        # real declarations out of the canon on that measurement.
        # Same rule as the juxtaposition branch: a definition operator at
        # PARENTHESIS DEPTH 0. `removing the LLM never breaks L0/L1` has ∄,
        # so the prose case stays a citation.
        return _has_op_at_depth0(rest)
    # JUXTAPOSITION. VSL's canon declares axioms with no operator directly
    # after the name — `A1   S1(L) = { V_i(L+1) }` — and those tables live
    # INSIDE quoted blocks (`axioms: "…"`). Requiring the operator adjacent to
    # the name dropped `defined` 116 → 57: A1..A15, D1..D21, DP1..DP5 and every
    # VSI-L* became "cited nowhere".
    # Neither is the gap width a discriminator: `msg_type : Message → …` and
    # `A := { O, S, … }` declare with ONE space, and 2410 corpus lines match
    # that shape against 156 with a wider gap.
    # What separates a declaration from a WRAPPED SENTENCE is whether a
    # definition/relation operator appears at PARENTHESIS DEPTH 0:
    #   `A1   S1(L) = { V_i(L+1) }`               `=` at depth 0  → declares
    #   `D6 (no LLM at L<2) gated; panel never…`  `<` is INSIDE ( ) → prose
    # Depth matters: without it, the `<` in `L<2` reads as a relation and the
    # sentence declares D6 — the exact false positive that made two correct
    # documents look like they redefined a canon rule.
    m = JUXT.match(stripped)
    if not m:
        return False
    return _has_op_at_depth0(stripped[m.end(1):])


def _has_op_at_depth0(s: str) -> bool:
    """A definition/relation operator OUTSIDE every bracket.

    Depth is load-bearing: the `<` in `D6 (no LLM at L<2) gated…` sits inside
    ( ) and is ¬an operator of that line. Without it that sentence declares D6.
    """
    depth = 0
    for ch in s:
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif depth <= 0 and ch in DEF_OPS:
            return True
    return False


# ── self-test ────────────────────────────────────────────────────────────────
CASES = [
    # (source, line number, expected kind, expected name)
    ('a: 1\n',                                   1, "declaration", "a"),
    ('x: "open\nstill prose here\n"\n',          2, "continuation", ""),
    ('b: "v"\nAx_Q: "∃ π"\n',                    2, "declaration", "Ax_Q"),
    ('f: "the F_S4 keeps its\nD6: removing the LLM\n"\n', 2, "continuation", ""),
    ('// a comment\n',                           1, "comment", ""),
    ('u: "http://x/y"\nz: 2\n',                  2, "declaration", "z"),
    # `::=` is the BNF PRODUCTION operator and it DECLARES its left side
    # (vsl_language:717 `identifier ::= [a-zA-Z_]…`). An earlier version of
    # this case asserted "continuation"; that assertion was wrong, ¬the code.
    ('p ::= q\n',                                1, "declaration", "p"),
]


def _selftest() -> int:
    import tempfile
    ok = fail = 0
    for src, ln, kind, name in CASES:
        with tempfile.NamedTemporaryFile("w", suffix=".vsm", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(src); p = fh.name
        d = tokenize(p)
        Path(p).unlink()
        got = d.lines[ln - 1]
        if got.kind == kind and got.name == name:
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {src!r} line {ln}: want {kind}/{name!r}, "
                  f"got {got.kind}/{got.name!r}")

    # braces inside strings must not count toward block depth
    with tempfile.NamedTemporaryFile("w", suffix=".vsm", delete=False,
                                     encoding="utf-8") as fh:
        fh.write('b = {\n  s: "the set {x : L(x) ≤ τ} and [a,b)"\n}\n')
        p = fh.name
    d = tokenize(p); Path(p).unlink()
    if d.unbalanced() == 0:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ math literal counted as a block: depth {d.unbalanced()}")

    # an unterminated string must report WHERE it opened, so a block-depth
    # report can name the real cause instead of blaming innocent braces
    with tempfile.NamedTemporaryFile("w", suffix=".vsm", delete=False,
                                     encoding="utf-8") as fh:
        fh.write('block(B) {\n  note: "never closed\n  more: "x",\n}\n')
        p = fh.name
    d = tokenize(p); Path(p).unlink()
    if d.string_open_line == 2:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ unterminated string opener: want line 2, "
              f"got {d.string_open_line!r}")

    # a stray `}` must be caught at its LINE even when the net EOF depth
    # is 0 accidentally (a `}` here cancels an unclosed `{` elsewhere —
    # the 2026-08-15 TASKS.vsm incident shape)
    with tempfile.NamedTemporaryFile("w", suffix=".vsm", delete=False,
                                     encoding="utf-8") as fh:
        fh.write('block(A) {\n  ok: "1",\n}\n'
                 '} // stray closer: depth goes negative HERE\n'
                 'block(B) {\n  ok: "1",\n')
        p = fh.name
    d = tokenize(p); Path(p).unlink()
    neg = d.first_negative_depth()
    if neg is not None and neg[0] == 4:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ first negative depth: want line 3, got {neg!r}")
    if d.unbalanced() == 0:   # net accidentally balanced — the trap
        ok += 1
    else:
        fail += 1
        print(f"  ✗ net depth should be 0 (two errors canceling), "
              f"got {d.unbalanced()}")

    print(f"  tokenizer selftest: {ok} passed, {fail} failed")
    return 1 if fail else 0


def check(paths: list[Path]) -> int:
    """Blocking structural gate: balanced blocks, no unterminated string.

    This is the check the grammar gate could not make. vsl_parser called a
    document VALID with an unterminated string, because it never tracked where
    a string ended; the two defects it missed were BOTH of that shape:
      s3star_audit  `method: "read probe …` never closed, and the NEXT
                    declaration's opening quote closed it — silently losing
                    the rest of the field AND swallowing the sibling
      s4_visualization  `silent_fallback: "…` missing its terminator
    Both were in CERTIFIED documents. Both passed every gate. One had lost
    text at fuse time and nothing said so for two days.
    """
    # A `//` comment consumes the REST OF THE LINE. That is not a rule we
    # impose — it is what `//` means — but an author can forget it and put
    # code after one. worklist_vsl did: `target: "x" // (note), gate:
    # claude_review },` lost BOTH the field and the closing brace.
    # That instance was findable only because the swallowed `}` unbalanced the
    # document. Had the comment sat AFTER the brace, `gate:` would have
    # vanished in silence and ∄ gate would have seen it. This covers exactly
    # that: a FIELD after a mid-line comment. Narrow by construction — it
    # requires both a field shape AND a trailing closer — and it measures 0 on
    # the corpus today, so any hit is new.
    SWALLOWED = re.compile(r"(?:^|[,\s])([a-z_][a-z_0-9]*)\s*:\s*[A-Za-z_\"\[{]")
    bad = 0
    for p in paths:
        d = tokenize(p)
        for l in d.lines:
            # scan_line blanks string bodies into `code`; a `//` inside a
            # one-line string (e.g. hit: "…\\n// Falt…") survives in raw but
            # NOT in code. Gate on code, not raw — a mid-line comment must
            # be a real comment in the masked stream, not text inside a
            # string value. (Defect found 2026-08-14 by the child S5-local
            # verifier: 22 false positives on not_usage_audit.vsm.)
            if l.in_string or "//" not in l.code:
                continue
            i = l.code.find("//")
            if i == 0 or not l.code[:i].strip():
                continue                      # whole-line comment — fine
            tail = l.code[i + 2:]
            if SWALLOWED.search(tail) and re.search(r"[}\]],?\s*$", tail):
                bad += 1
                print(f"  ✗ {p}:{l.n}: a FIELD sits after a mid-line `//` — "
                      f"the comment runs to END OF LINE and swallows it")
                print(f"      {l.raw.strip()[:74]}")
        u = d.unbalanced()
        open_str = d.lines[-1].opens_string if d.lines else False
        # INTERMEDIATE depth check first: a `}` closing without an opener is
        # the ROOT defect; the net EOF balance may be 0 accidentally (two
        # errors canceling). Report the first negative line precisely.
        neg = d.first_negative_depth()
        if neg:
            bad += 1
            print(f"  ✗ {p}: block depth went NEGATIVE at line {neg[0]} "
                  f"(a `}}` closed without a matching `{{`)")
            print(f"      {neg[1]}")
        if u:
            bad += 1
            # Diagnose the REAL cause first: an unterminated string absorbs
            # every `}` after it, so the block imbalance is a symptom, not
            # the disease. Blaming innocent braces sent a 2026-08-13 debug
            # down the wrong path (sandbox/boot_ontology_pattern.vsm).
            if getattr(d, "string_open_line", None):
                print(f"  ✗ {p}: string opened at line {d.string_open_line} "
                      f"never closed — it absorbed the block closers "
                      f"(reported as block depth {u:+d} at EOF)")
            else:
                print(f"  ✗ {p}: block depth {u:+d} at EOF")
            depth = 0
            for l in d.lines:
                o, c = l.code.count("{"), l.code.count("}")
                if o != c:
                    depth += o - c
                    if depth == u and o > c:
                        print(f"      last unclosed opener → line {l.n}: "
                              f"{l.raw.strip()[:64]}")
        if open_str:
            bad += 1
            _at = (f" — opened at line {d.string_open_line}"
                   if getattr(d, "string_open_line", None) else "")
            print(f"  ✗ {p}: a string is still OPEN at EOF — "
                  f"an unterminated value swallows what follows it{_at}")
    if bad:
        print(f"  ✗ structure: {bad} defect(s) in {len(paths)} file(s)")
        return 1
    print(f"  ✓ structure: {len(paths)} files — blocks balanced, no open string")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if "--check" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--check"]
        paths = ([Path(a) for a in args] if args else
                 sorted((Path(__file__).resolve().parents[3]
                         / "system").rglob("*.vsm")))
        return check(paths)
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0]); return 0
    d = tokenize(sys.argv[1])
    print(f"  {d.path.name}: {len(d.lines)} lines, "
          f"{len(d.declarations())} declarations, "
          f"block depth at EOF {d.unbalanced()}")
    for l in d.declarations()[:20]:
        print(f"    {l.n:>4}  depth {l.depth}  {l.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
