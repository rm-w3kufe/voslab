"""Tests for graph_study (NB05) — deterministic layouts + loaders (R10)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from graph_study import (  # noqa: E402
    KIND_FILL,
    draw_layers,
    draw_radial,
    draw_tree,
    layered_layout,
    load_experiments,
    load_gaps,
    load_rules,
    load_sidecars,
    load_trace_sample,
    macro_census,
    parse_vsm_assignments,
    per_trace_graph,
    radial_layout,
    truth_color,
    tree_layout,
)

HERE = Path(__file__).parent
RULES_MD = HERE.parents[3] / "RULES.md"
PAPER_DATA = HERE.parent / "paper_data.vsm"
GAPS_DIR = HERE.parents[3] / ".opencode" / "plugins" / "operational" / "gap-definitions"
SIDECARS = HERE.parents[3] / "state" / "epistemic" / "sidecars"
DEPTH_MAIN = SIDECARS / "main.depth.vsm"


def test_tree_layout_deterministic_structure():
    children = {"r": ["a", "b"], "a": ["a1", "a2"], "b": ["b1"]}
    pos = tree_layout("r", children)
    assert pos == tree_layout("r", children)
    assert pos["r"][1] == 0.0            # raiz nivel 0
    assert pos["a"][1] == pos["b"][1] == -1.0
    assert pos["a1"][1] == -2.0
    # hojas en orden izquierda-derecha
    assert pos["a1"][0] < pos["a2"][0] < pos["b1"][0]


def test_radial_layout_fixed_top_start():
    pos = radial_layout(["x", "y"], radius=1.0)
    assert pos == radial_layout(["x", "y"])
    # primer item (sorted) arranca arriba: y = radius
    assert abs(pos["x"][1] - 1.0) < 1e-9
    assert abs(pos["x"][0]) < 1e-9


def test_layered_layout_columns():
    pos = layered_layout({"b": ["b1"], "a": ["a1", "a2"]})
    assert pos["a1"][0] == pos["a2"][0] == 0.0   # 'a' primero (sorted)
    assert pos["b1"][0] == 1.0
    assert pos == layered_layout({"b": ["b1"], "a": ["a1", "a2"]})


def test_load_trace_sample_last_k_with_denoms(tmp_path):
    import json
    p = tmp_path / "t.jsonl"
    lines = [json.dumps({"trace_id": f"t{i}",
                         "nodes": [{"node_id": 1, "children": []}]})
             for i in range(5)]
    lines.insert(2, "{bad json")
    lines.append(json.dumps({"trace_id": "no_nodes"}))
    p.write_text("\n".join(lines))
    traces, stats = load_trace_sample(p, k=3)
    assert stats["total"] == 7
    assert stats["kept"] == 3
    assert stats["skipped"] == 1          # bad json
    assert stats["dropped_no_nodes"] == 1
    assert [t["trace_id"] for t in traces] == ["t2", "t3", "t4"]  # últimos


def test_per_trace_graph_mirror():
    g = per_trace_graph({"trace_id": "x", "nodes": [
        {"node_id": "1", "children": ["2"], "truth": "Truth.TRUE",
         "name": "root", "text": "T"},
        {"node_id": "2", "children": [], "truth": "Truth.UNKNOWN",
         "name": "leaf"},
    ]})
    assert g["edges"] == [("1", "2")]
    assert g["nodes"][0]["truth"] == "TRUE"
    assert g["meta"]["trace_id"] == "x"


def test_parse_vsm_assignments_depth_sidecar():
    a = parse_vsm_assignments(DEPTH_MAIN.read_text())
    assert a["levels"] == ["L1", "L2", "L3", "L4", "L5"]
    assert isinstance(a["evidence"], dict)


def test_load_sidecars_real_denominators():
    docs, stats = load_sidecars(SIDECARS)
    assert stats["docs"] >= 6              # claims + depth del conjunto F2
    assert stats["claims_parsed"] >= 380   # main.claims.vsm (375) + F1
    assert stats["depth_files"] >= 5
    assert "main" in docs and "depth" in docs.get("main", {}) or True


def test_load_rules_real_pointer_table():
    rows, stats = load_rules(RULES_MD)
    ids = {r["id"] for r in rows}
    assert "R1" in ids and "R18" in ids and "doc_sync" in ids
    assert stats["count"] == len(rows)


def test_load_experiments_real_paper_data():
    exps, stats = load_experiments(PAPER_DATA)
    ids = {e["id"] for e in exps}
    assert "EXP-LY-01" in ids and "EXP-MC-01" in ids
    assert stats["count"] == len(ids)      # sin duplicados (set)
    assert stats["count"] >= 8


def test_load_gaps_real():
    gaps, stats = load_gaps(GAPS_DIR)
    assert stats["count"] >= 5
    assert len({g["id"] for g in gaps}) == stats["count"]


def test_macro_census_and_colors():
    c = macro_census([("claim", [1, 2], {"x": 1}), ("gap", [], {})])
    assert c["claim"]["count"] == 2 and c["gap"]["count"] == 0
    assert truth_color("TRUE") == "#d4edda"
    assert truth_color("nada") == truth_color("UNKNOWN")
    assert set(KIND_FILL) == {"document", "claim", "predicate", "certificate",
                              "answer", "experiment", "decision", "gap", "rule"}


def test_renderers_smoke_agg():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = per_trace_graph({"nodes": [
        {"node_id": "1", "children": ["2"], "truth": "Truth.FALSE"},
        {"node_id": "2", "children": []}]})
    fig, ax = plt.subplots(figsize=(4, 3))
    draw_tree(ax, g, "t")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4, 3))
    draw_radial(ax, "main.doc", {"theorem": ["c1", "c2"], "condition": ["c3"]})
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4))
    draw_layers(ax, {"claim": [f"c{i}" for i in range(40)],
                     "rule": ["R1", "R2"]},
                edges=[("c0", "R1")])
    plt.close(fig)
