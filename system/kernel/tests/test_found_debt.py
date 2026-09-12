"""test_found_debt.py — found-debt fixes (stubs audit): gap-engine-path
mediated via bridge, audit-proposal on canonical validator, retired
legs gone. All subprocess CLI (hermetic): reads existing repo files
only, zero writes.
"""
import json
import subprocess
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
BRIDGE = (VOSLAB / ".opencode" / "plugins" / "operational"
          / "tool_integration_bridge.py")
TREES = VOSLAB / ".opencode" / "plugins" / "support" / "trees"


def _run(cmd, *args):
    import os
    p = subprocess.run(
        [sys.executable, "-W", "ignore", str(BRIDGE), cmd, *args],
        capture_output=True, text=True, timeout=120, cwd=str(VOSLAB),
        env={**os.environ, "VOS_ROLE": "operator"},
    )
    return p


def _json_out(p):
    raw = p.stdout.strip()
    return json.loads(raw[raw.index("{"):])


def test_tree_file_evaluates():
    tree = sorted(TREES.glob("*.tree.vsm"))[0]
    p = _run("socratic-tree-file", str(tree), json.dumps({"type": "x"}))
    assert p.returncode == 0, p.stderr[:200]
    out = _json_out(p)
    assert "truth" in out and "certified" in out
    assert "outside workspace" not in str(out)


def test_tree_file_confined():
    p = _run("socratic-tree-file", "/etc/hostname", "{}")
    assert p.returncode == 0
    assert _json_out(p).get("error") == "tree path outside workspace"


def test_tree_file_missing():
    p = _run("socratic-tree-file",
             str(VOSLAB / "state" / "no-such-tree.vsm"), "{}")
    assert "not found" in _json_out(p).get("error", "")


def test_audit_proposal_live():
    p = _run("audit-proposal", "docs/plans/r2_verdict.vsm")
    assert p.returncode == 0, p.stderr[:200]
    out = _json_out(p)
    assert out.get("valid") is True
    p2 = _run("audit-proposal", "docs/plans/pending_completion_plan.vsm")
    assert _json_out(p2).get("filepath", "").endswith(".vsm")


def test_retired_cmds_gone():
    for cmd in ("verify-refs", "post-register"):
        p = _run(cmd, "x")
        assert p.returncode != 0, cmd
        assert "Unknown command" in p.stderr
