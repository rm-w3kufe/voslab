"""Tests for numeric_join (NB07 L5) — deterministic (R10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from numeric_join import (addendum_paper_cross,  # noqa: F401
                          numbers_tokens, registry_entries,
                          run, _variants)


def test_registry_entries_coverage():
    from numeric_join import paper_data_path
    entries = registry_entries(
        paper_data_path().read_text(errors="replace"))
    assert len(entries) == 17
    with_n = [e for e in entries if e["has_numbers"]]
    assert len(with_n) == 13
    assert [e["id"] for e in entries if not e["has_numbers"]] == \
        ["4", "5", "6", "11"]     # entradas del registro sin numbers=


def test_numbers_tokens_extraction():
    toks = numbers_tokens(
        "min stasis_cos=0.9377 (20.3°) year 2026 N=3000 seed=42")
    vals = [t["value"] for t in toks]
    assert "0.9377" in vals and "20.3" in vals and "3000" in vals
    assert "2026" not in vals       # año filtrado
    assert "42" not in vals         # entero de 2 dígitos: baja señal
    assert len(numbers_tokens("a=1.0 b=1.0")) == 1   # dedup estable


def test_variants_rule_documented():
    assert _variants("4.00") == ["4.00", "4.0"]   # única variante: trim
    assert _variants("0.942") == ["0.942"]        # sin zeros finales: igual
    assert _variants("500") == ["500"]            # enteros: solo literal


def test_join_summary_pinned():
    r = run()
    s = r["join_summary"]
    assert s["tokens_checked"] == 32
    assert s["in_paper"] == 30 and s["ratio_paper"] == 0.9375
    assert s["in_addendum"] == 5 and s["ratio_addendum"] == 0.1562
    assert s["in_both"] == 5 and s["in_neither"] == 2
    neither = {row["value"] for row in r["join_rows"]
               if row["value"] and not row["in_paper"]
               and not row["in_addendum"]}
    # exp10 (Maxwell): registry guarda los números del TOY, el paper
    # cita los del kernel real → drift honesto, no error de parseo
    assert neither == {"1.3499", "0.1214"}


def test_known_token_rows():
    r = run()
    rows = {(row["id"], row["value"]): row for row in r["join_rows"]
            if row["value"]}
    ly = rows[("EXP-LY-01", "0.01005")]
    assert ly["in_paper"] and ly["in_addendum"]
    sen = rows[("7", "0.9377")]
    assert sen["in_paper"] and not sen["in_addendum"]


def test_cross_addendum_paper():
    r = run()
    assert len(r["cross"]) == 3
    by = {c["id"]: c for c in r["cross"]}
    assert by["ns_ticks_N"]["verdict"] == "match"
    assert by["sigma_noise_bound"]["verdict"] == "match_phrase"
    assert by["sigma_in_convention"]["verdict"] == "match"
    assert all(c["in_paper"] and c["in_addendum"] for c in r["cross"])


def test_layer2a_abstract_body():
    r = run()
    l2 = r["layer2a"]
    assert l2["abstract_candidates"] == 10
    assert l2["numeric_total"] == 8 and l2["numeric_checked"] == 4
    assert l2["numeric_matched"] == 4 and l2["numeric_miss"] == []
    assert l2["ratio_numeric"] == 1.0
    # teoremas: join por oración EXACTA — techo honesto, paraphrase no matchea
    assert l2["theorem_total"] == 2 and l2["theorem_matched"] == 0
    assert l2["theorem_miss"][0].startswith("(6)~")


def test_deterministic_two_runs():
    assert run() == run()
