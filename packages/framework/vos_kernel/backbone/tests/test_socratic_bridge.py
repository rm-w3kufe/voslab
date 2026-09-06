"""tests/test_socratic_bridge.py — Tests for socratic bridge."""

import tempfile
from pathlib import Path

import pytest
from vos_kernel.backbone.socratic_bridge import SocraticBridge


@pytest.fixture
def bridge():
    """Create a socratic bridge instance."""
    return SocraticBridge()


def test_bridge_init(bridge):
    """SocraticBridge initializes correctly."""
    assert bridge.engine_path is not None


def test_load_tree_missing(bridge):
    """load_tree fails for missing file."""
    result = bridge.load_tree("/nonexistent/tree.vsm")
    assert result.success is False
    assert "not found" in result.error.lower()


def test_load_tree_invalid_vsl(bridge, tempfile_path):
    """load_tree fails for invalid VSL."""
    tree_file = Path(tempfile_path) / "bad.vsm"
    tree_file.write_text("not a vsl file")
    result = bridge.load_tree(tree_file)
    assert result.success is False


def test_register_predicate_missing(bridge):
    """register_predicate fails for missing file."""
    result = bridge.register_predicate("/nonexistent/predicate.py")
    assert result.success is False


def test_register_predicate_syntax_error(bridge, tempfile_path):
    """register_predicate fails for syntax error."""
    pred_file = Path(tempfile_path) / "bad.py"
    pred_file.write_text("def broken(")
    result = bridge.register_predicate(pred_file)
    assert result.success is False
    assert "syntax" in result.error.lower()


@pytest.fixture
def tempfile_path():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
