# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T6-F2: census-derived live count)
"""Tests fase-3d: bridge.py — vista tasks x comunidades vOS, low-connectivity.

NO-NEW-TRUTH: vista pura, no muta el grafo. R10: determinista, sin random.
Denominadores honestos: total_tasks, matched_tasks, unmatched_tasks, per-status.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from epistemic_graph import build, bridge_view
from epistemic_graph.bridge import _parse_tasks_vsm, LIVE_STATUSES

_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def graph():
    return build()


@pytest.fixture(scope="module")
def view(graph):
    return bridge_view(graph)


def test_bridge_schema(view):
    assert view["schema"] == "graph_bridge-v1"
    assert "fingerprint" in view
    assert "denominators" in view
    assert "tasks" in view
    assert "report" in view


def test_denominators_honest(view):
    d = view["denominators"]
    live = d["tasks_live"]
    matched = d["tasks_matched"]
    unmatched = d["tasks_unmatched"]
    # matched + unmatched = live
    assert matched + unmatched == live
    # live <= total_parsed
    assert live <= d["tasks_total_parsed"]
    # live_by_status sums to live
    assert sum(d["live_by_status"].values()) == live
    # statuses are live only
    for s in d["live_by_status"]:
        assert s in LIVE_STATUSES


def test_tasks_live_count_matches_census(view):
    """Live count = TASKS.vsm leído DOS veces: vista epistemic vs census
    canónico (state-canon tasks_provider) — cero restatements.

    Historia de la banda que este test reemplaza: 48-58 → 37±5
    (2026-10-13 orphan-triage) → 49±5 (2026-10-20 ARC round) — cada
    movimiento legítimo del census exigía reescribir la ventana a mano
    (restatement de S5 dentro del test, plan 2026-10-20 T6). Ahora
    compara los DOS parsers vivos: drift entre parsers = rojo inmediato
    (clase del incidente 2026-08-10: state-canon 349 vs onboard 353 por
    un '{' cotizado), movimiento real de TASKS = verde sin tocar nada.
    Censo canónico: MISMO reader que el check tasks-census-converge
    (tasks_provider.parse_vsm_file), ruta interna del repo (R6),
    cargado por spec (sin pisar sys.modules). Normaliza status como ese
    check (lower/strip/strip-comma — FASE-5-DATA-QUALITY). R10: puro,
    sin reloj ni I/O externo."""
    spec = importlib.util.spec_from_file_location(
        "tasks_provider_census",
        _ROOT / "packages" / "public" / "state-canon-mcp" / "instances"
        / "tasks_provider.py")
    tp = importlib.util.module_from_spec(spec)
    # registro obligatorio: tasks_provider usa @dataclass y este resuelve
    # anotaciones vía sys.modules[cls.__module__] (python 3.14)
    sys.modules["tasks_provider_census"] = tp
    spec.loader.exec_module(tp)

    def _norm(s: object) -> str:
        return str(s).strip().lower().rstrip(",").strip('"')

    census = tp.parse_vsm_file(_ROOT / "TASKS.vsm")
    census_live = {
        t["id"] for t in census["tasks"]
        if _norm(t.get("status")) in LIVE_STATUSES
    }
    view_live = {
        row["ref"] for row in view["tasks"]
        if _norm(row["status"]) in LIVE_STATUSES
    }
    # ambos parsers ven el MISMO set de ids vivos (drift = rojo)
    assert view_live == census_live, (
        f"parser drift vista vs census: Δ={sorted(view_live ^ census_live)}")
    # el denominador vive de ese set — sin banda hardcodeada
    assert view["denominators"]["tasks_live"] == len(census_live)
    assert view["denominators"]["tasks_matched"] + \
        view["denominators"]["tasks_unmatched"] == len(census_live)


def test_report_partition(view):
    """low_connectivity ∪ high_connectivity ∪ mid ⊆ all refs, disjuntos."""
    tasks = view["tasks"]
    all_refs = {t["ref"] for t in tasks}
    low = set(view["report"]["low_connectivity_candidates"])
    high = set(view["report"]["high_connectivity"])
    # low and high are disjoint
    assert low & high == set()
    # both are subsets of all refs
    assert low <= all_refs
    assert high <= all_refs


def test_low_connectivity_are_real_candidates(view):
    """Tasks with connectivity < MIN_SHARED_TOKENS (conn=0) are unmatched.
    The lowest-connectivity tasks should be the discard candidates."""
    tasks = view["tasks"]
    # at least some tasks have connectivity > 0 (matched)
    matched = [t for t in tasks if t["matched"]]
    assert len(matched) > 0
    # low_connectivity_candidates are unmatched (conn=0)
    for ref in view["report"]["low_connectivity_candidates"]:
        row = next(t for t in tasks if t["ref"] == ref)
        assert not row["matched"]
        assert row["connectivity"] == 0


def test_deterministic_rerun(graph):
    """R10: two runs produce identical results."""
    v1 = bridge_view(graph)
    v2 = bridge_view(graph)
    # same fingerprint
    assert v1["fingerprint"] == v2["fingerprint"]
    # same denominators
    assert v1["denominators"] == v2["denominators"]
    # same task rows
    assert v1["tasks"] == v2["tasks"]
    # same report
    assert v1["report"] == v2["report"]
