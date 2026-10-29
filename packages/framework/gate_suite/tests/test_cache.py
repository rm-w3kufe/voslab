#!/usr/bin/env python3
"""
test_cache.py — F3a manifest cache (REFS-OPT-001) for gate_suite.harness.

Covers: cold-set partition integrity, kill switch, dirty-modulo-shadow
detection, manifest roundtrip/single-slot, and the end-to-end hit path
(fake checks dir: warm run must skip the cacheable check but re-run the
cold one).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_FRAMEWORK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _FRAMEWORK_DIR not in sys.path:
    sys.path.insert(0, _FRAMEWORK_DIR)

from gate_suite import harness  # noqa: E402

CHECKS_DIR = Path(_FRAMEWORK_DIR).parent / "public" / "vsf-checks" / "checks"


def _check_names() -> set[str]:
    return {
        p.name for p in CHECKS_DIR.iterdir()
        if p.is_file() and not p.name.endswith(".md")
    }


# ── cold-set partition ───────────────────────────────────────────────────────

def test_cold_set_membership():
    names = _check_names()
    missing = harness.ALWAYS_COLD - names
    assert not missing, f"ALWAYS_COLD names not in checks dir: {sorted(missing)}"
    # 29 frozen 2026-10-06 (REFS-OPT-001) + pleasure-channel (G-34 P5,
    # 2026-10-07): its input is the gitignored pleasure ledger, which
    # appends during runs — cached results would be stale by construction.
    # + extractor-nonvacuous (EV-R3, 2026-10-15): reads gitignored
    # state/ (doc_manifest, symbol_table) — cached = stale by construction.
    # + systemd-units-fresh (T1-F2, 2026-10-21): external systemd user-bus
    #   state (timers/units) — no tracked file captures it, cached = stale.
    assert len(harness.ALWAYS_COLD) == 32, "frozen cold set is 32 checks"


def test_cold_set_reasons_documented():
    assert set(harness._COLD_REASONS) == set(harness.ALWAYS_COLD), (
        "every ALWAYS_COLD check needs a documented reason"
    )


def test_partition_excludes_known_cacheable():
    names = _check_names()
    cacheable = names - harness.ALWAYS_COLD
    # strace-audited biggest wins must stay cacheable
    # (child-boot-state-archive-gates retired in a550472 — removed here)
    for name in ("vsl-timestamp-required",
                 "learning-record-valid", "agent-map-valid"):
        assert name in cacheable, f"{name} must be cacheable"
    # strace-audited externals must stay cold
    for name in ("crl-expiry-proximity", "agent-plugin-log-valid", "workspaces-health"):
        assert name in harness.ALWAYS_COLD, f"{name} must be ALWAYS_COLD"
    assert harness.ALWAYS_COLD.isdisjoint(cacheable)


def test_ssh_mux_checks_are_cold_and_real():
    """The multiplexed ssh checks must run on every pass (external state)
    and must be actual files in the checks dir."""
    names = _check_names()
    assert harness.SSH_MUX_CHECKS <= harness.ALWAYS_COLD
    assert harness.SSH_MUX_CHECKS <= names


# ── kill switch ──────────────────────────────────────────────────────────────

def test_cache_disabled_env(monkeypatch):
    monkeypatch.setenv("VOS_GATES_CACHE", "0")
    assert not harness._cache_enabled()
    monkeypatch.setenv("VOS_GATES_CACHE", "1")
    assert harness._cache_enabled()
    monkeypatch.delenv("VOS_GATES_CACHE")
    assert harness._cache_enabled()  # default on


# ── dirty detection (real git repos in tmp) ──────────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )
    return out.stdout


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@test")
    _git(repo, "config", "user.name", "test")
    (repo / "tracked.txt").write_text("v1\n")
    shadow = repo / "state" / "epistemic"
    shadow.mkdir(parents=True)
    (shadow / "shadow.jsonl").write_text('{"n":1}\n')
    rsi = repo / "state" / "rsi"
    rsi.mkdir(parents=True)
    (rsi / ".session_idle_last").write_text('{"at":0}\n')
    distill = repo / "state" / "distill"
    distill.mkdir(parents=True)
    (distill / "candidates.jsonl").write_text("{}\n")
    reports = repo / "state" / "epistemic" / "reports"
    reports.mkdir(parents=True)
    (reports / "EVOLUTION.md").write_text("# e\n")
    (reports / "evolution_latest.json").write_text("{}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_dirty_modulo_shadow(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(harness, "_repo_root", lambda: repo)

    # clean tree -> not dirty
    assert not harness._dirty_modulo_shadow()

    # shadow.jsonl modified (D-24 volatile) -> still clean-modulo-shadow
    (repo / "state" / "epistemic" / "shadow.jsonl").write_text('{"n":2}\n')
    assert not harness._dirty_modulo_shadow()

    # runtime auto-append state (D-24 rationale extended 2026-10-07):
    # idle marker + distill candidates rewritten by hooks mid-session
    (repo / "state" / "rsi" / ".session_idle_last").write_text('{"at":1}\n')
    (repo / "state" / "distill" / "candidates.jsonl").write_text('{"id":"x"}\n')
    assert not harness._dirty_modulo_shadow()

    # daily evolution stage (D-24 rationale extended 2026-10-07, DIR prefix):
    # tracked report rewrite + new untracked daily file -> still clean
    # (real evidence: gate 5 went red seconds after commit 018e802 when
    # _evolution_daily_stage fired at 15:27:28Z mid-session)
    (repo / "state" / "epistemic" / "reports" / "EVOLUTION.md").write_text("# e2\n")
    (repo / "state" / "epistemic" / "reports" / "evolution_2026-10-07.json").write_text("{}\n")
    assert not harness._dirty_modulo_shadow()

    # any other tracked modification -> dirty
    (repo / "tracked.txt").write_text("v2\n")
    assert harness._dirty_modulo_shadow()
    _git(repo, "checkout", "--", "tracked.txt")

    # untracked file -> dirty (cache must not serve a working tree that
    # git can see beyond HEAD)
    (repo / "new.txt").write_text("x\n")
    assert harness._dirty_modulo_shadow()
    (repo / "new.txt").unlink()

    # only excluded auto-append files modified -> clean
    assert not harness._dirty_modulo_shadow()


def test_tree_hash_tracks_head(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(harness, "_repo_root", lambda: repo)
    t1 = harness._tree_hash()
    assert t1
    (repo / "tracked.txt").write_text("v2\n")
    _git(repo, "commit", "-aqm", "change")
    assert harness._tree_hash() != t1


# ── manifest roundtrip (single slot) ─────────────────────────────────────────

def test_manifest_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "run_gates_live.json"
    monkeypatch.setenv("VOS_GATES_CACHE_PATH", str(path))

    assert harness._load_manifest() is None  # absent

    harness._save_manifest("tree-A", {"zz": {"rc": 0, "at": "t"}})
    m = harness._load_manifest()
    assert m["tree"] == "tree-A"
    assert m["version"] == harness.CACHE_VERSION
    assert m["gate"] == harness.CACHE_GATE
    assert set(m["entries"]) == {"zz"}

    # single slot: next save overwrites
    harness._save_manifest("tree-B", {})
    assert harness._load_manifest()["tree"] == "tree-B"

    # corrupted file -> None (miss, never crash)
    path.write_text("{not json")
    assert harness._load_manifest() is None


# ── end-to-end hit path with fake checks ─────────────────────────────────────

def _write_fake_check(cdir: Path, name: str) -> None:
    script = cdir / name
    script.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$0" >> "$FAKE_MARKER"\n'
        "exit 0\n"
    )
    script.chmod(0o755)


@pytest.fixture
def fake_world(tmp_path, monkeypatch):
    cdir = tmp_path / "checks"
    cdir.mkdir()
    cold_name = "crl-expiry-proximity"          # member of ALWAYS_COLD
    cache_name = "zz-fake-cacheable"            # complement
    _write_fake_check(cdir, cold_name)
    _write_fake_check(cdir, cache_name)

    marker = tmp_path / "marker.log"
    monkeypatch.setenv("FAKE_MARKER", str(marker))
    monkeypatch.setenv("VOS_GATES_CACHE_PATH", str(tmp_path / "manifest.json"))
    # hermetic: the fake cold check shares a name with a real ssh check —
    # without this the fixture would spawn live ControlMaster prewarms
    monkeypatch.setenv("VOS_SSH_MUX", "0")
    monkeypatch.setattr(harness, "_dirty_modulo_shadow", lambda: False)
    monkeypatch.setattr(harness, "_tree_hash", lambda: "T-TEST")
    return cdir, marker, cold_name, cache_name


def _runs(marker: Path) -> list[str]:
    if not marker.exists():
        return []
    return [Path(line).name for line in marker.read_text().splitlines() if line]


def test_miss_then_hit_skips_cacheable(fake_world):
    cdir, marker, cold_name, cache_name = fake_world

    # miss: both run, manifest written
    assert harness.run_live_checks(cdir) == 0
    assert _runs(marker) == [cold_name, cache_name]
    manifest = json.loads(Path(os.environ["VOS_GATES_CACHE_PATH"]).read_text())
    assert manifest["tree"] == "T-TEST"
    assert cache_name in manifest["entries"]

    # hit: cold re-runs, cacheable is skipped
    assert harness.run_live_checks(cdir) == 0
    assert _runs(marker) == [cold_name, cache_name, cold_name]

    # kill switch: everything runs again even on a clean tree
    os.environ["VOS_GATES_CACHE"] = "0"
    try:
        assert harness.run_live_checks(cdir) == 0
        assert _runs(marker) == [
            cold_name, cache_name, cold_name, cold_name, cache_name,
        ]
    finally:
        os.environ.pop("VOS_GATES_CACHE", None)


def test_dirty_bypasses_read_and_write(fake_world, monkeypatch):
    cdir, marker, cold_name, cache_name = fake_world
    path = Path(os.environ["VOS_GATES_CACHE_PATH"])

    # green clean run writes the manifest
    assert harness.run_live_checks(cdir) == 0
    assert path.exists()

    # now the tree is dirty: no read (cacheable runs), no write (manifest
    # unchanged even though the run is green)
    monkeypatch.setattr(harness, "_dirty_modulo_shadow", lambda: True)
    path.write_text(json.dumps({"version": 999}))  # would be honored if read
    assert harness.run_live_checks(cdir) == 0
    assert _runs(marker)[-1] == cache_name  # cacheable ran despite file
    assert json.loads(path.read_text())["version"] == 999  # not overwritten


def test_red_run_never_writes_manifest(fake_world):
    cdir, marker, cold_name, cache_name = fake_world
    # make the cacheable check fail
    (cdir / cache_name).write_text("#!/usr/bin/env bash\nexit 3\n")
    (cdir / cache_name).chmod(0o755)

    assert harness.run_live_checks(cdir) == 1
    assert not Path(os.environ["VOS_GATES_CACHE_PATH"]).exists()


def test_hit_requires_matching_cacheable_set(fake_world):
    cdir, marker, cold_name, cache_name = fake_world
    path = Path(os.environ["VOS_GATES_CACHE_PATH"])

    assert harness.run_live_checks(cdir) == 0  # writes manifest for {cache_name}

    # stale entry set (e.g. classification changed without version bump)
    data = json.loads(path.read_text())
    data["entries"] = {"something-else": {"rc": 0, "at": "t"}}
    path.write_text(json.dumps(data))

    before = len(_runs(marker))
    assert harness.run_live_checks(cdir) == 0  # miss -> full run
    assert len(_runs(marker)) == before + 2     # both re-ran


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
