"""Tests for the CC-8.1 counterfactual shadow harness (vos_kernel/shadow.py).

Negative controls included: malformed entries MUST be rejected (a shadow
that accepts garbage would rubber-stamp anything).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent
                       / "packages/framework/vos_kernel"))

import shadow  # noqa: E402


def _repo_with_commit(tmp_path: Path, filename: str = "target.txt",
                      commit_ts: str = "2026-10-03T01:00:00Z") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ,
           "GIT_AUTHOR_DATE": commit_ts, "GIT_COMMITTER_DATE": commit_ts}

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args],
                       check=True, capture_output=True,
                       env={**env, "GIT_CONFIG_GLOBAL": str(tmp_path / "gconfig"),
                            "GIT_CONFIG_SYSTEM": os.devnull})

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    (repo / filename).write_text("v1\n", encoding="utf-8")
    git("add", filename)
    git("commit", "-q", "-m", "materialize target")
    return repo


BOUNDS_OK = {"pass": True, "reasons": ["guard=G-TEST", "guard_status=live"]}
BOUNDS_BLOCK = {"pass": False, "reasons": ["guard=G-TEST", "guard_status=dead"]}


def test_record_load_roundtrip(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    entry = shadow.record("audit-findings", {"fix": "x = 1"}, BOUNDS_OK,
                          ledger=ledger, entry_id="SHD-TEST-1")
    assert entry["id"] == "SHD-TEST-1"
    assert entry["target"] is None
    loaded = shadow.load(ledger)
    assert len(loaded) == 1
    assert loaded[0]["bounds"]["pass"] is True
    assert loaded[0]["ts"].endswith("Z")


def test_record_rejects_missing_bounds(tmp_path: Path) -> None:
    """Negative control: an entry without a bounds-check must not enter."""
    ledger = tmp_path / "shadow.jsonl"
    with pytest.raises(ValueError, match="bounds"):
        shadow.record("audit-findings", {"fix": "x = 1"},
                      {"reasons": []}, ledger=ledger)


def test_record_rejects_empty_source(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    with pytest.raises(ValueError, match="source"):
        shadow.record("", {"fix": "x = 1"}, BOUNDS_OK, ledger=ledger)


def test_record_dict_action_is_canonicalized(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    entry = shadow.record("audit-findings", {"b": 2, "a": 1}, BOUNDS_OK,
                          ledger=ledger)
    assert entry["action"] == '{"a": 1, "b": 2}'  # sort_keys → deterministic id


def test_analyze_blocked_and_deterministic(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.record("s", {"fix": "would"}, BOUNDS_BLOCK, ledger=ledger,
                  entry_id="SHD-BLOCKED")
    shadow.record("s", {"fix": "ok"}, BOUNDS_OK, ledger=ledger,
                  entry_id="SHD-OK")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    a = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    b = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    assert a == b  # R10: same inputs → same output
    assert a["new_count"] == 2
    assert a["blocked_count"] == 1
    assert a["blocked_ids"] == ["SHD-BLOCKED"]


def test_divergence_classification(tmp_path: Path) -> None:
    """blocked-but-materialized vs aligned-executed vs would-run-not-mat."""
    commit_ts = "2026-10-03T01:00:00Z"
    repo = _repo_with_commit(tmp_path, commit_ts=commit_ts)
    ledger = tmp_path / "shadow.jsonl"
    old = "2026-10-02T12:00:00Z"   # before the commit → materialized
    # 1) blocked by bounds, yet materialized in reality
    shadow.record("s", {"fix": "bad"}, BOUNDS_BLOCK, target="target.txt",
                  ledger=ledger, entry_id="SHD-DIV-1")
    lines = ledger.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["ts"] = old
    ledger.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    # 2) would-run and materialized → aligned
    shadow.record("s", {"fix": "good"}, BOUNDS_OK, target="target.txt",
                  ledger=ledger, entry_id="SHD-ALIGNED")
    lines = ledger.read_text(encoding="utf-8").splitlines()
    aligned = json.loads(lines[1])
    aligned["ts"] = old
    ledger.write_text(json.dumps(entry) + "\n" + json.dumps(aligned) + "\n",
                      encoding="utf-8")

    # 3) would-run, never materialized (target never existed)
    shadow.record("s", {"fix": "future"}, BOUNDS_OK, target="ghost.txt",
                  ledger=ledger, entry_id="SHD-NOTMAT")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=repo)
    kinds = {d["id"]: d["kind"] for d in report["divergences"]}
    assert kinds["SHD-DIV-1"] == "blocked-but-materialized"
    assert kinds["SHD-NOTMAT"] == "would-run-not-materialized"
    assert "SHD-ALIGNED" not in kinds  # aligned, not a divergence
    assert report["aligned_count"] == 1


def test_analyze_unverifiable_without_git(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.record("s", {"fix": "x"}, BOUNDS_OK, target="t.txt",
                  ledger=ledger, entry_id="SHD-NOGIT")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    report = shadow.analyze(cutoff, ledger=ledger, repo_root=tmp_path)
    assert report["divergences"][0]["kind"] == "unverifiable"


def test_collect_shadow_reads_live_ledger() -> None:
    """Integration: evolution_report.collect_shadow over the real workspace."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent
                            / "packages/framework/vos_kernel"))
    import evolution_report as er
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    report = er.collect_shadow(cutoff)
    assert "error" not in report
    assert report["total"] >= 50  # live ledger seeded by shadow_cycle
