"""Tests for l3_verify (NB06+NB07) — 9 symbolic checks, deterministic (R10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from l3_verify import (CHECK_FNS, VERDICTS, run_all, summary)  # noqa: E402

EXPECTED_IDS = [
    "pf_block_spectrum",
    "lambda_j_degenerate",
    "lyapunov_positive",
    "convergence_conditional",
    "landauer_identity",
    "s5_min_semantics",
    "margin_frontier",
    "cone_convex_grid",
    "lipschitz_deployed",
]


def test_run_all_shape_and_order():
    rows = run_all()
    assert len(rows) == 9
    assert [r["id"] for r in rows] == EXPECTED_IDS
    assert len(CHECK_FNS) == 9


def test_every_row_schema():
    for r in run_all():
        assert r["verdict"] in VERDICTS
        assert r["source"].startswith(("eq:", "thm:", "cor:", "prop:"))
        assert r["claim"] and len(r["evidence"]) >= 3


def test_pf_block_exact_eigen():
    r = next(x for x in run_all() if x["id"] == "pf_block_spectrum")
    assert r["verdict"] == "PASS"
    ev = " ".join(r["evidence"])
    assert "{1: 1, 99/100: 3}" in ev      # eigenvals exactos (Rational)
    assert "match@6dp=True" in ev          # ln(0.99) == -0.010050 @6dp


def test_lambda_degenerate_matches_pf():
    r = next(x for x in run_all() if x["id"] == "lambda_j_degenerate")
    assert r["verdict"] == "PASS"
    ev = " ".join(r["evidence"])
    assert "mult=4" in ev and "tangente 3" in ev
    assert "match@6dp=True" in ev


def test_lyapunov_nonnegative_terms():
    r = next(x for x in run_all() if x["id"] == "lyapunov_positive")
    assert r["verdict"] == "PASS"
    ev = " ".join(r["evidence"])
    assert "2sin^2" in ev.replace(" ", "")
    assert "True" in ev


def test_convergence_is_conditional():
    r = next(x for x in run_all() if x["id"] == "convergence_conditional")
    assert r["verdict"] == "CONDITIONAL"   # hipotesis, no derivable
    ev = " ".join(r["evidence"])
    assert "hipotesis" in ev


def test_landauer_unit_conversion():
    r = next(x for x in run_all() if x["id"] == "landauer_identity")
    assert r["verdict"] == "PASS"
    ev = " ".join(r["evidence"])
    assert "nats/ln2" in ev


def test_s5_min_semantics_pass():
    r = next(x for x in run_all() if x["id"] == "s5_min_semantics")
    assert r["verdict"] == "PASS"
    assert all("True" in e for e in r["evidence"][:3])


def test_margin_frontier_numbers():
    r = next(x for x in run_all() if x["id"] == "margin_frontier")
    assert r["verdict"] == "PASS"
    ev = " ".join(r["evidence"])
    assert "0.774597" in ev   # sqrt(0.6) = 0.7745966... redondeado @6dp
    assert "match@4dp=True" in ev


def test_cone_grid_finite_honest():
    r = next(x for x in run_all() if x["id"] == "cone_convex_grid")
    assert r["verdict"] == "PASS_GRID"     # clase distinta: NO es prueba
    ev = " ".join(r["evidence"])
    assert "violaciones: 0" in ev
    assert "NO constituye prueba formal" in ev


def test_lipschitz_deployed_constants():
    r = next(x for x in run_all() if x["id"] == "lipschitz_deployed")
    assert r["verdict"] == "PASS"          # rango [1.4, 24.4] reproducido
    ev = " ".join(r["evidence"])
    assert "1.118034" in ev and "1.092016" in ev   # constantes parseadas
    assert "match@3dp=True" in ev          # tabla vs REVIEW 2026-07-11
    assert "[1.4, 24.4]" in ev             # addendum §2 @1dp
    assert "4/4 fases" in ev               # L_f > 1 en todas


def test_summary_counts():
    s = summary(run_all())
    assert s["total"] == 9
    assert sum(s["by_verdict"].values()) == 9
    assert s["by_verdict"] == {"PASS": 7, "CONDITIONAL": 1, "PASS_GRID": 1}
    assert s["ids"] == EXPECTED_IDS


def test_deterministic_two_runs():
    assert run_all() == run_all()
