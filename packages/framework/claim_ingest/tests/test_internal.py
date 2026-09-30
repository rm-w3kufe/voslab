"""Intra-source consistency: denominators, contradictions, block rule."""
from __future__ import annotations

import pytest

from claim_ingest.internal import (
    ContradictionBlocked,
    blocked_ids,
    ensure_certifiable,
    internal_check,
)


def _claim(cid, *, type="number", quantity=None, value=None, op=None,
           negated=False, status="DECLARED", text=None, section="body",
           refs=None, source_id="SRC-X"):
    c = {"id": cid, "type": type, "subject": "s", "risk": "exploratory",
         "status": status, "text": text or f"claim {cid}",
         "provenance": "t", "certs": [], "section": section,
         "source_id": source_id}
    for k, v in (("quantity", quantity), ("value", value), ("op", op),
                 ("refs", refs)):
        if v is not None:
            c[k] = v
    if negated:
        c["negated"] = True
    return c


def test_range_contradiction_same_quantity():
    claims = [
        _claim("A", quantity="mu", value="5", op="="),
        _claim("B", quantity="mu", value="6", op="="),
    ]
    chk = internal_check(claims)
    assert chk["pairs_total"] == 1
    assert chk["pairs_comparable"] == 1
    assert chk["pairs_checked"] == 1
    assert len(chk["contradictions"]) == 1
    assert chk["contradictions"][0]["kind"] == "range"
    assert blocked_ids(chk) == {"A", "B"}


def test_touching_intervals_disjoint_by_openness():
    claims = [
        _claim("A", quantity="mu", value="0", op=">="),
        _claim("B", quantity="mu", value="0", op="<"),
    ]
    chk = internal_check(claims)
    assert len(chk["contradictions"]) == 1


def test_different_quantities_not_comparable():
    claims = [
        _claim("A", quantity="mu", value="5", op="="),
        _claim("B", quantity="lam", value="6", op="="),
    ]
    chk = internal_check(claims)
    assert chk["pairs_comparable"] == 0
    assert chk["contradictions"] == []


def test_negation_contained_interval():
    claims = [
        _claim("A", quantity="mu", value="5", op="="),
        _claim("B", quantity="mu", value="0", op=">=", negated=True),
    ]
    chk = internal_check(claims)
    assert len(chk["contradictions"]) == 1
    assert chk["contradictions"][0]["kind"] == "negation"


def test_negation_non_contained_is_not_contradiction():
    # mu <= 10 (affirmed) vs NOT(mu >= 0): compatible (e.g. mu = -3)
    claims = [
        _claim("A", quantity="mu", value="10", op="<="),
        _claim("B", quantity="mu", value="0", op=">=", negated=True),
    ]
    chk = internal_check(claims)
    assert chk["contradictions"] == []
    assert chk["pairs_comparable"] == 1  # judged, just not conflicting


def test_negation_text_strip_when_no_intervals():
    claims = [
        _claim("A", quantity="k0", type="theorem",
               text="the equilibrium is stable in every run"),
        _claim("B", quantity="k0", type="theorem", negated=True,
               text="the equilibrium is not stable in every run"),
    ]
    chk = internal_check(claims)
    assert len(chk["contradictions"]) == 1
    assert chk["contradictions"][0]["kind"] == "negation"


def test_unjudgeable_pairs_not_counted():
    # negated + no intervals + different texts -> honestly not counted
    claims = [
        _claim("A", quantity="k0", type="theorem", text="alpha beta gamma"),
        _claim("B", quantity="k0", type="theorem", negated=True,
               text="delta epsilon zeta"),
    ]
    chk = internal_check(claims)
    assert chk["pairs_comparable"] == 0
    assert chk["contradictions"] == []


def test_abstract_corroboration_and_unmatched():
    claims = [
        _claim("AB1", section="abstract", quantity="n", value="10", op="="),
        _claim("AB2", section="abstract", quantity="q", value="99", op="="),
        _claim("BD1", section="body", quantity="n", value="10", op="="),
    ]
    chk = internal_check(claims)
    rep = chk["abstract"]
    assert rep["abstract_claims"] == 2
    assert rep["corroborated"] == 1
    assert rep["unmatched"] == ["AB2"]


def test_block_rule_refuses_certified_under_contradiction():
    claims = [
        _claim("A", quantity="mu", value="5", op="=", status="CERTIFIED"),
        _claim("B", quantity="mu", value="6", op="="),
    ]
    chk = internal_check(claims)
    with pytest.raises(ContradictionBlocked):
        ensure_certifiable(claims[0], chk)


def test_block_rule_allows_declared_under_contradiction():
    claims = [
        _claim("A", quantity="mu", value="5", op="="),  # DECLARED
        _claim("B", quantity="mu", value="6", op="="),
    ]
    chk = internal_check(claims)
    ensure_certifiable(claims[0], chk)  # visible, not certified: allowed


def test_block_rule_allows_free_certified():
    claims = [
        _claim("A", quantity="mu", value="5", op="=", status="CERTIFIED"),
        _claim("B", quantity="lam", value="6", op="="),  # other quantity
    ]
    chk = internal_check(claims)
    ensure_certifiable(claims[0], chk)


def test_sources_are_separated():
    claims = [
        _claim("A", quantity="mu", value="5", op="=", source_id="S1"),
        _claim("B", quantity="mu", value="6", op="=", source_id="S2"),
    ]
    chk = internal_check(claims)
    assert chk["contradictions"] == []  # cross-source pairs don't exist
    assert chk["pairs_total"] == 0
