"""design: docs/plans/vos_package_detailed_plans.vsm
test_rsi_tree_generator.py — adversarial / edge-case tests.

Covers:
  - generate_tree: basic, with gaps, with base_tree
  - _analyze_gaps: various gap types
  - _create_branch: different modification types
  - _register_tree: file creation, manifest update
  - _load/_save_manifest: roundtrip

Every check must fail closed: no files created without valid input.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

METRICS_SPEC = Path(__file__).resolve().parent / "rsi_metrics.py"
SPEC_PATH = Path(__file__).resolve().parent / "rsi_tree_generator.py"
MANIFEST_SPEC = Path(__file__).resolve().parent / "rsi_manifest_parser.py"


@pytest.fixture
def generator():
    """Load rsi_tree_generator with sandboxed state."""
    m_spec = importlib.util.spec_from_file_location("rsi_metrics", str(METRICS_SPEC))
    m_mod = importlib.util.module_from_spec(m_spec)
    m_spec.loader.exec_module(m_mod)

    mp_spec = importlib.util.spec_from_file_location("rsi_manifest_parser", str(MANIFEST_SPEC))
    mp_mod = importlib.util.module_from_spec(mp_spec)
    mp_spec.loader.exec_module(mp_mod)

    sys.modules["rsi_metrics"] = m_mod
    sys.modules["rsi_manifest_parser"] = mp_mod

    spec = importlib.util.spec_from_file_location("rsi_tree_generator", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp()
    mod.TREES_DIR = Path(tmp) / "trees"
    mod.TREES_DIR.mkdir(parents=True, exist_ok=True)
    mod.TREES_MANIFEST = Path(tmp) / "rsi_trees.vsm"
    mod.MODIFICATIONS_FILE = Path(tmp) / "rsi_modifications.jsonl"
    obj = mod.RSITreeGenerator()
    return obj, mod, Path(tmp)


# ── generate_tree ───────────────────────────────────────────────────────

def test_generate_tree_basic(generator):
    """Basic tree generation should create a file."""
    gen, mod, tmp = generator
    gaps = {"gaps": [{"type": "low_accuracy", "severity": "high", "accuracy": 0.3}]}
    result = gen.generate_tree("test_pred", gaps)
    assert result  # filepath returned
    assert Path(result).exists()


def test_generate_tree_with_base_tree(generator):
    """Tree generation with base tree should work."""
    gen, mod, tmp = generator
    base = "⟦ base | TREE-v1 | vsm-1.2 | 2026-08-30T00:00:00Z ⟧\n@vsm 1.2\n@status active\n"
    gaps = {"gaps": [{"type": "threshold_low_accuracy", "severity": "high", "accuracy": 0.4}]}
    result = gen.generate_tree("test_pred", gaps, base_tree=base)
    assert result
    assert Path(result).exists()


def test_generate_tree_no_gaps(generator):
    """No gaps should still generate a basic tree."""
    gen, mod, tmp = generator
    gaps = {"gaps": []}
    result = gen.generate_tree("test_pred", gaps)
    assert result


# ── _analyze_gaps ───────────────────────────────────────────────────────

def test_analyze_gaps_low_accuracy(generator):
    """Low accuracy gap should suggest threshold adjustment."""
    gen, mod, tmp = generator
    gaps = {"gaps": [{"type": "low_accuracy", "accuracy": 0.3, "severity": "high"}]}
    mods = gen._analyze_gaps(gaps)
    assert len(mods) > 0
    assert any(m["type"] == "adjust_threshold" for m in mods)


def test_analyze_gaps_insufficient_thresholds(generator):
    """Insufficient thresholds should suggest adding branches."""
    gen, mod, tmp = generator
    gaps = {"gaps": [{"type": "insufficient_thresholds", "tested": 1}]}
    mods = gen._analyze_gaps(gaps)
    assert len(mods) > 0


def test_analyze_gaps_empty(generator):
    """Empty gaps should return empty modifications."""
    gen, mod, tmp = generator
    mods = gen._analyze_gaps({"gaps": []})
    assert mods == []


# ── _create_branch ──────────────────────────────────────────────────────

def test_create_branch(generator):
    """Branch creation should return valid VSM content."""
    gen, mod, tmp = generator
    mod = {"type": "adjust_threshold", "threshold": 0.8, "reason": "test"}
    branch = gen._create_branch(mod, 0)
    assert "adjustment" in branch.lower() or "threshold" in branch.lower()


# ── _load/_save_manifest ───────────────────────────────────────────────

def test_manifest_roundtrip(generator):
    """Manifest save/load should work."""
    gen, mod, tmp = generator
    manifest = {"trees": [{"name": "test_tree", "path": "/tmp/test.tree.vsm"}]}
    gen._save_manifest(manifest)
    loaded = gen._load_manifest()
    assert "trees" in loaded
    assert loaded["trees"][0]["name"] == "test_tree"


# ── Adversarial ─────────────────────────────────────────────────────────

def test_generate_tree_empty_gaps_dict(generator):
    """Empty gaps dict should not crash."""
    gen, mod, tmp = generator
    result = gen.generate_tree("test_pred", {})
    assert result


def test_generate_tree_many_gaps(generator):
    """Many gaps should not crash."""
    gen, mod, tmp = generator
    gaps = {"gaps": [{"type": "low_accuracy", "accuracy": 0.1, "severity": "high"} for _ in range(20)]}
    result = gen.generate_tree("test_pred", gaps)
    assert result
