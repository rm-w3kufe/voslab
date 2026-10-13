"""Tests fase-3d: bridge.py — vista tasks x comunidades vOS, low-connectivity.

NO-NEW-TRUTH: vista pura, no muta el grafo. R10: determinista, sin random.
Denominadores honestos: total_tasks, matched_tasks, unmatched_tasks, per-status.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from epistemic_graph import build, bridge_view
from epistemic_graph.bridge import _parse_tasks_vsm, LIVE_STATUSES


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


def test_tasks_live_count_matches_plan(view):
    """Live count sanity vs TASKS.vsm reality.
    2026-10-13 census (orphan-triage session): queued 19 + in_progress 10 +
    open 5 + partial 1 → parser live = 37. The old window (48-58) encoded a
    pre-closure plan state; heavy done/closed archival (87+31) legitimately
    shrank the live set. Window = 37 ±5 for edge cases."""
    d = view["denominators"]
    assert 32 <= d["tasks_live"] <= 42
    assert d["tasks_matched"] + d["tasks_unmatched"] == d["tasks_live"]


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
