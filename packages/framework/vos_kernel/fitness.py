"""fitness.py — multidimensional evolution fitness (debt D-06 FASE C, C1).

ONE deterministic aggregation of the three declared fitness dimensions:

    accuracy   correct / answered          (how right when it speaks)
    coverage   answered / total            (how much of the input it dares answer)
    simplicity 1 / complexity              (parsimony penalty, smaller is fitter)

composite = FITNESS_WEIGHTS[accuracy]*accuracy
          + FITNESS_WEIGHTS[coverage]*coverage
          + FITNESS_WEIGHTS[simplicity]*simplicity

Why these weights (declared, not buried — D-06 C2-style declaration rule):
accuracy is the primary objective (half the vote); coverage and simplicity
are the two regularizers, weighted equally at half of accuracy each. The
three weights sum to exactly 1.0, and all three are binary-exact floats
(0.5 / 0.25 / 0.25), so the composite of any dyadic-rational inputs is an
EXACT float — no epsilon needed in predicates (R10: same input, same
output, no randomness, no clock).

Missing-dimension policy (explicit, no silent defaults): any absent or
None dimension raises MissingDimensionError; unknown extra dimensions in
composite_fitness() raise ValueError (a typo must not silently carry a
weight of 0).
"""

from __future__ import annotations

from typing import Mapping

#: Declared dimension weights — the ONLY place these numbers live.
#: Callers must reference this constant, never restate the literals.
FITNESS_WEIGHTS: dict[str, float] = {
    "accuracy": 0.5,
    "coverage": 0.25,
    "simplicity": 0.25,
}

#: Declared dimension set, in canonical order.
DIMENSIONS: tuple[str, ...] = ("accuracy", "coverage", "simplicity")


class MissingDimensionError(ValueError):
    """A declared fitness dimension was absent — fail loud, never default."""


def _dimension(name: str, value: float | None) -> float:
    if value is None:
        raise MissingDimensionError(f"missing dimension: {name}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"dimension {name} must be a number, got {type(value).__name__}")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"dimension {name} out of [0, 1]: {value}")
    return value


def fitness_scores(*, accuracy: float | None = None,
                   coverage: float | None = None,
                   simplicity: float | None = None) -> dict[str, float]:
    """Validate and return the three fitness dimensions as a plain dict.

    Every declared dimension must be present and inside [0, 1]; anything
    else raises (MissingDimensionError / ValueError / TypeError) — there
    is no default value for a dimension nobody measured.
    """
    return {
        "accuracy": _dimension("accuracy", accuracy),
        "coverage": _dimension("coverage", coverage),
        "simplicity": _dimension("simplicity", simplicity),
    }


def composite_fitness(scores: Mapping[str, float]) -> float:
    """Weighted sum of the declared dimensions using FITNESS_WEIGHTS.

    Exact and deterministic: weights and inputs are floats, the sum order
    follows DIMENSIONS (fixed), so the same scores always yield bit-equal
    results.
    """
    unknown = sorted(set(scores) - set(DIMENSIONS))
    if unknown:
        raise ValueError(f"unknown dimension(s): {', '.join(unknown)}")
    missing = [d for d in DIMENSIONS if d not in scores]
    if missing:
        raise MissingDimensionError(f"missing dimension(s): {', '.join(missing)}")
    total = 0.0
    for dim in DIMENSIONS:
        total += _dimension(dim, scores[dim]) * FITNESS_WEIGHTS[dim]
    return total


def scores_from_counts(*, correct: int, answered: int, total: int,
                       complexity: int) -> dict[str, float]:
    """Derive the three dimensions from raw evaluation counts (the inputs
    every existing scorer already produces):

        accuracy   = correct / answered   (answered > 0)
        coverage   = answered / total     (total > 0)
        simplicity = 1 / complexity       (complexity >= 1)

    Hand-computable, integer-in / float-out, and every failure mode is a
    loud ValueError rather than a silent 0.0.
    """
    for name, value in (("correct", correct), ("answered", answered),
                        ("total", total), ("complexity", complexity)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if total <= 0:
        raise ValueError(f"total must be > 0, got {total}")
    if answered <= 0:
        raise ValueError(f"answered must be > 0, got {answered}")
    if answered > total:
        raise ValueError(f"answered ({answered}) cannot exceed total ({total})")
    if correct < 0 or correct > answered:
        raise ValueError(f"correct ({correct}) must be within [0, {answered}]")
    if complexity < 1:
        raise ValueError(f"complexity must be >= 1, got {complexity}")
    return fitness_scores(
        accuracy=correct / answered,
        coverage=answered / total,
        simplicity=1.0 / complexity,
    )
