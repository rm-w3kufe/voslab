"""ga_config.py — declared genetic-algorithm parameters (debt D-06 FASE C / C2).

Single source of truth for the GA tunables used on the vOSlab integration
surface (the `rsi_genetic_algorithm{,_v2}.py` shims below and the
`vsf_rsi_core.bridge` adapter). Consumers READ `GA_PARAMS` at call time —
never a restated literal — so a monkeypatch of this dict is observable in
the GA itself (the C2 contract, asserted by `test_ga_params.py`).

Values mirror the canonical upstream defaults
(~/packages/public/vsf-rsi/vsf_rsi/rsi_genetic_algorithm{,_v2}.py):
declaring them changes no behavior, it freezes it — a drift test in
test_ga_params.py fails if upstream moves without this file following.

Declared parameters:
  population_size    trees per forest (forest population)
  mutation_rate      per-gene mutation probability, GA v1 (original)
  mutation_rate_tuned
                     per-gene mutation probability, GA v2 (tuned)
  generation_window  max generations per evolve_forest run (ventana)
  patience_window    generations without improvement before early stop
                     (convergence ventana, DEBT-004)

crossover: upstream crossover is an always-on operator (there is no
probability parameter in the implementation), so there is no crossover
rate to declare — mutation is the only parameterized stochastic step.
"""

from __future__ import annotations

GA_PARAMS: dict[str, float | int] = {
    "population_size": 10,
    "mutation_rate": 0.1,
    "mutation_rate_tuned": 0.2,
    "generation_window": 10,
    "patience_window": 3,
}

__all__ = ["GA_PARAMS"]
