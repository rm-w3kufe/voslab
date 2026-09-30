from trace_graph.cli import main

from .fixtures import make_traces, write_file


def test_list(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", make_traces(),
                   extra_lines=("{broken",))
    rc = main(["list", "--traces", str(p)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "traces: 5 | skipped: 1" in out
    assert "claim_gate: 4" in out and "type_prefix: 1" in out


def test_export_dot_to_file(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", make_traces())
    out = tmp_path / "g.dot"
    rc = main(["export", "--tree", "claim_gate", "--format", "dot",
               "--traces", str(p), "--out", str(out)])
    assert rc == 0
    body = out.read_text()
    assert body.startswith("digraph claim_gate {") and "homes: R1=1" in body
    assert f"wrote {out}" in capsys.readouterr().out


def test_export_json_stdout(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", make_traces())
    rc = main(["export", "--tree", "claim_gate", "--format", "json",
               "--traces", str(p)])
    out = capsys.readouterr().out
    assert rc == 0 and '"links"' in out and '"keyed_by_fallback"' in out


def test_export_unknown_family_rc2(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", make_traces())
    rc = main(["export", "--tree", "nope", "--traces", str(p)])
    assert rc == 2
    assert "no traces" in capsys.readouterr().err


def test_show_trace(tmp_path, capsys):
    p = write_file(tmp_path / "t.jsonl", make_traces())
    rc = main(["show", "--trace", "t-a", "--format", "dot",
               "--traces", str(p)])
    assert rc == 0 and "n0 -> n1" in capsys.readouterr().out
    rc = main(["show", "--trace", "missing", "--traces", str(p)])
    assert rc == 2
