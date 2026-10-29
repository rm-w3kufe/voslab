"""test_pattern_runner — REAL execution of the shipped pattern-runner.ts
(PATTERN-RUNNER-v1, design: docs/design/sources/
pattern-runner-v1/pattern_runner.vsm).

Bundles .opencode/plugins/operational/handlers/pattern-runner.ts with
esbuild (the same class of transform opencode uses at load), then runs the
node harness (support/pattern_runner_node_test.mjs) against a fixture repo
root. Verifies classify routing, R17 needs-nod refusal, R9 algedonic alerts,
R10 determinism — on the ACTUAL bundle, not a reimplementation (R4).

Skips honestly (established convention) if esbuild is unavailable: the repo
ships no TS test runner; esbuild is resolved from PATH or the /tmp/opencode
dev install.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
HANDLER = REPO / ".opencode/plugins/operational/handlers/pattern-runner.ts"
NODE_HARNESS = Path(__file__).parent / "support" / "pattern_runner_node_test.mjs"

ESBUILD_CANDIDATES = [
    shutil.which("esbuild"),
    "/tmp/opencode/node_modules/.bin/esbuild",
]


def _find_esbuild() -> str | None:
    for c in ESBUILD_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


ESBUILD = _find_esbuild()

pytestmark = pytest.mark.skipif(
    ESBUILD is None,
    reason="esbuild unavailable (no TS test runner ships with repo)",
)


# ─── fixture repo root ───────────────────────────────────────────────────────

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_fixture(tmp_path: Path) -> Path:
    """A minimal repo root with the registry + the scripts the node harness
    asserts on. Rule ids sorted: fail-rule, glob-rule, missing-rule,
    needs-nod-rule, run-marker (the handler sorts by id — R10)."""
    root = tmp_path / "fixture_repo"
    (root / "state/rsi").mkdir(parents=True)

    registry = {
        "version": 1,
        "rules": [
            {
                "id": "run-marker",
                "on": "session.idle",
                "match": [],
                "run": "scripts/ok_marker.py",
                "args": ["marker-a"],
                "driver": "S1",
                "consent": "read-only",
                "desc": "writes marker-a",
            },
            {
                "id": "needs-nod-rule",
                "on": "session.idle",
                "match": [],
                "run": "scripts/needs_nod.py",
                "args": ["marker-b"],
                "driver": "S5",
                "consent": "needs-nod",
                "desc": "destructive-ish: must be blocked without S5 nod",
            },
            {
                "id": "fail-rule",
                "on": "session.idle",
                "match": [],
                "run": "scripts/fail_rule.py",
                "args": [],
                "driver": "S3",
                "consent": "read-only",
                "desc": "always exits 1",
            },
            {
                "id": "missing-rule",
                "on": "session.idle",
                "match": [],
                "run": "scripts/does_not_exist.py",
                "args": [],
                "driver": "S2",
                "consent": "read-only",
                "desc": "script absent → R9 alert",
            },
            {
                "id": "glob-rule",
                "on": "tool.execute.after",
                "match": [
                    {"field": "file_path", "op": "glob", "pattern": "docs/**"}
                ],
                "run": "scripts/ok_marker.py",
                "args": ["marker-c"],
                "driver": "S4",
                "consent": "read-only",
                "desc": "runs on docs/** writes",
            },
        ],
    }
    _write(root / "scripts/state/pattern_registry.json", json.dumps(registry))

    _write(
        root / "scripts/ok_marker.py",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "open(sys.argv[1], 'w').write('x')\n",
    )
    _write(
        root / "scripts/needs_nod.py",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "open(sys.argv[1], 'w').write('x')\n",
    )
    _write(root / "scripts/fail_rule.py", "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n")
    return root


# ─── bundle + run ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bundled_handler(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("bundle") / "pattern-runner.bundle.mjs"
    cmd = [
        ESBUILD,
        str(HANDLER),
        "--bundle",
        "--format=esm",
        "--platform=node",
        "--external:node:*",
        f"--outfile={out}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"esbuild failed: {proc.stderr[:500]}"
    assert out.exists(), "bundle not written"
    return out


def test_pattern_runner_real_execution(bundled_handler: Path, tmp_path: Path) -> None:
    root = make_fixture(tmp_path)
    proc = subprocess.run(
        ["node", str(NODE_HARNESS), str(bundled_handler), str(root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"node harness failed:\n{output}"
    # The harness prints one PASS/FAIL line per check — surface them all.
    assert "FAIL" not in output, output
    assert "ALL PASS" in output, output


def test_registry_is_valid_policy() -> None:
    """Static R16/R17 validation of the SHIPPED registry (policy artifact):
    legal consent values, known channels, in-repo paths, Sn drivers,
    ceiling-bounded timeouts. No execution — pure schema (deterministic)."""
    reg_path = REPO / "scripts/state/pattern_registry.json"
    data = json.loads(reg_path.read_text())
    rules = data["rules"]
    assert rules, "registry empty"
    channels = {
        "session.idle",
        "session.created",
        "tool.execute.after",
        "file.edited",
        "git.post-commit",
    }
    for r in rules:
        assert r["id"], "rule missing id"
        assert r["on"] in channels, f"{r['id']}: unknown channel {r['on']}"
        assert r["consent"] in {"read-only", "advisory", "needs-nod"}, r["id"]
        assert r["driver"] in {"S1", "S2", "S3", "S4", "S5"}, r["id"]
        assert not r["run"].startswith("/"), f"{r['id']}: absolute path"
        assert ".." not in r["run"], f"{r['id']}: parent traversal"
        assert r.get("timeout_ms", 15000) <= 60000, f"{r['id']}: timeout ceiling"
        assert isinstance(r["args"], list)
        for m in r["match"]:
            assert m["op"] in {"equals", "glob", "regex", "prefix", "present"}
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids"


def test_router_registers_pattern_runner_not_scripts_automation() -> None:
    """R16 migration check: the router wires pattern-runner; the migrated
    scripts-automation handler is gone (no orphan wiring)."""
    router_src = (
        REPO / ".opencode/plugins/operational/vsf-event-router.ts"
    ).read_text()
    assert "patternRunnerHandler" in router_src
    assert "scriptsAutomationHandler" not in router_src
    assert not (
        REPO / ".opencode/plugins/operational/handlers/scripts-automation.ts"
    ).exists(), "migrated handler file still present"
