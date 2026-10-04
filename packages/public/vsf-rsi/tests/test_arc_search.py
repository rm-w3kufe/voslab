"""Tests for arc_search: fitness, random baseline, GA mechanics."""
from vsf_rsi.arc_search import (
    _crossover,
    _mutate,
    fitness,
    ga_search,
    random_program,
    random_search,
)
from vsf_rsi.arc_dsl import apply
import random


def _pairs():
    # flip_h task, 2 train pairs
    return [
        {"input": [[1, 2], [3, 4]], "output": [[2, 1], [4, 3]]},
        {"input": [[5, 6], [7, 8]], "output": [[6, 5], [8, 7]]},
    ]


def test_fitness_exact_and_tiebreak():
    pairs = _pairs()
    assert fitness([("flip_h", [])], pairs) == (2, -1)
    assert fitness([("flip_h", []), ("identity", [])], pairs) == (2, -2)
    assert fitness([("rot90", [])], pairs)[0] == 0


def test_random_program_valid():
    rng = random.Random(0)
    for _ in range(50):
        p = random_program(rng)
        assert 1 <= len(p) <= 3
        apply(p, [[1]])  # never raises


def test_random_search_finds_flip():
    best, f = random_search(_pairs(), budget=400, seed=1)
    assert f[0] == 2, best


def test_mutate_crossover_valid():
    rng = random.Random(0)
    p1 = [("flip_h", []), ("recolor", [1, 2])]
    p2 = [("rot90", [])]
    for _ in range(50):
        m = _mutate(rng, p1)
        assert 1 <= len(m) <= 3
        apply(m, [[1, 2]])
        c = _crossover(rng, p1, p2)
        assert 1 <= len(c) <= 3
        apply(c, [[1, 2]])


def test_ga_beats_or_ties_random():
    pairs = _pairs()
    _, fr = random_search(pairs, budget=144, seed=7)
    _, fg = ga_search(pairs, pop_size=24, generations=6, seed=7)
    assert fg >= fr  # same eval budget (24*6=144): evolution must not lose
    assert fg[0] == 2
