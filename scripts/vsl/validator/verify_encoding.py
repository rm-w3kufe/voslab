#!/usr/bin/env python3
"""verify_encoding.py — byte-level certification for .vsm documents.

Why this exists: on 2026-08-07 a glyph audit of docs/spec_revision found the
corpus mixing FOUR codepoints for "dash" (U+002D, U+2013, U+2014, U+2212) and
TWO for "prime" (U+0027, U+2032). Every one of those pairs is visually
identical, or nearly so, at the size a human reads a spec. A reader cannot
tell them apart; a parser treats them as unrelated. That is the worst possible
combination -- a difference that is invisible to review and load-bearing to
machines.

Glyph closure (verify_primer_closure.py) cannot see any of this: it asks
"is this sign declared?", never "is this the sign you think it is?". This
file is the second question.

What it certifies, per file:

  BLOCKING
    utf8        decodes as UTF-8
    nfc         text == NFC(text). Mixed normalisation makes two byte
                sequences that render identically compare unequal -- so a
                grep, a hash, and a diff all silently disagree with the eye.
    no_bom      no U+FEFF at the start (breaks the `@vsm` first-line rule)
    no_invisible  no NBSP (U+00A0), no zero-width (U+200B-200D, U+FEFF
                mid-file). These survive copy-paste out of rendered docs and
                are undetectable in review.
    header      ⟦ … ⟧ identity header/footer present with EXACTLY 4
                pipe-separated fields. A 5th field does not error -- the
                parser keeps reporting VALID while reading nothing (found
                2026-08-04, by looking at output rather than exit code).
    timestamp   date field MUST be UTC timestamp (2026-08-22T19:14:18Z),
                date-only (2026-08-22) REJECTED (FASE-1-ENFORCEMENT-2026-08-22).

  ADVISORY (reported, never blocks -- these need judgement, not a rule)
    dashes      census per codepoint, against the declared roles:
                  -  U+002D  identifiers, ISO dates, compounds
                  –  U+2013  numeric and code ranges
                  —  U+2014  prose parenthetical
                  −  U+2212  arithmetic minus
                Flags ASCII hyphen adjacent to a math operand, and U+2212
                inside an identifier -- the two directions that actually
                corrupt meaning.

Usage:
  python3 scripts/vsl/verify_encoding.py [path ...]     # default: spec_revision
                                                        # system/boot is inside it
Exit: 0 clean · 1 a BLOCKING check failed.

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ["docs/spec_revision"]

# NO-EMOJIS, rmw3 2026-08-06 (revision_plan.vsm §352): pictographic codepoints
# render as broken characters and destroy machine-readability. The rule names
# its own ranges and its own conversion table (done→✓, cross→✗, warn→?).
#
# It had NO enforcement until now. Found 2026-08-07 by rmw3 READING the file,
# after a ⚠ (U+26A0) this session had introduced survived every gate: closure
# only inspects the primer, encoding did not look at codepoint class, and the
# glyph census compares USED against DECLARED — an undeclared pictograph
# sitting in a comment is invisible to all three at once.
EMOJI_RANGES = [(0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                (0x1F1E6, 0x1F1FF), (0xFE00, 0xFE0F), (0x2300, 0x23FF)]
# Exempt: the verification markers the rule itself permits, plus the
# typographic set vsl_language declares as non-operators (✸ is the covenant
# watermark — part of the constitutional signature).
EMOJI_EXEMPT = set("✓◐◯✗✸†★▼")


def in_emoji_range(ch: str) -> bool:
    return any(a <= ord(ch) <= b for a, b in EMOJI_RANGES)

INVISIBLE = {" ": "NBSP", "​": "ZWSP", "‌": "ZWNJ",
             "‍": "ZWJ", "⁠": "WORD-JOINER"}
HEADER = re.compile(r"⟦([^⟧]*)⟧")
# VSM 1.2 protocol dates (vsl_language_primer §file_grammar, promoted
# 2026-08-16): timestamp REQUIRED (timestamp ::= date "T" hh ":" mm
# [":" ss ["." frac]] "Z" — UTC, precision seconds in docs / µs in events).
# date-only REJECTED (FASE-1-ENFORCEMENT-2026-08-22: unified timestamp format).
RE_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # REJECTED — no hour
RE_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z$")

# The covenant carries a CONSTITUTIONAL SIGNATURE, not an identity footer:
#   ⟦ VSF ✸ 2026 | Valparaíso, Chile ⟧
# Two fields, a watermark and a place. It is the document's seal, and it
# predates the 4-field identity convention. Ratified as a declared exception
# by rmw3 (S5) 2026-08-07 rather than reshaped to fit a rule written for
# machine-read specs. A constitution is not a spec file.
SIGNATURE_EXCEPTION = {"covenant.vsm"}

# math operand on either side of an ASCII hyphen => almost certainly a minus.
# Digits are deliberately EXCLUDED on both sides: `2026-08-07`, `A5-Corolario-2`
# and `38-51%` are all hyphen-correct, and including \d made every ISO date in
# the corpus a false positive (first run, 2026-08-07 -- the advisory was pure
# noise, which is how an advisory gets ignored).
MATH_NEIGHBOUR = re.compile(
    r"[)\]ΩΣλσεμτθκδγβφψαω]\s*-\s*[(\[ΩΣλσεμτθκδγβφψαω]")
# U+2212 inside a WORD => almost certainly meant to be a hyphen. Requires a
# multi-letter run on one side: `x−y` and `B−B` are single-letter variables,
# i.e. correct arithmetic, and matching them made the advisory wrong in the
# one direction it is supposed to be authoritative about.
MINUS_IN_WORD = re.compile(r"[A-Za-z]{2,}−[A-Za-z]|[A-Za-z]−[A-Za-z]{2,}")

# ASCII apostrophe doing the job of a prime. Declared 2026-08-07: ′ (U+2032)
# is the prime, formula-only; ' (U+0027) is apostrophe/quote, prose-only.
# Before that split the SAME formula existed in both encodings in two
# different documents -- d(x,x′) here, d(x,x') there. Advisory rather than
# blocking because a closing quote after a variable-shaped token ("was
# '≥MEDIUM → S5'") is indistinguishable to a regex.
ASCII_PRIME = re.compile(r"(?<![A-Za-z0-9_])(V|S[1-5]|[xyzewtqpσπμληΩΔ])'(?![A-Za-z0-9])")


def check(path: Path) -> tuple[list[str], list[str]]:
    """Return (blocking_problems, advisories) for one file."""
    bad: list[str] = []
    adv: list[str] = []
    raw = path.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        bad.append("BOM at start of file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return [f"not valid UTF-8: {e}"], []

    if unicodedata.normalize("NFC", text) != text:
        bad.append("not NFC-normalised (renders identically, compares unequal)")

    for ch, name in INVISIBLE.items():
        n = text.count(ch)
        if n:
            bad.append(f"{n}× invisible {name} (U+{ord(ch):04X})")

    seen: dict[str, int] = {}
    for ln_no, line in enumerate(text.splitlines(), 1):
        for ch in line:
            if in_emoji_range(ch) and ch not in EMOJI_EXEMPT:
                seen.setdefault(ch, ln_no)
    for ch, ln_no in seen.items():
        bad.append(f"emoji/pictograph {ch} (U+{ord(ch):04X} "
                   f"{unicodedata.name(ch, '?')}) at line {ln_no} — NO-EMOJIS "
                   f"rule. Convert per revision_plan §352: warn→? cross→✗ "
                   f"done→✓")

    # The identity header/footer are POSITIONAL -- first and last non-blank
    # line. Scanning the whole text instead matched any ⟦…⟧ in prose (a
    # literal "⟦…⟧" in ph00_boot_coherence_review reported as a 1-field
    # header on the first run).
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return bad + ["empty file"], adv
    positions = [("header", lines[0]), ("footer", lines[-1])]
    if path.name in SIGNATURE_EXCEPTION:
        # FOOTER only. The covenant's last line is its constitutional SEAL
        # (two fields: a mark and a place), which its own §watermark section
        # shows is neither an identity footer nor a node watermark -- that
        # format is declared as four fields and required of NODES. The
        # identity HEADER is still required: every document in spec_revision
        # must be machine-identifiable. Narrowed 2026-08-07 after reading
        # §watermark; the first version waived both, which was wider than the
        # ratified exception.
        adv.append("constitutional seal — footer rule waived, header enforced")
        positions = [("header", lines[0])]
    # Version-aware footer policy. vsm-1.2.1 changed the closing footer to a
    # NAME-ONLY closure ⟦ /name ⟧ (see vsl_language_primer §closure); the
    # header keeps the 4-field form. Legacy vsm-1.2 documents keep the 4-field
    # footer; both forms are accepted there (forward-compatible with name-only).
    is_legacy = True
    hfields: list[str] = []
    if lines:
        hdr = HEADER.fullmatch(lines[0].strip())
        if hdr:
            hfields = [x.strip() for x in hdr.group(1).split("|")]
            if len(hfields) >= 3:
                mver = re.match(r"vsm-(\d+)\.(\d+)(?:\.(\d+))?$", hfields[2])
                if mver:
                    vt = (int(mver.group(1)), int(mver.group(2)),
                          int(mver.group(3) or 0))
                    is_legacy = vt < (1, 2, 1)

    for pos, ln in positions:
        m = HEADER.fullmatch(ln.strip())
        if not m:
            bad.append(f"no ⟦ … ⟧ identity {pos} (line is: {ln.strip()[:52]})")
            continue
        fields = [x.strip() for x in m.group(1).split("|")]
        nf = len(fields)
        date_field = None
        if pos == "header":
            if nf != 4:
                bad.append(f"header has {nf} fields, must be 4: "
                           f"{ln.strip()[:60]}")
                continue
            date_field = fields[3]
        else:  # footer
            if nf == 1:
                # NAME-ONLY closure ⟦ /name ⟧ (vsm-1.2.1 §closure). Valid for
                # all versions; required for vsm-1.2.1+, accepted as legacy
                # forward-compat for vsm-1.2.
                if not fields[0].startswith("/"):
                    bad.append(f"footer name-only must start with '/': "
                               f"{ln.strip()[:60]}")
            elif nf == 4:
                # Legacy 4-field footer form.
                if not is_legacy:
                    bad.append(f"footer must be ⟦ /name ⟧ for vsm-{hfields[2]} "
                               f"(name-only; see vsl_language_primer §closure): "
                               f"{ln.strip()[:60]}")
                else:
                    date_field = fields[3]
            else:
                bad.append(f"footer has {nf} fields, must be 1 (name-only) or "
                           f"4 (legacy): {ln.strip()[:60]}")
        if date_field is not None:
            # FASE-1-ENFORCEMENT-2026-08-22: timestamp REQUIRED, date-only
            # REJECTED. All .vsm headers must use UTC timestamp.
            if RE_DATE_ONLY.match(date_field):
                bad.append(f"{pos} date field '{date_field}' is date-only — "
                           f"REJECTED. Use UTC timestamp: "
                           f"2026-08-22T19:14:18Z — FASE-1-ENFORCEMENT, "
                           f"unified timestamp format")
            elif not RE_TIMESTAMP.match(date_field):
                bad.append(f"{pos} date field '{date_field}' is not ISO 8601 "
                           f"(expected UTC timestamp 2026-08-16T19:14:18Z) — "
                           f"VSM 1.2 protocol, vsl_language_primer §file_grammar")

    for m in MATH_NEIGHBOUR.finditer(text):
        adv.append(f"ASCII hyphen between math operands (want U+2212 −): "
                   f"{m.group(0).strip()!r}")
    for m in MINUS_IN_WORD.finditer(text):
        adv.append(f"U+2212 minus inside a word (want U+002D -): "
                   f"{m.group(0)!r}")
    for m in ASCII_PRIME.finditer(text):
        adv.append(f"ASCII apostrophe as prime (want U+2032 ′): "
                   f"{m.group(0)!r}")
    return bad, adv


def main() -> int:
    targets = sys.argv[1:] or DEFAULT
    files: list[Path] = []
    for t in targets:
        p = ROOT / t
        files.extend(sorted(p.rglob("*.vsm")) if p.is_dir() else [p])
    files = [f for f in files if "agent_layer" not in str(f)]

    rc = 0
    n_adv = 0
    for f in files:
        bad, adv = check(f)
        # Handle files outside ROOT gracefully (e.g., /tmp/)
        try:
            rel = f.relative_to(ROOT)
        except ValueError:
            rel = f
        if bad:
            rc = 1
            print(f"  ✗ {rel}")
            for b in bad:
                print(f"      {b}")
        n_adv += len(adv)
        for a in adv[:3]:
            print(f"  ? {rel}: {a}")

    if rc == 0:
        print(f"  ✓ encoding certified — {len(files)} files: UTF-8, NFC, "
              f"no BOM, no invisibles, 4-field headers, UTC timestamps")
    if n_adv:
        print(f"    ({n_adv} dash advisories — judgement, not a gate)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
