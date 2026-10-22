# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/analytic_engine/depth.py)
"""Tests for depth_estimator (deterministic, R10) — calibrated thresholds."""

from pathlib import Path

from analytic_engine.depth import estimate, features

ROOT = Path(__file__).parents[4]  # vOSlab/
MAIN_TEX = ROOT / "docs/papers/attractor_convergence/main.tex"
FIERRO_TXT = (
    ROOT / "docs/papers/attractor_convergence/analysis/data/fierro_review.txt"
)
CARTA = ROOT / "docs/correspondence/fierro/addendum_omega/carta_acompanamiento.md"
PROPOSAL = ROOT / "docs/plans/claim_ingest_proposal.vsm"
ADDENDUM = ROOT / "docs/correspondence/fierro/addendum_omega/addendum.tex"


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def test_main_tex_full_stack():
    est = estimate(_read(MAIN_TEX), name="main.tex")
    assert est["levels"] == ["L1", "L2", "L3", "L4", "L5"]
    assert "sympy" in est["tools"]
    assert "z3" in est["tools"]  # inequality symbols present
    assert "l2_parser" in est["tools"]
    assert est["evidence"]["theorem_envs"] == 17
    assert est["evidence"]["equation_envs"] > 0


def test_fierro_standalone_vs_set():
    txt = _read(FIERRO_TXT)
    solo = estimate(txt, name="fierro", related_sources=1)
    assert solo["levels"] == ["L1"]  # no own eqs/refs — objections route to paper
    set_ = estimate(txt, name="fierro", related_sources=3)
    assert set_["levels"] == ["L1", "L5"]  # set context enables cross-source


def test_carta_prose_only_l1():
    est = estimate(_read(CARTA), name="carta")
    assert est["levels"] == ["L1"]
    assert est["tools"] == ["claim_ingest"]


def test_vsm_proposal_structure():
    est = estimate(_read(PROPOSAL), name="proposal")
    assert "L1" in est["levels"] and "L2" in est["levels"]  # vsm_blocks
    assert "L3" not in est["levels"] and "L4" not in est["levels"]


def test_addendum_math_set_full_stack():
    est = estimate(_read(ADDENDUM), name="addendum")
    assert est["levels"] == ["L1", "L2", "L3", "L4", "L5"]
    assert est["evidence"]["numbered_sections"] == 3  # §1 §2 §3 = Q1-Q3
    assert est["evidence"]["math_density"] >= 1.0


def test_empty_text_no_levels():
    est = estimate("", name="empty")
    assert est["levels"] == []
    assert "no analyzable structure" in est["verdict"]


def test_determinism():
    txt = _read(MAIN_TEX)
    assert estimate(txt, name="x") == estimate(txt, name="x")


def test_features_shape():
    f = features("some text with 5 samples and always")
    assert isinstance(f, dict) and "math_density" in f
    assert f["quant_claims"] >= 2


def test_analyze_depth_integration():
    from analytic_engine import analyze

    result = analyze(text="We measured 5 samples, always zero exits (EXP-XX-01).",
                     name="tiny", depth=True)
    assert "depth" in result
    assert result["depth"]["levels"] == ["L1", "L4"]
    # depth off by default
    result2 = analyze(text="We measured 5 samples.", name="tiny")
    assert "depth" not in result2


# ── DEPTH-v1 sidecar ──────────────────────────────────────────────────────────

def test_render_depth_valid_vsm():
    from analytic_engine.depth import render_depth

    est = estimate("We measured 5 samples (EXP-XX-01), always.", name="x")
    content = render_depth("x", est)
    from vos_kernel.utils.vsm_kernel import validate_vsm_content
    v = validate_vsm_content(content)
    assert v["valid"], v.get("errors")
    assert "DEPTH-v1" in content
    assert content.rstrip().endswith("⟦ /x ⟧")
    assert '"L1"' in content and '"L4"' in content


def test_persist_depth_idempotent(tmp_path, monkeypatch):
    import analytic_engine.depth as depth_mod

    monkeypatch.setattr(depth_mod, "_repo_root", lambda: tmp_path)
    txt = "We measured 5 samples, always (EXP-XX-01)."
    first = depth_mod.persist_depth(txt, name="demo")
    assert first["depth_status"] == "written"
    sidecar = tmp_path / "state/epistemic/sidecars/demo.depth.vsm"
    assert Path(first["depth_path"]) == sidecar
    bytes1 = sidecar.read_bytes()
    second = depth_mod.persist_depth(txt, name="demo")
    assert second["depth_status"] == "unchanged"
    assert sidecar.read_bytes() == bytes1  # timestamp-only header ignored


def test_persist_depth_change_writes(tmp_path, monkeypatch):
    import analytic_engine.depth as depth_mod

    monkeypatch.setattr(depth_mod, "_repo_root", lambda: tmp_path)
    txt = "data (EXP-XX-01) measured mean 3."  # L1+L4 standalone
    depth_mod.persist_depth(txt, name="demo", related_sources=1)
    out = depth_mod.persist_depth(txt, name="demo", related_sources=4)  # +L5
    assert out["depth_status"] == "written"
    assert "L5" in out["estimate"]["levels"]


def test_write_depth_outside_workspace(tmp_path, monkeypatch):
    import pytest

    import analytic_engine.depth as depth_mod

    monkeypatch.setattr(depth_mod, "_repo_root", lambda: tmp_path)
    est = estimate("5 samples measured", name="x")
    with pytest.raises(PermissionError):
        depth_mod.write_depth("/etc/evil.depth.vsm", "x", est)


def test_analyze_persist_depth(tmp_path, monkeypatch):
    import analytic_engine.depth as depth_mod
    from analytic_engine import analyze

    monkeypatch.setattr(depth_mod, "_repo_root", lambda: tmp_path)
    r = analyze(text="We measured 5 samples (EXP-XX-01).", name="tiny",
                persist_depth=True)
    assert "depth" in r
    assert r["depth_status"] == "written"
    assert (tmp_path / "state/epistemic/sidecars/tiny.depth.vsm").exists()
    # persist without explicit depth still computes the estimate
    assert r["depth"]["levels"] == ["L1", "L4"]
