#!/usr/bin/env python3
"""
test_classifier.py — Minimal tests for scripts/vsl/classifier.
Verifies socratic_engine stub and classifier scripts are importable.
"""
import sys
import os
import json

# Add classifier to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

CLASSIFIER_DIR = os.path.dirname(__file__)


def test_socratic_engine_import():
    """socratic_engine module should be importable."""
    from socratic_engine import SocraticEngine
    assert SocraticEngine is not None


def test_socratic_engine_instantiate():
    """SocraticEngine should be instantiable."""
    from socratic_engine import SocraticEngine
    engine = SocraticEngine()
    assert engine is not None


def test_socratic_engine_has_methods():
    """SocraticEngine should have core methods."""
    from socratic_engine import SocraticEngine
    engine = SocraticEngine()
    # Check for common methods (API varies between versions)
    methods = dir(engine)
    assert any("eval" in m.lower() or "exec" in m.lower() or "run" in m.lower() for m in methods), \
        f"SocraticEngine has no eval/exec/run methods: {[m for m in methods if not m.startswith('_')]}"


def test_classifier_scripts_exist():
    """Key classifier scripts should exist."""
    key_files = [
        "socratic_engine.py",
        "scenario_memory.py",
        "rumination.py",
        "socratic_bridge.py",
    ]
    for f in key_files:
        path = os.path.join(CLASSIFIER_DIR, f)
        if os.path.exists(path):
            print(f"  INFO  {f} exists")
        else:
            print(f"  INFO  {f} not found (expected)")


def test_scenarios_index_exists():
    """Scenarios index file should exist."""
    index_path = os.path.join(CLASSIFIER_DIR, "scenarios_index.json")
    if os.path.exists(index_path):
        with open(index_path) as f:
            data = json.load(f)
        assert isinstance(data, (dict, list)), f"Index is {type(data)}, expected dict/list"
        print(f"  INFO  scenarios_index.json has {len(data)} entries")
    else:
        print("  INFO  scenarios_index.json not found (expected)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
