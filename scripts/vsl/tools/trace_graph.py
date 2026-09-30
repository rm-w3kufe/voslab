#!/usr/bin/env python3
"""trace_graph.py — graph views over state/rsi/tree_traces.jsonl (permanent).

Views:
  per-trace   — exact evaluation tree of one decision (local node_ids)
  aggregate   — canonical tree skeleton + traversal weights, keyed by
                recorded VSL text; old rows key on type:name and meta
                reports keyed_by_fallback (honesty denominators)

Usage:
  python3 scripts/vsl/tools/trace_graph.py list
  python3 scripts/vsl/tools/trace_graph.py export --tree claim_gate --format dot [--out FILE]
  python3 scripts/vsl/tools/trace_graph.py show --trace TRACE_ID --format json

Python/notebook API:
  from trace_graph import load_traces, aggregate, per_trace, to_dot, to_json, to_networkx
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "framework"))

from trace_graph.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
