"""Integration: vsf-tools is pinned into vOSLAB and importable."""
import tempfile

from vsf_tools import (
    MemoryIndexGenerator,
    SilentHTTPHandler,
    create_silent_server,
)


def test_vsf_tools_gen_index_pinned(tmp_path):
    d = tmp_path / "memory"
    d.mkdir()
    (d / "x.md").write_text(
        '---\nname: "X"\ndescription: "d"\ntype: reference\n---\n'
    )
    out = MemoryIndexGenerator(str(d)).write()
    assert "X" in out  # negative-control: generation works through the pin


def test_vsf_tools_silent_server_pinned():
    class H(SilentHTTPHandler):
        def do_GET(self):
            pass

    srv = create_silent_server(("127.0.0.1", 0), H)
    assert srv.server_address[1] > 0  # ephemeral port bound
    srv.server_close()
