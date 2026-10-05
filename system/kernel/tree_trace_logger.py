#!/usr/bin/env python3
"""tree_trace_logger.py — Structured decision trace for vOSlab

Captures the full socratic evaluation tree as a structured trace:
- Every node evaluated (predicates, operators, short-circuits)
- Truth + evidence at each node
- Path taken through the tree
- Context and timing
- Session-level aggregation

Output: state/rsi/tree_traces.jsonl (append-only, rotated at 10K lines)

Usage:
    from tree_trace_logger import TreeTraceLogger
    logger = TreeTraceLogger()
    trace = logger.capture(evaluation_result, tree, context)
    logger.persist(trace)
    summary = logger.session_summary()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("tree_trace_logger")

# ─── Path setup ────────────────────────────────────────────────────────────────
# NOTE: VOSLAB_PATH is re-read at runtime (not cached at import) because
# pytest may import this module before VOSLAB_PATH is set in the environment.
def _voslab_path() -> Path:
    return Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))

def _trace_log() -> Path:
    # VOS_TREE_TRACE_FILE: test isolation (conftest sets it to session tmp).
    # Production never sets it → real path. Same lesson as RSI_* dirs.
    override = os.environ.get("VOS_TREE_TRACE_FILE")
    if override:
        return Path(override)
    return _voslab_path() / "state" / "rsi" / "tree_traces.jsonl"

def _trace_dir() -> Path:
    override = os.environ.get("VOS_TREE_TRACE_DIR")
    if override:
        return Path(override)
    return _voslab_path() / "state" / "rsi" / "traces"

MAX_LINES = 10000


@dataclass
class NodeTrace:
    """Trace for a single node in the evaluation tree."""
    node_id: int
    node_type: str  # "predicate", "operator", "literal", "short_circuit"
    name: str
    truth: str
    certified: bool
    evidence: Any = None
    latency_ms: float = 0.0
    children_ids: List[int] = field(default_factory=list)
    args: Any = None
    error: Optional[str] = None
    # Textual predicate as written in the tree (F3 2026-09-30): e.g.
    # 'ctx_equals($ctx, cert_present, true) -> R0' — lets a trace show the
    # UNevaluated branches too (short-circuit placeholders keep the text).
    text: Optional[str] = None
    # Literal human question the node asks (F4 2026-09-30), from the tree's
    # q: field — traces read as questions, not only as formulae.
    question: Optional[str] = None


@dataclass
class TreeTrace:
    """Complete trace of a socratic tree evaluation."""
    trace_id: str
    ts: str
    session_id: Optional[str]
    # The original tree (input)
    tree_hash: str
    tree_shape: str  # "AND(predicate, OR(...))" — human-readable
    # The evaluation result
    final_truth: str
    final_certified: bool
    final_source: str
    # The full trace
    nodes: List[NodeTrace]
    total_nodes: int
    predicates_evaluated: int
    operators_evaluated: int
    # Timing
    total_latency_ms: float
    # Context snapshot (subset, not full ctx)
    context_keys: List[str]
    # Decision-grade snapshot (F1/F2 2026-09-30): the winning route home
    # (raw, e.g. "R1-FAIL") + full ctx values — makes the persisted trace
    # explain WHY this path, not just the root truth.
    home: str = ""
    context: dict = field(default_factory=dict)
    # Attestation placeholder (filled by capa 2)
    attestation: Optional[str] = None


class TreeTraceLogger:
    """Captures and persists structured decision traces."""

    def __init__(self, log_file: Optional[Path] = None, session_id: Optional[str] = None):
        self.log_file = log_file or _trace_log()
        self.session_id = session_id or os.environ.get("SESSION_ID")
        self._node_counter = 0
        self._session_traces: List[TreeTrace] = []
        self._session_start = time.time()

    def capture(self, evaluation, tree: dict, context: dict = None,
                latency_ms: float = 0.0, home: str = "") -> TreeTrace:
        """Capture a full evaluation trace from an engine Evaluation result.

        Args:
            evaluation: socratic_engine.engine.Evaluation (recursive dataclass)
            tree: the original tree dict (for hash + shape)
            context: evaluation context (keys + full values persisted)
            latency_ms: total evaluation latency
            home: winning route/home of the decision ("" when not applicable)

        Returns:
            TreeTrace with full node-by-node trace
        """
        self._node_counter = 0
        nodes = []
        self._walk_evaluation(evaluation, nodes, tree)
        for n in nodes:
            n.text = self._fit_text(n.text)
            n.question = self._fit_text(n.question)

        tree_hash = hashlib.sha256(
            json.dumps(tree, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        tree_shape = self._tree_shape(tree)

        trace = TreeTrace(
            trace_id=f"trace-{int(time.time() * 1000)}-{os.getpid()}",
            ts=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            tree_hash=tree_hash,
            tree_shape=tree_shape,
            final_truth=str(evaluation.truth),
            final_certified=evaluation.certified,
            final_source=evaluation.source or "unknown",
            nodes=nodes,
            total_nodes=len(nodes),
            predicates_evaluated=sum(1 for n in nodes if n.node_type == "predicate"),
            operators_evaluated=sum(1 for n in nodes if n.node_type == "operator"),
            total_latency_ms=round(latency_ms, 3),
            context_keys=sorted((context or {}).keys()),
            home=home,
            context=dict(context or {}),
        )

        self._session_traces.append(trace)
        return trace

    def _walk_evaluation(self, evaluation, nodes: List[NodeTrace],
                         tree_node: Any = None, depth: int = 0) -> int:
        """Recursively walk an Evaluation tree, building NodeTrace list.

        tree_node (optional): the corresponding node of the source tree,
        aligned positionally with evaluation.children — used to attach the
        TEXTUAL predicate (args + home) even to short-circuit placeholders
        (branches the logic never reached still show what they would ask).

        Returns the node_id of the created node.
        """
        node_id = self._node_counter
        self._node_counter += 1

        # Determine node type from source
        source = evaluation.source or "unknown"
        if source.startswith("op:"):
            node_type = "operator"
            name = source[3:]  # "AND", "OR", etc.
        elif source == "short_circuit":
            node_type = "short_circuit"
            name = "short_circuit"
        elif source == "literal":
            node_type = "literal"
            name = "literal"
        else:
            node_type = "predicate"
            name = source

        # Append THIS node first (pre-order: parent before children)
        # so root is always nodes[0]
        node = NodeTrace(
            node_id=node_id,
            node_type=node_type,
            name=name,
            truth=str(evaluation.truth),
            certified=evaluation.certified,
            evidence=evaluation.evidence if isinstance(evaluation.evidence, (dict, list, str, int, float, bool, type(None))) else str(evaluation.evidence),
            children_ids=[],  # filled after children are processed
        )
        if isinstance(tree_node, dict):
            if node_type == "predicate":
                node.args = tree_node.get("args", tree_node.get("kwargs"))
            node.text = self._tree_text(tree_node)
            node.question = tree_node.get("q")
        nodes.append(node)

        # Then process children (they get appended after this node)
        tchildren = (tree_node.get("children", [])
                    if isinstance(tree_node, dict) else [])
        for i, child in enumerate(evaluation.children):
            tchild = tchildren[i] if i < len(tchildren) else None
            child_id = self._walk_evaluation(child, nodes, tchild, depth + 1)
            node.children_ids.append(child_id)

        return node_id

    _MAX_TEXT = 600

    @classmethod
    def _tree_text(cls, tree, max_depth: int = 6) -> str:
        """Literal textual rendering of a tree node (F3): predicates as
        written ('ctx_equals($ctx, cert_present, true) -> R0'), operators
        as nested formulae with a children cap. Pure + deterministic (R10)."""
        if max_depth <= 0:
            return "…"
        if not isinstance(tree, dict):
            return str(tree)
        if "predicate" in tree:
            name = tree["predicate"]
            if "args" in tree:
                inner = ", ".join(str(a) for a in tree["args"])
            elif "kwargs" in tree:
                inner = ", ".join(f"{k}={v}" for k, v in
                                  sorted(tree["kwargs"].items()))
            else:
                inner = ""
            text = f"{name}({inner})"
            if tree.get("home"):
                text += f" -> {tree['home']}"
            return text
        if "op" in tree:
            children = tree.get("children", [])
            parts = [cls._tree_text(c, max_depth - 1)
                     for c in children[:4]]
            if len(children) > 4:
                parts.append(f"…(+{len(children) - 4})")
            text = f"{tree['op']}({', '.join(parts)})"
            if tree.get("home"):
                text += f" -> {tree['home']}"
            if tree.get("else_home"):
                text += f" [else: {tree['else_home']}]"
            return text
        return str(tree)[:cls._MAX_TEXT]

    @classmethod
    def _fit_text(cls, text: Optional[str]) -> Optional[str]:
        if isinstance(text, str) and len(text) > cls._MAX_TEXT:
            return text[:cls._MAX_TEXT] + "…"
        return text

    @staticmethod
    def _tree_shape(tree, max_depth: int = 3) -> str:
        """Generate a human-readable tree shape string.

        Static since EP-0/F2 (2026-09-27): pure function of the tree —
        rsi_cycle._log_event reuses it for error detail (same builder as
        trace tree_shape, no divergence).
        """
        if max_depth <= 0:
            return "..."
        if isinstance(tree, dict):
            if "predicate" in tree:
                name = tree["predicate"]
                return name
            if "op" in tree:
                op = tree["op"]
                children = tree.get("children", [])
                parts = [TreeTraceLogger._tree_shape(c, max_depth - 1)
                         for c in children[:4]]
                return f"{op}({', '.join(parts)})"
        if isinstance(tree, bool):
            return str(tree)
        return "?"

    def persist(self, trace: TreeTrace) -> None:
        """Append a trace to the JSONL log file."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "trace_id": trace.trace_id,
            "ts": trace.ts,
            "session_id": trace.session_id,
            "tree_hash": trace.tree_hash,
            "tree_shape": trace.tree_shape,
            "final_truth": trace.final_truth,
            "final_certified": trace.final_certified,
            "final_source": trace.final_source,
            "total_nodes": trace.total_nodes,
            "predicates_evaluated": trace.predicates_evaluated,
            "operators_evaluated": trace.operators_evaluated,
            "total_latency_ms": trace.total_latency_ms,
            "context_keys": trace.context_keys,
            "home": trace.home,
            "context": trace.context,
            "attestation": trace.attestation,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "type": n.node_type,
                    "name": n.name,
                    "truth": n.truth,
                    "certified": n.certified,
                    "evidence": n.evidence,
                    "children": n.children_ids,
                    "error": n.error,
                    "args": n.args,
                    "text": n.text,
                    "question": n.question,
                }
                for n in trace.nodes
            ],
        }
        with open(str(self.log_file), "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        # Rotate if too large
        try:
            lines = self.log_file.read_text().splitlines()
            if len(lines) > MAX_LINES:
                self.log_file.write_text("\n".join(lines[-MAX_LINES // 2:]) + "\n")
        except OSError as e:
            _logger.debug("trace log rotation failed: %s", e)

    def persist_session_trace(self, trace: TreeTrace) -> None:
        """Persist a full trace to individual file for detailed analysis."""
        _trace_dir().mkdir(parents=True, exist_ok=True)
        trace_file = _trace_dir() / f"{trace.trace_id}.json"
        entry = {
            "trace_id": trace.trace_id,
            "ts": trace.ts,
            "session_id": trace.session_id,
            "tree_hash": trace.tree_hash,
            "tree_shape": trace.tree_shape,
            "final_truth": trace.final_truth,
            "final_certified": trace.final_certified,
            "final_source": trace.final_source,
            "total_nodes": trace.total_nodes,
            "predicates_evaluated": trace.predicates_evaluated,
            "operators_evaluated": trace.operators_evaluated,
            "total_latency_ms": trace.total_latency_ms,
            "context_keys": trace.context_keys,
            "home": trace.home,
            "context": trace.context,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "type": n.node_type,
                    "name": n.name,
                    "truth": n.truth,
                    "certified": n.certified,
                    "evidence": n.evidence,
                    "children": n.children_ids,
                    "error": n.error,
                    "args": n.args,
                    "text": n.text,
                    "question": n.question,
                }
                for n in trace.nodes
            ],
        }
        trace_file.write_text(json.dumps(entry, indent=2, default=str))

    def session_summary(self) -> dict:
        """Generate a session-level summary of all traces."""
        traces = self._session_traces
        if not traces:
            return {"traces": 0}

        truths = {}
        sources = {}
        total_latency = 0.0
        total_nodes = 0
        total_predicates = 0

        for t in traces:
            truths[t.final_truth] = truths.get(t.final_truth, 0) + 1
            sources[t.final_source] = sources.get(t.final_source, 0) + 1
            total_latency += t.total_latency_ms
            total_nodes += t.total_nodes
            total_predicates += t.predicates_evaluated

        return {
            "session_id": self.session_id,
            "traces": len(traces),
            "truths": truths,
            "sources": sources,
            "total_latency_ms": round(total_latency, 3),
            "avg_latency_ms": round(total_latency / len(traces), 3) if traces else 0,
            "total_nodes": total_nodes,
            "total_predicates": total_predicates,
            "duration_seconds": round(time.time() - self._session_start, 1),
            "first_trace": traces[0].ts if traces else None,
            "last_trace": traces[-1].ts if traces else None,
        }

    def persist_session_summary(self) -> dict:
        """Generate and persist session summary."""
        summary = self.session_summary()
        summary_file = _voslab_path() / "state" / "rsi" / "session_summary.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary, indent=2, default=str))
        return summary


# ─── CLI standalone ────────────────────────────────────────────────────────────

def main():
    """CLI: read recent traces and print summary."""
    import sys
    log_file = Path(sys.argv[1]) if len(sys.argv) > 1 else _trace_log()
    if not log_file.exists():
        print(f"No traces at {log_file}")
        return

    lines = log_file.read_text().splitlines()
    print(f"Total traces: {len(lines)}")

    # Parse last N
    n = min(10, len(lines))
    print(f"\nLast {n} traces:")
    for line in lines[-n:]:
        try:
            entry = json.loads(line)
            print(f"  {entry['ts'][:19]} | {entry['final_truth']:>8} | {entry['final_source']:>20} | nodes={entry['total_nodes']} | {entry['total_latency_ms']:.1f}ms | {entry['tree_shape'][:60]}")
        except (json.JSONDecodeError, KeyError) as e:
            _logger.debug("trace display entry skipped: %s", e)
            continue

    # Aggregate
    truths = {}
    for line in lines:
        try:
            e = json.loads(line)
            t = e["final_truth"]
            truths[t] = truths.get(t, 0) + 1
        except Exception:
            continue
    print(f"\nTruth distribution: {truths}")


if __name__ == "__main__":
    main()
