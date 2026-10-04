"""arc_search.py — program synthesis over the grid DSL (phase 1).

Random baseline + tiny generational GA. Fitness = exact-match fraction
on train pairs (tie-break: shorter programs). Deterministic given seed.
Budgets stay small: op set ~10, program length ≤ 3, populations ≤ 24.

NOT a solver claim — phase-1 search headroom probe. The harness
measures whatever this finds against the 0.0 floor.
"""
from __future__ import annotations

import random

from .arc_dsl import OP_NAMES, OPS, apply


def _rand_params(rng: random.Random, name: str) -> list:
    arity = OPS[name][1]
    if name == "recolor":
        return [rng.randint(0, 9), rng.randint(0, 9)]
    if name == "shift":
        return [rng.randint(-2, 2), rng.randint(-2, 2)]
    return [rng.randint(0, 9) for _ in range(arity)]


def random_program(rng: random.Random, max_len: int = 3) -> list:
    n = rng.randint(1, max_len)
    prog = []
    for _ in range(n):
        name = rng.choice(OP_NAMES)
        if name == "identity":
            continue
        prog.append((name, _rand_params(rng, name)))
    return prog or [("identity", [])]


def fitness(program, train_pairs) -> tuple:
    """(matches, -length): exact grid equality per train pair."""
    if not train_pairs:
        return (0, 0)
    hits = 0
    for pair in train_pairs:
        try:
            if apply(program, pair["input"]) == pair["output"]:
                hits += 1
        except Exception:
            continue
    return (hits, -len(program))


def random_search(train_pairs, budget: int = 200,
                  seed: int = 0) -> tuple:
    """Best of `budget` random programs. Returns (program, fitness)."""
    rng = random.Random(seed)
    best, best_f = [("identity", [])], fitness([("identity", [])],
                                               train_pairs)
    for _ in range(budget):
        prog = random_program(rng)
        f = fitness(prog, train_pairs)
        if f > best_f:
            best, best_f = prog, f
    return best, best_f


def _mutate(rng: random.Random, prog: list) -> list:
    prog = [list(s) for s in prog]
    if not prog:
        return random_program(rng)
    op = rng.choice(["swap", "jitter", "add", "drop", "trunc"])
    if op == "swap" or not prog:
        i = rng.randrange(len(prog))
        name = rng.choice(OP_NAMES)
        prog[i] = [name, _rand_params(rng, name)]
    elif op == "jitter":
        i = rng.randrange(len(prog))
        name = prog[i][0]
        prog[i][1] = _rand_params(rng, name)
    elif op == "add" and len(prog) < 3:
        name = rng.choice(OP_NAMES)
        prog.insert(rng.randint(0, len(prog)), [name, _rand_params(rng, name)])
    elif op == "drop" and len(prog) > 1:
        prog.pop(rng.randrange(len(prog)))
    elif op == "trunc" and len(prog) > 1:
        prog = prog[:rng.randint(1, len(prog))]
    return [(s[0], list(s[1])) for s in prog if s[0] in OPS]


def _crossover(rng: random.Random, p1: list, p2: list) -> list:
    cut = rng.randint(0, min(len(p1), len(p2)))
    child = [list(s) for s in p1[:cut]] + \
        [list(s) for s in p2[cut:cut + 2]]
    child = [(s[0], list(s[1])) for s in child if s[0] in OPS]
    return child[:3] or [("identity", [])]


def ga_search(train_pairs, pop_size: int = 24, generations: int = 6,
              seed: int = 0) -> tuple:
    """Generational GA with elitism. Returns (program, fitness)."""
    rng = random.Random(seed)
    pop = [random_program(rng) for _ in range(pop_size)]
    best, best_f = [("identity", [])], fitness([("identity", [])],
                                               train_pairs)
    for _ in range(generations):
        scored = sorted(((fitness(p, train_pairs), p) for p in pop),
                        reverse=True, key=lambda t: t[0])
        if scored[0][0] > best_f:
            best_f, best = scored[0]
        elites = [p for _, p in scored[: max(2, pop_size // 4)]]
        nxt = list(elites)
        while len(nxt) < pop_size:
            if rng.random() < 0.6 and len(elites) >= 2:
                a, b = rng.sample(elites, 2)
                nxt.append(_mutate(rng, _crossover(rng, a, b)))
            else:
                nxt.append(_mutate(rng, rng.choice(elites)))
        pop = nxt
    return best, best_f
