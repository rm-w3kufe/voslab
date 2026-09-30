"""trace_graph — graph views over state/rsi/tree_traces.jsonl.

Permanent capability of the system (approved by rmw3, 2026-09-30):
  * per-trace   — exact evaluation tree of one decision
  * aggregate   — canonical tree skeleton + traversal weights, keyed by
                  recorded VSL text (fallback reported in meta)
Exports: DOT (graphviz), JSON nodes/links (gephi/d3), networkx (notebook).
CLI:  python3 -m trace_graph list|export --tree claim_gate --format dot
"""
from .load import load_traces, traces_path, family
from .graph import per_trace, aggregate, families
from .export import to_dot, to_json, to_networkx

__all__ = [
    "load_traces", "traces_path", "family",
    "per_trace", "aggregate", "families",
    "to_dot", "to_json", "to_networkx",
]
