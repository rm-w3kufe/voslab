"""Coverage predicate: buckets, denominators, sidecar roundtrip, guard."""
from __future__ import annotations

from pathlib import Path

import pytest

from vos_kernel.epistemic import load_sidecar
from vos_kernel.utils.vsm_kernel import validate_vsm_content

from claim_ingest.ledger import coverage, render_ledger, write_ledger
from claim_ingest.ledger.ledger import ledger_name_for


def _claim(cid, status, scope=None):
    c = {"id": cid, "type": "number", "subject": "x", "risk": "exploratory",
         "status": status, "text": f"claim {cid}", "provenance": "t",
         "certs": []}
    if scope:
        c["scope"] = scope
    return c


def test_coverage_buckets_and_denominator():
    claims = [
        _claim("A", "CERTIFIED"),
        _claim("B", "REFUTED"),
        _claim("C", "DECLARED"),
        _claim("D", "OBSERVED"),
        _claim("E", "UNKNOWN"),
        _claim("F", "DECLARED", scope="out_of_scope"),
    ]
    cov = coverage(claims)
    assert cov["verified"] == 1
    assert cov["refuted"] == 1
    assert cov["untested"] == 3          # DECLARED + OBSERVED + UNKNOWN
    assert cov["out_of_scope"] == 1      # never folded into untested
    assert cov["total"] == 6
    # exhaustive: buckets sum to total (denominator rule)
    assert (cov["verified"] + cov["refuted"] + cov["untested"]
            + cov["out_of_scope"]) == cov["total"]


def test_coverage_route_distribution():
    claims = [_claim("A", "DECLARED"), _claim("B", "DECLARED")]
    routes = [{"claim_id": "A", "route": "R1", "verdict": "PASS",
               "status": "DECLARED"},
              {"claim_id": "B", "route": "R2", "verdict": "PASS",
               "status": "OBSERVED"}]
    cov = coverage(claims, routes)
    assert cov["routes"] == {"R1": 1, "R2": 1}
    assert sum(cov["routes"].values()) == cov["total"]


def test_render_ledger_valid_and_loadable(tmp_path):
    claims = [_claim("A", "DECLARED")]
    cov = coverage(claims)
    internal = {"pairs_total": 0, "pairs_comparable": 0, "pairs_checked": 0,
                "contradictions": [], "abstract": None}
    content = render_ledger("demo_ledger", claims, cov, internal)
    assert validate_vsm_content(content)["valid"]
    p = tmp_path / "demo.claims.vsm"
    p.write_text(content)
    loaded = load_sidecar(p)
    assert loaded[0]["id"] == "A"
    assert "coverage = " in content and "internal_check = " in content


def test_write_ledger_inside_root_only(tmp_path, monkeypatch):
    import claim_ingest.ledger.ledger as L

    monkeypatch.setattr(L, "repo_root", lambda: tmp_path)
    ok = write_ledger(tmp_path / "sub" / "l.claims.vsm", "doc.vsm",
                      [_claim("A", "DECLARED")], {"total": 1}, {})
    assert ok.exists()
    with pytest.raises(PermissionError):
        write_ledger(Path("/etc/evil.claims.vsm"), "doc.vsm",
                     [_claim("A", "DECLARED")], {"total": 1}, {})


def test_ledger_name_identifier():
    assert ledger_name_for("Lange–Lerner_Model.pdf") == "lange_lerner_model"
    assert ledger_name_for("???") == "ledger"
