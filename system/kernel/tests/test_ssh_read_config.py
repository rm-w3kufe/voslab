"""Tests for ~/.ssh/read_config.py (D-31, S5-authorized 2026-10-07).

Two layers:
  1. Fixture tests — parser/lookup semantics against a synthetic
     ssh_config in tmp_path (deterministic, machine-independent).
  2. Live tests — the real ~/.ssh/config, its FQDN reverse lookup, and
     CLI exit codes. Skipped when the script is absent (fresh clone).

Semantics cross-checked against `ssh -G` (D-31 evidence, 23/23 hosts):
first-wins scalars, list-valued forwards accumulate, HostName is NOT a
match pattern (reverse lookup is ours to do), unset Port == default 22.
The old parser split on ':' — every directive was dropped and unknown
hosts exited 0 while the spec chains `read_config.py h && ssh h`.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path.home() / ".ssh" / "read_config.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="~/.ssh/read_config.py not present"
)


def _load():
    spec = importlib.util.spec_from_file_location("ssh_read_config", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rc():
    return _load()


FIXTURE = """\
# fixture config — mirrors the production shapes that broke the old parser
Host alpha
    HostName alpha.example.org
    User alice
    IdentityFile ~/.ssh/alpha_key
    DynamicForward 1080                     # SOCKS v5
    LocalForward 3128 127.0.0.1:3128
    ServerAliveInterval 60
    ConnectTimeout 5

Host alpha-tun
    HostName alpha.example.org
    User alice
    LocalForward 3128 127.0.0.1:3128
    LocalForward 9050 127.0.0.1:9050

Host beta beta-alt
    HostName 10.10.20.9
    User root
    Port 2290
    LocalForward 8006  127.0.0.1:8006

Host gamma
\tHostName host#tag\t\t# inline, no whitespace before '#'
\tUser g
\tIdentityFile ~/.ssh/gamma

Host delta
    User d
Match host somewhere
    User wrong

Host *
    ConnectTimeout 20
"""


def _block(blocks, name):
    for patterns, directives in blocks:
        if name in patterns:
            return directives
    raise AssertionError(f"no block for {name!r}")


@pytest.fixture()
def blocks(rc, tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(FIXTURE, encoding="utf-8")
    return rc.parse_ssh_config(cfg)


# ─── parser ───────────────────────────────────────────────────────────


def test_parse_keyword_value_not_colon(rc, blocks):
    """ssh_config is whitespace `Keyword Value` — the old ':' parser
    dropped every directive (hosts['n01'] == {})."""
    alpha = _block(blocks, "alpha")
    assert alpha["hostname"] == "alpha.example.org"
    assert alpha["user"] == "alice"
    assert alpha["identityfile"] == "~/.ssh/alpha_key"
    assert alpha["serveraliveinterval"] == "60"


def test_inline_comment_stripped_only_after_whitespace(rc, blocks):
    """`# ` after whitespace is a comment; `host#tag` keeps its '#'
    (OpenSSH behaviour, probe c1)."""
    assert _block(blocks, "alpha")["dynamicforward"] == ["1080"]
    assert _block(blocks, "gamma")["hostname"] == "host#tag"


def test_multi_pattern_shares_block(rc, blocks):
    """`Host beta beta-alt` — one directives dict, both patterns resolve."""
    alt = rc.resolve_connection(blocks, "beta-alt")
    assert alt["port"] == "2290"
    assert alt["hostname"] == "10.10.20.9"


def test_list_valued_forwards_accumulate(rc, blocks):
    """LocalForward is MULTI_VALUE — both lines kept, not first-wins."""
    tun = rc.resolve_connection(blocks, "alpha-tun")
    assert tun["local_forwards"] == [
        "3128 127.0.0.1:3128",
        "9050 127.0.0.1:9050",
    ]


def test_match_block_directives_dropped(rc, blocks):
    """Match-scoped directives are unsupported — must not leak into the
    preceding Host block."""
    assert _block(blocks, "delta")["user"] == "d"
    assert "wrong" not in _block(blocks, "delta").values()


def test_merge_first_wins_and_wildcard_fills_gaps(rc, blocks):
    """Specific block beats `Host *` (first-wins); hosts without the
    scalar inherit the wildcard default."""
    merged_alpha = rc._merged_for(blocks, "alpha")
    assert merged_alpha["connecttimeout"] == "5"  # explicit wins over *
    merged_beta = rc._merged_for(blocks, "beta")
    assert merged_beta["connecttimeout"] == "20"  # gap filled by Host *
    # forwards still accumulate across matching blocks
    assert merged_alpha["localforward"] == ["3128 127.0.0.1:3128"]


# ─── lookup ───────────────────────────────────────────────────────────


def test_reverse_hostname_resolves_to_alias(rc, blocks):
    """HostName is not a match pattern — FQDN must reverse-resolve to
    the alias so `ssh <alias>` picks up key/user (Host * only otherwise)."""
    info = rc.resolve_connection(blocks, "alpha.example.org")
    assert info["alias"] == "alpha"
    assert info["connection_chain"] == ["alpha"]


def test_exact_pattern_beats_substring(rc, blocks):
    """`alpha` must not land on `alpha-tun` via substring fallback."""
    assert rc._resolve_alias(blocks, "alpha") == "alpha"
    assert rc._resolve_alias(blocks, "alpha-tun") == "alpha-tun"


def test_unknown_host_is_error(rc, blocks):
    assert rc._resolve_alias(blocks, "no-such-host") is None
    info = rc.resolve_connection(blocks, "no-such-host")
    assert info == {"error": "Host 'no-such-host' not found in SSH config"}


def test_empty_query_is_none(rc, blocks):
    assert rc._resolve_alias(blocks, "") is None


def test_tunnel_arg_joins_tokens(rc):
    """`3128 127.0.0.1:3128` -> `-L 3128:127.0.0.1:3128`; double-space
    config (n02-all) collapses too."""
    assert rc._fwd_arg("-L", "3128 127.0.0.1:3128") == "-L 3128:127.0.0.1:3128"
    assert rc._fwd_arg("-L", "8006  127.0.0.1:8006") == "-L 8006:127.0.0.1:8006"
    assert rc._fwd_arg("-D", "1080") == "-D 1080"


def test_missing_config_returns_empty(rc, tmp_path):
    assert rc.parse_ssh_config(tmp_path / "absent") == []


# ─── live: real ~/.ssh/config ─────────────────────────────────────────


@pytest.fixture(scope="module")
def live(rc):
    blocks = rc.parse_ssh_config(SCRIPT.parent / "config")
    if not blocks:
        pytest.skip("no ~/.ssh/config")
    return blocks


def test_live_n01(live, rc):
    info = rc.resolve_connection(live, "n01")
    assert info["user"] == "rmw3"
    assert info["identity"] == "~/.ssh/vsf_n01"
    assert info["hostname"] == "n01.u2738.org"
    assert info["dynamic_forwards"] == ["1080"]


def test_live_n02_chain_and_port(live, rc):
    info = rc.resolve_connection(live, "n02")
    assert info["proxy_jump"] == "n01"
    assert info["port"] == "2290"
    assert info["connection_chain"] == ["n01", "n02"]


def test_live_fqdn_resolves_to_alias(live, rc):
    assert rc._resolve_alias(live, "n01.u2738.org") == "n01"


def test_live_tunnel_args_are_complete(live, rc):
    """Old CLI printed `-L 3128` (missing target) for n01-tun."""
    info = rc.resolve_connection(live, "n01-tun")
    assert rc._fwd_arg("-L", info["local_forwards"][0]) == (
        "-L 3128:127.0.0.1:3128"
    )


# ─── live: CLI exit contract (spec: `read_config.py h && ssh h`) ──────


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def test_cli_known_host_exits_zero():
    assert _run("n01").returncode == 0


def test_cli_unknown_host_exits_one():
    res = _run("no-such-host-d31")
    assert res.returncode == 1
    assert "not found" in res.stdout


def test_cli_list_exits_zero():
    res = _run("--list")
    assert res.returncode == 0
    assert "Configured SSH hosts" in res.stdout


def test_cli_topology_exits_zero():
    res = _run("--topology")
    assert res.returncode == 0
    assert "VSF Network Topology" in res.stdout


def test_cli_no_args_exits_one():
    assert _run().returncode == 1
