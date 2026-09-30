import json

from trace_graph.load import family, load_traces, traces_path

from .fixtures import make_traces, write_file


def test_family_forms():
    assert family("claim_gate(AND(a, b))") == "claim_gate"
    assert family("type_prefix(foo)") == "type_prefix"
    assert family("AND(x, y)") == "AND"
    assert family(None) == "?"
    assert family("") == "?"


def test_load_counts_malformed(tmp_path):
    p = write_file(tmp_path / "t.jsonl", make_traces(),
                   extra_lines=("{broken", '"not-a-dict"', "42"))
    traces, skipped = load_traces(p)
    assert len(traces) == 5
    assert skipped == 3


def test_load_missing_file(tmp_path):
    assert load_traces(tmp_path / "nope.jsonl") == ([], 0)


def test_traces_path_env_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("VOSLAB_PATH", str(tmp_path))
    assert traces_path() == tmp_path / "state" / "rsi" / "tree_traces.jsonl"


def test_load_preserves_old_row_shapes(tmp_path):
    p = write_file(tmp_path / "t.jsonl", make_traces())
    traces, _ = load_traces(p)
    old = next(t for t in traces if t["trace_id"] == "t-c")
    assert "home" not in old and "context" not in old
    assert "text" not in old["nodes"][0]
    # json sanity: every row re-serializes
    json.dumps(traces)
