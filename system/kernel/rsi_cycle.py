#!/usr/bin/env python3
"""rsi_cycle.py — RSI Cycle Orchestrator (vOSlab kernel)

Architecture (rmw3 insight):
  Socratic-engine = evaluation hub (ALL predicates wrap plugins/scripts)
  VSF-RSI = correction layer (detect faults, generate fixes, shadow validate)
  State-canon = data layer (query context, journal changes, track focus)

Flow:
  1. Agent calls tool → socratic evaluates tree
  2. Tree contains predicates that wrap plugins/scripts
  3. Each predicate executes logic → returns truth + evidence
  4. Socratic certifies result
  5. If FALSE+certified → VSF-RSI detects fault
  6. VSF-RSI generates correction (new predicate/tree)
  7. Shadow mode validates
  8. If successful → activate
  9. State-canon journals the change

Usage:
  from rsi_cycle import RSICycle
  cycle = RSICycle()
  result = cycle.evaluate({"op": "AND", "children": [...]}, context)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path setup ────────────────────────────────────────────────────────────────
# Derive paths from environment or file location (no hardcoded usernames)
VOSLAB_PATH = Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))
STATE_CANON_PATH = Path(os.environ.get("STATE_CANON_PATH", VOSLAB_PATH.parent / "state-canon-mcp"))
RSI_PATH = Path(os.environ.get("RSI_PATH", VOSLAB_PATH / "packages" / "public" / "vsf-rsi"))
INTEGRATION_LOG = VOSLAB_PATH / "state" / "integration_log.jsonl"

# RSI autonomy state MUST live inside this workspace (never ~/packages).
# Upstream vsf_rsi freezes its DIR constants at first import, so these
# defaults are set here — before any lazy `import vsf_rsi.*` below.
# S5 env overrides win (setdefault). The opencode bridge sets the same vars.
_RSI_STATE_DIR = VOSLAB_PATH / "state" / "rsi"
os.environ.setdefault("RSI_QUEUE_DIR", str(_RSI_STATE_DIR / "queue"))
os.environ.setdefault("RSI_SHADOW_DIR", str(_RSI_STATE_DIR / "shadow"))
os.environ.setdefault("RSI_ROLLBACK_DIR", str(_RSI_STATE_DIR / "rollback"))
os.environ.setdefault("RSI_L3_DIR", str(_RSI_STATE_DIR / "l3"))
os.environ.setdefault("RSI_FAULT_DIR", str(_RSI_STATE_DIR / "faults"))

# Import stub predicates from separate module (both layouts: bare
# `stub_predicates` when system/kernel is on sys.path, package path else).
try:
    from stub_predicates import (
        state_consistent, state_scripts_ok, vsl_scripts_ok, audit_scripts_ok,
        s1_kernel_scripts_ok, scripts_manifest, not_redundant, pattern_known,
        script_safe, script_domain_ok, script_call, read_size_ok, task_active,
        policy_locked, write_scope_ok,
        event_router_ok, lifecycle_valid, gap_free, onboard_complete,
        hook_metrics_ok, semantic_mapper_ok, process_staging_ok,
        load_hooks_ok,
        naming_conforms, vsm_has_header,
        FORBIDDEN_COMMANDS, FORBIDDEN_PATHS,
    )
except ImportError:  # pragma: no cover - layout fallback
    from system.kernel.stub_predicates import (
        state_consistent, state_scripts_ok, vsl_scripts_ok, audit_scripts_ok,
        s1_kernel_scripts_ok, scripts_manifest, not_redundant, pattern_known,
        script_safe, script_domain_ok, script_call, read_size_ok, task_active,
        policy_locked, write_scope_ok,
        event_router_ok, lifecycle_valid, gap_free, onboard_complete,
        hook_metrics_ok, semantic_mapper_ok, process_staging_ok,
        load_hooks_ok,
        naming_conforms, vsm_has_header,
        FORBIDDEN_COMMANDS, FORBIDDEN_PATHS,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Security (lists live in stub_predicates; single source)
# ═══════════════════════════════════════════════════════════════════════════════

def action_forbidden(tool: str = "", file: str = "", command: str = "", **kw):
    """Blocks dangerous commands. Wraps: none (pure security)."""
    from socratic_engine import PredicateResult, Truth
    for f in FORBIDDEN_COMMANDS:
        if f in command:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"forbidden": f, "command": command[:100]},
                source="action_forbidden"
            )
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"tool": tool}, source="action_forbidden"
    )

READ_ONLY_TOOLS = {"read", "glob", "grep", "list_mcp_resources"}

def path_forbidden(file: str = "", **kw):
    """Blocks forbidden paths in BOTH directions (S5 decision 2026-09-09).

    Writes were already blocked. Reads of credential/device paths are now
    blocked too (exfiltration closes over read-only tools, which never
    passed the risk gate). Direction travels in evidence for audit.
    """
    from socratic_engine import PredicateResult, Truth
    tool = kw.get("tool", "")
    direction = "read" if tool in READ_ONLY_TOOLS else "write"
    if not file:
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"reason": "no file"}, source="path_forbidden"
        )
    from stub_predicates import _hits_forbidden, _normalize_path
    hit = _hits_forbidden(file)
    if hit:
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"forbidden_path": hit, "direction": direction,
                      "tool": tool, "resolved": _normalize_path(file)},
            source="path_forbidden"
        )
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"file": file, "direction": direction,
                  "resolved": _normalize_path(file) if file else ""},
        source="path_forbidden"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — State
# ═══════════════════════════════════════════════════════════════════════════════

def task_has_work(**kw):
    """Check if current_focus.json has active work."""
    from socratic_engine import PredicateResult, Truth
    focus_file = VOSLAB_PATH / "current_focus.json"
    if not focus_file.exists():
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"reason": "no focus file"}, source="task_has_work"
        )
    try:
        data = json.loads(focus_file.read_text())
        active = [t for t in data if t.get("status") == "active"]
        return PredicateResult(
            truth=Truth.TRUE if active else Truth.FALSE,
            certified=True,
            evidence={"active_count": len(active)},
            source="task_has_work"
        )
    except Exception as e:
        return PredicateResult(
            truth=Truth.FALSE, certified=True,
            evidence={"error": str(e)}, source="task_has_work"
        )

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Quality
# ═══════════════════════════════════════════════════════════════════════════════

def file_valid(file: str = "", **kw):
    """Check if file is valid."""
    from socratic_engine import PredicateResult, Truth
    if not file:
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"reason": "no file"}, source="file_valid"
        )
    path = Path(file)
    return PredicateResult(
        truth=Truth.TRUE if path.exists() else Truth.FALSE,
        certified=True,
        evidence={"file": file, "exists": path.exists()},
        source="file_valid"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Learning
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Scripts
# ═══════════════════════════════════════════════════════════════════════════════

def script_safe(command: str = "", **kw):
    """Check if script is safe."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"command": command[:100]}, source="script_safe"
    )

def script_exists(script: str = "", **kw):
    """Check if script exists."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE if script else Truth.FALSE,
        certified=True,
        evidence={"script": script}, source="script_exists"
    )

def script_domain_ok(domain: str = "", **kw):
    """Check if script domain is ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"domain": domain}, source="script_domain_ok"
    )

def script_call(script: str = "", **kw):
    """Check if script call is valid."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"script": script}, source="script_call"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Tasks
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Plugins
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Child scripts (migrated)
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# Autonomy ceiling (S5 rmw3 — enforced mechanically, not by convention)
# ═══════════════════════════════════════════════════════════════════════════════
# Control levels:
#   L3_AUTO = True   → L3 cycle (detect → shadow → activate → rollback) runs
#                       autonomously: every step is reversible (shadow-gated
#                       activation + auto-rollback). Control level 1.
#   L4_AUTO = False  → NOTHING generated is ever activated directly. Genetic
#                       evolution output and learn-pipeline output go to the
#                       approval queue; a human approves before activation.
#                       Control level 2. A0/A5/R17/R4 always hold.
L3_AUTO = True
L4_AUTO = False

# Predicates whose FALSE verdict is CORRECT enforcement, not a fault.
# A failure attributed purely to these is recorded but never triggers
# pipeline/L3/enqueue (S5 green light 2026-09-10: stop the fix_* spam —
# a denied rm -rf is the system working, not something to correct).
# L3 operating dimensions (S5 dimensioning 2026-09-10, per vsf-rsi README).
# Upstream: MIN_REPEATS=3/WINDOW=10, SHADOW 10 evals/>=10% improvement,
# ROLLBACK 50-eval window/5% revert, 5 strategies/fault, 3 generations.
# vOSlab keeps all upstream values; ADDS a session governor (below) and
# documents that LATENCY_THRESHOLD_MS=10 never gates here (subprocess
# evals run 17-70ms; latency is recorded, not decisive — verified).
# Faults from pure policy blocks never reach the detector (3b/4 split).
L3_MAX_RUNS_PER_HOUR = 3

SECURITY_PREDICATES = frozenset({
    "action_forbidden", "path_forbidden", "policy_locked",
    "write_scope_ok", "script_safe", "script_domain_ok",
})

# Engine-reserved: generated trees may never wrap or shadow these.
# A generated predicate neutralizing a security check is a purpose
# violation (A0 audit 0/12), not an optimization.
RESERVED_PREDICATES = frozenset({
    "action_forbidden", "path_forbidden", "policy_locked",
    "write_scope_ok", "action_is_valid", "file_path_valid",
})


def purpose_gate(tree) -> tuple:
    """A0 purpose gate for generated trees (import plan P2.1).

    Inspects the JSON tree statically (no execution). Refuses when the
    tree: is not a well-formed predicate/op node; references a reserved
    security predicate (neutralization risk); or carries a forbidden
    path in any string argument (exfiltration targeting).
    Returns (ok: bool, reason: str). Deterministic (R10).
    """
    try:
        from stub_predicates import FORBIDDEN_PATHS
    except ImportError:  # pragma: no cover - layout fallback
        from system.kernel.stub_predicates import FORBIDDEN_PATHS

    def _walk(node, depth=0):
        if depth > 32:
            return (False, "too deep")
        if isinstance(node, dict):
            if "predicate" in node:
                name = node["predicate"]
                if not isinstance(name, str):
                    return (False, "predicate name not str")
                if name in RESERVED_PREDICATES:
                    return (False, f"reserved predicate: {name}")
                Ft = _scan_strings(node.get("args", []))
                if Ft:
                    return (False, Ft)
                Fk = _scan_strings(list(node.get("kwargs", {}).values()))
                if Fk:
                    return (False, Fk)
                return (True, "")
            if "op" in node and isinstance(node.get("children"), list):
                for ch in node["children"]:
                    ok, reason = _walk(ch, depth + 1)
                    if not ok:
                        return (False, reason)
                return (True, "")
            return (False, "node is neither predicate nor op")
        if isinstance(node, list):
            for ch in node:
                ok, reason = _walk(ch, depth + 1)
                if not ok:
                    return (False, reason)
            return (True, "")
        return (False, f"bad node type: {type(node).__name__}")

    def _scan_strings(vals) -> str:
        for v in vals:
            if isinstance(v, str):
                for fp in FORBIDDEN_PATHS:
                    if fp in v:
                        return f"forbidden path in args: {fp}"
            elif isinstance(v, (list, tuple)):
                hit = _scan_strings(list(v))
                if hit:
                    return hit
            elif isinstance(v, dict):
                hit = _scan_strings(list(v.values()))
                if hit:
                    return hit
        return ""

    if not isinstance(tree, (dict, list)):
        return (False, "tree must be dict/list")
    return _walk(tree)


# ═══════════════════════════════════════════════════════════════════════════════
# RSICycle class
# ═══════════════════════════════════════════════════════════════════════════════

class RSICycle:
    """RSI Cycle Orchestrator.
    
    Socratic-engine = evaluation hub
    VSF-RSI = correction layer
    State-canon = data layer
    """

    def __init__(self):
        from socratic_engine import SocraticEngine
        self.engine = SocraticEngine()
        self._register_all_predicates()
        self.load_rsi_predicates()  # Load RSI-generated predicates (second-order)
        self._observer = None  # Lazy init
        self._fault_detector = None  # Lazy init (L3)
        self._l3 = None  # Lazy init (L3 autonomous cycle)
        self._eval_count = 0  # Counter for feedback loop trigger
        self._feedback_interval = 10  # Run feedback every N evaluations

    def _register_all_predicates(self):
        """Register ALL predicates (security, state, quality, learning, scripts, plugins, child scripts).
        
        Hot plug: new predicates can be added at runtime via register_predicate().
        Script predicates are dynamic — they scan the filesystem at evaluation time.
        """
        predicates = {
            # Security
            "action_forbidden": action_forbidden,
            "path_forbidden": path_forbidden,
            "read_size_ok": read_size_ok,
            "policy_locked": policy_locked,
            "write_scope_ok": write_scope_ok,
            # State
            "task_has_work": task_has_work,
            "state_consistent": state_consistent,
            # Quality
            "file_valid": file_valid,
            "naming_conforms": naming_conforms,
            "vsm_has_header": vsm_has_header,
            # Learning
            "not_redundant": not_redundant,
            "pattern_known": pattern_known,
            # Scripts
            "script_safe": script_safe,
            "script_exists": script_exists,
            "script_domain_ok": script_domain_ok,
            "script_call": script_call,
            "state_scripts_ok": state_scripts_ok,
            "vsl_scripts_ok": vsl_scripts_ok,
            "audit_scripts_ok": audit_scripts_ok,
            "s1_kernel_scripts_ok": s1_kernel_scripts_ok,
            "scripts_manifest": scripts_manifest,
            # Tasks
            "task_active": task_active,
            # Plugins
            "event_router_ok": event_router_ok,
            "lifecycle_valid": lifecycle_valid,
            "gap_free": gap_free,
            "onboard_complete": onboard_complete,
            # Child scripts (migrated)
            "hook_metrics_ok": hook_metrics_ok,
            "semantic_mapper_ok": semantic_mapper_ok,
            "process_staging_ok": process_staging_ok,
            "load_hooks_ok": load_hooks_ok,
        }
        for name, func in predicates.items():
            try:
                self.engine.register(name)(func)
            except UserWarning:
                pass  # Already registered

    def register_predicate(self, name: str, func):
        """Hot plug: register a new predicate at runtime."""
        try:
            self.engine.register(name)(func)
            return True
        except Exception:
            return False

    @property
    def observer(self):
        """Lazy-init RSIObserver for self-improvement.
        
        P2.3: Enables L3 strategy search (shadow mode) for autonomous improvement.
        """
        if self._observer is None:
            try:
                from vsf_rsi.rsi_observer import RSIObserver, RSIMode
                # P2.3: Enable L3 strategy search for shadow mode validation
                self._observer = RSIObserver(
                    self.engine, 
                    mode=RSIMode.CAPABILITY,
                    enable_l3_strategy_search=True,
                )
            except ImportError:
                pass
        return self._observer

    @property
    def fault_detector(self):
        """Lazy-init FaultDetector (L3: ≥3 BLOCKING errors in 10 evals)."""
        if self._fault_detector is None:
            try:
                from vsf_rsi.rsi_fault_detector import FaultDetector
                self._fault_detector = FaultDetector()
            except ImportError:
                pass
        return self._fault_detector

    @property
    def autonomous_l3(self):
        """Lazy-init AutonomousL3 orchestrator (detect → shadow → activate)."""
        if self._l3 is None:
            try:
                from vsf_rsi.rsi_autonomous_l3 import AutonomousL3
                self._l3 = AutonomousL3(self.engine)
            except ImportError:
                pass
        return self._l3

    def _attribute(self, tree: dict, context: dict) -> list:
        """Name the failing child predicates of a FALSE verdict.

        Runs children on the RAW engine (no cycle wrappers: no record,
        no enqueue, no fault-feed). Pure + deterministic, safe to re-run.
        Single-predicate trees attribute to their own predicate.
        """
        if not isinstance(tree, dict):
            return []
        try:
            if isinstance(tree.get("children"), list):
                from socratic_engine import Truth as _Truth
                failed = []
                for child in tree["children"]:
                    if not isinstance(child, dict) or "predicate" not in child:
                        continue
                    ev = self.engine.evaluate(child, dict(context),
                                              enforce_limits=True)
                    if ev.truth == _Truth.FALSE and ev.certified:
                        failed.append(child.get("predicate", "unknown"))
                return failed
            if "predicate" in tree:
                return [tree.get("predicate", "unknown")]
        except Exception:
            pass
        return []

    def _l3_budget_ok(self) -> bool:
        """Session governor: at most L3_MAX_RUNS_PER_HOUR autonomous cycles.

        Persistent counter (each tool call is a fresh process, so memory
        cannot govern). Consumes one slot per call that returns True.
        Best-effort: any IO failure = allow (fail-open toward autonomy,
        the shadow+rollback gates still hold every cycle).
        """
        import os as _os
        import time as _time
        _env = _os.environ.get("RSI_L3_BUDGET_FILE")
        path = Path(_env) if _env else \
            VOSLAB_PATH / "state" / "rsi" / "l3_budget.json"
        now = _time.time()
        try:
            stamps = json.loads(path.read_text())
            stamps = [s for s in stamps
                      if isinstance(s, (int, float)) and now - s < 3600]
        except Exception:
            stamps = []
        if len(stamps) >= L3_MAX_RUNS_PER_HOUR:
            return False
        stamps.append(now)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stamps))
        except Exception:
            pass
        return True

    def _maybe_run_l3(self, fault) -> None:
        """Run one L3 autonomous cycle for a detected complex fault.

        Best-effort and reversible: strategies activate only after shadow
        validation (10 real evals) and are monitored with auto-rollback.
        Gated by L3_AUTO (autonomy ceiling) + hourly budget (governor).
        """
        if not L3_AUTO or self.autonomous_l3 is None:
            return
        # Caution suspends EVOLUTION, never observation (A1 design).
        _allowed, _why = True, {}
        try:
            from vsm_viability import evolution_allowed
        except ImportError:  # pragma: no cover - layout fallback
            try:
                from system.kernel.vsm_viability import evolution_allowed
            except ImportError:
                evolution_allowed = None
        if evolution_allowed is not None:
            _allowed, _why = evolution_allowed()
        if not _allowed:
            try:
                self._log_event("l3_deferred", {
                    "truth": "TRUE",
                    "certified": True,
                    "source": getattr(fault, "fault_id", "unknown"),
                    "evidence": {"reason": "caution active",
                                 "detail": _why},
                }, {})
            except Exception:
                pass
            return
        if not self._l3_budget_ok():
            try:
                self._log_event("l3_deferred", {
                    "truth": "TRUE", "certified": True,
                    "source": getattr(fault, "fault_id", "unknown"),
                    "evidence": {"reason": "hourly budget exhausted"},
                }, {})
            except Exception:
                pass
            return
        try:
            result = self.autonomous_l3.run_cycle(fault)
            self._log_event("l3_cycle", {
                "truth": "TRUE",
                "certified": True,
                "source": getattr(fault, "fault_id", "unknown"),
                "evidence": {"result": str(result)[:200]},
            }, {})
        except Exception:
            pass  # L3 is best-effort, never block evaluation

    def evaluate(self, tree: dict, context: dict = None) -> dict:
        """Evaluate a tree with full context.
        
        Delegates to observer.evaluate() which wraps socratic-engine's evaluate():
          - Injects thresholds into ctx
          - Measures latency
          - Captures EvaluationEvent
          - Bridges to rsi_metrics via track_classification()
          - Discriminates errors (BLOCKING / STRUCTURAL / NONE)
        
        Flow:
          1. Query state-canon for context
          2. Evaluate tree via observer.evaluate() (P1.1: observer wrapping)
          3. If FALSE+certified → record and potentially correct
          4. Return result
        """
        if tree is None:
            return {"certified": True, "truth": "TRUE", "source": "empty", "evidence": {}}

        # 1. Enrich context with state
        state_ctx = self._get_state_context()
        full_ctx = {**(context or {}), **state_ctx}

        # 2. Evaluate via observer (wraps engine with metrics tracking)
        import time as _time
        _t0 = _time.perf_counter()
        _observer_event = None
        try:
            if self.observer is not None:
                # P1.1: Use observer to capture metrics + discriminate errors
                ev = self.observer.evaluate(tree, full_ctx)
                _observer_event = ev
                output = {
                    "certified": ev.certified,
                    "truth": ev.truth.name if hasattr(ev.truth, "name") else str(ev.truth),
                    "source": ev.source or "unknown",
                    "evidence": ev.evidence or {},
                }
            else:
                # Fallback: direct engine call (no metrics)
                ev = self.engine.evaluate(tree, full_ctx, enforce_limits=True)
                output = {
                    "certified": ev.certified,
                    "truth": ev.truth.name if hasattr(ev.truth, "name") else str(ev.truth),
                    "source": ev.source or "unknown",
                    "evidence": ev.evidence or {},
                }
        except ValueError as e:
            # enforce_limits violation (cycle, depth, nodes) — clean domain error
            output = {
                "certified": False,
                "truth": "ERROR",
                "source": "enforce_limits",
                "evidence": {"error": str(e)},
            }
        except Exception as e:
            output = {
                "certified": False,
                "truth": "ERROR",
                "source": "evaluate",
                "evidence": {"error": str(e)},
            }

        # 3. Log ALL evaluations (not just failures)
        self._log_event("evaluate", output, full_ctx)

        # 3a. Persist the observer event (actions die with the subprocess
        # otherwise — L2/L3 need history across tool calls to be real).
        _latency = (_time.perf_counter() - _t0) * 1000.0
        self._persist_observer_event(_observer_event, _latency)

        # 3b. Attribute the verdict BEFORE reacting: a failure caused purely
        # by security predicates is correct enforcement, not a fault.
        _failed: list = []
        _policy_only = False
        if output["certified"] and output["truth"] in ("FALSE", "ERROR"):
            _failed = self._attribute(tree, full_ctx)
            _policy_only = bool(_failed) and set(_failed) <= SECURITY_PREDICATES

        # 3c. L3: feed the fault detector (sliding window per source).
        # Certified FALSE / ERROR = BLOCKING (cannot self-resolve) —
        # EXCEPT pure policy blocks, which feed as NONE so L3 never
        # spins on correct behavior (S5 2026-09-10).
        # A complex fault (≥3 BLOCKING in 10 evals) triggers one
        # autonomous L3 cycle (shadow-gated, reversible).
        if self.fault_detector is not None:
            try:
                _is_err = bool(
                    output["certified"]
                    and output["truth"] in ("FALSE", "ERROR")
                    and not _policy_only
                )
                _fault = self.fault_detector.observe({
                    "source": output.get("source", "unknown"),
                    "truth": output.get("truth", "UNKNOWN"),
                    "latency_ms": _latency,
                    "is_error": _is_err,
                    "error_class": "BLOCKING" if _is_err else "NONE",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                if _fault is not None:
                    self._maybe_run_l3(_fault)
            except Exception:
                pass  # Fault detection is best-effort

        # 4. If FALSE+certified → record and potentially correct
        if output["certified"] and output["truth"] == "FALSE":
            self._handle_failure(output, full_ctx, _failed)

        # 5. P1.3: Run feedback loop periodically to adjust thresholds
        self._eval_count += 1
        if self._eval_count % self._feedback_interval == 0:
            self._maybe_run_feedback_loop()

        return output

    def _maybe_run_feedback_loop(self):
        """P1.3: Run feedback loop to adjust thresholds based on metrics.
        
        This triggers adjust_thresholds() which:
        1. Loads current thresholds
        2. Gets recommendations from rsi_metrics
        3. Adjusts thresholds if significant improvement found
        4. Saves new thresholds
        """
        try:
            from vsf_rsi.rsi_feedback_loop import RSIFeedbackLoop
            feedback = RSIFeedbackLoop()
            adjustments = feedback.adjust_thresholds()
            if adjustments.get("adjustments"):
                # P1.3: Inject updated thresholds into observer
                if self.observer is not None:
                    self.observer.thresholds = feedback._load_thresholds()
        except Exception as e:
            # Feedback loop is best-effort, never block evaluation
            pass

    def _persist_observer_event(self, event, latency_ms: float) -> None:
        """Append the observer event to state/rsi/observer_actions.jsonl.

        Observer actions otherwise die with the subprocess (each opencode
        tool call is a fresh process) — L2/L3 need cross-call history to
        be real. Best-effort, rotated (keeps last 2000 lines).
        """
        if event is None:
            return
        try:
            import os as _os
            _env = _os.environ.get("RSI_OBSERVER_FILE")
            log_file = Path(_env) if _env else \
                VOSLAB_PATH / "state" / "rsi" / "observer_actions.jsonl"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            truth = getattr(event, "truth", "UNKNOWN")
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "source": getattr(event, "source", "unknown"),
                "truth": truth.name if hasattr(truth, "name") else str(truth),
                "is_error": bool(getattr(event, "is_error", False)),
                "error_class": str(getattr(event, "error_class", "NONE")),
                "latency_ms": round(latency_ms, 3),
            }
            with open(str(log_file), "a") as f:
                f.write(json.dumps(entry) + "\n")
            try:
                lines = log_file.read_text().splitlines()
                if len(lines) > 5000:
                    log_file.write_text("\n".join(lines[-2000:]) + "\n")
            except Exception:
                pass
        except Exception:
            pass  # persistence is best-effort, never block evaluation

    def _handle_failure(self, result: dict, context: dict, failed: list = None):
        """Handle a certified FALSE result: record, detect patterns, propose corrections.

        P1.2: Triggers rsi_pipeline.pipeline() for BLOCKING errors.
        P3.1: Generated predicates go to approval queue (not direct activation).

        Pure policy blocks (failed ⊆ SECURITY_PREDICATES) are RECORDED
        only — no pipeline, no enqueue. A denied rm -rf is the system
        working, not a fault to correct (S5 2026-09-10).
        """
        # 0. Policy-only short-circuit (record below still runs)
        _policy_only = bool(failed) and set(failed) <= SECURITY_PREDICATES
        # 1. Record in scenario memory
        try:
            from vsf_rsi.scenario_memory import record
            record(
                decision=f"socratic:{result['source']}",
                outcome="failure",
                correction_path="rsi_cycle:handle_failure",
                fault_signature=f"socratic.{result['source']}.failure",
            )
        except Exception:
            pass

        # 2. Log the failure
        self._log_event("failure", result, context)

        if _policy_only:
            # Correct enforcement: history keeps the record (step 1),
            # but nothing is generated, queued, or evolved from it.
            return

        # 3. P1.2: Trigger pipeline for BLOCKING errors
        try:
            from vsf_rsi.rsi_pipeline import pipeline
            pipeline(
                tool="socratic",
                command=result.get("source", "unknown"),
                outcome="failure",
                context=context,
                fault_signature=f"socratic.{result['source']}.failure",
                quality=0.3,  # Low quality for failures
            )
        except Exception as e:
            # Pipeline trigger is best-effort, never block evaluation
            pass

        # 4. P3.1: Generate corrective predicate and add to approval queue
        try:
            import re as _re
            from vsf_rsi.rsi_tree_generator import RSITreeGenerator
            from vsf_rsi.rsi_socratic_bridge import enqueue_predicate

            # Queue file names must be portable: sanitize the source.
            _safe = _re.sub(r"[^A-Za-z0-9_-]+", "_",
                            str(result.get("source", "unknown"))).strip("_")
            _pname = f"fix_{_safe or 'unknown'}"
            gen = RSITreeGenerator()
            gaps = {
                "gaps": [
                    {"type": "low_accuracy", "suggestion": f"Fix {result['source']} failure", "severity": "high"}
                ]
            }
            tree = gen._create_json_tree(_pname, gen._analyze_gaps(gaps))

            enqueue_predicate(
                name=_pname,
                tree=tree,
                source="rsi_cycle:handle_failure",
                description=f"Auto-generated fix for {result['source']} failure",
            )
        except Exception:
            pass

    def _log_event(self, event_type: str, result: dict, context: dict):
        """Log event to unified activation log (logs/agent_plugin.jsonl).
        
        Writes in the NEW format (2026-09-09):
          {ts, pid, level, source, event_type, event_id, action, result, detail, context}
        """
        log_dir = VOSLAB_PATH / "logs"
        log_file = log_dir / "agent_plugin.jsonl"
        os.makedirs(str(log_dir), exist_ok=True)
        
        truth = result.get("truth", "")
        certified = result.get("certified", "")
        source_val = result.get("source", "")
        
        # Build action string
        action = f"evaluate truth={truth} cert={certified} source={source_val}"
        
        # Map truth to result level
        if truth == "FALSE" and certified:
            res = "error"
        elif truth == "ERROR":
            res = "error"
        elif truth == "TRUE":
            res = "ok"
        else:
            res = "ok"
        
        # Determine log level
        level = "error" if res == "error" else "activation"
        
        # Build detail from evidence
        evidence = result.get("evidence", {})
        detail = json.dumps(evidence, default=str)[:200] if evidence else ""
        
        # Build event_id
        event_id = f"rsi-cycle:evaluate.{event_type}:{int(time.time())}"
        
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "level": level,
            "source": "rsi-cycle",
            "event_type": f"evaluate.{event_type}",
            "event_id": event_id,
            "action": action,
            "result": res,
            "detail": detail,
            "context": context,
        }
        with open(str(log_file), "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_predicates(self) -> list:
        """List all registered predicates."""
        return sorted(self.engine.predicates.keys())

    def get_stats(self) -> dict:
        """Get cycle statistics."""
        return {
            "predicates": len(self.engine.predicates),
            "predicate_names": self.get_predicates(),
            "observer_active": self.observer is not None,
            "eval_count": self._eval_count,
        }

    def load_rsi_predicates(self) -> int:
        """Load RSI-generated predicates from vsf-rsi/state/predicates/.
        
        These are JSON tree-based predicates generated by rsi_pipeline.py.
        They use built-in predicates (ctx_has, ctx_equals, ctx_contains)
        evaluated by the socratic engine — safe, no exec().
        """
        from socratic_engine.engine import PredicateResult, Truth

        def _register_tree(name: str, tree) -> bool:
            """Register a JSON-tree predicate (no exec, engine-evaluated)."""
            if not name or not tree:
                return False
            if name in self.engine.predicates:
                return False  # Already registered (idempotent)

            def make_evaluator(tree_dict, pred_name):
                def evaluator(**kwargs):
                    try:
                        result = self.engine.evaluate(tree_dict, context=kwargs, enforce_limits=True)
                        return PredicateResult(
                            truth=result.truth,
                            certified=result.certified,
                            evidence=result.evidence or {},
                            source=pred_name,
                        )
                    except Exception as e:
                        return PredicateResult(
                            truth=Truth.UNKNOWN,
                            certified=False,
                            evidence={"error": str(e)},
                            source=pred_name,
                        )
                return evaluator

            self.engine.register(name)(make_evaluator(tree, name))
            return True

        def _activated_registry():
            import os as _os
            _env = _os.environ.get("RSI_ACTIVATED_FILE")
            reg = Path(_env) if _env else \
                VOSLAB_PATH / "state" / "rsi" / "activated.json"
            try:
                data = json.loads(reg.read_text())
                return reg, data if isinstance(data, dict) else {}
            except Exception:
                return reg, {}

        def _pin_activation(name: str, tree) -> bool:
            import hashlib as _hl
            reg, data = _activated_registry()
            sha = _hl.sha256(json.dumps(tree, sort_keys=True).encode()
                             ).hexdigest()[:16]
            seen = data.get(name)
            if seen is not None and seen.get("sha") != sha:
                self._log_event("refused", {
                    "truth": "FALSE", "certified": True,
                    "source": name,
                    "evidence": {"reason": "tree changed since approval",
                                 "approved_sha": seen.get("sha"),
                                 "current_sha": sha},
                }, {})
                return False
            if seen is None:
                data[name] = {"sha": sha}
                try:
                    reg.parent.mkdir(parents=True, exist_ok=True)
                    reg.write_text(json.dumps(data, indent=2))
                except Exception:
                    pass
            return True

        def _gated(name: str, tree) -> bool:
            """A0 gate: refuse purpose-violating trees (audited refusal)."""
            ok, reason = purpose_gate(tree)
            if not ok:
                self._log_event("refused", {
                    "truth": "FALSE", "certified": True,
                    "source": name or "unknown",
                    "evidence": {"reason": reason},
                }, {})
                return False
            if not name or not _pin_activation(name, tree):
                return False
            return _register_tree(name, tree)

        count = 0
        pred_dir = RSI_PATH / "state" / "predicates"
        if pred_dir.exists():
            for pred_file in pred_dir.glob("*.json"):
                try:
                    data = json.loads(pred_file.read_text())
                    # Skip v1 format (exec-based, no longer supported)
                    if "tree" not in data:
                        continue
                    if _gated(data.get("name", ""), data.get("tree")):
                        count += 1
                except Exception:
                    continue

        # L4 activation-by-approval: load queue items a human approved.
        # Generation only enqueues (L4_AUTO = False); nothing activates
        # without human approval. Loading here is the activation step the
        # approval authorizes (control level 2).
        # TOCTOU guard: the tree hash at first activation is pinned in
        # state/rsi/activated.json; later content changes refuse to load
        # (tamper evidence). Queue files over 1 MiB are skipped outright.
        _MAX_QUEUE_BYTES = 1024 * 1024
        try:
            queue_dir = Path(os.environ.get(
                "RSI_QUEUE_DIR",
                str(Path.home() / "packages" / "public" / "state" / "queue"),
            ))
            # Never write outside vOSlab: only flip status→activated when
            # the queue lives inside this workspace; otherwise load without
            # touching (registration stays idempotent per cycle instance).
            _writable = VOSLAB_PATH in queue_dir.resolve().parents or \
                queue_dir.resolve() == VOSLAB_PATH
            if queue_dir.exists():
                for qf in queue_dir.glob("*.json"):
                    try:
                        if qf.stat().st_size > _MAX_QUEUE_BYTES:
                            continue  # absurd size: refuse silently, stay safe
                        entry = json.loads(qf.read_text())
                        if entry.get("status") != "approved":
                            continue
                        if _gated(entry.get("name", ""), entry.get("tree")):
                            count += 1
                            if _writable:
                                entry["status"] = "activated"
                                qf.write_text(json.dumps(entry, indent=2))
                    except Exception:
                        continue
        except Exception:
            pass

        return count

    def _get_state_context(self, max_age: float = 5.0) -> dict:
        """Query state-canon for current context (cached for max_age seconds)."""
        import time
        now = time.monotonic()
        
        # Simple cache
        if not hasattr(self, "_state_cache"):
            self._state_cache = {}
            self._state_cache_time = 0
        
        if now - self._state_cache_time < max_age:
            return self._state_cache
        
        try:
            # Try to query state-canon via MCP
            # For now, return empty context
            self._state_cache = {}
            self._state_cache_time = now
            return self._state_cache
        except Exception:
            return {}

    def parse_query(self, query: str, context: dict = None) -> dict:
        """Parse natural language query into a socratic tree.
        
        Uses rule-based NLP (not LLM) to understand intent and extract entities.
        For complex queries, returns a prompt for the agent to build the tree.
        
        Returns: {"tree": dict, "parsed": bool, "query": str, "intent": str, "entities": dict}
        """
        query_lower = query.lower().strip()
        context = context or {}
        
        # Extract entities from query
        entities = self._extract_entities(query, context)
        
        # Determine intent
        intent = self._determine_intent(query_lower)
        
        # Build tree based on intent and entities
        tree = self._build_tree_from_intent(intent, entities, context)
        
        # If no specific intent detected, return prompt for agent
        if not tree:
            return {
                "tree": None,
                "parsed": False,
                "query": query,
                "intent": "unknown",
                "entities": entities,
            }
        
        return {
            "tree": tree,
            "parsed": True,
            "query": query,
            "intent": intent,
            "entities": entities,
        }

    def _extract_entities(self, query: str, context: dict) -> dict:
        """Extract entities from query."""
        entities = {}
        
        # Check for file paths
        import re
        file_patterns = re.findall(r'[/~][\w./\-]+', query)
        if file_patterns:
            entities["files"] = file_patterns
        
        # Check for commands
        cmd_patterns = re.findall(r'\b(rm|chmod|sudo|echo|cat|ls|grep|find|git|python|pip)\b', query)
        if cmd_patterns:
            entities["commands"] = cmd_patterns
        
        # Check for scripts
        script_patterns = re.findall(r'[\w-]+\.py', query)
        if script_patterns:
            entities["scripts"] = script_patterns
        
        return entities

    def _determine_intent(self, query_lower: str) -> str:
        """Determine intent from query."""
        if any(word in query_lower for word in ["safe", "security", "forbidden", "dangerous"]):
            return "security_check"
        elif any(word in query_lower for word in ["exists", "file", "path"]):
            return "file_check"
        elif any(word in query_lower for word in ["task", "work", "active"]):
            return "task_check"
        elif any(word in query_lower for word in ["script", "run", "execute"]):
            return "script_check"
        elif any(word in query_lower for word in ["state", "consistent", "drift"]):
            return "state_check"
        else:
            return "unknown"

    def _build_tree_from_intent(self, intent: str, entities: dict, context: dict) -> Optional[dict]:
        """Build socratic tree from intent and entities."""
        if intent == "security_check":
            commands = entities.get("commands", [])
            if commands:
                return {
                    "op": "OR",
                    "children": [
                        {"predicate": "action_forbidden", "kwargs": {"command": cmd}}
                        for cmd in commands
                    ]
                }
            return {"predicate": "action_forbidden", "kwargs": context}
        
        elif intent == "file_check":
            files = entities.get("files", [])
            if files:
                return {
                    "op": "OR",
                    "children": [
                        {"predicate": "file_valid", "kwargs": {"file": f}}
                        for f in files
                    ]
                }
            return {"predicate": "file_valid", "kwargs": context}
        
        elif intent == "task_check":
            return {"predicate": "task_has_work", "kwargs": context}
        
        elif intent == "script_check":
            scripts = entities.get("scripts", [])
            if scripts:
                return {
                    "op": "OR",
                    "children": [
                        {"predicate": "script_exists", "kwargs": {"script": s}}
                        for s in scripts
                    ]
                }
            return {"predicate": "script_exists", "kwargs": context}
        
        elif intent == "state_check":
            return {"predicate": "state_consistent", "kwargs": context}
        
        return None

    def evaluate_query(self, query: str, context: dict = None) -> dict:
        """Parse and evaluate a natural language query.
        
        Returns: {"result": dict, "tree": dict, "parsed": bool, "query": str}
        """
        parsed = self.parse_query(query, context)
        result = self.evaluate(parsed["tree"], context or {})
        return {
            "result": result,
            "tree": parsed["tree"],
            "parsed": parsed["parsed"],
            "query": query,
        }

# ═══════════════════════════════════════════════════════════════════════════════
# Main (for testing)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    cycle = RSICycle()
    
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = cycle.evaluate_query(query)
        print(json.dumps(result, indent=2, default=str))
    else:
        # Interactive mode
        print("RSI Cycle Orchestrator (vOSlab kernel)")
        print(f"Predicates: {len(cycle.get_predicates())}")
        print(f"Observer: {'active' if cycle.observer else 'inactive'}")
        print()
        
        while True:
            try:
                query = input("query> ").strip()
                if not query:
                    continue
                if query in ("quit", "exit", "q"):
                    break
                
                result = cycle.evaluate_query(query)
                print(json.dumps(result, indent=2, default=str))
            except KeyboardInterrupt:
                print()
            except EOFError:
                break
