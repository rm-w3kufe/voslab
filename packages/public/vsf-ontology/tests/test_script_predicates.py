# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: packages/public/vsf-ontology/vsf_ontology/script_predicates.py)
"""tests/test_script_predicates.py — Tests for script predicates."""

import tempfile
import os
from pathlib import Path

import pytest
from vsf_ontology.script_predicates import (
    script_analyze,
    script_has_tree,
    script_needs_integration,
    script_classify,
    script_read,
    staging_has_scripts,
    staging_has_docs,
    staging_read_doc,
    spec_changed,
    version_bumped,
    code_updated,
    plugins_updated,
    changelog_updated,
)


class TestScriptAnalyze:
    def test_simple(self):
        result = script_analyze("import os\nprint('hello')")
        assert "os" in result["imports"]
        assert result["has_main"] is False
        assert result["has_tree"] is False

    def test_with_main(self):
        content = "import os\nif __name__ == '__main__':\n    pass"
        result = script_analyze(content)
        assert result["has_main"] is True

    def test_with_tree(self):
        content = "socratic('TEST') = {}"
        result = script_analyze(content)
        assert result["has_tree"] is True

    def test_empty(self):
        result = script_analyze("")
        assert result["imports"] == []
        assert result["has_main"] is False


class TestScriptHasTree:
    def test_nonexistent(self):
        assert script_has_tree("nonexistent_xyz_123") is False


class TestScriptNeedsIntegration:
    def test_small(self):
        assert script_needs_integration({"size": 100, "imports": ["os"]}) is False

    def test_large(self):
        assert script_needs_integration({"size": 600, "imports": ["os"]}) is True

    def test_many_imports(self):
        assert script_needs_integration({"size": 100, "imports": ["a", "b", "c", "d", "e", "f"]}) is True

    def test_not_dict(self):
        assert script_needs_integration("not a dict") is False


class TestScriptClassify:
    def test_has_tree(self):
        assert script_classify({"has_tree": True}) == "HAS_TREE"

    def test_standalone(self):
        assert script_classify({"has_tree": False, "has_main": True}) == "STANDALONE"

    def test_module(self):
        assert script_classify({"has_tree": False, "has_main": False}) == "MODULE"

    def test_unknown(self):
        assert script_classify("not a dict") == "UNKNOWN"


class TestScriptRead:
    def test_nonexistent(self):
        assert script_read("/nonexistent/path.py") == ""


class TestStagingHasScripts:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert staging_has_scripts(tmpdir) is False

    def test_with_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "test.py"), "w").close()
            assert staging_has_scripts(tmpdir) is True

    def test_nonexistent(self):
        assert staging_has_scripts("/nonexistent/dir") is False


class TestStagingHasDocs:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert staging_has_docs(tmpdir) is False

    def test_with_docs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "test.vsm"), "w").close()
            assert staging_has_docs(tmpdir) is True


class TestStagingReadDoc:
    def test_nonexistent(self):
        assert staging_read_doc("/nonexistent/path.vsm") == ""


class TestSpecChanged:
    def test_spec(self):
        assert spec_changed("spec") is True

    def test_language(self):
        assert spec_changed("language") is True

    def test_other(self):
        assert spec_changed("code") is False


class TestVersionBumped:
    def test_nonexistent(self):
        assert version_bumped("/nonexistent/path.vsm") is False

    def test_old_version(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vsm", delete=False) as f:
            f.write("@vsm 1.2.0\n")
            f.flush()
            assert version_bumped(f.name) is False
            os.unlink(f.name)

    def test_new_version(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vsm", delete=False) as f:
            f.write("@vsm 1.2.2\n")
            f.flush()
            assert version_bumped(f.name) is True
            os.unlink(f.name)


class TestCodeUpdated:
    def test_code(self):
        assert code_updated("code") is True

    def test_other(self):
        assert code_updated("docs") is False


class TestPluginsUpdated:
    def test_plugins(self):
        assert plugins_updated("plugins") is True

    def test_other(self):
        assert plugins_updated("docs") is False


class TestChangelogUpdated:
    def test_nonexistent(self):
        assert changelog_updated("/nonexistent/path.vsm") is False
