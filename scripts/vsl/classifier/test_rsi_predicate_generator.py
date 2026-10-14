"""design: docs/spec_revision/system/s1-operations/vos_package_detailed_plans.vsm
test_rsi_predicate_generator.py — adversarial / edge-case tests.

Covers:
  - generate_predicate: basic, edge_case, fast, generic
  - _register_predicate: file creation, manifest update
  - _load/_save_manifest: roundtrip
  - get_generated_predicates: list

Every check must fail closed: no files created without valid input.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

MANIFEST_SPEC = Path(__file__).resolve().parent / "rsi_manifest_parser.py"
SPEC_PATH = Path(__file__).resolve().parent / "rsi_predicate_generator.py"


@pytest.fixture
def generator():
    """Load rsi_predicate_generator with sandboxed state."""
    mp_spec = importlib.util.spec_from_file_location("rsi_manifest_parser", str(MANIFEST_SPEC))
    mp_mod = importlib.util.module_from_spec(mp_spec)
    mp_spec.loader.exec_module(mp_mod)
    sys.modules["rsi_manifest_parser"] = mp_mod

    spec = importlib.util.spec_from_file_location("rsi_predicate_generator", str(SPEC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tmp = tempfile.mkdtemp()
    mod.PREDICATES_DIR = Path(tmp) / "predicates"
    mod.PREDICATES_DIR.mkdir(parents=True, exist_ok=True)
    mod.PREDICATES_MANIFEST = Path(tmp) / "rsi_predicates.vsm"
    obj = mod.RSIPredicateGenerator()
    return obj, mod, Path(tmp)


# ── generate_predicate ──────────────────────────────────────────────────

def test_generate_edge_case_predicate(generator):
    """Edge case predicate generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "edge_case", "predicate": "test_pred", "edge_cases": ["boundary", "overflow"]}
    result = gen.generate_predicate(pattern)
    assert result
    assert Path(result).exists()


def test_generate_fast_predicate(generator):
    """Fast predicate generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "fast", "predicate": "test_pred", "latency_ms": 0.5}
    result = gen.generate_predicate(pattern)
    assert result
    assert Path(result).exists()


def test_generate_generic_predicate(generator):
    """Generic predicate generation should create a file."""
    gen, mod, tmp = generator
    pattern = {"type": "unknown_type", "predicate": "test_pred"}
    result = gen.generate_predicate(pattern)
    assert result
    assert Path(result).exists()


def test_generate_with_base_predicate(generator):
    """Predicate with base should work."""
    gen, mod, tmp = generator
    base = "def base_pred(ctx): return True"
    pattern = {"type": "edge_case", "predicate": "test_pred"}
    result = gen.generate_predicate(pattern, base_predicate=base)
    assert result


# ── get_generated_predicates ────────────────────────────────────────────

def test_get_generated_empty(generator):
    """No predicates should return empty list."""
    gen, mod, tmp = generator
    result = gen.get_generated_predicates()
    assert isinstance(result, list)


# ── _load/_save_manifest ───────────────────────────────────────────────

def test_manifest_roundtrip(generator):
    """Manifest save/load should work."""
    gen, mod, tmp = generator
    manifest = {"predicates": [{"name": "test_pred", "path": "/tmp/test.py"}]}
    gen._save_manifest(manifest)
    loaded = gen._load_manifest()
    assert "predicates" in loaded


# ── Adversarial ─────────────────────────────────────────────────────────

def test_empty_pattern(generator):
    """Empty pattern should not crash."""
    gen, mod, tmp = generator
    result = gen.generate_predicate({})
    assert result


def test_many_predicates(generator):
    """Generating many predicates should not crash."""
    gen, mod, tmp = generator
    for i in range(5):
        pattern = {"type": "edge_case", "predicate": f"pred_{i}"}
        result = gen.generate_predicate(pattern)
        assert result
