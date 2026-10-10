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


def test_a0_inventory_b2():
    from l2_parser import a0_inventory
    inv = a0_inventory(_tex(MAIN_TEX))
    assert len(inv) == 21
    secs = {r["section"] for r in inv}
    # embedding en la capa de convergencia...
    assert "The Feasible Region $\\Omega$" in secs
    assert "A Coordinate-Free Viability Functional" in secs
    # ...y el marco de capa-agente que el paper YA declara
    assert "Ethics as a governance instantiation, not a mathematical primitive" in secs
    assert "Governance and ethics (A0 covenant)" in secs
    # el aviso explícito de no mezclar capas
    assert any("Conflating the two layers" in r["snippet"] for r in inv)


def test_fierro_bullets_no_preamble():
    from l2_parser import fierro_bullets
    txt = (HERE / "data" / "fierro_review.txt").read_text(errors="replace")
    bullets = fierro_bullets(txt)
    assert len(bullets) == 3
    assert bullets[0].startswith("To apply the Brower theorem")
    assert "noise" in bullets[2] and "σ · η(t)" in bullets[2]


def test_correlate_all_discharged():
    from l2_parser import correlate
    add = ADDENDUM_TEX.read_text(errors="replace")
    txt = (HERE / "data" / "fierro_review.txt").read_text(errors="replace")
    rows = correlate(_tex(MAIN_TEX), add, txt)
    assert [r["qi"] for r in rows] == [1, 2, 3]
    for r in rows:
        assert r["status"] == "DISCHARGED", f"Q{r['qi']} open: {r}"


# ── NB04: L2-full — inventory / dependency graph / proof-vs-asserted ─────────

from l2_parser import dependency_graph, equation_inventory, proof_audit  # noqa: E402


def test_equation_inventory_main():
    inv = equation_inventory(_tex(MAIN_TEX))
    blocks = [r for r in inv if r["block"]]
    loose = [r for r in inv if not r["block"]]
    assert len(blocks) == 22
    assert len(inv) == 27                      # 22 bloques + 5 eq: sueltos
    assert sum(1 for r in inv if r["label"]) == 20  # denominador de labels eq:
    assert all(r["section"] for r in inv)      # sin seccion = error
    assert inv == sorted(inv, key=lambda r: r["line"])  # orden de documento
    assert [r["idx"] for r in inv] == list(range(1, len(inv) + 1))


def test_equation_inventory_determinism():
    a = equation_inventory(_tex(MAIN_TEX))
    b = equation_inventory(_tex(MAIN_TEX))
    assert a == b


def test_dependency_graph_resolved_only():
    g = dependency_graph(_tex(MAIN_TEX))
    labels = set()
    import re as _re
    labels.update(_re.findall(r"\\label\{([^}]+)\}", _tex(MAIN_TEX)))
    assert g["denominator"]["dangling"] == 0
    assert all(t in labels for _, t in g["edges"])
    ids = {n["id"] for n in g["nodes"]}
    assert "def:kernel" in ids and "eq:dynamics" in ids
    assert ("def:kernel", "eq:dynamics") in g["edges"]
    assert g["edges"] == sorted(g["edges"])


def test_proof_audit_denominator_and_finding():
    rows = proof_audit(_tex(MAIN_TEX))
    assert len(rows) == 17                     # todo env, sin skips
    classes = [r["classification"] for r in rows]
    assert classes.count("formal-proof") == 0  # hallazgo NB04: sin \begin{proof}
    assert classes.count("discharged-by-measurement") == 1
    dis = [r for r in rows if r["classification"] == "discharged-by-measurement"]
    assert dis[0]["label"] == "thm:hybrid_invariance"
    assert all(r["section"] for r in rows)


def test_proof_audit_synthetic_classifications():
    tex = (
        "\\begin{theorem}\\label{thm:in} s. "
        "\\begin{proof} done \\end{proof} \\end{theorem}\n"
        "\\begin{proposition}\\label{prop:adj} s. \\end{proposition}\n"
        "\\begin{proof} adjacent proof \\end{proof}\n"
        "\\begin{definition}\\label{def:bare} just stated \\end{definition}\n"
        "\\begin{remark}\\label{rem:dis} "
        "result is discharged by measurement. \\end{remark}\n"
        "\\begin{lemma}\\label{lem:as} it follows from standard facts. \\end{lemma}\n"
    )
    by = {r["label"]: r["classification"] for r in proof_audit(tex)}
    assert by["thm:in"] == "formal-proof"          # in_body
    assert by["prop:adj"] == "formal-proof"        # adjacent (400 chars)
    assert by["def:bare"] == "statement-only"
    assert by["rem:dis"] == "discharged-by-measurement"
    assert by["lem:as"] == "asserted"


def test_proof_audit_determinism():
    a = proof_audit(_tex(MAIN_TEX))
    b = proof_audit(_tex(MAIN_TEX))
    assert a == b
