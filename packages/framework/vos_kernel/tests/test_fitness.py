"""Tests for vos_kernel.fitness — multidimensional fitness (D-06 FASE C / C1).

Every numeric expectation here is HAND-COMPUTED and asserted with `==`
(no approx): the declared weights are binary-exact (0.5 / 0.25 / 0.25)
so dyadic inputs produce exact floats — that exactness is part of the
contract (R10), not an accident.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from vos_kernel import fitness as F


class TestDeclaredWeights:
    def test_weights_exact_values(self):
        """The declaration itself, exact — C1 evidence to cite."""
        assert F.FITNESS_WEIGHTS == {
            "accuracy": 0.5, "coverage": 0.25, "simplicity": 0.25,
        }

    def test_weights_sum_to_one_exactly(self):
        """Binary-exact weights: no float fuzz, composite stays in [0,1]."""
        assert sum(F.FITNESS_WEIGHTS.values()) == 1.0

    def test_dimensions_order(self):
        assert F.DIMENSIONS == ("accuracy", "coverage", "simplicity")

    def test_module_imports_no_entropy_or_clock(self):
        """R10: the predicate must not pull in randomness or the clock."""
        tree = ast.parse(inspect.getsource(F))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert roots == {"__future__", "typing"}


class TestCompositeFitness:
    def test_hand_computed_composite(self):
        """0.75*0.5 + 0.5*0.25 + 0.25*0.25 = 0.375 + 0.125 + 0.0625 = 0.5625."""
        scores = F.fitness_scores(accuracy=0.75, coverage=0.5, simplicity=0.25)
        assert scores == {"accuracy": 0.75, "coverage": 0.5, "simplicity": 0.25}
        assert F.composite_fitness(scores) == 0.5625

    def test_negative_control_accuracy_changes_composite(self):
        """Same coverage/simplicity, worse accuracy -> strictly different
        composite (0.3125 != 0.5625): the aggregation actually weighs
        accuracy rather than ignoring it."""
        good = F.composite_fitness(
            F.fitness_scores(accuracy=0.75, coverage=0.5, simplicity=0.25))
        bad = F.composite_fitness(
            F.fitness_scores(accuracy=0.25, coverage=0.5, simplicity=0.25))
        assert bad == 0.3125
        assert good - bad == 0.25  # delta = weight(accuracy) * 0.5

    def test_bounds(self):
        assert F.composite_fitness(F.fitness_scores(
            accuracy=1.0, coverage=1.0, simplicity=1.0)) == 1.0
        assert F.composite_fitness(F.fitness_scores(
            accuracy=0.0, coverage=0.0, simplicity=0.0)) == 0.0

    def test_deterministic_repeated_calls(self):
        scores = F.fitness_scores(accuracy=0.5, coverage=0.5, simplicity=0.5)
        assert [F.composite_fitness(scores) for _ in range(5)] == [0.5] * 5

    def test_int_inputs_accepted(self):
        assert F.composite_fitness({"accuracy": 1, "coverage": 0, "simplicity": 0}) == 0.5


class TestMissingDimension:
    def test_fitness_scores_omitted_dimension_raises(self):
        with pytest.raises(F.MissingDimensionError, match="simplicity"):
            F.fitness_scores(accuracy=0.5, coverage=0.5)

    def test_fitness_scores_none_dimension_raises(self):
        with pytest.raises(F.MissingDimensionError, match="coverage"):
            F.fitness_scores(accuracy=0.5, coverage=None, simplicity=0.5)

    def test_composite_missing_key_raises(self):
        with pytest.raises(F.MissingDimensionError, match="simplicity"):
            F.composite_fitness({"accuracy": 0.5, "coverage": 0.5})

    def test_composite_unknown_extra_raises(self):
        """A typo'd dimension must not silently carry weight 0."""
        with pytest.raises(ValueError, match="unknown dimension.*diversity"):
            F.composite_fitness({"accuracy": 0.5, "coverage": 0.5,
                                 "simplicity": 0.5, "diversity": 0.1})

    @pytest.mark.parametrize("dim,value", [
        ("accuracy", -0.1), ("coverage", 1.5), ("simplicity", 2.0),
    ])
    def test_out_of_range_raises(self, dim, value):
        args = {"accuracy": 0.5, "coverage": 0.5, "simplicity": 0.5}
        args[dim] = value
        with pytest.raises(ValueError, match="out of \\[0, 1\\]"):
            F.fitness_scores(**args)


class TestScoresFromCounts:
    def test_hand_computed_counts(self):
        """correct=6, answered=8, total=16, complexity=4
        -> accuracy 0.75, coverage 0.5, simplicity 0.25 -> 0.5625."""
        scores = F.scores_from_counts(correct=6, answered=8, total=16,
                                      complexity=4)
        assert scores == {"accuracy": 0.75, "coverage": 0.5, "simplicity": 0.25}
        assert F.composite_fitness(scores) == 0.5625

    def test_zero_answered_is_loud(self):
        """No answered cases is not accuracy 0 — it is a measurement gap."""
        with pytest.raises(ValueError, match="answered must be > 0"):
            F.scores_from_counts(correct=0, answered=0, total=10, complexity=2)

    @pytest.mark.parametrize("kwargs,match", [
        (dict(correct=1, answered=10, total=5, complexity=2), "exceed total"),
        (dict(correct=11, answered=10, total=10, complexity=2), "within"),
        (dict(correct=0, answered=1, total=1, complexity=0), "complexity"),
        (dict(correct=0, answered=1, total=0, complexity=1), "total must be > 0"),
    ])
    def test_invalid_counts_loud(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            F.scores_from_counts(**kwargs)
