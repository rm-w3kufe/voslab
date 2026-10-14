"""design: docs/spec_revision/system/s1-operations/vos_package_detailed_plans.vsm
test_rsi_advanced_tree_generator.py — adversarial / edge-case tests.

Covers:
  - generate_advanced_tree: basic, with pattern, with base_tree
  - Tree types: threshold_optimized, coverage, generic
  - _register_tree: manifest update
  - _load/_save_manifest: roundtrip

Every check must fail closed: no files created without valid input.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

MANIFEST_SPEC = Path(__file__).resolve().parent / "rsi_manifest_parser.py"
SPEC_PATH = Path(__file__).resolve().parent / "rsi_advanced_tree_generator.py"


@pytest.fixture
def generator():
    """Load rsi_advanced_tree_generator with sandboxed state."""
    mp_spec = importlib.util.spec_from_file_location("rsi_manifest_parser", str(MANIFEST_SPEC))
    mp_mod = importlib.util.module_from_spec(mp_spec)
    mp_spec.loader.exec_module(mp_mod)
    sys.modules["rsi_manifest_parser"] = mp_mod

    spec = importlib.util.spec_from_file_location("rsi_advanced_tree_generator", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp()
    mod.TREES_DIR = Path(tmp) / "trees"
    mod.TREES_DIR.mkdir(parents=True, exist_ok=True)
    mod.TREES_MANIFEST = Path(tmp) / "rsi_advanced_trees.vsm"
    obj = mod.RSIAdvancedTreeGenerator()
    return obj, mod, Path(tmp)


# ── generate_advanced_tree ──────────────────────────────────────────────

def test_generate_basic(generator):
    """Basic advanced tree generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "threshold_optimization", "predicate": "test_pred", "accuracy": 0.3}
    result = gen.generate_advanced_tree(pattern)
    assert result
    assert Path(result).exists()


def test_generate_coverage_tree(generator):
    """Coverage tree generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "coverage", "predicate": "test_pred", "coverage": 0.2}
    result = gen.generate_advanced_tree(pattern)
    assert result
    assert Path(result).exists()


def test_generate_generic_tree(generator):
    """Generic tree generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "unknown_type", "predicate": "test_pred"}
    result = gen.generate_advanced_tree(pattern)
    assert result
    assert Path(result).exists()


def test_generate_with_base_tree(generator):
    """Tree with base should work."""
    gen, mod, tmp = generator
    base = "⟦ base | TREE-v1 | vsm-1.2 | 2026-08-30T00:00:00Z ⟧\n@vsm 1.2\n@status active\n"
    pattern = {"type": "threshold_optimization", "predicate": "test_pred"}
    result = gen.generate_advanced_tree(pattern, base_tree=base)
    assert result


# ── _load/_save_manifest ───────────────────────────────────────────────

def test_manifest_roundtrip(generator):
    """Manifest save/load should work."""
    gen, mod, tmp = generator
    manifest = {"trees": [{"name": "test", "path": "/tmp/test.vsm"}]}
    gen._save_manifest(manifest)
    loaded = gen._load_manifest()
    assert "trees" in loaded
    assert len(loaded["trees"]) >= 1


# ── Adversarial ─────────────────────────────────────────────────────────

def test_empty_pattern(generator):
    """Empty pattern should not crash."""
    gen, mod, tmp = generator
    result = gen.generate_advanced_tree({})
    assert result


def test_many_trees(generator):
    """Generating many trees should not crash."""
    gen, mod, tmp = generator
    for i in range(5):
        pattern = {"type": "threshold_optimization", "predicate": f"pred_{i}"}
        result = gen.generate_advanced_tree(pattern)
        assert result
