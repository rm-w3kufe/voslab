"""epistemic_graph — unified epistemic projection (trace_graph + sidecars).

Permanent capability (docs/plans/graph_epistemic_proposal.vsm, ratified
by S5 2026-10-10): one deterministic graph over 7 persisted sources.

  9 node kinds : document, claim, predicate, certificate, answer,
                 experiment, decision, gap, rule
  6 edge kinds : child_of, extracted_from, certified_by, derived_from,
                 correlates_with, answers
  dims         : base {kind, status, source, ts} + per-kind extras

Rules: NO-NEW-TRUTH (view, never source; rebuildable from scratch),
D3 content-keyed identity, R10 determinism.

CLI:  python3 -m epistemic_graph stats|export|show
"""
from .graph import build, by_kind, by_dim, KINDS, EDGE_KINDS
from .export import to_dot, to_json, to_networkx

__all__ = [
    "build", "by_kind", "by_dim", "KINDS", "EDGE_KINDS",
    "to_dot", "to_json", "to_networkx",
]
