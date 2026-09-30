"""Deterministic claim extraction patterns (R10, claim_ingest proposal).

Pure functions over text: same input -> same candidates, always.
No I/O, no clock, no randomness. The net is conservative on purpose:
a sentence becomes a candidate only when a crisp pattern fires
(numeric equality, inequality, percentage, ratio, quantifier).
Everything else stays visible as uncovered prose (denominator rule),
it never becomes a silently "verified" claim.

Two tiers per sentence:
  1. numeric patterns -> type=number candidates (quantity-keyed when the
     left-hand side is an identifier, so intra-source pairs compare);
  2. only if tier 1 did not fire: quantifier sentences -> type=theorem.
"""
from __future__ import annotations

import re

# sentence boundaries: end-of-sentence punctuation or newline
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# identifier-ish left-hand side, greek letters allowed (mu, lam, K0, X)
_LHS = r"[A-Za-zμ][\wμ]*(?:[_\{][\w]+\}?)?"

_NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?:\s*/\s*\d+)?"

# left-hand side candidates directly before an operator may be function
# words ("mu is not >= 0" -> "not"): step back to the real identifier
_FUNC = {
    "not", "never", "no", "cannot", "is", "are", "was", "were", "be",
    "been", "it", "this", "that", "the", "a", "an", "under", "than",
    "always", "es", "son", "está", "estan", "el", "la", "los", "las",
    "un", "una", "que", "siempre", "nunca", "bajo", "jamás", "jamas",
}
_IDENT = re.compile(r"[A-Za-zμ][\wμ]*(?:[_\{][\w]+\}?)?")


def _real_lhs(sentence: str, start: int, lhs: str) -> str:
    """True subject identifier for a match starting at `start`."""
    if lhs.lower() not in _FUNC:
        return lhs
    ids = _IDENT.findall(sentence[:start])
    for tok in reversed(ids):
        if tok.lower() not in _FUNC:
            return tok
    return lhs


# numeric equality: K0 = 5,  n = 10
_EQ = re.compile(rf"(?P<lhs>{_LHS})\s*(?:=|equals)\s*(?P<val>{_NUM})")

# inequality (ops ordered: two-char before one-char; '=' not included)
_INEQ = re.compile(rf"(?P<lhs>{_LHS})\s*(?P<op><=|>=|≥|≤|<|>)\s*(?P<val>{_NUM})")

# percentage / ratio without an identifier lhs
_PCT = re.compile(r"(?P<val>-?\d+(?:\.\d+)?)\s*%")
_RATIO = re.compile(r"(?<![\d./])(?P<a>\d{1,6})\s*/\s*(?P<b>\d{1,6})(?![\d.])")

# universal / impossibility quantifiers (EN + ES)
_QUANT = re.compile(
    r"\b(?:always|never|every|all|none|must|cannot|can never|"
    r"siempre|nunca|todos|toda|todas|ninguno|ninguna|jamás|jamas)\b",
    re.I,
)

# near negation of an identifier: "mu is not >= 0", "K0 never equals 5"
def _near_neg(lhs: str) -> re.Pattern:
    return re.compile(
        rf"\b{re.escape(lhs)}\b(?:\s+\w+){{0,2}}\s+"
        r"(?:is\s+|are\s+)?(?:not|never|cannot|nunca|jamás|jamas)\b",
        re.I,
    )

# equation / section references (attached as locator evidence, never claims)
_EQREF = re.compile(
    r"\b(?:equation|ecuación|ecuacion|eq\.)\s*\(?\s*(\d{1,3}(?:\.\d+)?)\s*\)?"
    r"|(?:§|section\s+|sección\s+|seccion\s+)(\d{1,2}(?:\.\d+)?)"
)
_EQRANGE = re.compile(r"\((\d{1,3})\)\s*[–—-]\s*\((\d{1,3})\)")

_OP_CANON = {"≥": ">=", "≤": "<="}

# PDF layout guards (paper pilot finding: pdftotext -layout emits index
# fragments and control bytes that must never become claims):
#   G1 layout-index: summation bounds ("h=1", "f =1") are single lowercase
#     identifiers equal to 1 — never registered as numeric claims. Real
#     short claims ("K0 = 5", "n = 10") keep their multi-char/non-1 lhs.
#   G2 control bytes: \x10/\x11 and friends from PDF internals.
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f]")


def _is_layout_index(lhs: str, value: str) -> bool:
    """True only for the summation-index signature: single lowercase = 1."""
    return bool(re.fullmatch(r"[a-z]", lhs)) and value == "1"


def claim_noise_reason(text: str, pattern: str | None = None) -> str | None:
    """Deterministic noise verdict for an EXISTING claim (registry marking).

    Returns a reason string when the claim is a layout artifact, else None.
    Same rules as the extract-time guards, applied to stored text, so the
    pilot registry can be marked without re-extraction (no id churn).
    """
    if not text:
        return None
    if _CTRL.search(text):
        return "control-chars"
    if pattern == "num_eq":
        matches = list(_EQ.finditer(text))
        if matches and all(
                _is_layout_index(m.group("lhs"),
                                 re.sub(r"\s+", "", m.group("val")))
                for m in matches):
            return "layout-index"
    return None


def quantity_key(lhs: str) -> str:
    """Normalized comparison key: 'K_0'/'k0'/'K0' style collapse."""
    return re.sub(r"[^0-9a-zμ]+", "", lhs.lower())


def split_sentences(text: str, line_offset: int = 0):
    """(lineno, sentence) pairs; lineno is 1-based inside `text`."""
    out = []
    for i, raw in enumerate(text.splitlines()):
        for part in _SENT_SPLIT.split(raw):
            s = part.strip()
            if s:
                out.append((line_offset + i + 1, s))
    return out


def _refs_of(sentence: str) -> list[str]:
    refs: list[str] = []
    for m in _EQREF.finditer(sentence):
        n = m.group(1) or m.group(2)
        if n and f"eq:{n}" not in refs:
            refs.append(f"eq:{n}")
    for m in _EQRANGE.finditer(sentence):
        r = f"eq:{m.group(1)}-{m.group(2)}"
        if r not in refs:
            refs.append(r)
    return refs


def _cand(sentence, section, line, pattern, ctype, value=None,
          quantity=None, op=None, refs=None, negated=False):
    return {
        "text": sentence,
        "section": section,
        "line": line,
        "method": "deterministic",
        "pattern": pattern,
        "type": ctype,
        "value": value,
        "quantity": quantity,
        "op": op,
        "refs": refs or [],
        "negated": negated,
    }


def _numeric_candidates(sentence, section, line, refs):
    out = []
    for m in _INEQ.finditer(sentence):
        lhs = _real_lhs(sentence, m.start("lhs"), m.group("lhs"))
        op = _OP_CANON.get(m.group("op"), m.group("op"))
        out.append(_cand(
            sentence, section, line, "ineq", "number",
            value=re.sub(r"\s+", "", m.group("val")),
            quantity=quantity_key(lhs), op=op, refs=refs,
            negated=bool(_near_neg(lhs).search(sentence)),
        ))
    ineq_spans = [m.span() for m in _INEQ.finditer(sentence)]
    for m in _EQ.finditer(sentence):
        if any(s <= m.start() < e for s, e in ineq_spans):
            continue  # '=' consumed as part of <=/>=, not a separate equality
        lhs = _real_lhs(sentence, m.start("lhs"), m.group("lhs"))
        val = re.sub(r"\s+", "", m.group("val"))
        if _is_layout_index(lhs, val):
            continue  # G1: pdftotext summation bound, not a claim
        out.append(_cand(
            sentence, section, line, "num_eq", "number",
            value=val,
            quantity=quantity_key(lhs), op="=", refs=refs,
            negated=bool(_near_neg(lhs).search(sentence)),
        ))
    if not out:
        m = _PCT.search(sentence)
        if m:
            out.append(_cand(sentence, section, line, "pct", "number",
                             value=m.group("val"), refs=refs))
        else:
            m = _RATIO.search(sentence)
            if m:
                out.append(_cand(sentence, section, line, "ratio", "number",
                                 value=f"{m.group('a')}/{m.group('b')}",
                                 refs=refs))
    return out


def _theorem_candidate(sentence, section, line, refs):
    if not _QUANT.search(sentence):
        return None
    if len(re.findall(r"\w+", sentence)) < 6:
        return None
    negated = bool(re.search(
        r"\b(?:not|never|cannot|no\b|nunca|jamás|jamas)\b", sentence, re.I))
    return _cand(sentence, section, line, "quantifier", "theorem",
                 refs=refs, negated=negated)


def extract_from_section(text: str, section: str = "body",
                         line_offset: int = 0,
                         seen: set | None = None) -> list[dict]:
    """Deterministic candidates for one section (deduped across calls)."""
    seen = seen if seen is not None else set()
    out: list[dict] = []
    for line, sentence in split_sentences(text, line_offset):
        if _CTRL.search(sentence):
            continue  # G2: PDF control bytes, layout never content
        refs = _refs_of(sentence)
        cands = _numeric_candidates(sentence, section, line, refs)
        if not cands:
            th = _theorem_candidate(sentence, section, line, refs)
            if th is not None:
                cands = [th]
        for c in cands:
            key = (c["section"], c["line"], c["pattern"],
                   c.get("quantity"), c.get("value"), c["text"])
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


def extract_deterministic(text: str,
                          sections: dict[str, str] | None = None
                          ) -> list[dict]:
    """Extract candidates. `sections` splits named spans (e.g. abstract
    vs body); default treats the whole text as section "body"."""
    if not sections:
        return extract_from_section(text, "body")
    out: list[dict] = []
    seen: set = set()
    for name, span in sections.items():
        out.extend(extract_from_section(span, name, seen=seen))
    return out
