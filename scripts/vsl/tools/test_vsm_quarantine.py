"""Tests for vsm_quarantine.py — stash/restore/quarantine semantics.

Covers the FND-VSM-STASH-BLIND-01 fallback fix: a TRACKED file without
stash must be COPIED to quarantine + HEAD-restored (tree keeps a valid
file), never moved out of the tree. New/untracked files keep the old
move semantics. All isolation via tmp_path: VSM_QUARANTINE_DIR seam for
the quarantine dir, throwaway git repo for tracked cases.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import vsm_quarantine as Q


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, timeout=30)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init")
    return repo


def _qdir(monkeypatch, tmp_path: Path) -> Path:
    q = tmp_path / "q"
    monkeypatch.setenv("VSM_QUARANTINE_DIR", str(q))
    return q


def test_stash_restore_roundtrip(tmp_path: Path, monkeypatch):
    _qdir(monkeypatch, tmp_path)
    f = tmp_path / "doc.vsm"
    f.write_text("original")
    assert Q.cmd_stash(str(f)) == 0
    f.write_text("breach")
    tok = Q._token(str(f))
    assert Q.cmd_restore(tok) == 0
    assert f.read_text() == "original"


def test_restore_without_stash_refused(tmp_path: Path, monkeypatch):
    _qdir(monkeypatch, tmp_path)
    assert Q.cmd_restore("deadbeefdeadbeef") == 2


def test_quarantine_missing_refused(tmp_path: Path, monkeypatch):
    _qdir(monkeypatch, tmp_path)
    assert Q.cmd_quarantine(str(tmp_path / "nope.vsm")) == 2


def test_new_file_moves(tmp_path: Path, monkeypatch):
    q = _qdir(monkeypatch, tmp_path)
    outside = tmp_path / "work"
    outside.mkdir()
    f = outside / "new.vsm"
    f.write_text("breach content")
    assert Q.cmd_quarantine(str(f)) == 0
    assert not f.exists()  # moved out
    moved = list(q.glob("new.*.vsm"))
    assert len(moved) == 1 and moved[0].read_text() == "breach content"


def test_tracked_file_copies_and_restores_head(tmp_path: Path, monkeypatch):
    q = _qdir(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    f = repo / "doc.vsm"
    f.write_text("HEAD content")
    _git(repo, "add", "doc.vsm")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "add doc")
    f.write_text("HEAD content + uncommitted priors + BREACH")
    assert Q.cmd_quarantine(str(f)) == 0
    # tree keeps a VALID file (HEAD), breach preserved as evidence
    assert f.read_text() == "HEAD content"
    copies = list(q.glob("doc.*.vsm"))
    assert len(copies) == 1
    assert copies[0].read_text() == "HEAD content + uncommitted priors + BREACH"


def test_tracked_staged_never_committed_falls_back_to_move(
        tmp_path: Path, monkeypatch):
    q = _qdir(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    f = repo / "staged.vsm"
    f.write_text("staged only")
    _git(repo, "add", "staged.vsm")  # tracked in index, no HEAD version
    assert Q.cmd_quarantine(str(f)) == 0
    assert not f.exists()  # moved: nothing committable to restore
    moved = list(q.glob("staged.*.vsm"))
    assert len(moved) == 1 and moved[0].read_text() == "staged only"


def test_token_deterministic(tmp_path: Path):
    f = tmp_path / "a.vsm"
    f.write_text("x")
    assert Q._token(str(f)) == Q._token(str(f))
    assert len(Q._token(str(f))) == 16


def test_quarantine_entry_json_shape(tmp_path: Path, monkeypatch):
    _qdir(monkeypatch, tmp_path)
    f = tmp_path / "doc.vsm"
    f.write_text("v1")
    assert Q.cmd_stash(str(f)) == 0
    tok = Q._token(str(f))
    q = Path(os.environ["VSM_QUARANTINE_DIR"])
    entry = json.loads((q / f"{tok}.json").read_text())
    assert entry["existed"] is True
    assert entry["path"] == str(f.resolve())
