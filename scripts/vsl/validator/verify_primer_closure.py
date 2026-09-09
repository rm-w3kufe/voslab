#!/usr/bin/env python3
"""verify_primer_closure.py — notation-closure checker for the VSL boot primer.

Closure property being enforced:

    ∀ glyph g used anywhere in the primer:
        g ∈ the set of glyphs DECLARED in the primer's own notation{} section

i.e. the document defines every symbol it uses, in itself, with no appeal to
an external table. This is what makes the primer portable: an agent that has
never seen vsm_notation_spec.md can still read every sign in it.

Why this exists: the 2026-08-03/04 audit found the prose canon
(docs/spec/vsm_notation_spec.md Part I) declares `⟹` as "Escalation" while
using it as logical implication in its own axioms, and uses `⊤` without ever
declaring it. Those are exactly the collisions a human reader silently
patches over and an external agent cannot. This check makes "every sign is
grounded" a tested property rather than a claim -- same discipline as
verify_boot_primer.py (staleness), applied to internal coherence instead.

The declared set is parsed FROM the document, not hardcoded here, so the
check cannot go stale against an edited notation section.

Usage:
  python3 scripts/vsl/verify_primer_closure.py           # check (default)
  python3 scripts/vsl/verify_primer_closure.py --list    # show declared set

Exit codes: 0 = closed (every glyph used is declared)
            1 = OPEN (>=1 undeclared glyph, or notation section not found)

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIMER = ROOT / "docs/spec_revision/system/boot/core_boot_primer.vsm"

# Characters that carry no semantic load: box-drawing used in the section
# banners, prose punctuation (em/en dash, ellipsis, typographic quotes), and
# plain ASCII (declared wholesale as the substrate's lexical base -- letters,
# digits, and keyboard punctuation are not "glyphs" in the sense this check
# cares about). Prose punctuation is excluded deliberately: it appears only
# inside `//` commentary, never in a formal expression, so declaring it in
# notation{} would be noise rather than grounding.
DECORATIVE = set("═─│┌┐└┘├┤┬┴┼" "—–…“”‘’")


def is_glyph(ch: str) -> bool:
    """A 'glyph' = a non-ASCII symbol carrying notation meaning."""
    if ch.isascii() or ch.isspace():
        return False
    if ch in DECORATIVE:
        return False
    # Letters (e.g. accented prose) are not notation symbols -- except the
    # Greek ones VSL genuinely uses as variables (λ τ ε ψ φ Δ).
    cat = unicodedata.category(ch)
    if cat.startswith("L") and not ("GREEK" in unicodedata.name(ch, "")):
        return False
    return True


def split_sections(text: str) -> tuple[str, str]:
    """Return (notation_section, everything_else)."""
    m = re.search(r"^\s*notation:\s*\"", text, re.M)
    if not m:
        return "", text
    start = m.end()
    # notation section ends at the first `",` that closes the VSL string
    end_m = re.compile(r"\",\s*$", re.M).search(text, start)
    if not end_m:
        return "", text
    end = end_m.start()
    return text[start:end], text[:m.start()] + text[end:]


def glyphs_in(s: str) -> set[str]:
    return {ch for ch in s if is_glyph(ch)}


def _split_args(inner: str) -> list[str]:
    """Split top-level commas only. Commas inside {set} literals are NOT
    argument separators — scope({A0, A0.1}) is ONE argument (a set).

    The v2 boot primer declares `scope(X) := set of systems…` (arity 1) and
    uses it as scope({A0, A0.1}) / scope({A1..A11}). A naive split(",") read
    the set's inner comma as a second argument and flagged ARITY MISMATCH on
    the canonical production file — a false positive that would have blocked
    the boot promotion of 2026-08-11. Top-level-only splitting is correct for
    every predicate, not a special case.
    """
    args: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in inner:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            if "".join(cur).strip():
                args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        args.append("".join(cur))
    return args


def arity_check(notation: str, rest: str) -> list[str]:
    """Second closure axis: a predicate must be USED with the arity it was
    DECLARED with, and every predicate used must be declared at all.

    Why this exists: on 2026-08-04 an external reviewer (Kimi K3) found the
    primer used `T(A,B)` in channels{} while trust{} declared only `T(t)` —
    and `Q2` as a dangling forward reference. This script reported
    "notation closed" through both, because it only compared GLYPHS. A
    checker that passes a document containing undefined predicates is worse
    than no checker: it converts an open question into false confidence.
    Glyph closure was necessary and not sufficient; this is the missing half.
    """
    decl: dict[str, set[int]] = {}
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(([^()]*)\)\s*(?:∈|:=)",
                         notation):
        args = _split_args(m.group(2))
        decl.setdefault(m.group(1), set()).add(len(args))
    # shorthands declared as equivalences: T(t) ≡ T(self, peer, t)
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(([^()]*)\)\s*≡", notation):
        args = _split_args(m.group(2))
        decl.setdefault(m.group(1), set()).add(len(args))

    # Strip `//` prose before checking, exactly as term_check does. Found
    # 2026-08-04 when a header comment describing a FIX ("...in audit()...")
    # tripped the guard on its own commit. Formal expressions live in the VSL
    # body; commentary about them is prose. The two axes disagreeing on this
    # was an inconsistency in this file, not a finding about the primer.
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in rest.splitlines())

    problems: list[str] = []
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(([^()]*)\)", body):
        name, inner = m.group(1), m.group(2)
        if name not in decl:
            continue                      # handled by term_check (3rd axis)
        n = len(_split_args(inner))
        if n not in decl[name]:
            problems.append(
                f"{name} used with {n} arg(s); declared with "
                f"{sorted(decl[name])} — {m.group(0)[:52]}")
    return sorted(set(problems))


# Structural vocabulary of the primer itself + VSL keywords + the S1..S5
# selectors. These are not terms the document must define -- they ARE the
# document. Kept explicit and small: every addition here narrows what the
# check can catch, so each one should be defensible on its own.
STRUCTURAL = {
    "primer", "vsl_def", "notation", "structure", "axioms_vsf", "axioms_universal",
    "axioms_extension", "foundation", "tick", "channels", "trust", "comms",
    "handshake", "scope", "substrate", "vsl", "disambiguation",
    "requires", "required", "mediated", "transitions", "assert", "iff",
    "true", "false", "and", "not", "per", "the", "for", "all", "any",
    "log", "min", "max", "sup", "inf", "abs", "measure", "conformance",
}


def term_check(notation: str, rest: str) -> list[str]:
    """Third closure axis: multi-character TERM names must be declared.

    Found externally by Qwen Chat, 2026-08-04: `error_S2` appears in
    trust{}'s audit formula and is declared nowhere — "which technically
    violates your own closure rule". Correct, and broader than the one
    example: `reachability`, `stability` and `audit` were equally undeclared.

    The first two axes could not see this. Glyph closure ignores ASCII
    entirely; arity closure explicitly skipped names it did not recognise as
    predicates. So "notation closed" had been asserted three times while the
    definition of "closed" quietly shrank to whatever was being checked.
    That is the failure this file exists to prevent, committed by this file.

    SCOPE, deliberately narrow -- first attempt scanned every word and
    produced 271 hits, almost all ordinary English from `//` comments. That
    is the noise level that gets a checker ignored, and an ignored checker is
    worse than none (cf. the canon-census stage-1 review, same session, same
    lesson). Narrowed to what actually carries the defect:

      an identifier is checked ONLY when it appears as an OPERAND -- adjacent
      to an arithmetic/relational operator -- which is exactly the shape of
      `(1 − error_S2)`. Labels, enum members, section keys and prose are out
      of scope by construction, not by blocklist.

    Anything introduced anywhere via `:=` / `::=` counts as declared: the
    document is allowed to define a term at its point of use.
    """
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in rest.splitlines())
    declared = set(re.findall(r"\b([A-Za-z][A-Za-z0-9_]{2,})\b", notation))
    declared |= set(re.findall(r"([A-Za-z][A-Za-z0-9_]{2,})\s*(?:\([^()]*\))?\s*::?=",
                              body))
    OPS = r"[+\-−·/=≤≥<>∈∉≠≈]"
    used = set(re.findall(rf"{OPS}\s*\(?\s*([a-z][A-Za-z0-9_]{{2,}})\b", body))
    used |= set(re.findall(rf"\b([a-z][A-Za-z0-9_]{{2,}})\s*\)?\s*{OPS}", body))
    return sorted(used - declared - STRUCTURAL)


def main() -> int:
    if not PRIMER.exists():
        print(f"  ✗ primer not found: {PRIMER.relative_to(ROOT)}")
        return 1

    text = PRIMER.read_text(encoding="utf-8")
    notation, rest = split_sections(text)

    if not notation:
        print("  ✗ no notation{} section found -- closure cannot be checked.")
        print("    The primer must declare its own glyphs to stay portable.")
        return 1

    declared = glyphs_in(notation)
    used = glyphs_in(rest)

    if "--list" in sys.argv:
        print(f"  declared ({len(declared)}): {' '.join(sorted(declared))}")
        print(f"  used     ({len(used)}): {' '.join(sorted(used))}")
        return 0

    undeclared = used - declared
    if undeclared:
        print("  ✗ NOTATION NOT CLOSED — glyph(s) used but never declared:")
        for ch in sorted(undeclared):
            name = unicodedata.name(ch, "?")
            # show one line of context so the fix is obvious
            ctx = ""
            for line in rest.splitlines():
                if ch in line:
                    ctx = line.strip()
                    break
            print(f"      {ch}  ({name})")
            if ctx:
                print(f"         first use: {ctx[:78]}")
        print()
        print("  Fix: declare each glyph in the primer's notation{} section")
        print("  (substrate: or vsl:), or replace it with a declared one.")
        print("  Do NOT suppress this check -- an undeclared sign is exactly")
        print("  what an external agent cannot resolve.")
        return 1

    arity = arity_check(notation, rest)
    if arity:
        print("  ✗ ARITY MISMATCH — predicate used with an undeclared shape:")
        for p in arity:
            print(f"      {p}")
        print()
        print("  Fix: declare every arity the document actually uses in the")
        print("  notation{} section (or as an explicit ≡ shorthand). Glyph")
        print("  closure alone is NOT sufficient -- it passed this file while")
        print("  T(A,B) and Q2 were undefined (found externally, 2026-08-04).")
        return 1

    if "--terms" in sys.argv:
        terms = term_check(notation, rest)
        print(f"\n  [advisory] {len(terms)} candidate undeclared terms "
              f"— NOT a gate, expect false positives:")
        for t in terms:
            ctx = next((l.strip() for l in rest.splitlines() if t in l), "")
            print(f"      {t:<22} {ctx[:52]}")
        print("\n  Known noise classes still unfiltered: field accesses"
              " (op.autonomy),\n  enum members ({directive,...}), RHS labels"
              " (S1 := execute), ∃-bound\n  names. Regex cannot separate these"
              " -- rebuild on scripts/vsl/vsl_parser.py.")

    print(f"  ✓ notation closed — {len(used)} glyphs, all declared; "
          f"predicate arities consistent")
    print("    (term closure: advisory only, --terms — see docstring)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
