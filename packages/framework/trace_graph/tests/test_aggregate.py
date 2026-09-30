from trace_graph.graph import aggregate, families, per_trace

from .fixtures import make_traces


def test_families_counts():
    assert families(make_traces()) == {
        "claim_gate": 4, "type_prefix": 1}


def test_aggregate_filter_and_denominators():
    agg = aggregate(make_traces(), tree="claim_gate")
    assert agg["family"] == "claim_gate"
    m = agg["meta"]
    assert m["traces"] == 4              # A B C D (E filtered out)
    assert m["traces_without_nodes"] == 1  # D
    assert m["homes"] == {"R1": 1}


def test_aggregate_keys_by_text_across_shapes():
    agg = aggregate(make_traces(), tree="claim_gate")
    nodes = agg["nodes"]
    # A's evaluated operator 'a($x)' and B's placeholder merge on text
    assert nodes["a($x)"]["evals"] == 2
    assert nodes["a($x)"]["keyed_by"] == "text"
    assert nodes["a($x)"]["truths"] == {"Truth.TRUE": 1, "Truth.UNKNOWN": 1}
    # child edge exists only where branch was evaluated (A)
    edges = {(e["source"], e["target"]): e["weight"] for e in agg["edges"]}
    assert edges[("a($x)", "inner($x)")] == 1
    assert edges[("AND(a, b)", "a($x)")] == 2   # both traces contain it
    # old row nodes counted as fallback, never silently keyed as text
    assert nodes["operator:AND"]["keyed_by"] == "fallback"
    assert nodes["predicate:ctx_equals"]["keyed_by"] == "fallback"
    assert (agg["meta"]["keyed_by_text"],
            agg["meta"]["keyed_by_fallback"]) == (4, 2)


def test_aggregate_deterministic():
    t = make_traces()
    assert aggregate(t, tree="claim_gate") == aggregate(t, tree="claim_gate")


def test_duplicate_sibling_text_gets_suffix():
    traces = [{
        "trace_id": "dup", "tree_shape": "claim_gate(x)",
        "nodes": [
            {"node_id": 0, "type": "operator", "name": "AND",
             "truth": "Truth.TRUE", "certified": True, "text": "root",
             "children": [1, 2]},
            {"node_id": 1, "type": "predicate", "name": "p",
             "truth": "Truth.TRUE", "certified": True, "text": "p($x)",
             "children": []},
            {"node_id": 2, "type": "predicate", "name": "p",
             "truth": "Truth.FALSE", "certified": True, "text": "p($x)",
             "children": []},
        ],
    }]
    nodes = aggregate(traces, tree="claim_gate")["nodes"]
    assert "p($x)" in nodes and "p($x)#2" in nodes


def test_per_trace_uses_local_ids_and_meta():
    g = per_trace(make_traces()[0])
    assert g["meta"]["home"] == "R1"
    assert g["meta"]["trace_id"] == "t-a"
    assert {n["id"] for n in g["nodes"]} == {"0", "1", "2", "3"}
    assert ("0", "1") in g["edges"] and ("1", "3") in g["edges"]
    # question survives for F4 nodes
    assert any(n["question"] for n in g["nodes"])
