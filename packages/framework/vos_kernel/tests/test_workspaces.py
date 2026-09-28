"""EP-4 D2 tests — declared-workspace registry (vos_kernel.workspaces).

Covers: fail-soft load, declare validation (id/kind/absolute/uniqueness),
boundary-aware longest-match lookup, check rc semantics, CLI through
vsctl, and validity of the REAL seeded registry (read-only).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from vos_kernel import workspaces
from vos_kernel.epistemic import repo_root

VSCTL = repo_root() / "scripts" / "vsl" / "vsctl"


@pytest.fixture()
def reg_root(tmp_path: Path) -> Path:
    """Isolated registry root (state/workspaces.json under tmp)."""
    (tmp_path / "state").mkdir()
    return tmp_path


def _write_registry(root: Path, workspaces_list: list[dict]) -> Path:
    path = root / "state" / "workspaces.json"
    path.write_text(json.dumps({"version": 1, "workspaces": workspaces_list}))
    return path


# ─── load ────────────────────────────────────────────────────────────────────

def test_load_missing_file_is_fail_soft(reg_root: Path):
    reg = workspaces.load(reg_root / "no-such-dir")
    assert reg["workspaces"] == []
    assert reg["version"] == workspaces.REGISTRY_VERSION


def test_load_malformed_file_is_fail_soft(reg_root: Path):
    (reg_root / "state" / "workspaces.json").write_text("{not json")
    assert workspaces.load(reg_root)["workspaces"] == []


# ─── declare ─────────────────────────────────────────────────────────────────

def test_declare_creates_sorted_registry(reg_root: Path):
    workspaces.declare("/tmp/opencode", "sandbox-tmp", "sandbox",
                       registry_root=reg_root)
    workspaces.declare("/home/user/docs", "shared-docs", "reference",
                       registry_root=reg_root)
    stored = json.loads((reg_root / "state" / "workspaces.json")
                        .read_text())
    ids = [e["id"] for e in stored["workspaces"]]
    assert ids == sorted(ids)
    entry = next(e for e in stored["workspaces"]
                 if e["id"] == "sandbox-tmp")
    assert entry["root"] == "/tmp/opencode"
    assert entry["kind"] == "sandbox"


def test_declare_rejects_bad_input(reg_root: Path):
    workspaces.declare("/tmp/one", "ws-one", "sandbox",
                       registry_root=reg_root)
    with pytest.raises(ValueError):                      # duplicate id
        workspaces.declare("/tmp/two", "ws-one", "sandbox",
                           registry_root=reg_root)
    with pytest.raises(ValueError):                      # duplicate root
        workspaces.declare("/tmp/one", "ws-two", "shared",
                           registry_root=reg_root)
    with pytest.raises(ValueError):                      # bad kind
        workspaces.declare("/tmp/three", "ws-three", "galaxy",
                           registry_root=reg_root)
    with pytest.raises(ValueError):                      # relative root
        workspaces.declare("relative/path", "ws-four", "shared",
                           registry_root=reg_root)
    with pytest.raises(ValueError):                      # bad id chars
        workspaces.declare("/tmp/four", "bad id!", "shared",
                           registry_root=reg_root)


# ─── lookup (boundary + longest match) ───────────────────────────────────────

def test_lookup_exact_and_nested(reg_root: Path):
    workspaces.declare("/data/ws", "ws", "shared", registry_root=reg_root)
    assert workspaces.lookup("/data/ws", reg_root)["id"] == "ws"
    assert workspaces.lookup("/data/ws/deep/file.txt",
                             reg_root)["id"] == "ws"
    assert workspaces.lookup("/data/other.txt", reg_root) is None


def test_lookup_separator_boundary(reg_root: Path):
    """`/data/ws2` must NOT match root `/data/ws` (no separator boundary)."""
    workspaces.declare("/data/ws", "ws", "shared", registry_root=reg_root)
    assert workspaces.lookup("/data/ws2/file.txt", reg_root) is None


def test_lookup_longest_root_wins(reg_root: Path):
    workspaces.declare("/data", "broad", "shared", registry_root=reg_root)
    workspaces.declare("/data/ws", "inner", "sandbox",
                       registry_root=reg_root)
    assert workspaces.lookup("/data/ws/file", reg_root)["id"] == "inner"
    assert workspaces.lookup("/data/other", reg_root)["id"] == "broad"


def test_lookup_unaffected_by_trailing_slash(reg_root: Path):
    workspaces.declare("/data/ws/", "ws", "shared",
                       registry_root=reg_root)
    assert workspaces.lookup("/data/ws/x", reg_root)["id"] == "ws"


# ─── CLI (via vsctl) ─────────────────────────────────────────────────────────

def _vsctl(*args: str, tmp: Path) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "PYTHONPATH": str(repo_root() / "packages" / "framework"),
           # repo_root() is __file__-anchored: isolate the registry so
           # the CLI test never writes the real state/workspaces.json
           "VOS_WORKSPACES_PATH": str(tmp / "state" / "workspaces.json")}
    return subprocess.run([str(VSCTL), *args], capture_output=True,
                          text=True, env=env, cwd=str(tmp))


def test_cli_declare_list_check(tmp_path: Path):
    r = _vsctl("workspace", "declare", "/tmp/opencode", "--id",
               "cli-sandbox", "--kind", "sandbox", tmp=tmp_path)
    assert r.returncode == 0, r.stderr
    r = _vsctl("workspace", "list", tmp=tmp_path)
    assert r.returncode == 0
    reg = json.loads(r.stdout)
    assert reg["workspaces"][0]["id"] == "cli-sandbox"
    # check: declared → rc0, undeclared → rc1, duplicate declare → rc2
    r = _vsctl("workspace", "check", "/tmp/opencode/x.txt", tmp=tmp_path)
    assert r.returncode == 0 and "declared cli-sandbox" in r.stdout
    r = _vsctl("workspace", "check", "/etc/passwd", tmp=tmp_path)
    assert r.returncode == 1 and "undeclared" in r.stdout
    r = _vsctl("workspace", "declare", "/tmp/other", "--id",
               "cli-sandbox", "--kind", "sandbox", tmp=tmp_path)
    assert r.returncode == 2 and "already declared" in r.stderr


# ─── real registry (read-only sanity) ────────────────────────────────────────

def test_real_registry_is_valid():
    reg = workspaces.load()
    assert isinstance(reg["workspaces"], list)
    for e in reg["workspaces"]:
        assert os.path.isabs(e["root"]) and e["root"] == \
            os.path.normpath(e["root"])
        assert e["kind"] in workspaces.KINDS
        assert workspaces._ID_RE.match(e["id"])
    ids = [e["id"] for e in reg["workspaces"]]
    assert ids == sorted(ids)
    roots = [e["root"] for e in reg["workspaces"]]
    assert len(roots) == len(set(roots))
