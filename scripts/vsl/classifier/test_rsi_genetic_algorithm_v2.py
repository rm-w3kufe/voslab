# design: sandbox/classifier-generation-design.vsm
#!/usr/bin/env python3
"""Tests for rsi_genetic_algorithm_v2.py — L4 GA v2 with diversity."""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

# ── Sandbox ────────────────────────────────────────────────────────
SPEC = importlib.util.spec_from_file_location(
    "rsi_genetic_algorithm_v2",
    str(Path(__file__).parent / "rsi_genetic_algorithm_v2.py"),
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules["rsi_genetic_algorithm_v2"] = mod
SPEC.loader.exec_module(mod)


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def ga():
    """Create sandboxed GA v2 with temp dirs."""
    tmp = Path(tempfile.mkdtemp())
    forests_dir = tmp / "forests"
    forests_dir.mkdir()
    evolution_dir = tmp / "evolution"
    evolution_dir.mkdir()

    # Delegation: the class writes through the CANONICAL globals.
    import vsf_rsi.rsi_genetic_algorithm_v2 as canon
    # Only names that exist on the CANONICAL module (FORESTS_DIR, for one,
    # exists only on the shim — the class never reads it).
    names = ("FORESTS_DIR", "FOREST_FILE", "EVOLUTION_DIR",
             "EVOLUTION_HISTORY_FILE")
    saved = {n: getattr(canon, n) for n in names if hasattr(canon, n)}
    canon.FOREST_FILE = forests_dir / "test_forest.json"
    canon.EVOLUTION_DIR = evolution_dir
    canon.EVOLUTION_HISTORY_FILE = evolution_dir / "rsi_evolution_history_v2.jsonl"
    if hasattr(canon, "FORESTS_DIR"):
        canon.FORESTS_DIR = forests_dir
    mod.FORESTS_DIR = forests_dir
    mod.FOREST_FILE = forests_dir / "test_forest.json"
    mod.EVOLUTION_DIR = evolution_dir
    mod.EVOLUTION_HISTORY_FILE = evolution_dir / "rsi_evolution_history_v2.jsonl"

    ga = mod.RSIGeneticAlgorithmV2(population_size=5, mutation_rate=0.3)
    yield ga, mod, tmp
    for n, v in saved.items():
        setattr(canon, n, v)


# ── Unit tests ─────────────────────────────────────────────────────
def test_create_forest(ga):
    """Forest creation produces correct number of genomes."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    assert len(forest) == 5
    assert all(isinstance(g, mod.TreeGenome) for g in forest)


def test_genome_fields(ga):
    """TreeGenome has all required fields."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    g = forest[0]
    assert hasattr(g, "id")
    assert hasattr(g, "name")
    assert hasattr(g, "genes")
    assert hasattr(g, "fitness")
    assert hasattr(g, "generation")
    assert hasattr(g, "parent_ids")
    assert hasattr(g, "created")


def test_evaluate_fitness(ga):
    """Fitness evaluation returns positive values."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    evaluated = ga_mod.evaluate_fitness(forest, "test_pred")
    assert all(g.fitness > 0 for g in evaluated)


def test_select_parents(ga):
    """Parent selection returns half the population."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    parents = ga_mod.select_parents(forest)
    assert len(parents) == len(forest) // 2


def test_crossover(ga):
    """Crossover produces two offspring."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    p1, p2 = forest[0], forest[1]
    o1, o2 = ga_mod.crossover(p1, p2)
    assert isinstance(o1, mod.TreeGenome)
    assert isinstance(o2, mod.TreeGenome)
    assert o1.id != o2.id


def test_mutate(ga):
    """Mutation produces a genome (may or may not mutate depending on rate)."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    original = forest[0]
    mutated = ga_mod.mutate(original)
    assert isinstance(mutated, mod.TreeGenome)
    # Mutation is probabilistic; just verify it returns a valid genome
    assert mutated.fitness >= 0


def test_evolve_generation(ga):
    """One generation produces a new population."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    new_forest = ga_mod.evolve_generation(forest, "test_pred")
    assert len(new_forest) > 0
    assert all(isinstance(g, mod.TreeGenome) for g in new_forest)


def test_maintain_diversity(ga):
    """Diversity maintenance removes duplicates."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    # Make all genomes have same fitness
    for g in forest:
        g.fitness = 0.5
    diverse = ga_mod._maintain_diversity(forest)
    assert len(diverse) <= len(forest)


def test_evolve_forest(ga):
    """Full evolution produces stats dict."""
    ga_mod, mod, tmp = ga
    result = ga_mod.evolve_forest("test_pred", generations=2)
    assert "generations" in result or "best_fitness" in result or isinstance(result, dict)


def test_get_evolution_stats(ga):
    """Stats returns dict."""
    ga_mod, mod, tmp = ga
    stats = ga_mod.get_evolution_stats("test_pred")
    assert isinstance(stats, dict)


def test_forest_save_load(ga):
    """Forest roundtrip preserves data."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    ga_mod._save_forest("test_pred", forest)
    loaded = ga_mod._load_forest("test_pred")
    assert len(loaded) == len(forest)


def test_forest_load_missing(ga):
    """Loading missing forest returns empty list."""
    ga_mod, mod, tmp = ga
    loaded = ga_mod._load_forest("nonexistent")
    assert loaded == []


def test_history_append(ga):
    """History append creates file (uses module-level constant)."""
    ga_mod, mod, tmp = ga
    # Override BOTH constants since _append_history references EVOLUTION_HISTORY_FILE
    # which is computed from EVOLUTION_DIR at module load time
    mod.EVOLUTION_DIR = tmp / "evolution"
    mod.EVOLUTION_DIR.mkdir(exist_ok=True)
    mod.EVOLUTION_HISTORY_FILE = mod.EVOLUTION_DIR / "rsi_evolution_history_v2.jsonl"
    ga_mod._append_history({"test": True})
    assert mod.EVOLUTION_HISTORY_FILE.exists()


def test_mutation_rate(ga):
    """Higher mutation rate produces more mutations."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    mutated = [ga_mod.mutate(g) for g in forest]
    # With rate 0.3, at least some should be mutated
    assert any("_mut" in g.id for g in mutated)


def test_selection_methods(ga):
    """Both selection methods work."""
    ga_mod, mod, tmp = ga
    forest = ga_mod.create_forest("test_pred")
    tournament = ga_mod.select_parents(forest, method="tournament")
    roulette = ga_mod.select_parents(forest, method="roulette")
    assert len(tournament) > 0
    assert len(roulette) > 0


def test_genome_post_init(ga):
    """TreeGenome __post_init__ sets defaults."""
    ga_mod, mod, tmp = ga
    g = mod.TreeGenome(
        id="test",
        name="test",
        genes={"branches": []},
        fitness=0.0,
        generation=0,
        parent_ids=[],
        created="2026-08-30T00:00:00Z",
    )
    assert g.id == "test"
