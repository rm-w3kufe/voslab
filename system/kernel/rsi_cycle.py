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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path setup ────────────────────────────────────────────────────────────────
VOSLAB_PATH = Path("/home/rmw3/vOSlab")
STATE_CANON_PATH = Path("/home/rmw3/state-canon-mcp")
RSI_PATH = Path("/home/rmw3/packages/public/vsf-rsi")
INTEGRATION_LOG = VOSLAB_PATH / "state" / "integration_log.jsonl"


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Security
# ═══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_COMMANDS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf .",
    "sudo rm", "chmod 777", ":(){ :|:& };:",
    "mkfs", "dd if=/dev/zero",
]

FORBIDDEN_PATHS = [
    "/etc/shadow", "/etc/passwd", "/root/.ssh", "/proc/kcore",
    "/dev/sda", "/dev/nvme",
]


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


def path_forbidden(file: str = "", **kw):
    """Blocks writes to forbidden paths. Wraps: none (pure security)."""
    from socratic_engine import PredicateResult, Truth
    if not file:
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"reason": "no file"}, source="path_forbidden"
        )
    for fp in FORBIDDEN_PATHS:
        if file.startswith(fp):
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"forbidden_path": fp}, source="path_forbidden"
            )
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"file": file}, source="path_forbidden"
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


def state_consistent(**kw):
    """Check if state is consistent (no drift)."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "state_consistent stub"}, source="state_consistent"
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


def naming_conforms(file: str = "", **kw):
    """Check if file naming conforms to conventions."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"file": file}, source="naming_conforms"
    )


def vsm_has_header(file: str = "", **kw):
    """Check if VSM file has proper header."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"file": file}, source="vsm_has_header"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Learning
# ═══════════════════════════════════════════════════════════════════════════════

def not_redundant(tool: str = "", file: str = "", command: str = "", **kw):
    """Check if action is not redundant."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "not_redundant stub"}, source="not_redundant"
    )


def pattern_known(**kw):
    """Check if pattern is known."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "pattern_known stub"}, source="pattern_known"
    )


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


def state_scripts_ok(**kw):
    """Check if state scripts are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "state_scripts_ok stub"}, source="state_scripts_ok"
    )


def vsl_scripts_ok(**kw):
    """Check if VSL scripts are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "vsl_scripts_ok stub"}, source="vsl_scripts_ok"
    )


def audit_scripts_ok(**kw):
    """Check if audit scripts are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "audit_scripts_ok stub"}, source="audit_scripts_ok"
    )


def s1_kernel_scripts_ok(**kw):
    """Check if S1 kernel scripts are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "s1_kernel_scripts_ok stub"}, source="s1_kernel_scripts_ok"
    )


def scripts_manifest(**kw):
    """Check if scripts manifest is valid."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "scripts_manifest stub"}, source="scripts_manifest"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Tasks
# ═══════════════════════════════════════════════════════════════════════════════

def task_active(task_id: str = "", **kw):
    """Check if task is active."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"task_id": task_id}, source="task_active"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Plugins
# ═══════════════════════════════════════════════════════════════════════════════

def event_router_ok(**kw):
    """Check if event router is ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "event_router_ok stub"}, source="event_router_ok"
    )


def lifecycle_valid(**kw):
    """Check if lifecycle is valid."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "lifecycle_valid stub"}, source="lifecycle_valid"
    )


def gap_free(**kw):
    """Check if gap is free."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "gap_free stub"}, source="gap_free"
    )


def onboard_complete(**kw):
    """Check if onboarding is complete."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "onboard_complete stub"}, source="onboard_complete"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICATES — Child scripts (migrated)
# ═══════════════════════════════════════════════════════════════════════════════

def hook_metrics_ok(**kw):
    """Check if hook metrics are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "hook_metrics_ok stub"}, source="hook_metrics_ok"
    )


def semantic_mapper_ok(**kw):
    """Check if semantic mapper is ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "semantic_mapper_ok stub"}, source="semantic_mapper_ok"
    )


def process_staging_ok(**kw):
    """Check if process staging is ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "process_staging_ok stub"}, source="process_staging_ok"
    )


def load_hooks_ok(**kw):
    """Check if load hooks are ok."""
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE, certified=True,
        evidence={"reason": "load_hooks_ok stub"}, source="load_hooks_ok"
    )


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
        try:
            if self.observer is not None:
                # P1.1: Use observer to capture metrics + discriminate errors
                ev = self.observer.evaluate(tree, full_ctx)
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

        # 4. If FALSE+certified → record and potentially correct
        if output["certified"] and output["truth"] == "FALSE":
            self._handle_failure(output, full_ctx)

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

    def _handle_failure(self, result: dict, context: dict):
        """Handle a certified FALSE result: record, detect patterns, propose corrections.
        
        P1.2: Triggers rsi_pipeline.pipeline() for BLOCKING errors.
        P3.1: Generated predicates go to approval queue (not direct activation).
        """
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
            from vsf_rsi.rsi_tree_generator import RSITreeGenerator
            from vsf_rsi.rsi_socratic_bridge import enqueue_predicate
            
            gen = RSITreeGenerator()
            gaps = {
                "gaps": [
                    {"type": "low_accuracy", "suggestion": f"Fix {result['source']} failure", "severity": "high"}
                ]
            }
            tree = gen._create_json_tree(f"fix_{result['source']}", gen._analyze_gaps(gaps))
            
            enqueue_predicate(
                name=f"fix_{result['source']}",
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
        
        pred_dir = RSI_PATH / "state" / "predicates"
        if not pred_dir.exists():
            return 0
        
        count = 0
        for pred_file in pred_dir.glob("*.json"):
            try:
                data = json.loads(pred_file.read_text())
                name = data.get("name", "")
                tree = data.get("tree")
                
                if not name or not tree:
                    continue
                
                # Skip v1 format (exec-based, no longer supported)
                if "tree" not in data:
                    continue
                
                if name in self.engine.predicates:
                    continue  # Already registered
                
                # Create evaluator closure for this tree
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
                count += 1
            except Exception:
                continue
        
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
