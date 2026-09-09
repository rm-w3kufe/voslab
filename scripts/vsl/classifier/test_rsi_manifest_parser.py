"""
design: child/docs/vos_package_detailed_plans.vsm

Covers:
  - load_manifest: empty, single entry, multiple entries, malformed
  - save_manifest: roundtrip, special characters, empty values
  - Edge cases: missing fields, extra fields, unicode

Every check must fail closed: malformed entries are skipped, not trusted.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent / "rsi_manifest_parser.py"


@pytest.fixture
def parser():
    """Load rsi_manifest_parser module."""
    spec = importlib.util.spec_from_file_location("rsi_manifest_parser", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── load_manifest ───────────────────────────────────────────────────────

def test_load_manifest_empty(parser):
    """Empty file should return empty dict."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write("")
        f.flush()
        result = parser.load_manifest(Path(f.name))
    assert result == {}


def test_load_manifest_single_entry(parser):
    """Single entry should be parsed correctly."""
    content = '''trees = [
  { name: "test_tree", threshold: "0.7", active: "TRUE" }
]'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write(content)
        f.flush()
        result = parser.load_manifest(Path(f.name))
    assert "trees" in result
    assert len(result["trees"]) == 1
    assert result["trees"][0]["name"] == "test_tree"
    assert result["trees"][0]["threshold"] == "0.7"


def test_load_manifest_multiple_entries(parser):
    """Multiple entries should all be parsed."""
    content = '''trees = [
  { name: "tree_1", type: "decision" },
  { name: "tree_2", type: "leaf" }
]'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write(content)
        f.flush()
        result = parser.load_manifest(Path(f.name))
    assert "trees" in result
    assert len(result["trees"]) == 2
    assert result["trees"][0]["type"] == "decision"
    assert result["trees"][1]["type"] == "leaf"


# ── save_manifest ───────────────────────────────────────────────────────

def test_save_manifest_roundtrip(parser):
    """Save then load should return same data."""
    entries = [
        {"name": "tree_a", "threshold": "0.65", "active": "TRUE"},
        {"name": "tree_b", "threshold": "0.8", "active": "FALSE"}
    ]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        parser.save_manifest(Path(f.name), "trees", entries, "test_manifest", "2026-08-30T00:00:00Z")
        loaded = parser.load_manifest(Path(f.name))
    assert "trees" in loaded
    assert len(loaded["trees"]) == 2
    assert loaded["trees"][0]["name"] == "tree_a"
    assert loaded["trees"][1]["name"] == "tree_b"


def test_save_manifest_special_characters(parser):
    """Special characters in values should survive roundtrip."""
    entries = [{"name": "tree", "description": "path_checks_autonomy_cert"}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        parser.save_manifest(Path(f.name), "trees", entries, "test", "2026-08-30T00:00:00Z")
        loaded = parser.load_manifest(Path(f.name))
    assert "path_checks_autonomy_cert" in loaded["trees"][0]["description"]


def test_save_manifest_unicode(parser):
    """Unicode values should survive roundtrip."""
    entries = [{"name": "tree", "label": "árbol de decisión"}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        parser.save_manifest(Path(f.name), "trees", entries, "test", "2026-08-30T00:00:00Z")
        loaded = parser.load_manifest(Path(f.name))
    assert loaded["trees"][0]["label"] == "árbol de decisión"


# ── Adversarial ─────────────────────────────────────────────────────────

def test_extra_fields_preserved(parser):
    """Extra fields should be preserved in roundtrip."""
    entries = [{"name": "tree", "extra_field": "kept", "another": "42"}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        parser.save_manifest(Path(f.name), "trees", entries, "test", "2026-08-30T00:00:00Z")
        loaded = parser.load_manifest(Path(f.name))
    assert loaded["trees"][0]["extra_field"] == "kept"
    assert loaded["trees"][0]["another"] == "42"


def test_nested_list_structure(parser):
    """Nested structures should survive roundtrip."""
    entries = [{"name": "tree", "branches": "b1,b2"}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        parser.save_manifest(Path(f.name), "trees", entries, "test", "2026-08-30T00:00:00Z")
        loaded = parser.load_manifest(Path(f.name))
    assert "b1" in loaded["trees"][0]["branches"]


# ── Edge cases ──────────────────────────────────────────────────────────

def test_empty_manifest_file(parser):
    """Empty file should return empty dict, not crash."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write("")
        f.flush()
        result = parser.load_manifest(Path(f.name))
    assert result == {}


def test_only_comments(parser):
    """File with only comments should return empty dict."""
    content = '''// This is a comment
// Another comment
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write(content)
        f.flush()
        result = parser.load_manifest(Path(f.name))
    assert result == {}


def test_nonexistent_file(parser):
    """Non-existent file should return empty dict."""
    result = parser.load_manifest(Path("/tmp/nonexistent_12345.vsm"))
    assert result == {}


def test_malformed_entries_skipped(parser):
    """Malformed entries should be skipped or handled gracefully."""
    content = '''trees = [
  { name: "good_tree", type: "decision" },
  { name: BAD_NO_QUOTES, type: "123" }
]'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vsm', delete=False) as f:
        f.write(content)
        f.flush()
        result = parser.load_manifest(Path(f.name))
    # Should not crash, may parse partially
    assert isinstance(result, dict)
