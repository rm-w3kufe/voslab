# design: docs/spec_revision/design-sources/relocate-vsm-v1/relocate_vsm_spec.vsm (SUT: packages/public/vsf-tools/vsf_tools/relocate_vsm.py)
"""Tests for relocate_vsm (duel winner vs scripts/shared copy).

The scripts/shared copy lacked `import os` (NameError at import) and was
referenced by nothing at its real path; the TS plugin pointed at
nonexistent scripts/docs/. Package version is canonical (installed).
"""
import os
import sys

import pytest

import vsf_tools.relocate_vsm as R


@pytest.fixture
def tiny_repo(tmp_path, monkeypatch):
    # Layout mirrors the real corpus roots (docs/spec_revision/).
    (tmp_path / "docs" / "spec_revision").mkdir(parents=True)
    (tmp_path / "docs" / "spec_revision" / "old.vsm").write_text(
        "link docs/spec_revision/other.vsm here\n")
    (tmp_path / "docs" / "spec_revision" / "other.vsm").write_text("plain\n")
    monkeypatch.setenv("VOS_ROOT", str(tmp_path))
    monkeypatch.setattr(R, "ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _doc(p, *parts):
    return p / "docs" / "spec_revision" / parts[-1]


def test_relocate_moves_and_remaps(tiny_repo):
    rc = R.relocate("docs/spec_revision/old.vsm",
                    "docs/spec_revision/new.vsm", dry_run=False)
    assert rc == 0
    assert not _doc(tiny_repo, "old.vsm").exists()
    assert _doc(tiny_repo, "new.vsm").exists()


def test_relocate_dry_run_changes_nothing(tiny_repo):
    rc = R.relocate("docs/spec_revision/old.vsm",
                    "docs/spec_revision/new.vsm", dry_run=True)
    assert rc == 0
    assert _doc(tiny_repo, "old.vsm").exists()
    assert not _doc(tiny_repo, "new.vsm").exists()


def test_relocate_pattern_b_remap_only(tiny_repo):
    # Move already happened (plugin fires AFTER git mv): remap only.
    _doc(tiny_repo, "old.vsm").rename(_doc(tiny_repo, "new.vsm"))
    _doc(tiny_repo, "other.vsm").write_text(
        "see docs/spec_revision/old.vsm for details\n")
    rc = R.relocate("docs/spec_revision/old.vsm",
                    "docs/spec_revision/new.vsm", dry_run=False)
    assert rc == 0
    assert "docs/spec_revision/new.vsm" in _doc(
        tiny_repo, "other.vsm").read_text()


def test_module_imports_cleanly():
    # Regression: scripts/shared copy died here (missing `import os`).
    import importlib
    mod = importlib.reload(R)
    assert callable(mod.relocate) and callable(mod.main)
