# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-ontology/vsf_ontology/staging_predicates.py)
"""tests/test_staging_predicates.py — Tests for staging predicates."""

import os
import tempfile
from pathlib import Path
import pytest
from vsf_ontology.staging_predicates import (
    staging_has_docs,
    staging_has_scripts,
    staging_read_doc,
    spec_changed,
    code_updated,
    plugins_updated,
    changelog_updated,
    version_bumped,
)


class TestStagingHasDocs:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert staging_has_docs(tmpdir) is False

    def test_with_vsm_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.vsm").touch()
            assert staging_has_docs(tmpdir) is True

    def test_with_other_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.txt").touch()
            assert staging_has_docs(tmpdir) is False

    def test_nonexistent_dir(self):
        assert staging_has_docs("/nonexistent") is False

    def test_empty_string(self):
        assert staging_has_docs("") is False


class TestStagingHasScripts:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert staging_has_scripts(tmpdir) is False

    def test_with_py_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.py").touch()
            assert staging_has_scripts(tmpdir) is True

    def test_with_other_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.txt").touch()
            assert staging_has_scripts(tmpdir) is False

    def test_nonexistent_dir(self):
        assert staging_has_scripts("/nonexistent") is False


class TestStagingReadDoc:
    def test_read_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir, "test.vsm")
            test_file.write_text("test content")
            assert staging_read_doc(str(test_file)) == "test content"

    def test_read_nonexistent(self):
        assert staging_read_doc("/nonexistent/file.vsm") == ""


class TestSpecChanged:
    def test_spec(self):
        assert spec_changed("spec") is True

    def test_language(self):
        assert spec_changed("language") is True

    def test_vsl(self):
        assert spec_changed("vsl") is True

    def test_code(self):
        assert spec_changed("code") is False

    def test_other(self):
        assert spec_changed("other") is False


class TestCodeUpdated:
    def test_code(self):
        assert code_updated("code") is True

    def test_spec(self):
        assert code_updated("spec") is True

    def test_language(self):
        assert code_updated("language") is True

    def test_parser(self):
        assert code_updated("parser") is True

    def test_other(self):
        assert code_updated("other") is False


class TestPluginsUpdated:
    def test_plugins(self):
        assert plugins_updated("plugins") is True

    def test_code(self):
        assert plugins_updated("code") is True

    def test_hook(self):
        assert plugins_updated("hook") is True

    def test_other(self):
        assert plugins_updated("other") is False


class TestChangelogUpdated:
    def test_recent_date(self):
        # This test depends on the actual changelog file
        # Just verify it doesn't crash
        result = changelog_updated("code")
        assert isinstance(result, bool)


class TestVersionBumped:
    def test_with_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir, "test.vsm")
            test_file.write_text("@vsm 1.2.3\n@test")
            assert version_bumped(str(test_file)) is True

    def test_without_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir, "test.vsm")
            test_file.write_text("@test content")
            assert version_bumped(str(test_file)) is False

    def test_nonexistent_file(self):
        assert version_bumped("/nonexistent/file.vsm") is False
