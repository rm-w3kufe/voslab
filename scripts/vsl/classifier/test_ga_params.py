"""tests for D-06 FASE C2 — declared GA parameters (ga_config.GA_PARAMS).

Covers:
  - exact declared values (single source of truth)
  - call-time read: shims observe a monkeypatched GA_PARAMS
  - explicit constructor/evolve arguments always win over the declaration
  - no restated parameter literals in shim sources (drift guard)
  - drift test: GA_PARAMS mirrors inspect.signature of the canonical
    upstream defaults (fails if upstream moves without ga_config following)
"""
import importlib.util
import inspect
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ga_mod = _load("rsi_genetic_algorithm", HERE / "rsi_genetic_algorithm.py")
ga_mod_v2 = _load("rsi_genetic_algorithm_v2", HERE / "rsi_genetic_algorithm_v2.py")
ga_config = sys.modules["ga_config"]

EXPECTED = {
    "population_size": 10,
    "mutation_rate": 0.1,
    "mutation_rate_tuned": 0.2,
    "generation_window": 10,
    "patience_window": 3,
}


class TestDeclaration:
    def test_exact_values(self):
        assert dict(ga_config.GA_PARAMS) == EXPECTED

    def test_weights_keys_complete(self):
        assert set(ga_config.GA_PARAMS) == set(EXPECTED)


class TestCallTimeRead:
    def test_v1_constructor_reads_declaration(self, monkeypatch):
        monkeypatch.setitem(ga_config.GA_PARAMS, "population_size", 7)
        monkeypatch.setitem(ga_config.GA_PARAMS, "mutation_rate", 0.42)
        ga = ga_mod.RSIGeneticAlgorithm()
        assert ga.population_size == 7
        assert ga.mutation_rate == 0.42

    def test_v1_explicit_args_win(self, monkeypatch):
        monkeypatch.setitem(ga_config.GA_PARAMS, "population_size", 7)
        ga = ga_mod.RSIGeneticAlgorithm(population_size=3, mutation_rate=0.5)
        assert ga.population_size == 3
        assert ga.mutation_rate == 0.5

    def test_v2_constructor_reads_declaration(self, monkeypatch):
        monkeypatch.setitem(ga_config.GA_PARAMS, "population_size", 6)
        monkeypatch.setitem(ga_config.GA_PARAMS, "mutation_rate_tuned", 0.33)
        ga = ga_mod_v2.RSIGeneticAlgorithmV2()
        assert ga.population_size == 6
        assert ga.mutation_rate == 0.33

    def test_v2_ignores_v1_mutation_key(self, monkeypatch):
        monkeypatch.setitem(ga_config.GA_PARAMS, "mutation_rate", 0.9)
        monkeypatch.setitem(ga_config.GA_PARAMS, "mutation_rate_tuned", 0.2)
        ga = ga_mod_v2.RSIGeneticAlgorithmV2()
        assert ga.mutation_rate == 0.2

    @pytest.mark.parametrize(
        "mod,cls",
        [(ga_mod, "RSIGeneticAlgorithm"), (ga_mod_v2, "RSIGeneticAlgorithmV2")],
    )
    def test_evolve_forest_windows_from_declaration(
        self, monkeypatch, mod, cls
    ):
        seen = {}

        def recorder(self, predicate_name, generations=None, patience=None,
                     convergence_threshold=None, **kw):
            seen["generations"] = generations
            seen["patience"] = patience
            return {"recorded": True}

        monkeypatch.setattr(mod._mod.RSIGeneticAlgorithm
                            if cls == "RSIGeneticAlgorithm"
                            else mod._mod.RSIGeneticAlgorithmV2,
                            "evolve_forest", recorder)
        monkeypatch.setitem(ga_config.GA_PARAMS, "generation_window", 4)
        monkeypatch.setitem(ga_config.GA_PARAMS, "patience_window", 2)
        ga = getattr(mod, cls)()
        out = ga.evolve_forest("pred")
        assert out == {"recorded": True}
        assert seen == {"generations": 4, "patience": 2}

    @pytest.mark.parametrize(
        "mod,cls",
        [(ga_mod, "RSIGeneticAlgorithm"), (ga_mod_v2, "RSIGeneticAlgorithmV2")],
    )
    def test_evolve_forest_explicit_args_win(self, monkeypatch, mod, cls):
        seen = {}

        def recorder(self, predicate_name, generations=None, patience=None,
                     convergence_threshold=None, **kw):
            seen["generations"] = generations
            seen["patience"] = patience
            return {}

        monkeypatch.setattr(mod._mod.RSIGeneticAlgorithm
                            if cls == "RSIGeneticAlgorithm"
                            else mod._mod.RSIGeneticAlgorithmV2,
                            "evolve_forest", recorder)
        ga = getattr(mod, cls)()
        ga.evolve_forest("pred", generations=9, patience=8)
        assert seen == {"generations": 9, "patience": 8}


class TestNoRestatedLiterals:
    @pytest.mark.parametrize(
        "filename",
        ["rsi_genetic_algorithm.py", "rsi_genetic_algorithm_v2.py"],
    )
    def test_shims_have_no_numeric_parameter_literals(self, filename):
        source = (HERE / filename).read_text(encoding="utf-8")
        matches = re.findall(
            r"(population_size|mutation_rate|generations|patience)\s*[=:]\s*"
            r"(?<!None)\d+\.?\d*", source)
        assert matches == [], f"restated literals in {filename}: {matches}"


class TestDriftVsCanonical:
    """GA_PARAMS must mirror upstream inspect.signature defaults exactly."""

    @pytest.fixture(scope="class")
    def canon(self):
        import vsf_rsi.rsi_genetic_algorithm as c1
        import vsf_rsi.rsi_genetic_algorithm_v2 as c2
        return c1, c2

    def test_population_and_mutation_match_upstream(self, canon):
        c1, c2 = canon
        p1 = inspect.signature(c1.RSIGeneticAlgorithm.__init__).parameters
        p2 = inspect.signature(c2.RSIGeneticAlgorithmV2.__init__).parameters
        assert ga_config.GA_PARAMS["population_size"] == p1["population_size"].default
        assert ga_config.GA_PARAMS["population_size"] == p2["population_size"].default
        assert ga_config.GA_PARAMS["mutation_rate"] == p1["mutation_rate"].default
        assert ga_config.GA_PARAMS["mutation_rate_tuned"] == p2["mutation_rate"].default

    def test_windows_match_upstream(self, canon):
        c1, c2 = canon
        f1 = inspect.signature(c1.RSIGeneticAlgorithm.evolve_forest).parameters
        f2 = inspect.signature(c2.RSIGeneticAlgorithmV2.evolve_forest).parameters
        assert ga_config.GA_PARAMS["generation_window"] == f1["generations"].default
        assert ga_config.GA_PARAMS["generation_window"] == f2["generations"].default
        assert ga_config.GA_PARAMS["patience_window"] == f1["patience"].default
        assert ga_config.GA_PARAMS["patience_window"] == f2["patience"].default
