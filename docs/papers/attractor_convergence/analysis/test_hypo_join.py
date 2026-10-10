"""Tests for hypo_join (NB07 L4) — deterministic (R10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from hypo_join import (KINDS, RESOLUTIONS, find_hypotheses,  # noqa: E402
                       main_tex_path, run)


def test_find_hypotheses_count_and_kinds():
    tex = main_tex_path().read_text(errors="replace")
    hyps = find_hypotheses(tex)
    assert len(hyps) == 15
    by_kind = {k: sum(1 for h in hyps if h["kind"] == k) for k in KINDS}
    assert by_kind == {"named": 3, "table": 4, "finding": 8}


def test_hypotheses_sections():
    tex = main_tex_path().read_text(errors="replace")
    hyps = find_hypotheses(tex)
    ids_sec = {(h["id"], h["section"]) for h in hyps}
    assert ("H_floor", "sec:thermal_ladder") in ids_sec
    assert ("H_linear", "sec:thermal_ladder") in ids_sec
    # tabla realgov: H1,H2,H4,H5 (H3 no aparece — hueco honesto del paper)
    table = {h["id"] for h in hyps if h["kind"] == "table"}
    assert table == {"H1", "H2", "H4", "H5"}
    findings = [h for h in hyps if h["kind"] == "finding"]
    assert {h["section"] for h in findings} == {
        "sec:thermal_cycling", "sec:maxwell"}
    assert all(h["id"] in {"H1", "H2", "H3", "H4"} for h in findings)


def test_table_verdicts_captured():
    tex = main_tex_path().read_text(errors="replace")
    hyps = find_hypotheses(tex)
    v = {h["id"]: h["verdict"] for h in hyps if h["kind"] == "table"}
    assert v["H1"] == "PASS"
    assert v["H4"] == "viable"   # minúsculas, como en tab:realgov


def test_mapping_known_rows():
    rows, _ = run()
    by = {(r["section"], r["id"]): r for r in rows}
    floor = by[("sec:thermal_ladder", "H_floor")]
    assert floor["resolution"] == "protocol"
    assert floor["results"].endswith("thermal_ladder/results.vsm")
    assert floor["verdict_text"].startswith("CONFIRMED")
    h1 = by[("sec:real_proc_gov", "H1")]
    assert h1["resolution"] == "exact" and h1["exp"] == "EXP-L1-01"
    assert "real_process_governance" in h1["results"]
    assert h1["verdict_text"].startswith("PASS")
    m3 = by[("sec:maxwell", "H3")]
    assert m3["resolution"] == "exact" and m3["exp"] == "EXP-OE-02"
    assert m3["verdict_text"].startswith("CONFIRMED")


def test_thermal_cycling_gap_honest():
    rows, cov = run()
    gaps = [r for r in rows if r["results"] is None]
    assert len(gaps) == 4
    assert all(r["section"] == "sec:thermal_cycling" for r in gaps)
    assert all(r["exp"] == "EXP-TC-01" for r in gaps)
    assert all(r["resolution"] == "exp_no_results" for r in gaps)
    assert cov["gaps"] == [f"sec:thermal_cycling:H{i}" for i in
                           ("1", "2", "3", "4")]


def test_coverage_denominator():
    rows, cov = run()
    assert cov["total_hypotheses"] == 15
    assert cov["with_results_file"] == 11
    assert cov["with_verdict"] == 11
    assert cov["with_values"] == 11
    assert cov["ratio_results"] == 0.7333
    assert cov["by_resolution"]["exact"] == 8
    assert cov["by_resolution"]["protocol"] == 3
    assert cov["by_resolution"]["exp_no_results"] == 4
    for k in ("exact", "protocol", "token", "exp_no_results",
              "ambiguous", "none"):
        assert k in cov["by_resolution"]


def test_values_present_when_mapped():
    rows, _ = run()
    for r in rows:
        if r["results"] is not None:
            assert r["n_values"] >= 3, r["id"]
            assert r["verdict_text"], r["id"]


def test_resolution_classes_closed():
    rows, _ = run()
    assert all(r["resolution"] in RESOLUTIONS for r in rows)


def test_deterministic_two_runs():
    assert run() == run()
