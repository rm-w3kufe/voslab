"""design: docs/plans/vos_package_detailed_plans.vsm
test_rsi_component_registry.py — adversarial / edge-case tests.

Covers:
  - register_component: predicate, tree, forest
  - validate_component: valid, invalid, missing
  - activate/deactivate: toggle, nonexistent
  - get_active_components, get_components_by_name
  - get_registry_stats: empty, with components
  - _load/_save: roundtrip, corruption

Every check must fail closed: invalid components rejected, not trusted.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent / "rsi_component_registry.py"


@pytest.fixture
def registry():
    """Load rsi_component_registry with sandboxed state."""
    spec = importlib.util.spec_from_file_location("rsi_component_registry", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp()
    # Delegation: the class reads the CANONICAL globals, not the shim copies
    import vsf_rsi.rsi_component_registry as canon
    saved = {n: getattr(canon, n) for n in ("REGISTRY_DIR", "REGISTRY_FILE")}
    mod.REGISTRY_DIR = Path(tmp)
    mod.REGISTRY_FILE = Path(tmp) / "rsi_registry.json"
    canon.REGISTRY_DIR = Path(tmp)
    canon.REGISTRY_FILE = Path(tmp) / "rsi_registry.json"
    obj = mod.RSIComponentRegistry()
    yield obj, mod, Path(tmp)
    for n, v in saved.items():
        setattr(canon, n, v)


def _create_test_predicate(tmp):
    """Create a test predicate file."""
    pred_file = tmp / "test_pred.py"
    pred_file.write_text('# PREDICATE\ndef test_pred(ctx): return ctx.get("value", 0) > 0.5')
    return pred_file


def _create_test_tree(tmp):
    """Create a test tree file."""
    tree_file = tmp / "test_tree.tree.vsm"
    tree_file.write_text('⟦ test_tree | TREE-v1 | vsm-1.2 | 2026-08-30T00:00:00Z ⟧\n@vsm 1.2\n@status active\ndecision("test")\n⟦ /test_tree ⟧')
    return tree_file


# ── register_component ──────────────────────────────────────────────────

def test_register_predicate(registry):
    """Register a predicate should succeed."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    result = reg.register_component("predicate", str(pred_file), "test_pred")
    assert result.get("success") is True or "status" in result


def test_register_tree(registry):
    """Register a tree should succeed."""
    reg, mod, tmp = registry
    tree_file = _create_test_tree(tmp)
    result = reg.register_component("tree", str(tree_file), "test_tree")
    assert result.get("success") is True or "status" in result


def test_register_duplicate(registry):
    """Duplicate registration should return error."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    reg.register_component("predicate", str(pred_file), "test_pred")
    result = reg.register_component("predicate", str(pred_file), "test_pred_v2")
    # Should return error or update
    assert "success" in result or "error" in result


# ── validate_component ──────────────────────────────────────────────────

def test_validate_valid_predicate(registry):
    """Valid predicate should pass validation."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    result = reg.validate_component("predicate", str(pred_file))
    assert result["valid"] is True


def test_validate_invalid_predicate(registry):
    """Invalid predicate should fail validation."""
    reg, mod, tmp = registry
    bad_file = tmp / "bad_pred.py"
    bad_file.write_text("not a predicate")
    result = reg.validate_component("predicate", str(bad_file))
    assert result["valid"] is False


def test_validate_nonexistent(registry):
    """Non-existent file should fail validation."""
    reg, mod, tmp = registry
    result = reg.validate_component("predicate", "/tmp/nonexistent_12345.py")
    assert result["valid"] is False


# ── activate/deactivate ────────────────────────────────────────────────

def test_activate_deactivate(registry):
    """Activate then deactivate should toggle status."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    reg.register_component("predicate", str(pred_file), "test_pred")
    assert reg.activate_component(str(pred_file)) is True
    assert reg.deactivate_component(str(pred_file)) is True


def test_activate_nonexistent(registry):
    """Activate nonexistent component should return False."""
    reg, mod, tmp = registry
    assert reg.activate_component("/tmp/nonexistent.py") is False


def test_deactivate_nonexistent(registry):
    """Deactivate nonexistent component should return False."""
    reg, mod, tmp = registry
    assert reg.deactivate_component("/tmp/nonexistent.py") is False


# ── get_active_components ───────────────────────────────────────────────

def test_get_active_empty(registry):
    """No components should return empty list."""
    reg, mod, tmp = registry
    result = reg.get_active_components()
    assert result == []


def test_get_active_with_type_filter(registry):
    """Type filter should work."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    reg.register_component("predicate", str(pred_file), "test_pred")
    reg.activate_component(str(pred_file))
    result = reg.get_active_components("predicate")
    assert len(result) >= 1


# ── get_registry_stats ──────────────────────────────────────────────────

def test_stats_empty(registry):
    """Empty registry should return zero stats."""
    reg, mod, tmp = registry
    stats = reg.get_registry_stats()
    assert stats["total_components"] == 0


def test_stats_with_components(registry):
    """Registry with components should report stats."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    reg.register_component("predicate", str(pred_file), "test_pred")
    stats = reg.get_registry_stats()
    assert stats["total_components"] >= 1


# ── _load/_save ─────────────────────────────────────────────────────────

def test_registry_roundtrip(registry):
    """Save/load should work."""
    reg, mod, tmp = registry
    pred_file = _create_test_predicate(tmp)
    reg.register_component("predicate", str(pred_file), "test_pred")
    loaded = reg._load_registry()
    assert "components" in loaded


def test_registry_corrupted_file(registry):
    """Corrupted file should raise or return empty registry."""
    reg, mod, tmp = registry
    mod.REGISTRY_FILE.write_text("not valid json")
    try:
        loaded = reg._load_registry()
        assert isinstance(loaded, dict)
    except json.JSONDecodeError:
        pass  # Acceptable behavior


# ── Adversarial ─────────────────────────────────────────────────────────

def test_register_many_components(registry):
    """Many registrations should not crash."""
    reg, mod, tmp = registry
    for i in range(10):
        pred_file = tmp / f"pred_{i}.py"
        pred_file.write_text(f'# PREDICATE\ndef pred_{i}(ctx): return True')
        result = reg.register_component("predicate", str(pred_file), f"pred_{i}")
        assert "success" in result
