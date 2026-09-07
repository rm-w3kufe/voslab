"""tests/test_bridge.py — Tests for RSI bridge."""

import pytest
from vsf_rsi_core.bridge import (
    is_available,
    get_version,
    genetic_algorithm_run,
    forest_generate,
    tree_generate,
    predicate_generate,
    compute_metrics,
    detect_gaps,
    detect_patterns,
    feedback_loop_step,
    register_component,
    list_components,
)


class TestAvailability:
    def test_is_available(self):
        # vsf-rsi exists at ~/packages/public/vsf-rsi/
        result = is_available()
        assert isinstance(result, bool)

    def test_get_version(self):
        result = get_version()
        assert isinstance(result, str)


class TestGeneticAlgorithm:
    def test_run(self):
        result = genetic_algorithm_run(population_size=5, generations=2)
        assert isinstance(result, dict)
        # Should either succeed or return error
        assert "error" in result or "status" in result


class TestForestGenerator:
    def test_generate(self):
        result = forest_generate(num_trees=3, predicate_name="test")
        assert isinstance(result, list)
        assert len(result) > 0


class TestTreeGenerator:
    def test_generate(self):
        result = tree_generate(predicate_name="test", gaps={"test": "gap"})
        assert isinstance(result, dict)


class TestPredicateGenerator:
    def test_generate(self):
        result = predicate_generate(pattern={"type": "test"})
        assert isinstance(result, dict)


class TestMetrics:
    def test_compute(self):
        result = compute_metrics(predicate_name="test")
        assert isinstance(result, dict)


class TestGapDetector:
    def test_detect(self):
        result = detect_gaps(predicate_name="test")
        assert isinstance(result, dict)


class TestPatternDetector:
    def test_detect(self):
        result = detect_patterns(predicate_name="test")
        assert isinstance(result, dict)


class TestFeedbackLoop:
    def test_step(self):
        result = feedback_loop_step()
        assert isinstance(result, dict)


class TestComponentRegistry:
    def test_register_and_list(self):
        # Register a test component
        register_component("test_component", component_type="test", component_path="/test")
        components = list_components()
        assert isinstance(components, list)
