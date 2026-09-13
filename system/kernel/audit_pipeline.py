#!/usr/bin/env python3
"""audit_pipeline.py — F4: Unified 4-layer audit trail pipeline.

Wraps trace → attest → feedback → alert into a single interface.
Replaces scattered imports in rsi_cycle.py.

Usage:
    from audit_pipeline import AuditPipeline

    pipeline = AuditPipeline(session_id="session-123")
    result = pipeline.run(evaluation_event, tree, context, latency_ms)
    # result contains: trace, attestation, alerts
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("audit_pipeline")


class AuditPipeline:
    """Unified 4-layer audit trail pipeline.

    Layers:
      1. TreeTraceLogger — captures full evaluation tree
      2. AttestationSigner — signs trace with Ed25519
      3. FeedbackLoop — session-level pattern detection
      4. AlertMonitor — anomaly detection + alerting
    """

    def __init__(self, session_id: Optional[str] = None):
        self._session_id = session_id
        self._trace_logger = None
        self._signer = None
        self._metrics = {
            "evals_total": 0,
            "traces_captured": 0,
            "traces_lost": 0,
            "attestations_signed": 0,
            "attestations_lost": 0,
        }

    def _get_trace_logger(self):
        if self._trace_logger is None:
            from tree_trace_logger import TreeTraceLogger
            self._trace_logger = TreeTraceLogger(session_id=self._session_id)
        return self._trace_logger

    def _get_signer(self):
        if self._signer is None:
            from tree_trace_attest import AttestationSigner
            self._signer = AttestationSigner()
        return self._signer

    def run(self, event, tree: dict, context: dict,
            latency_ms: float) -> Dict[str, Any]:
        """Run the full audit pipeline for one evaluation.

        Args:
            event: EvaluationEvent from socratic-engine
            tree: The tree that was evaluated
            context: Evaluation context
            latency_ms: Evaluation latency in milliseconds

        Returns:
            Dict with trace_id, attestation, alerts, metrics
        """
        result = {
            "trace_id": None,
            "attestation": None,
            "alerts": [],
            "metrics": self._metrics,
        }

        if event is None:
            self._metrics["traces_lost"] += 1
            return result

        self._metrics["evals_total"] += 1

        # Layer 1: Trace capture
        try:
            trace = self._get_trace_logger().capture(
                event, tree, context, latency_ms
            )
            self._get_trace_logger().persist(trace)
            self._metrics["traces_captured"] += 1
            result["trace_id"] = trace.trace_id

            # Layer 2: Attestation
            try:
                att = self._get_signer().sign_trace(asdict(trace))
                att_dir = (
                    Path(os.environ.get("VOSLAB_PATH", "."))
                    / "state" / "rsi" / "attestations"
                )
                from tree_trace_attest import persist_attestation
                persist_attestation(att, att_dir)
                self._metrics["attestations_signed"] += 1
                result["attestation"] = att
            except Exception as e:
                self._metrics["attestations_lost"] += 1
                logger.warning("Attestation lost: %s", e)

        except Exception as e:
            self._metrics["traces_lost"] += 1
            logger.warning("Trace lost: %s", e)

        return result

    def check_alerts(self) -> List:
        """Run Layer 4: alerting checks."""
        try:
            from alerting import AlertMonitor
            monitor = AlertMonitor()
            return monitor.check()
        except Exception as e:
            logger.debug("Alert check failed: %s", e)
            return []

    def close_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Run Layer 3: session feedback loop."""
        try:
            from feedback_loop import FeedbackLoop
            loop = FeedbackLoop()
            report = loop.close_session(session_id or self._session_id)
            return asdict(report)
        except Exception as e:
            logger.debug("Feedback loop failed: %s", e)
            return {}

    @property
    def metrics(self) -> Dict[str, Any]:
        return dict(self._metrics)
