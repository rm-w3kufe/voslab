"""epistemic_graph — unified epistemic projection (trace_graph + sidecars).

Permanent capability (docs/plans/graph_epistemic_proposal.vsm, ratified
by S5 2026-10-10; fase-2 approved 2026-10-11): one deterministic graph
over 7 persisted sources.

  9 node kinds : document, claim, predicate, certificate, answer,
                 experiment, decision, gap, rule
  10 edge kinds: 6 MVP — child_of, extracted_from, certified_by,
                 derived_from, correlates_with, answers
               + 4 fase-2 — contradicts, refutes, supersedes, resolves
  dims         : base {kind, status, source, ts} + per-kind extras
  vistas       : by_kind / by_dim / by_edge (cross views: claim->predicate,
                 decision->gap, experiment<->claim)

Rules: NO-NEW-TRUTH (view, never source; rebuildable from scratch),
D3 content-keyed identity, R10 determinism.

CLI:  python3 -m epistemic_graph stats|export|show [--kind|--dim|--edge]
"""
from .graph import build, by_kind, by_dim, by_edge, KINDS, EDGE_KINDS
from .export import to_dot, to_json, to_networkx
from .graph_health import health, write_snapshot, LAYERS
from .discovery import discover, write_queue, MIN_SCORE_PROVISIONAL, communities
from .bridge import bridge_view, write_bridge

__all__ = [
    "build", "by_kind", "by_dim", "by_edge", "KINDS", "EDGE_KINDS",
    "to_dot", "to_json", "to_networkx",
    "health", "write_snapshot", "LAYERS",
    "discover", "write_queue", "MIN_SCORE_PROVISIONAL", "communities",
    "bridge_view", "write_bridge",
]
