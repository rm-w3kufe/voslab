"""Tests for l2_parser — B1 coherencia interna (deterministic, R10)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from l2_parser import (  # noqa: E402
    addendum_sections,
    analyse,
    dangling_refs,
    figure_tokens,
    parse_envs,
)

HERE = Path(__file__).parent
MAIN_TEX = HERE.parent / "main.tex"
ADDENDUM_TEX = HERE.parent.parent.parent / "correspondence" / "fierro" / "addendum_omega" / "addendum.tex"


def _tex(path: Path) -> str:
    return path.read_text(errors="replace")


def test_env_count_17():
    recs = parse_envs(_tex(MAIN_TEX))
    assert len(recs) == 17
    kinds = [r["kind"] for r in recs]
    assert kinds.count("theorem") == 2
    assert kinds.count("definition") == 5
    assert kinds.count("corollary") == 1
    assert kinds.count("proposition") == 1


def test_thm1_hybrid_invariance_record():
    recs = {r["label"]: r for r in parse_envs(_tex(MAIN_TEX)) if r["label"]}
    t1 = recs["thm:hybrid_invariance"]
    assert t1["kind"] == "theorem"
    assert t1["name"] == "Hybrid invariance"
    assert t1["line"] == 729
    # three numbered conclusions with bold heads
    assert len(t1["conclusions"]) == 3
    heads = [c["head"] for c in t1["conclusions"]]
    assert heads[0].startswith("Existence (Krylov--Bogolyubov + Banach)")
    assert heads[1].startswith("Convergence in expectation")
    assert heads[2].startswith("Confinement (empirical)")
    # F1 discharge: convexity not required (stated in item 1)
    assert "requires the convexity" in t1["conclusions"][0]["text"]
    # F3 discharge: non-expansiveness explicitly not claimed (item 3)
    assert "do not claim per-step non-expansiveness" in t1["conclusions"][2]["text"]
    # cross-links: convergence theorem + measurement sections
    assert "thm:convergence" in t1["refs"]
    assert "sec:sustained_noise" in t1["refs"]
    assert "sec:thermal_cycling" in t1["refs"]
    # hypotheses markers in the statement
    assert "with" in t1["hyp_markers"] and "Then" in t1["hyp_markers"]


def test_thm2_convergence_record():
    recs = {r["label"]: r for r in parse_envs(_tex(MAIN_TEX)) if r["label"]}
    t2 = recs["thm:convergence"]
    assert t2["kind"] == "theorem"
    assert t2["name"] == "Convergence in expectation"
    assert t2["line"] == 824
    # statement-only (equation, no enumerate)
    assert t2["conclusions"] == []
    assert "eq:dynamics" in t2["refs"]
    assert "eq:convergence" in t2["labels"]  # label inside body
    assert any(m in t2["hyp_markers"] for m in ("Under", "if"))


def test_no_dangling_refs():
    assert dangling_refs(_tex(MAIN_TEX)) == []


def test_figure_tokens_all_present():
    tok = figure_tokens(_tex(MAIN_TEX))
    assert all(tok.values()), f"missing: {[k for k, v in tok.items() if not v]}"


def test_addendum_q_sections():
    secs = addendum_sections(_tex(ADDENDUM_TEX))
    assert len(secs) == 5
    assert secs[0] == "Context"
    assert secs[1].startswith("1. Convexity")
    assert secs[2].startswith("2. Continuity and Invariance")
    assert secs[3].startswith("3. Stochastic Perturbations")
    assert secs[4] == "Integration with the Manuscript"


def test_determinism():
    a = analyse(MAIN_TEX)
    b = analyse(MAIN_TEX)
    assert a == b
