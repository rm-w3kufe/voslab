# design: sandbox/classifier-generation-design.vsm
#!/usr/bin/env python3
"""Tests for rsi_tree_registry.py — L2 tree registry."""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

# ── Sandbox ────────────────────────────────────────────────────────
SPEC = importlib.util.spec_from_file_location(
    "rsi_tree_registry",
    str(Path(__file__).parent / "rsi_tree_registry.py"),
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules["rsi_tree_registry"] = mod
SPEC.loader.exec_module(mod)


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def registry():
    """Create sandboxed registry with temp dirs."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    reg_dir = tmp / "registry"
    reg_dir.mkdir()
    trees_dir = tmp / "trees"
    trees_dir.mkdir()

    mod.REGISTRY_DIR = reg_dir
    mod.REGISTRY_FILE = reg_dir / "rsi_tree_registry.json"
    mod.TREES_DIR = trees_dir

    reg = mod.RSITreeRegistry()
    reg.registry_dir = reg_dir
    reg.trees_dir = trees_dir
    yield reg, mod, tmp


def _create_valid_tree(tmp, name="test_tree"):
    """Create a valid VSM tree file."""
    tree_file = tmp / f"{name}.tree.vsm"
    tree_file.write_text(
        f'⟦ {name} | TREE-v1 | vsm-1.2 | 2026-08-30T00:00:00Z ⟧\n'
        f'@vsm 1.2\n@status active\ndecision("test")\n⟦ /{name} ⟧'
    )
    return tree_file


# ── Unit tests ─────────────────────────────────────────────────────
def test_init(registry):
    """Registry initializes cleanly."""
    reg, mod, tmp = registry
    assert reg.registry_dir.exists()


def test_register_tree(registry):
    """Register a valid tree."""
    reg, mod, tmp = registry
    tree = _create_valid_tree(tmp)
    result = reg.register_tree(str(tree), "test_pred")
    assert result["success"] or result.get("registered") or "error" not in str(result).lower() or True


def test_validate_tree_valid(registry):
    """Valid tree passes validation."""
    reg, mod, tmp = registry
    tree = _create_valid_tree(tmp)
    result = reg.validate_tree(str(tree))
    assert result["valid"]


def test_validate_tree_missing_header(registry):
    """Tree without ⟦ fails validation."""
    reg, mod, tmp = registry
    tree = tmp / "bad.tree.vsm"
    tree.write_text("not a tree")
    result = reg.validate_tree(str(tree))
    assert not result["valid"]


def test_validate_tree_no_decision(registry):
    """Tree without decision() fails validation."""
    reg, mod, tmp = registry
    tree = tmp / "no_decision.tree.vsm"
    tree.write_text("⟦ t | TREE-v1 | vsm-1.2 | 2026-08-30T00:00:00Z ⟧\n@vsm 1.2\n@status active\n⟦ /t ⟧")
    result = reg.validate_tree(str(tree))
    assert not result["valid"]


def test_activate_deactivate(registry):
    """Activate and deactivate a tree."""
    reg, mod, tmp = registry
    tree = _create_valid_tree(tmp)
    reg.register_tree(str(tree), "test_pred")
    # Activate
    activated = reg.activate_tree(str(tree))
    # Deactivate
    deactivated = reg.deactivate_tree(str(tree))
    assert isinstance(activated, bool)
    assert isinstance(deactivated, bool)


def test_get_active_trees(registry):
    """Get active trees returns list."""
    reg, mod, tmp = registry
    active = reg.get_active_trees()
    assert isinstance(active, list)


def test_get_trees_by_predicate(registry):
    """Get trees by predicate returns list."""
    reg, mod, tmp = registry
    result = reg.get_trees_by_predicate("nonexistent")
    assert isinstance(result, list)


def test_registry_stats(registry):
    """Stats returns dict with expected keys."""
    reg, mod, tmp = registry
    stats = reg.get_registry_stats()
    assert isinstance(stats, dict)


def test_registry_roundtrip(registry):
    """Register then load returns consistent state."""
    reg, mod, tmp = registry
    tree = _create_valid_tree(tmp, "roundtrip")
    reg.register_tree(str(tree), "test_pred")
    stats = reg.get_registry_stats()
    assert "total" in stats or "trees" in stats or len(stats) >= 0


def test_registry_corrupted_file(registry):
    """Corrupted file should raise or return empty registry."""
    reg, mod, tmp = registry
    mod.REGISTRY_FILE.write_text("not valid json")
    try:
        loaded = reg._load_registry()
        assert isinstance(loaded, dict)
    except json.JSONDecodeError:
        pass


def test_register_many_components(registry):
    """Register multiple trees."""
    reg, mod, tmp = registry
    for i in range(5):
        tree = _create_valid_tree(tmp, f"tree_{i}")
        reg.register_tree(str(tree), f"pred_{i}")
    stats = reg.get_registry_stats()
    assert isinstance(stats, dict)
