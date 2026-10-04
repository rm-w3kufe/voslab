"""test_lifecycle_census.py — G-27 auto_verify for the docs/ re-census.

Two guarantees:
  1. Fixture determinism: each lifecycle category maps from the R10
     decision tree exactly as documented (same input -> same category),
     and violators (RUNTIME outside D-C, unbound CONSIDERED) drive rc=1.
  2. Live clean state: the real docs/ tree currently has zero
     violators — any transition that should have happened and did not
     fails the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
TOOL = VOSLAB / "scripts" / "vsl" / "tools" / "lifecycle_census.py"


def run(root: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), *args],
        capture_output=True, text=True, cwd=repo,
    )


def make_repo(tmp_path: Path) -> Path:
    """Minimal repo: docs/ fixture + instance.vsm binding + system/ twin."""
    repo = tmp_path / "repo"
    docs = repo / "docs"
    inst = repo / "system" / "instance" / "vsf-instance-v1"
    inst.mkdir(parents=True)
    (inst / "instance.vsm").write_text(
        "binding: \"docs/governance/\"\n"
    )

    def w(rel: str, text: str) -> Path:
        p = docs / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    w("archive/frozen.vsm", "x\n")                        # FROZEN
    w("sessions/log.md", "record\n")                     # RECORD
    w("guide.md", "narrative\n")                         # NARRATIVE
    w("figure.png", "\x89PNG")                           # ARTIFACT
    w("state.json", "{}")                                # ARTIFACT (json evidence)
    w("papers/make_figures.py", "print(1)\n")            # STAY-D-C
    w("loose_script.py", "print(1)\n")                   # RUNTIME -> violator
    w("governance/covenant.vsm", "canonical\n")          # bound twin -> ACTIVE-GOV
    (repo / "system" / "boot").mkdir(parents=True)
    (repo / "system" / "boot" / "covenant.vsm").write_text("canonical\n")
    w("spec/rules.vsm", "  rule(SESAME): open\n")        # logic, no twin -> LOGIC-MARKER
    w("dup.vsm", "same bytes\n")                         # unbound twin -> CONSIDERED
    (repo / "system" / "dup.vsm").write_text("same bytes\n")
    return repo


def test_fixture_categories(tmp_path: Path):
    repo = make_repo(tmp_path)
    out = run(repo / "docs", repo, "--json")
    assert out.returncode == 1, out.stderr  # violators present
    import json
    data = json.loads(out.stdout)
    assert data["counts"]["FROZEN"] == 1
    assert data["counts"]["RECORD"] == 1
    assert data["counts"]["NARRATIVE"] == 1
    assert data["counts"]["ARTIFACT"] == 2  # png + json
    assert data["counts"]["STAY-D-C"] == 1
    assert data["counts"]["ACTIVE-GOV"] == 1  # bound covenant twin
    assert data["counts"]["LOGIC-MARKER"] == 1
    assert data["logic_markers"] == ["spec/rules.vsm"]
    cats = dict(data["violators"])  # {rel: category}
    assert cats == {"loose_script.py": "RUNTIME",
                    "dup.vsm": "CONSIDERED"}


def test_fixture_deterministic_twice(tmp_path: Path):
    repo = make_repo(tmp_path)
    a = run(repo / "docs", repo, "--json").stdout
    b = run(repo / "docs", repo, "--json").stdout
    assert a == b


def test_live_docs_census_clean():
    """The real docs/ tree has no pending transitions (rc=0)."""
    out = run(VOSLAB / "docs", VOSLAB, "--violators")
    assert out.returncode == 0, (
        f"docs/ has lifecycle violators:\n{out.stdout}\n{out.stderr}"
    )
