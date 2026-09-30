"""Intra-source consistency (claim_ingest proposal, layer 2a).

Deterministic rules only; every health statement carries its denominator:
  pairs_total      — all same-source pairs (n choose 2)
  pairs_comparable — pairs a deterministic rule could judge
  pairs_checked    — pairs actually evaluated (<= comparable)
  contradictions   — checked pairs that conflict (kind: range | negation)

Judged cases (precision over recall — unjudgeable pairs are NOT counted):
  range    — both sides assert intervals (op+value), neither negated:
             disjoint intervals => contradiction.
  negation — same quantity, exactly one side negated:
             (a) both intervals  => contradiction iff affirmed interval
                 is contained in the negated proposition's interval;
             (b) no intervals     => contradiction iff both texts are
                 equal after stripping negation tokens.

Plus abstract corroboration: every abstract-section claim must be
backed by a body claim (shared quantity+value, shared equation ref, or
deterministic token overlap). Unmatched abstract claims stay visible.

Block rule (mirror of G-EP-CERT-LINKAGE): a claim in an unresolved
contradiction may not be CERTIFIED — `ensure_certifiable` enforces it.
"""
from __future__ import annotations

import itertools
import math
import re

from ..extract.patterns import quantity_key  # shared normalizer (R10)


class ContradictionBlocked(RuntimeError):
    """Certification refused: unresolved intra-source contradiction."""


_NEG_TOKENS = re.compile(
    r"\b(?:not|never|cannot|no|nunca|jamás|jamas)\b", re.I)
_STOP = {
    "the", "a", "an", "of", "to", "and", "is", "are", "in", "for", "on",
    "that", "with", "as", "by", "or", "at", "from", "be", "this", "it",
    "el", "la", "los", "las", "de", "del", "en", "y", "que", "un", "una",
    "por", "con", "para", "se", "sus", "su",
}


def _f(val) -> float | None:
    s = str(val).strip()
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            d = float(den)
            return None if d == 0 else float(num) / d
        return float(s)
    except (ValueError, ZeroDivisionError):
        return None


def _interval(op: str | None, val) -> tuple | None:
    """(lo, lo_open, hi, hi_open); None when unparseable."""
    v = _f(val)
    if v is None:
        return None
    op = op or "="
    if op == "=":
        return (v, False, v, False)
    if op in (">=", "≥"):
        return (v, False, math.inf, True)
    if op == ">":
        return (v, True, math.inf, True)
    if op in ("<=", "≤"):
        return (-math.inf, True, v, False)
    if op == "<":
        return (-math.inf, True, v, True)
    return None


def _disjoint(a: tuple, b: tuple) -> bool:
    a_lo, a_lop, a_hi, a_hip = a
    b_lo, b_lop, b_hi, b_hip = b
    if a_hi < b_lo or b_hi < a_lo:
        return True
    if a_hi == b_lo and (a_hip or b_lop):
        return True
    if b_hi == a_lo and (b_hip or a_lop):
        return True
    return False


def _contains(outer: tuple, inner: tuple) -> bool:
    """inner subset-of outer, respecting open/closed bounds."""
    o_lo, o_lop, o_hi, o_hip = outer
    i_lo, i_lop, i_hi, i_hip = inner
    if i_lo == o_lo:
        if o_lop and not i_lop:
            return False
    elif i_lo < o_lo:
        return False
    if i_hi == o_hi:
        if o_hip and not i_hip:
            return False
    elif i_hi > o_hi:
        return False
    return True


def _strip_neg(text: str) -> str:
    s = _NEG_TOKENS.sub(" ", text.lower())
    return re.sub(r"[^0-9a-zμ]+", " ", s).strip()


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-zμ0-9]+", text.lower())
            if w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_quantity(a: dict, b: dict) -> bool:
    return quantity_key(str(a["quantity"])) == quantity_key(str(b["quantity"]))


def _is_neg(c: dict) -> bool:
    return bool(c.get("negated"))


def _range_pairs(claims, tally) -> list[dict]:
    out = []
    nums = [c for c in claims
            if c.get("type") == "number" and c.get("quantity")
            and not _is_neg(c)]
    for a, b in itertools.combinations(nums, 2):
        if not _same_quantity(a, b):
            continue
        ia = _interval(a.get("op"), a.get("value"))
        ib = _interval(b.get("op"), b.get("value"))
        if ia is None or ib is None:
            continue  # unjudgeable: not counted
        tally["comparable"] += 1
        tally["checked"] += 1
        if _disjoint(ia, ib):
            out.append({
                "a": a["id"], "b": b["id"], "kind": "range",
                "detail": (f"{a['quantity']}: "
                           f"{a.get('op', '=')}{a.get('value')} vs "
                           f"{b.get('op', '=')}{b.get('value')}"),
            })
    return out


def _negation_pairs(claims, tally) -> list[dict]:
    out = []
    keyed = [c for c in claims if c.get("quantity")]
    for a, b in itertools.combinations(keyed, 2):
        if not _same_quantity(a, b):
            continue
        na, nb = _is_neg(a), _is_neg(b)
        if na == nb:
            continue  # both or neither: not this rule's business
        neg, aff = (a, b) if na else (b, a)
        ia = _interval(aff.get("op"), aff.get("value"))
        ib = _interval(neg.get("op"), neg.get("value"))
        if ia is not None and ib is not None:
            # judge: affirmed proposition contradicts NOT(proposition)
            # iff affirmed interval is inside the proposition's interval
            tally["comparable"] += 1
            tally["checked"] += 1
            if _contains(ib, ia):
                out.append({
                    "a": a["id"], "b": b["id"], "kind": "negation",
                    "detail": (f"{a['quantity']}: "
                               f"{aff.get('op', '=')}{aff.get('value')} "
                               f"contradicts negated proposition"),
                })
            continue
        if _strip_neg(str(a.get("text", ""))) == _strip_neg(
                str(b.get("text", ""))):
            tally["comparable"] += 1
            tally["checked"] += 1
            out.append({
                "a": a["id"], "b": b["id"], "kind": "negation",
                "detail": f"{a['quantity']}: text negation split",
            })
        # else: unjudgeable (no intervals, texts differ) -> not counted
    return out


def _abstract_report(claims) -> dict:
    abstracts = [c for c in claims if c.get("section") == "abstract"]
    body = [c for c in claims if c.get("section") != "abstract"]
    unmatched: list[str] = []
    for a in abstracts:
        ok = False
        ta = _tokens(a.get("text", ""))
        for b in body:
            qa, qb = a.get("quantity"), b.get("quantity")
            if qa and qb and quantity_key(str(qa)) == quantity_key(str(qb)):
                va, vb = _f(a.get("value")), _f(b.get("value"))
                if va is not None and vb is not None and va == vb:
                    ok = True
                    break
                if a.get("value") and a.get("value") == b.get("value"):
                    ok = True
                    break
            ra, rb = set(a.get("refs", [])), set(b.get("refs", []))
            if ra and rb and ra & rb:
                ok = True
                break
            if _jaccard(ta, _tokens(b.get("text", ""))) >= 0.5:
                ok = True
                break
        if not ok:
            unmatched.append(a["id"])
    return {"abstract_claims": len(abstracts),
            "corroborated": len(abstracts) - len(unmatched),
            "unmatched": unmatched}


def internal_check(claims: list[dict]) -> dict:
    """Deterministic intra-source consistency with full denominators."""
    sources: dict[str, list[dict]] = {}
    for c in claims:
        sources.setdefault(str(c.get("source_id", "?")), []).append(c)

    tally = {"total": 0, "comparable": 0, "checked": 0}
    contradictions: list[dict] = []
    for group in sources.values():
        n = len(group)
        tally["total"] += n * (n - 1) // 2
        rng = _range_pairs(group, tally)
        contradictions.extend(rng)
        decided = {(d["a"], d["b"]) for d in rng}
        for d in _negation_pairs(group, tally):
            if (d["a"], d["b"]) not in decided:
                contradictions.append(d)

    return {
        "pairs_total": tally["total"],
        "pairs_comparable": tally["comparable"],
        "pairs_checked": tally["checked"],
        "contradictions": contradictions,
        "abstract": _abstract_report(claims),
    }


def blocked_ids(check: dict) -> set:
    """Claims sitting in an unresolved contradiction."""
    out: set = set()
    for d in check.get("contradictions", []):
        out.add(d["a"])
        out.add(d["b"])
    return out


def ensure_certifiable(claim: dict, check: dict) -> None:
    """Block rule: no CERTIFIED while an intra-source contradiction is open."""
    if (claim.get("status") == "CERTIFIED"
            and claim.get("id") in blocked_ids(check)):
        raise ContradictionBlocked(
            f"{claim['id']}: CERTIFIED refused — unresolved contradiction "
            f"with {sorted(blocked_ids(check) - {claim['id']})}")
