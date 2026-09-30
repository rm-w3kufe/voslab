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


# --- layout guards (G1 index-eq, G2 control bytes; paper pilot finding) ---

def test_g1_layout_index_never_a_claim():
    # pdftotext -layout summation bounds must not register
    assert extract_deterministic("Optimize with subject to h=1 .") == [] or \
        all(c.get("value") != "1" or c.get("quantity") != "h"
            for c in extract_deterministic("Optimize subject h=1 now."))
    assert extract_deterministic("f =1") == []


def test_g1_real_short_claims_survive():
    cands = extract_deterministic("The run reaches K0 = 5 at start.")
    assert len(cands) == 1 and cands[0]["value"] == "5"
    cands = extract_deterministic("We set n = 10 as baseline.")
    assert len(cands) == 1 and cands[0]["quantity"] == "n"


def test_g1_kills_only_index_matches_not_the_sentence():
    # a good equality in the same sentence still registers
    cands = extract_deterministic("Index h=1 while theta = 0.75 holds.")
    assert len(cands) == 1
    assert cands[0]["quantity"] == "theta" and cands[0]["value"] == "0.75"


def test_g2_control_bytes_skip_sentence():
    assert extract_deterministic("bad\x10\x11 layout K0 = 5 end.") == []


def test_claim_noise_reason_registry_rules():
    from claim_ingest.extract.patterns import claim_noise_reason
    assert claim_noise_reason("f =1", "num_eq") == "layout-index"
    assert claim_noise_reason("bad\x10\x11 junk", "num_eq") == "control-chars"
    # real numeric claim: not noise
    assert claim_noise_reason("The run reaches K0 = 5 at start.",
                              "num_eq") is None
    # prose: never noise by these rules
    assert claim_noise_reason("Every planner must choose the weights.",
                              "quantifier") is None
    # num_eq pattern but no visible equation -> conservative, not flagged
    assert claim_noise_reason("no equation visible here at all",
                              "num_eq") is None
