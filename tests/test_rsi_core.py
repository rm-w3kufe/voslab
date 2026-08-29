"""Integration: vsf-rsi-core (agnostic) pinned into vOSLAB and usable."""

import pytest

from vsf_rsi_core import RSIGeneticAlgorithm


def test_pinned_rsi_core_evolves(tmp_path):
    ga = RSIGeneticAlgorithm(population_size=4, metrics_dir=tmp_path)
    result = ga.evolve_forest("ac_viable", generations=2)
    assert result["generations"] == 2
    assert len(result["final_forest"]) == 4
