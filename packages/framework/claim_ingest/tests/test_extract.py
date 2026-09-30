"""Deterministic extraction: patterns, sections, R10 determinism."""
from __future__ import annotations

from claim_ingest.extract import extract_deterministic
from claim_ingest.extract.patterns import (
    quantity_key,
    split_sentences,
)


def test_num_eq_candidate():
    cands = extract_deterministic("The run reaches K0 = 5 at start.")
    assert len(cands) == 1
    c = cands[0]
    assert c["type"] == "number"
    assert c["pattern"] == "num_eq"
    assert c["value"] == "5"
    assert c["quantity"] == quantity_key("K0") == "k0"
    assert c["op"] == "="
    assert c["method"] == "deterministic"


def test_ineq_candidate_with_canonical_op():
    cands = extract_deterministic("We require mu >= 0 in every run.")
    assert len(cands) == 1
    c = cands[0]
    assert c["pattern"] == "ineq"
    assert c["op"] == ">="
    assert c["value"] == "0"
    assert c["quantity"] == "mu"


def test_near_negation_flagged():
    cands = extract_deterministic("Here mu is not >= 0 under stress.")
    assert len(cands) == 1
    assert cands[0]["negated"] is True


def test_theorem_only_when_no_number():
    text = "All prices remain non-negative under every scheduled update."
    cands = extract_deterministic(text)
    assert len(cands) == 1
    assert cands[0]["type"] == "theorem"
    assert cands[0]["pattern"] == "quantifier"


def test_number_sentence_not_duplicated_as_theorem():
    cands = extract_deterministic(
        "The panel always reaches 24/24 checks every single run.")
    assert len(cands) == 1
    assert cands[0]["type"] == "number"


def test_pct_and_ratio():
    c1 = extract_deterministic("Capacity grows 12.5% each round.")
    assert c1[0]["pattern"] == "pct" and c1[0]["value"] == "12.5"
    c2 = extract_deterministic("The panel reports 24/24 checks passed.")
    assert c2[0]["pattern"] == "ratio" and c2[0]["value"] == "24/24"


def test_non_claim_sentence_yields_nothing():
    assert extract_deterministic("Setup complete with libraries loaded.") == []


def test_determinism_r10():
    text = (
        "The run reaches n = 10. Prices satisfy mu >= 0.\n"
        "All updates stay deterministic under every schedule."
    )
    a = extract_deterministic(text)
    b = extract_deterministic(text)
    assert a == b


def test_sections_split_with_local_lines():
    sections = {
        "abstract": "The mechanism reaches n = 10 at scale.",
        "body": "Convergence reaches n = 10 after the update.",
    }
    cands = extract_deterministic("", sections)
    by_sec = {c["section"]: c for c in cands}
    assert set(by_sec) == {"abstract", "body"}
    assert by_sec["abstract"]["line"] == 1
    assert by_sec["body"]["line"] == 1


def test_dedup_within_section():
    # same sentence twice on ONE line dedups; distinct lines stay distinct
    same_line = extract_deterministic("K0 = 5 happens. K0 = 5 happens.")
    assert len(same_line) == 1
    two_lines = extract_deterministic("K0 = 5 happens.\nK0 = 5 happens.")
    assert len(two_lines) == 2
    assert two_lines == extract_deterministic(
        "K0 = 5 happens.\nK0 = 5 happens.")


def test_split_sentences_line_numbers():
    out = split_sentences("One. Two.\nThree!")
    assert [s for _, s in out] == ["One.", "Two.", "Three!"]
    assert [n for n, _ in out] == [1, 1, 2]
