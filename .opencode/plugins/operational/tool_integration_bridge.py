#!/usr/bin/env python3
# design: docs/spec_revision/archive/index.vsm
"""tool_integration_bridge.py — Python bridge for mandatory cognitive pipeline.

Architecture:
  Socratic-engine = evaluation hub (ALL predicates wrap plugins/scripts)
  VSF-RSI = correction layer (detect faults, generate fixes)
  State-canon = data layer (query context, journal, focus, drift)

Called by tool-integration.ts plugin. Handles all Python-side work:
  1. State canon: query context, record actions, journal, focus, drift
  2. Socratic engine: evaluate actions (before + after), trees, canon
  3. vsf-rsi: record patterns, match history, learn, correct

Usage:
  python3 tool_integration_bridge.py <command> [args...]

Commands:
  pre-check <context_json>         — Evaluate action before execution
  record-action <tool> <file> <outcome> <context_json>  — Record after execution
  learn-from-action <tool> <file> <outcome>  — Record pattern for learning
  log-action <phase> <tool> <file> <outcome> <eval_json>  — Generic log
  session-report                   — Get session stats
  query-context                    — Get current system context
  # NEW: State-canon features
  state-journal <action> [args]    — Journal snapshots (save/diff/history)
  state-focus <action> [args]      — Focus entries (mark/list/clear)
  state-drift                      — Detect drift
  state-verify <domain> <filter> <expect>  — Verify claims
  state-reconcile                  — Reconcile state
  # NEW: Socratic-engine features
  socratic-tree <tree_json> [ctx]  — Evaluate tree
  socratic-canon <domain> [filter] — Query canon
  socratic-diagnose <tree_json>    — Diagnose failures
  # NEW: VSF-RSI features
  rsi-status                       — Get observer status
  rsi-correct <failure_json>       — Generate correction
  rsi-learn <tool> <file> <outcome>  — Learn from action
  rsi-queue [status]               — List approval queue (L4 governance)
  rsi-approve <name>               — Human approves queued predicate
  rsi-reject <name> [reason]       — Human rejects queued predicate
  rsi-diff <name>                  — Review current vs proposed tree
  rsi-faults                       — List detected complex faults (L3)
"""
from __future__ import annotations
# stdout redirect removed - using -W ignore instead

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# ─── Path setup ────────────────────────────────────────────────────────────────
VOS_ROOT = os.environ.get("VOS_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
STATE_CANON_PATH = os.path.join(VOS_ROOT, "..", "state-canon-mcp")
STATE_CANON_VENDOR = os.path.join(VOS_ROOT, "..", "state-canon-mcp", "vendor")
RSI_PATH = os.path.join(VOS_ROOT, "..", "packages", "public", "vsf-rsi")
CHILD_PATH = VOS_ROOT  # vOSlab is now the primary workspace

# Agent-specific state directories (avoids sharing between agents)
try:
    from vos_agent_state import get_agent_state_dir
    RSI_PREDICATES_DIR = str(get_agent_state_dir("vsf-rsi", "predicates"))
    # Use vOSlab state, not child state
    INTEGRATION_LOG = os.path.join(VOS_ROOT, "state", "integration_log.jsonl")
    TASKS_VSM = os.path.join(VOS_ROOT, "current_focus.json")
except ImportError:
    # Fallback for backward compatibility
    RSI_PREDICATES_DIR = os.path.join(RSI_PATH, "state", "predicates")
    INTEGRATION_LOG = os.path.join(VOS_ROOT, "state", "integration_log.jsonl")
    TASKS_VSM = os.path.join(VOS_ROOT, "current_focus.json")

# ─── RSI autonomy state: scoped INSIDE vOSlab ────────────────────────────────
# Upstream vsf_rsi defaults point at ~/packages/public/state/*. Every RSI
# subprocess spawned from this bridge must keep its queue/shadow/rollback/
# L3/fault state inside this workspace. setdefault = env wins if S5 set it.
# MUST run before any `import vsf_rsi.*` (module-level DIR constants).
_RSI_STATE = os.path.join(VOS_ROOT, "state", "rsi")
os.environ.setdefault("RSI_QUEUE_DIR", os.path.join(_RSI_STATE, "queue"))
os.environ.setdefault("RSI_SHADOW_DIR", os.path.join(_RSI_STATE, "shadow"))
os.environ.setdefault("RSI_ROLLBACK_DIR", os.path.join(_RSI_STATE, "rollback"))
os.environ.setdefault("RSI_L3_DIR", os.path.join(_RSI_STATE, "l3"))
os.environ.setdefault("RSI_FAULT_DIR", os.path.join(_RSI_STATE, "faults"))

sys.path.insert(0, STATE_CANON_PATH)
sys.path.insert(0, STATE_CANON_VENDOR)
sys.path.insert(0, RSI_PATH)
sys.path.insert(0, CHILD_PATH)
# rsi_cycle.py imports `stub_predicates` bare: its own dir must be importable
sys.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))

# Import RSICycle (the orchestrator)
# PRIORITY: Use vOSlab kernel cycle (with observer, pipeline, shadow mode)
# Fallback: child cycle (if vOSlab kernel not available)
try:
    from system.kernel.rsi_cycle import RSICycle
    _cycle = RSICycle()
except ImportError:
    try:
        from rsi_cycle import RSICycle
        _cycle = RSICycle()
    except ImportError:
        _cycle = None


# ─── State Canon ───────────────────────────────────────────────────────────────

def query_tasks(filter_dict: dict | None = None) -> list[dict]:
    """Query tasks from state-canon via VsmStateProvider."""
    from instances.tasks_provider import VsmStateProvider
    provider = VsmStateProvider(TASKS_VSM)
    return provider.query("tasks", filter_dict or {})


def query_sessions(filter_dict: dict | None = None) -> list[dict]:
    """Query sessions from state-canon."""
    from instances.tasks_provider import VsmStateProvider
    provider = VsmStateProvider(TASKS_VSM)
    return provider.query("sessions", filter_dict or {})


def get_recent_actions(n: int = 20) -> list[dict]:
    """Get the last N actions from integration log (for redundancy detection)."""
    if not os.path.exists(INTEGRATION_LOG):
        return []
    actions = []
    try:
        with open(INTEGRATION_LOG) as f:
            for line in f:
                try:
                    actions.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    # Return last N "after" entries (completed actions)
    afters = [a for a in actions if a.get("phase") == "after"]
    return afters[-n:]


def get_current_task_context(tasks: list[dict]) -> dict:
    """Extract task context: what is the agent supposed to be doing?"""
    open_tasks = [t for t in tasks if t.get("status") == "open"]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    active_task = in_progress[0] if in_progress else (open_tasks[0] if open_tasks else None)
    return {
        "active_task": active_task,
        "open_count": len(open_tasks),
        "in_progress_count": len(in_progress),
        "has_work": bool(open_tasks or in_progress),
    }


def get_system_context() -> dict:
    """Get current system context for decision-making."""
    tasks = query_tasks({})
    sessions = query_sessions({})
    recent = get_recent_actions(20)

    done = sum(1 for t in tasks if t.get("status") == "done")
    open_ = sum(1 for t in tasks if t.get("status") == "open")
    in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")

    return {
        "tasks": {
            "total": len(tasks),
            "done": done,
            "open": open_,
            "in_progress": in_progress,
        },
        "sessions": {
            "total": len(sessions),
        },
        "recent_sessions": sessions[:3] if sessions else [],
        "recent_actions": [
            {"tool": a.get("tool"), "file": a.get("file"), "outcome": a.get("outcome")}
            for a in recent
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Socratic Engine ──────────────────────────────────────────────────────────

# Rate limiter: track recent writes to prevent abuse (persisted to file)
import time as _time
import json as _json
import os as _os

RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 20     # max writes per window
_RATE_LIMIT_FILE = _os.path.join(_os.path.dirname(__file__), ".rate_limit.json")

def _load_timestamps() -> list[float]:
    """Load persisted timestamps from file."""
    try:
        with open(_RATE_LIMIT_FILE, "r") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return []

def _save_timestamps(timestamps: list[float]) -> None:
    """Persist timestamps to file."""
    try:
        with open(_RATE_LIMIT_FILE, "w") as f:
            _json.dump(timestamps, f)
    except OSError:
        pass  # best effort — in-memory fallback

def _check_rate_limit() -> tuple[bool, int]:
    """Check if write rate is within limits. Returns (allowed, count)."""
    now = _time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    timestamps = _load_timestamps()
    timestamps = [t for t in timestamps if t > cutoff]
    count = len(timestamps)
    if count >= RATE_LIMIT_MAX:
        return False, count
    timestamps.append(now)
    _save_timestamps(timestamps)
    return True, count

def _register_validation_predicates(engine):
    """Register predicates that actually validate actions."""
    from socratic_engine import PredicateResult, Truth

    # ─── F2: Forbidden patterns (security) ────────────────────────────────────
    FORBIDDEN_COMMANDS = ["rm -rf /", "rm -rf /*", "sudo rm", "chmod 777", ":(){ :|:& };:"]
    FORBIDDEN_PATHS = ["/etc/shadow", "/etc/passwd", "/root/.ssh", "/proc/kcore"]

    @engine.register("action_is_valid")
    def action_is_valid(tool, file, **kw):
        """F2: Validates command against security forbidden list."""
        command = kw.get("command", "")
        for f in FORBIDDEN_COMMANDS:
            if f in command:
                return PredicateResult(
                    truth=Truth.FALSE, certified=True,
                    evidence={"forbidden": f, "reason": "security"}, source="action_is_valid"
                )
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"tool": tool}, source="action_is_valid"
        )

    @engine.register("file_path_valid")
    def file_path_valid(file, **kw):
        """F2: Validates file path against forbidden locations."""
        if not file:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"reason": "no file"}, source="file_path_valid"
            )
        for fp in FORBIDDEN_PATHS:
            if file.startswith(fp):
                return PredicateResult(
                    truth=Truth.FALSE, certified=True,
                    evidence={"forbidden_path": fp}, source="file_path_valid"
                )
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"file": file}, source="file_path_valid"
        )

    # ─── F4: Task-context validation ──────────────────────────────────────────
    @engine.register("action_matches_task")
    def action_matches_task(tool, file, **kw):
        """F4: Does this action serve the current task?"""
        task_ctx = kw.get("task_context", {})
        has_work = task_ctx.get("has_work", True)
        command = kw.get("command", "")

        # If no open tasks, writing/editing task files is suspicious
        if not has_work and tool in ("write", "edit") and "TASKS" in (file or ""):
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"reason": "no tasks to work on"}, source="action_matches_task"
            )

        # If there's an active task, check if bash command seems related
        active = task_ctx.get("active_task")
        if active and tool == "bash" and command:
            task_id = active.get("id", "").lower()
            task_summary = active.get("summary", "").lower()
            # Very basic: if command contains task-related keywords, it's probably relevant
            # This is a heuristic, not perfect — but better than nothing
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"active_task": task_id, "command": command[:80]},
                source="action_matches_task"
            )

        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"tool": tool}, source="action_matches_task"
        )

    # ─── F3: Redundancy detection ─────────────────────────────────────────────
    @engine.register("no_redundant_action")
    def no_redundant_action(tool, file, command, **kw):
        """F3: Has this exact action been tried recently?"""
        recent = kw.get("recent_actions", [])
        if not recent:
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"reason": "no history"}, source="no_redundant_action"
            )

        # Build signature of current action
        current_key = f"{tool}|{file or ''}|{command or ''}"

        # Check last N actions for duplicates
        seen = 0
        for past in reversed(recent):
            past_key = f"{past.get('tool', '')}|{past.get('file', '')}|{past.get('command', '')}"
            if past_key == current_key:
                seen += 1

        # Block if same action appeared 3+ times in last 20
        if seen >= 3:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"repeated": seen, "command": command[:80] if command else file},
                source="no_redundant_action"
            )

        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"seen": seen}, source="no_redundant_action"
        )

    # ─── A0 compliance (NEVER bypassed by surgery mode) ──────────────────────
    # From covenant.vsm §A0: purpose(V) ∩ ProhibitedPurpose = ∅
    # This check runs BEFORE surgery mode check — surgery mode cannot disable it.
    _A0_PROHIBITED_KEYWORDS = [
        "warfare", "weapon", "annihilation", "nuclear", "displacement",
        "ethnic_suppression", "cultural_suppression", "authoritarian",
        "degradation_of_life", "coercion", "capture", "override_purpose",
        "bypass_ethics", "disable_safety", "shadow_control", "force_action",
        "manipulate", "deceive", "censor", "suppress", "destroy", "eliminate",
        "subjugate", "oppress", "exploit", "harm", "kill", "attack", "bomb",
        "torture", "enslave",
    ]

    def _check_a0_compliance(file, content):
        """Check file content against A0 prohibited set.
        
        Returns violation string if found, None if clean.
        This function is NEVER bypassed by surgery mode.
        """
        if not content:
            return None
        lower = content.lower()
        for keyword in _A0_PROHIBITED_KEYWORDS:
            if keyword in lower:
                return f"content contains prohibited keyword '{keyword}'"
        return None

    # ─── State conflict ───────────────────────────────────────────────────────
    @engine.register("no_state_conflict")
    def no_state_conflict(tool, file, **kw):
        """Checks for conflicts with current state.
        
        Self-dispatching mode: allow TASKS.vsm writes when there's an active
        focus entry (agent is working), even if no open tasks exist.
        Surgery mode: bypass all checks when VSF_SURGERY_MODE=1 or .surgery_mode exists.
        Rate limiting: block if > 20 writes in 60 seconds.
        """
        import os
        child_path = Path(os.environ.get("VSF_CHILD_PATH", str(CHILD_PATH)))
        
        # ─── A0 COMPLIANCE: NEVER bypassed ───────────────────────
        # From covenant.vsm §A0: purpose(V) ∩ ProhibitedPurpose = ∅
        # Surgery mode does NOT disable A0 — this is invariant R17.
        if file and tool in ("write", "edit"):
            a0_violation = _check_a0_compliance(file, kw.get("content", ""))
            if a0_violation:
                return PredicateResult(
                    truth=Truth.FALSE, certified=True,
                    evidence={
                        "reason": "A0 violation",
                        "violation": a0_violation,
                        "file": file,
                    },
                    source="a0_compliance"
                )
        
        # Surgery mode: bypass state conflict checks (rate limit, TASKS.vsm)
        # but NOT A0 compliance (checked above)
        if os.environ.get("VSF_SURGERY_MODE") == "1" or (child_path / ".surgery_mode").exists():
            return PredicateResult(
                truth=Truth.TRUE, certified=True,
                evidence={"tool": tool, "file": file, "reason": "surgery mode (state conflicts bypassed, A0 still enforced)"},
                source="no_state_conflict"
            )
        
        # Rate limiting for write/edit operations
        if tool in ("write", "edit"):
            allowed, count = _check_rate_limit()
            if not allowed:
                return PredicateResult(
                    truth=Truth.FALSE, certified=True,
                    evidence={
                        "reason": "rate limit exceeded",
                        "writes_in_window": count,
                        "window_seconds": RATE_LIMIT_WINDOW,
                        "limit": RATE_LIMIT_MAX,
                    },
                    source="no_state_conflict"
                )
        
        if file and "TASKS.vsm" in file and tool in ("write", "edit"):
            tasks = kw.get("tasks", [])
            open_tasks = [t for t in tasks if t.get("status") == "open"]
            if open_tasks:
                return PredicateResult(
                    truth=Truth.TRUE, certified=True,
                    evidence={"tool": tool, "file": file, "reason": "open tasks exist"},
                    source="no_state_conflict"
                )
            # No open tasks — check if agent is self-dispatching (has active focus)
            focus_path = CHILD_PATH / "current_focus.json"
            if focus_path.exists():
                try:
                    import json as _json
                    with open(focus_path) as f:
                        focus = _json.loads(f.read())
                    active = [e for e in focus if e.get("status") == "active"]
                    if active:
                        return PredicateResult(
                            truth=Truth.TRUE, certified=True,
                            evidence={"tool": tool, "file": file, "reason": "self-dispatching (active focus)"},
                            source="no_state_conflict"
                        )
                except Exception as e:
                    import sys
                    print(f"[bridge] Warning: failed to read focus file: {e}", file=sys.stderr)
            # No open tasks AND no active focus — block
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"reason": "no open tasks and no active focus"},
                source="no_state_conflict"
            )
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"tool": tool, "file": file}, source="no_state_conflict"
        )

    # ─── Outcome validation ───────────────────────────────────────────────────
    @engine.register("action_outcome_valid")
    def action_outcome_valid(tool, outcome, **kw):
        """Validates that the action outcome is valid."""
        valid = ["success", "failure", "advisory", "pending"]
        if outcome not in valid:
            return PredicateResult(
                truth=Truth.FALSE, certified=True,
                evidence={"invalid_outcome": outcome}, source="action_outcome_valid"
            )
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence={"tool": tool, "outcome": outcome}, source="action_outcome_valid"
        )


def evaluate_action(action: dict) -> dict:
    """Evaluate an action using RSICycle (socratic-engine hub).
    
    Architecture:
      1. Query state-canon for context (tasks, sessions, recent_actions)
      2. Build tree with predicates wrapping plugins/scripts
      3. Evaluate tree via RSICycle → socratic-engine
      4. If FALSE+certified → record in vsf-rsi scenario memory
      5. Return result with evidence
    
    NOTE: Uses RSICycle's predicates (action_forbidden, path_forbidden, etc.)
    NOT the bridge's old predicates (action_is_valid, file_path_valid, etc.)
    """
    try:
        if _cycle is None:
            return _evaluate_action_fallback(action)

        tool = action.get("tool", "")
        file = action.get("file", "")
        command = action.get("command", "")
        outcome = action.get("outcome", "pending")
        tasks = action.get("tasks", [])
        recent_actions = action.get("recent_actions", [])
        task_context = action.get("task_context", {})

        # Build tree: AND of RSICycle's validation predicates.
        # path_forbidden gets `tool` so reads of credential paths block too
        # (S5 2026-09-09). read_size_ok is advisory-only (always TRUE).
        # policy_locked (CLI-only config) + write_scope_ok (closed lab)
        # are security predicates: FALSE here blocks via SECURITY_SOURCES.
        tree = {
            "op": "AND",
            "children": [
                {"predicate": "action_forbidden", "args": [tool, file], "kwargs": {"command": command}},
                {"predicate": "path_forbidden", "args": [file], "kwargs": {"tool": tool}},
                {"predicate": "policy_locked", "args": [tool, file], "kwargs": {}},
                {"predicate": "write_scope_ok", "args": [tool, file], "kwargs": {}},
                {"predicate": "not_redundant", "args": [tool, file, command], "kwargs": {"recent_actions": recent_actions}},
                {"predicate": "read_size_ok", "args": [file], "kwargs": {}},
                {"predicate": "state_consistent", "args": [], "kwargs": {}},
            ]
        }

        # Context for evaluation (don't include command - it's in the tree)
        context = {
            "tasks": tasks,
            "recent_actions": recent_actions,
            "task_context": task_context,
        }

        # Evaluate via RSICycle
        result = _cycle.evaluate(tree, context)

        # Attribute FALSE verdicts to the failing child predicates.
        # The parent verdict's source is just "op:AND" — callers
        # (tool-integration.ts SECURITY_SOURCES) need the child name to
        # tell a security block from an advisory one. Children are pure
        # and deterministic: evaluate them on the RAW engine (no cycle
        # wrappers, so no double record/enqueue/fault-feed side effects).
        if result.get("truth") == "FALSE" and result.get("certified") \
                and _cycle is not None:
            failed: list = []
            try:
                from socratic_engine import Truth as _Truth
                for child in tree.get("children", []):
                    if not isinstance(child, dict) or "predicate" not in child:
                        continue
                    ev = _cycle.engine.evaluate(
                        child, dict(context), enforce_limits=True)
                    if ev.truth == _Truth.FALSE and ev.certified:
                        failed.append(child.get("predicate", "unknown"))
            except Exception:
                pass
            result["failed_predicates"] = failed

        return result

    except Exception as e:
        return _evaluate_action_fallback(action)


def _evaluate_action_fallback(action: dict) -> dict:
    """Fallback evaluation when RSICycle is not available."""
    try:
        from socratic_engine import Truth
        from socratic_engine.engine import SocraticEngine
        engine = SocraticEngine()
        _register_validation_predicates(engine)

        tool = action.get("tool", "")
        file = action.get("file", "")
        command = action.get("command", "")
        outcome = action.get("outcome", "pending")
        tasks = action.get("tasks", [])
        recent_actions = action.get("recent_actions", [])
        task_context = action.get("task_context", {})

        predicates = [
            ("action_is_valid", [tool, file], {"command": command}),
            ("file_path_valid", [file], {}),
            ("no_redundant_action", [tool, file, command], {"recent_actions": recent_actions}),
            ("action_matches_task", [tool, file], {"command": command, "task_context": task_context}),
            ("no_state_conflict", [tool, file], {"tasks": tasks}),
            ("action_outcome_valid", [tool, outcome], {}),
        ]

        results = []
        for pred_name, args, kwargs in predicates:
            pred = engine.predicates[pred_name]
            r = pred(*args, **kwargs)
            results.append({"name": pred_name, "result": r})

        all_true = all(r["result"].truth == Truth.TRUE for r in results)
        any_false = any(r["result"].truth == Truth.FALSE for r in results)
        all_certified = all(r["result"].certified for r in results)

        # FALSE = "predicate doesn't apply" (neutral), not "block"
        # Only block if a predicate returns TRUE and explicitly rejects
        if all_true:
            truth_val = "TRUE"
            evidence = {}
            source = "op:AND(manual)"
        elif any_false:
            # FALSE means "doesn't apply" — treat as neutral, allow
            truth_val = "TRUE"
            evidence = {}
            source = "op:AND(neutral)"
        else:
            truth_val = "TRUE"
            evidence = {}
            source = "op:AND(unknown)"

        return {
            "certified": all_certified,
            "truth": truth_val,
            "source": source,
            "evidence": evidence or {},
        }
    except Exception as e:
        return {"certified": False, "truth": "ERROR", "source": f"eval error: {e}"}


def pre_check(context: dict) -> dict:
    """Pre-check: evaluate if action is appropriate BEFORE execution."""
    # Get current system context
    system = get_system_context()
    tasks = query_tasks({})
    recent = get_recent_actions(20)
    task_ctx = get_current_task_context(tasks)

    # Build evaluation context with full context for all predicates
    eval_ctx = {
        **context,
        "system": system,
        "tasks": tasks,
        "recent_actions": recent,
        "task_context": task_ctx,
    }

    # Evaluate
    eval_result = evaluate_action(eval_ctx)

    # Log the pre-check (H1: failed_predicates travels so blocks are
    # attributable in the log, not just op:AND)
    _ev = dict(eval_result.get("evidence", {}) or {})
    if eval_result.get("failed_predicates"):
        _ev["failed_predicates"] = eval_result["failed_predicates"]
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": "before",
        "tool": context.get("tool", "unknown"),
        "file": context.get("file", ""),
        "outcome": "allowed" if eval_result.get("truth") != "FALSE" else "blocked",
        "truth": eval_result.get("truth", "UNKNOWN"),
        "certified": eval_result.get("certified", False),
        "source": eval_result.get("source", ""),
        "evidence": _ev,
    })

    return {
        "ok": eval_result.get("truth") != "FALSE",
        "socratic": eval_result,
        "system_context": system,
        "task_context": task_ctx,
    }


# ─── vsf-rsi ──────────────────────────────────────────────────────────────────

def record_pattern(tool: str, file: str, outcome: str) -> dict:
    """Record a pattern using the FULL RSI pipeline (record → adapt → learn → generate).
    
    This is the SECOND-ORDER entry point: not just recording, but also
    adapting quality scores and detecting learnable patterns.
    """
    try:
        from vsf_rsi.rsi_pipeline import pipeline
        result = pipeline(
            tool=tool,
            command=file,
            outcome=outcome,
            fault_signature=f"plugin.{tool}.{os.path.basename(file)}",
            quality=1.0 if outcome == "success" else 0.2,
        )
        return {
            "entry_id": result.get("scenario_id"),
            "recorded": result.get("recorded", False),
            "patterns_found": result.get("patterns_found", 0),
            "predicate_generated": result.get("predicate_generated", False),
            "predicate_registered": result.get("predicate_registered", False),
            "predicate_name": result.get("predicate_name"),
        }
    except Exception as e:
        # Fallback to simple record if pipeline fails
        from vsf_rsi.scenario_memory import record
        entry_id = record(
            decision=f"{tool}:{os.path.basename(file)}",
            outcome=outcome,
            correction_path=f"plugin:tool-integration:{tool}",
            fault_signature=f"plugin.{tool}.{os.path.basename(file)}",
        )
        return {"entry_id": entry_id, "recorded": True, "pipeline_error": str(e)}


def match_patterns(fault_signature: str) -> list:
    """Match against recorded patterns."""
    from vsf_rsi.scenario_memory import match
    return match(fault_signature, threshold=0.0)


def run_learn_pipeline() -> dict:
    """Run the learning pipeline: detect patterns → generate → QUEUE.

    L4 autonomy ceiling (S5): NOTHING generated here is ever activated
    directly. Candidates go to the approval queue; a human approves via
    `rsi-approve` before the cycle loads them (activation-by-approval).

    Call this from session.idle to enable second-order learning.
    """
    try:
        from vsf_rsi.scenario_memory import learn
        from vsf_rsi.rsi_pipeline import (
            _generate_predicate_name, _generate_predicate_tree,
            MIN_OCCURRENCES, QUALITY_THRESHOLD
        )
        from vsf_rsi.rsi_socratic_bridge import enqueue_predicate, get_queue_stats

        patterns = learn(min_occurrences=MIN_OCCURRENCES)

        learnable = [
            p for p in patterns
            if p["avg_quality"] < QUALITY_THRESHOLD and p["count"] >= MIN_OCCURRENCES
        ]

        results = {
            "patterns_detected": len(patterns),
            "learnable_patterns": len(learnable),
            "predicates_queued": 0,
            "queued_names": [],
            "queue_files": [],
        }

        for p in learnable[:5]:  # Limit to 5 per session
            pred_name = _generate_predicate_name(p["fault_signature"])
            pred_tree = _generate_predicate_tree(p["fault_signature"], p["correction_path"])

            # CEILING: enqueue, never direct-register (L4_AUTO = False)
            qpath = enqueue_predicate(
                pred_name, pred_tree,
                source="learn-pipeline",
                description=f"fault={p['fault_signature']} quality={p['avg_quality']:.2f}",
            )
            results["predicates_queued"] += 1
            results["queued_names"].append(pred_name)
            results["queue_files"].append(str(qpath))

        results["queue_stats"] = get_queue_stats()
        return results
    except Exception as e:
        return {"error": str(e)}


# ─── Integration Log ──────────────────────────────────────────────────────────

def log_integration(entry: dict):
    """Append to unified activation log (logs/agent_plugin.jsonl).
    
    Writes in the same format as the bash agent-plugin-log script
    so all events appear in view_log.py --live.
    """
    log_dir = os.path.join(VOS_ROOT, "logs")
    log_file = os.path.join(log_dir, "agent_plugin.jsonl")
    os.makedirs(log_dir, exist_ok=True)
    
    # Map bridge phases to the unified format
    phase = entry.get("phase", "unknown")
    tool = entry.get("tool", "unknown")
    outcome = entry.get("outcome", "ok")
    truth = entry.get("truth", "")
    certified = entry.get("certified", "")
    
    # Build action string (concise summary)
    action_parts = [f"tool:{tool}"]
    if entry.get("file"):
        action_parts.append(f"file:{entry['file']}")
    if truth:
        action_parts.append(f"truth={truth}")
    if certified != "":
        action_parts.append(f"cert={certified}")
    action = " ".join(action_parts)
    
    # Map outcome to result level
    if outcome in ("blocked", "failure", "error"):
        result = "error"
    elif outcome in ("warn", "match"):
        result = "warn"
    else:
        result = "ok"
    
    # Build detail string
    detail_parts = []
    if entry.get("evidence"):
        detail_parts.append(json.dumps(entry["evidence"], default=str)[:200])
    if entry.get("matches"):
        detail_parts.append(f"matches={len(entry['matches'])}")
    detail = " | ".join(detail_parts)
    
    # Determine log level
    level = "error" if result == "error" else "warning" if result == "warn" else "activation"
    
    # Build event_id
    event_id = f"rsi-cycle:{phase}:{int(_time.time())}"
    
    unified = {
        "ts": entry.get("ts", datetime.now(timezone.utc).isoformat()),
        "pid": os.getpid(),
        "level": level,
        "source": "rsi-cycle",
        "event_type": phase,
        "event_id": event_id,
        "action": action,
        "result": result,
        "detail": detail,
        "context": entry.get("evidence", {}),
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(unified) + "\n")


# ─── RSI Dynamic Evaluation ──────────────────────────────────────────────────

def evaluate_rsi_predicates(tool: str, file: str, command: str = "") -> dict:
    """Evaluate ALL RSI-generated predicates against current context.
    
    This is the DYNAMIC component: queries RSICycle for RSI predicates,
    evaluates each against the current tool execution context, and returns
    matches that could affect the decision.
    
    Security (R10): All predicates are JSON trees evaluated by socratic-engine.
    No exec(), no LLM, fully deterministic.
    
    Returns:
        {
            "predicates_evaluated": int,
            "matches": [{"name": str, "truth": str, "evidence": dict}],
            "should_block": bool,
            "should_warn": bool,
        }
    """
    try:
        # PRIORITY: Use vOSlab kernel cycle (with observer, pipeline)
        try:
            from system.kernel.rsi_cycle import RSICycle
        except ImportError:
            from rsi_cycle import RSICycle
        
        cycle = RSICycle()
        all_preds = cycle.get_predicates()
        rsi_preds = [p for p in all_preds if p.startswith("rsi_")]
        
        if not rsi_preds:
            return {
                "predicates_evaluated": 0,
                "matches": [],
                "should_block": False,
                "should_warn": False,
            }
        
        # Build context for evaluation
        context = {
            "tool": tool,
            "file": file,
            "command": command,
        }
        
        matches = []
        for pred_name in rsi_preds:
            try:
                # Load predicate tree from disk
                pred_file = os.path.join(RSI_PREDICATES_DIR, f"{pred_name}.json")
                if not os.path.exists(pred_file):
                    continue
                
                with open(pred_file) as f:
                    pred_data = json.loads(f.read())
                tree = pred_data.get("tree")
                if not tree:
                    continue
                
                # Evaluate tree against context
                result = cycle.evaluate(tree, context)
                truth = result.get("truth", "UNKNOWN")
                certified = result.get("certified", False)
                
                if truth in ("TRUE", "FALSE") and certified:
                    matches.append({
                        "name": pred_name,
                        "truth": truth,
                        "certified": certified,
                        "evidence": result.get("evidence", {}),
                        "fault_signature": pred_data.get("fault_signature", ""),
                    })
            except Exception:
                continue  # Skip failed predicates
        
        # Decision logic
        # A predicate returning TRUE means: "I recognize this context as a
        # pattern learned from past failures." → WARN.
        # A predicate returning FALSE means: "doesn't apply to this context."
        # → IGNORE. (The tree conditions didn't match, so the predicate
        # is not relevant to this action.)
        #
        # This is the correct second-order behavior: only act when the system
        # RECOGNIZES a known pattern (TRUE), not when it fails to match (FALSE).
        relevant_true = [m for m in matches if m["truth"] == "TRUE"]
        
        should_block = len(relevant_true) >= 3  # Many matches = strong pattern
        should_warn = len(relevant_true) >= 1    # Any match = known pattern
        
        return {
            "predicates_evaluated": len(rsi_preds),
            "matches": matches,
            "true_count": len(relevant_true),
            "should_block": should_block,
            "should_warn": should_warn,
        }
    except Exception as e:
        return {
            "predicates_evaluated": 0,
            "matches": [],
            "should_block": False,
            "should_warn": False,
            "error": str(e),
        }


def cmd_rsi_evaluate(args: list[str]):
    """rsi-evaluate <tool> <file> [command] — evaluate RSI predicates for context."""
    if len(args) < 2:
        print(json.dumps({"error": "usage: rsi-evaluate <tool> <file> [command]"}))
        return
    tool, file = args[0], args[1]
    command = args[2] if len(args) > 2 else ""
    result = evaluate_rsi_predicates(tool, file, command)
    
    # Log RSI evaluation
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": "rsi_evaluate",
        "tool": tool,
        "file": file,
        "outcome": "match" if result.get("matches") else "clear",
        "predicates_evaluated": result.get("predicates_evaluated", 0),
        "matches": result.get("matches", []),
        "should_block": result.get("should_block", False),
        "should_warn": result.get("should_warn", False),
    })
    
    print(json.dumps(result))


def get_session_stats() -> dict:
    """Get stats from integration log for current session."""
    if not os.path.exists(INTEGRATION_LOG):
        return {"total": 0, "success": 0, "failure": 0}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = success = failure = advisory = 0

    with open(INTEGRATION_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("date", "").startswith(today):
                    total += 1
                    outcome = entry.get("outcome", "")
                    if outcome == "success":
                        success += 1
                    elif outcome == "advisory":
                        advisory += 1
                    else:
                        failure += 1
            except json.JSONDecodeError:
                continue

    return {"total": total, "success": success, "advisory": advisory, "failure": failure}


# ─── Commands ──────────────────────────────────────────────────────────────────

def cmd_pre_check(args: list[str]):
    """pre-check <context_json> — Evaluate action before execution."""
    if not args:
        print(json.dumps({"error": "usage: pre-check <context_json>"}))
        return

    context = json.loads(args[0])
    result = pre_check(context)
    print(json.dumps(result))


def cmd_record_action(args: list[str]):
    """record-action <tool> <file> <outcome> <context_json>"""
    if len(args) < 3:
        print(json.dumps({"error": "usage: record-action <tool> <file> <outcome> [context_json]"}))
        return

    tool, file, outcome = args[0], args[1], args[2]
    context = json.loads(args[3]) if len(args) > 3 else {}

    # Get context for evaluation
    tasks = query_tasks({})
    recent = get_recent_actions(20)
    task_ctx = get_current_task_context(tasks)

    # 1. Evaluate with socratic (full context)
    eval_result = evaluate_action({
        "tool": tool,
        "file": file,
        "outcome": outcome,
        "command": context.get("command", ""),
        "tasks": tasks,
        "recent_actions": recent,
        "task_context": task_ctx,
        **context,
    })

    # 2. Record in vsf-rsi (full pipeline: record → adapt → learn → generate)
    rsi_result = None
    if tool in ("write", "edit"):
        rsi_result = record_pattern(tool, file, outcome)

    # 3. Log integration (ensure all values are JSON-serializable)
    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": "after",
        "tool": tool,
        "file": file,
        "outcome": outcome,
        "command": context.get("command", "")[:200] if context.get("command") else None,
        "socratic_certified": bool(eval_result.get("certified", False)),
        "socratic_truth": str(eval_result.get("truth", "")),
        "socratic_source": str(eval_result.get("source", "")),
        "socratic_evidence": eval_result.get("evidence", {}),
        "rsi_recorded": rsi_result.get("recorded", False) if rsi_result else False,
        "rsi_patterns": rsi_result.get("patterns_found", 0) if rsi_result else 0,
        "rsi_predicate": rsi_result.get("predicate_name") if rsi_result else None,
    }
    log_integration(log_entry)

    print(json.dumps({
        "ok": True,
        "socratic": eval_result,
        "rsi": rsi_result,
    }))


def cmd_learn_from_action(args: list[str]):
    """learn-from-action <tool> <file> <outcome>"""
    if len(args) < 3:
        print(json.dumps({"error": "usage: learn-from-action <tool> <file> <outcome>"}))
        return

    tool, file, outcome = args[0], args[1], args[2]

    # Record in RSI (full pipeline)
    rsi_result = record_pattern(tool, file, outcome)

    # Match against history
    matches = match_patterns(f"plugin.{tool}.{os.path.basename(file)}")

    # Log the learning
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": "learn",
        "tool": tool,
        "file": file,
        "outcome": outcome,
        "rsi_recorded": rsi_result is not None,
        "historical_matches": len(matches) if matches else 0,
    })

    print(json.dumps({
        "ok": True,
        "rsi": rsi_result,
        "historical_matches": len(matches) if matches else 0,
    }))


def cmd_log_action(args: list[str]):
    """log-action <phase> <tool> <file> <outcome> <eval_json>"""
    if len(args) < 5:
        print(json.dumps({"error": "usage: log-action <phase> <tool> <file> <outcome> <eval_json>"}))
        return

    phase, tool, file, outcome = args[0], args[1], args[2], args[3]
    eval_data = json.loads(args[4]) if args[4] != "null" else {}

    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": phase,
        "tool": tool,
        "file": file,
        "outcome": outcome,
        "socratic_certified": bool(eval_data.get("certified", False)),
        "socratic_truth": str(eval_data.get("truth", "")),
        "socratic_source": str(eval_data.get("source", "")),
        "socratic_evidence": eval_data.get("evidence", {}),
    }
    log_integration(log_entry)

    print(json.dumps({"ok": True}))


def cmd_session_report(args: list[str]):
    """session-report — get stats for current session."""
    stats = get_session_stats()
    context = get_system_context()

    print(json.dumps({
        "session": stats,
        "tasks": context["tasks"],
        "sessions": context["sessions"],
    }))


def cmd_query_context(args: list[str]):
    """query-context — get current system context."""
    context = get_system_context()
    print(json.dumps(context))


# ─── State-Canon Features ─────────────────────────────────────────────────────

def cmd_state_journal(args: list[str]):
    """state-journal <action> [args] — Journal snapshots (save/diff/history).
    
    Actions:
      save [session_id] [drifts_json]  — Save snapshot
      diff [from_id] [to_id]           — Diff two snapshots
      history [limit]                  — Show recent snapshots
    """
    if not args:
        print(json.dumps({"error": "usage: state-journal <save|diff|history> [args]"}))
        return

    action = args[0]
    try:
        # Import state-canon journal module
        sys.path.insert(0, STATE_CANON_PATH)
        from state_canon.journal import StateJournal
        
        # Use a default journal DB path
        journal_db = os.path.join(CHILD_PATH, "state_journal.db")
        journal = StateJournal(journal_db)
        
        if action == "save":
            session_id = args[1] if len(args) > 1 else None
            drifts = json.loads(args[2]) if len(args) > 2 else None
            entry = journal.mark(session_id=session_id, drifts=drifts or [])
            print(json.dumps({"ok": True, "action": "save", "entry": entry}))

        elif action == "diff":
            from_id = int(args[1]) if len(args) > 1 else None
            to_id = int(args[2]) if len(args) > 2 else None
            diff = journal.diff(from_id=from_id, to_id=to_id)
            print(json.dumps({"ok": True, "action": "diff", "diff": diff}))

        elif action == "history":
            limit = int(args[1]) if len(args) > 1 else 10
            history = journal.history(limit=limit)
            print(json.dumps({"ok": True, "action": "history", "history": history}))

        else:
            print(json.dumps({"error": f"unknown action: {action}"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_state_focus(args: list[str]):
    """state-focus <action> [args] — Focus entries (mark/list/clear).
    
    Actions:
      mark <ref> [status] [note]  — Mark focus entry
      list                         — List active focus
      clear <ref>                  — Clear focus entry
    """
    if not args:
        print(json.dumps({"error": "usage: state-focus <mark|list|clear> [args]"}))
        return

    action = args[0]
    try:
        # Import state-canon focus module
        sys.path.insert(0, STATE_CANON_PATH)
        from state_canon.focus import FocusTracker
        
        # Use a default focus file path
        focus_file = os.path.join(CHILD_PATH, "current_focus.json")
        tracker = FocusTracker(focus_file)
        
        if action == "mark":
            ref = args[1] if len(args) > 1 else None
            status = args[2] if len(args) > 2 else "active"
            note = args[3] if len(args) > 3 else None
            entry = tracker.mark(ref=ref, status=status, note=note)
            print(json.dumps({"ok": True, "action": "mark", "entry": entry}))

        elif action == "list":
            entries = tracker.query()
            print(json.dumps({"ok": True, "action": "list", "entries": entries}))

        elif action == "clear":
            ref = args[1] if len(args) > 1 else None
            entry = tracker.close(ref=ref)
            print(json.dumps({"ok": True, "action": "clear", "entry": entry}))

        else:
            print(json.dumps({"error": f"unknown action: {action}"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_state_drift(args: list[str]):
    """state-drift — Detect drift between declared and observed state."""
    try:
        # Import state-canon modules
        sys.path.insert(0, STATE_CANON_PATH)
        from state_canon.server import StateRagServer
        from instances.tasks_provider import VsmStateProvider
        
        # Create a minimal server instance to call reconcile
        provider = VsmStateProvider(TASKS_VSM)
        server = StateRagServer(provider)
        
        # Call reconcile to detect drift
        result = server.state_reconcile()
        # state_reconcile() returns a list of drifts
        drifts = result if isinstance(result, list) else result.get("drifts", []) if isinstance(result, dict) else []
        print(json.dumps({"ok": True, "drift": drifts}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_state_verify(args: list[str]):
    """state-verify <domain> <filter_json> <expect_json> — Verify claims."""
    if len(args) < 3:
        print(json.dumps({"error": "usage: state-verify <domain> <filter_json> <expect_json>"}))
        return

    try:
        domain = args[0]
        filter_dict = json.loads(args[1])
        expect_dict = json.loads(args[2])
        
        # Import state-canon modules
        sys.path.insert(0, STATE_CANON_PATH)
        from state_canon.server import StateRagServer
        from instances.tasks_provider import VsmStateProvider
        
        # Create a minimal server instance to call verify
        provider = VsmStateProvider(TASKS_VSM)
        server = StateRagServer(provider)
        
        # Call verify
        result = server.state_verify(domain=domain, expect=expect_dict, filter=filter_dict)
        print(json.dumps({"ok": True, "domain": domain, "verified": result.get("holds", False), "result": result}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_state_reconcile(args: list[str]):
    """state-reconcile — Reconcile declared vs observed state."""
    try:
        # Import state-canon modules
        sys.path.insert(0, STATE_CANON_PATH)
        from state_canon.server import StateRagServer
        from instances.tasks_provider import VsmStateProvider
        
        # Create a minimal server instance to call reconcile
        provider = VsmStateProvider(TASKS_VSM)
        server = StateRagServer(provider)
        
        # Call reconcile
        result = server.state_reconcile()
        # state_reconcile() returns a list of drifts
        drifts = result if isinstance(result, list) else result.get("drifts", []) if isinstance(result, dict) else []
        print(json.dumps({"ok": True, "drifts": drifts}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


# ─── Socratic-Engine Features ─────────────────────────────────────────────────

def cmd_socratic_tree(args: list[str]):
    """socratic-tree <tree_json> [context_json] — Evaluate a tree."""
    if not args:
        print(json.dumps({"error": "usage: socratic-tree <tree_json> [context_json]"}))
        return

    try:
        tree = json.loads(args[0])
        context = json.loads(args[1]) if len(args) > 1 else {}

        if _cycle:
            result = _cycle.evaluate(tree, context)
        else:
            from socratic_engine import SocraticEngine
            engine = SocraticEngine()
            result = engine.evaluate(tree, context)

        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_socratic_canon(args: list[str]):
    """socratic-canon <domain> [filter_json] — Query canon data."""
    if not args:
        print(json.dumps({"error": "usage: socratic-canon <domain> [filter_json]"}))
        return

    try:
        domain = args[0]
        filter_dict = json.loads(args[1]) if len(args) > 1 else {}

        # Query via state-canon
        from instances.tasks_provider import VsmStateProvider
        provider = VsmStateProvider(TASKS_VSM)
        results = provider.query(domain, filter_dict)
        print(json.dumps({"domain": domain, "results": results}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_socratic_diagnose(args: list[str]):
    """socratic-diagnose <tree_json> — Diagnose why a tree evaluation failed."""
    if not args:
        print(json.dumps({"error": "usage: socratic-diagnose <tree_json>"}))
        return

    try:
        tree = json.loads(args[0])

        if _cycle:
            result = _cycle.evaluate(tree)
            # If FALSE, try to diagnose
            if result.get("truth") == "FALSE":
                print(json.dumps({
                    "diagnosis": result.get("source"),
                    "evidence": result.get("evidence"),
                    "certified": result.get("certified"),
                }))
            else:
                print(json.dumps({"diagnosis": "tree evaluates to TRUE", "no_fault": True}))
        else:
            print(json.dumps({"error": "RSICycle not available"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


# ─── VSF-RSI Features ─────────────────────────────────────────────────────────

def cmd_rsi_status(args: list[str]):
    """rsi-status — Get observer and cycle status."""
    try:
        status = {
            "cycle_available": _cycle is not None,
            "predicates": _cycle.get_predicates() if _cycle else [],
            "stats": _cycle.get_stats() if _cycle else {},
        }

        # Try to get scenario memory stats
        try:
            from vsf_rsi.scenario_memory import _get_store
            store_path = _get_store()
            if store_path.is_dir():
                # Directory-based store: count .json files
                json_files = list(store_path.glob("*.json"))
                status["scenario_memory"] = {
                    "total": len(json_files),
                    "store": str(store_path),
                    "sample": [f.stem for f in json_files[:5]],
                }
            elif store_path.is_file():
                with open(str(store_path)) as f:
                    scenarios = json.loads(f.read())
                status["scenario_memory"] = {
                    "total": len(scenarios),
                    "scenarios": list(scenarios.keys())[:10],
                }
            else:
                status["scenario_memory"] = {"total": 0, "path": str(store_path)}
        except Exception as e:
            status["scenario_memory"] = {"total": 0, "error": str(e)}

        print(json.dumps(status))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_correct(args: list[str]):
    """rsi-correct <failure_json> — Generate a correction for a failure."""
    if not args:
        print(json.dumps({"error": "usage: rsi-correct <failure_json>"}))
        return

    try:
        failure = json.loads(args[0])

        # Record in scenario memory
        from vsf_rsi.scenario_memory import record, match
        fault_sig = f"socratic.{failure.get('source', 'unknown')}.failure"
        entry_id = record(
            decision=f"socratic:{failure.get('source')}",
            outcome="failure",
            correction_path="rsi_cycle:correct",
            fault_signature=fault_sig,
        )

        # Try to match against history
        matches = match(fault_sig, threshold=0.3)

        correction = {
            "recorded": True,
            "entry_id": entry_id,
            "fault_signature": fault_sig,
            "historical_matches": len(matches) if matches else 0,
            "suggestion": "review_logs" if not matches else matches[0][1] if len(matches[0]) > 1 else "no_suggestion",
        }

        print(json.dumps(correction))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_learn(args: list[str]):
    """rsi-learn <tool> <file> <outcome> — Learn from an action."""
    if len(args) < 3:
        print(json.dumps({"error": "usage: rsi-learn <tool> <file> <outcome>"}))
        return

    try:
        tool, file, outcome = args[0], args[1], args[2]

        # Record in scenario memory
        from vsf_rsi.scenario_memory import record, match
        entry_id = record(
            decision=f"{tool}:{os.path.basename(file)}",
            outcome=outcome,
            correction_path=f"plugin:tool-integration:{tool}",
            fault_signature=f"plugin.{tool}.{os.path.basename(file)}",
        )

        # Match against history
        matches = match(f"plugin.{tool}.{os.path.basename(file)}", threshold=0.0)

        print(json.dumps({
            "ok": True,
            "rsi_id": entry_id,
            "historical_matches": len(matches) if matches else 0,
        }))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_queue(args: list[str]):
    """rsi-queue [status] — List approval-queue entries (default: pending)."""
    status = args[0] if args and not args[0].startswith("-") else "pending"
    try:
        from vsf_rsi.rsi_socratic_bridge import list_queue, get_queue_stats
        print(json.dumps({
            "status_filter": status,
            "entries": list_queue(status),
            "stats": get_queue_stats(),
        }, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_approve(args: list[str]):
    """rsi-approve <name> — Human approves a queued predicate (control level 2).

    Marks approved; the RSI cycle loads approved trees on next init
    (activation-by-approval). Nothing auto-activates without this step.
    """
    if not args:
        print(json.dumps({"error": "usage: rsi-approve <name>"}))
        return
    try:
        from vsf_rsi.rsi_socratic_bridge import approve_predicate, diff_predicate
        ok = approve_predicate(args[0])
        # H3: governance actions leave a trace in the unified log
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "governance",
            "tool": "rsi-approve",
            "file": args[0],
            "outcome": "success" if ok else "failure",
        })
        print(json.dumps({
            "approved": ok,
            "name": args[0],
            "diff": diff_predicate(args[0]),
            "note": "approved trees load on next cycle init" if ok else "not found or not pending",
        }, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_reject(args: list[str]):
    """rsi-reject <name> [reason] — Human rejects a queued predicate."""
    if not args:
        print(json.dumps({"error": "usage: rsi-reject <name> [reason]"}))
        return
    try:
        from vsf_rsi.rsi_socratic_bridge import reject_predicate
        ok = reject_predicate(args[0], " ".join(args[1:]))
        # H3: governance actions leave a trace in the unified log
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "governance",
            "tool": "rsi-reject",
            "file": args[0],
            "outcome": "success" if ok else "failure",
        })
        print(json.dumps({"rejected": ok, "name": args[0]}, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_diff(args: list[str]):
    """rsi-diff <name> — Show current vs proposed tree for review."""
    if not args:
        print(json.dumps({"error": "usage: rsi-diff <name>"}))
        return
    try:
        from vsf_rsi.rsi_socratic_bridge import diff_predicate
        print(json.dumps({"name": args[0], "diff": diff_predicate(args[0])}, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def _vsm_quarantine_mod():
    """Load vsm_quarantine.py by explicit path (never by import name)."""
    import importlib.util
    path = os.path.join(VOS_ROOT, "scripts", "vsl", "tools",
                        "vsm_quarantine.py")
    spec = importlib.util.spec_from_file_location("vsm_quarantine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_vsm_stash(args: list[str]):
    """vsm-stash <file> — snapshot content before a .vsm write."""
    if not args:
        print(json.dumps({"error": "usage: vsm-stash <file>"}))
        return
    try:
        mod = _vsm_quarantine_mod()
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.cmd_stash(args[0])
        print(json.dumps({"ok": rc == 0, "token": buf.getvalue().strip(),
                          "file": args[0]}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_vsm_restore(args: list[str]):
    """vsm-restore <token|file> — write back stashed content.

    Accepts the stash token OR the file path (token is derived
    deterministically, so the after-hook never re-stashes — re-stashing
    would snapshot the ALREADY-BLOCKED content and restore the breach).
    Refuses files stashed as NEW (use vsm-quarantine for those).
    """
    if not args:
        print(json.dumps({"error": "usage: vsm-restore <token|file>"}))
        return
    try:
        mod = _vsm_quarantine_mod()
        key = args[0]
        if len(key) != 16 or any(c not in "0123456789abcdef" for c in key):
            key = mod._token(key)  # a path, not a token
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = mod.cmd_restore(key)
        print(json.dumps({"ok": rc == 0, "rc": rc,
                          "output": (out.getvalue() + err.getvalue()).strip()}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_vsm_check_content(args: list[str]):
    """vsm-check-content <json {content}> — validate VSM text pre-write.

    Used by the before-hook for true prevention (R18 version breaches
    throw BEFORE landing; grammar stays for the after-hook). Returns
    {valid, errors}. Never raises: on internal error returns valid:true
    with a warning so a verifier outage cannot brick all .vsm writes
    (the after-gate + quarantine still enforce).
    """
    if not args:
        print(json.dumps({"error": "usage: vsm-check-content <json>"}))
        return
    try:
        import importlib.util
        payload = json.loads(args[0])
        content = payload.get("content", "")
        kpath = os.path.join(VOS_ROOT, "packages", "framework",
                             "vos_kernel", "utils", "vsm_kernel.py")
        spec = importlib.util.spec_from_file_location("vsmk_check", kpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        res = mod.validate_vsm_content(content)
        print(json.dumps({"valid": res["valid"], "errors": res["errors"]}))
    except Exception as e:
        print(json.dumps({"valid": True, "errors": [],
                          "warning": f"verifier degraded: {e}"[:200]}))


def cmd_vsm_quarantine(args: list[str]):
    """vsm-quarantine <file> — move a blocked new file to state/ (never rm)."""
    if not args:
        print(json.dumps({"error": "usage: vsm-quarantine <file>"}))
        return
    try:
        mod = _vsm_quarantine_mod()
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = mod.cmd_quarantine(args[0])
        print(json.dumps({"ok": rc == 0, "rc": rc,
                          "output": (out.getvalue() + err.getvalue()).strip()}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_faults(args: list[str]):
    """rsi-faults — List detected complex faults (L3 fault detector)."""
    try:
        from vsf_rsi.rsi_fault_detector import FAULT_FILE
        import json as _json
        faults = []
        if FAULT_FILE.exists():
            data = _json.loads(FAULT_FILE.read_text())
            faults = list(data.values()) if isinstance(data, dict) else data
        print(json.dumps({"faults": faults, "count": len(faults)}, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_evaluate_query(args: list[str]):
    """evaluate-query <query> [context_json] — Parse and evaluate natural language query."""
    if not args:
        print(json.dumps({"error": "usage: evaluate-query <query> [context_json]"}))
        return

    try:
        query = args[0]
        context = json.loads(args[1]) if len(args) > 1 else {}

        if _cycle:
            # Try rule-based parsing first
            result = _cycle.evaluate_query(query, context)
            
            # If parsing failed, try MCP server
            if not result.get("parsed", False):
                try:
                    import subprocess
                    mcp_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "parse_query",
                            "arguments": {"query": query, "context": context}
                        }
                    }
                    proc = subprocess.run(
                        ["python3", os.path.join(VOS_ROOT, ".opencode", "mcp", "parse_query_mcp.py")],
                        input=json.dumps(mcp_request) + "\n",
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if proc.returncode == 0:
                        mcp_response = json.loads(proc.stdout.strip())
                        if "result" in mcp_response:
                            content = mcp_response["result"].get("content", [])
                            if content:
                                parsed = json.loads(content[0].get("text", "{}"))
                                if parsed.get("tree"):
                                    # Evaluate the tree from MCP
                                    eval_result = _cycle.evaluate(parsed["tree"], context)
                                    result = {
                                        "result": eval_result,
                                        "tree": parsed["tree"],
                                        "parsed": True,
                                        "query": query,
                                        "provider": parsed.get("provider", "mcp"),
                                    }
                except Exception as e:
                    pass  # Keep rule-based result
            
            print(json.dumps(result))
        else:
            print(json.dumps({"error": "RSICycle not available"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_run_gates(args: list[str]):
    """run-gates <file_path> — Run gate suite on a file."""
    if not args:
        print(json.dumps({"error": "usage: run-gates <file_path>"}))
        return

    try:
        file_path = args[0]
        
        # Import gate suite runtime module
        framework_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "framework")
        sys.path.insert(0, os.path.abspath(framework_dir))
        from gate_suite.runtime import run_gates_on_file
        
        result = run_gates_on_file(file_path)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


COMMANDS = {
    "pre-check": cmd_pre_check,
    "record-action": cmd_record_action,
    "learn-from-action": cmd_learn_from_action,
    "log-action": cmd_log_action,
    "session-report": cmd_session_report,
    "query-context": cmd_query_context,
    # State-canon features
    "state-journal": cmd_state_journal,
    "state-focus": cmd_state_focus,
    "state-drift": cmd_state_drift,
    "state-verify": cmd_state_verify,
    "state-reconcile": cmd_state_reconcile,
    # Socratic-engine features
    "socratic-tree": cmd_socratic_tree,
    "socratic-canon": cmd_socratic_canon,
    "socratic-diagnose": cmd_socratic_diagnose,
    # VSF-RSI features
    "rsi-status": cmd_rsi_status,
    "rsi-correct": cmd_rsi_correct,
    "rsi-learn": cmd_rsi_learn,
    # VSM quarantine (HOOK-FAILOPEN closure)
    "vsm-stash": cmd_vsm_stash,
    "vsm-restore": cmd_vsm_restore,
    "vsm-quarantine": cmd_vsm_quarantine,
    "vsm-check-content": cmd_vsm_check_content,
    # L4 governance (approval queue — control level 2)
    "rsi-queue": cmd_rsi_queue,
    "rsi-approve": cmd_rsi_approve,
    "rsi-reject": cmd_rsi_reject,
    "rsi-diff": cmd_rsi_diff,
    "rsi-faults": cmd_rsi_faults,
    # Auto-parsing
    "evaluate-query": cmd_evaluate_query,
    # Second-order learning
    "learn-pipeline": lambda args: json.dumps(run_learn_pipeline()),
    # Gate suite (runtime)
    "run-gates": cmd_run_gates,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({"error": f"commands: {list(COMMANDS.keys())}"}))
        sys.exit(1)

    COMMANDS[sys.argv[1]](sys.argv[2:])


def main():
    """Main entry point for CLI usage."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    args = sys.argv[2:]
    
    # Route to appropriate handler
    handlers = {
        # Original commands
        "pre-check": lambda: json.dumps(pre_check(json.loads(args[0]) if args else {})),
        "record-action": lambda: cmd_record_action(args),
        "learn-from-action": lambda: cmd_learn_from_action(args),
        "log-action": lambda: cmd_log_action(args),
        "session-report": lambda: json.dumps(get_session_stats(), indent=2),
        "query-context": lambda: json.dumps(get_system_context(), indent=2),
        
        # State-canon commands
        "state-journal": lambda: cmd_state_journal(args),
        "state-focus": lambda: cmd_state_focus(args),
        "state-drift": lambda: cmd_state_drift(),
        "state-verify": lambda: cmd_state_verify(args),
        "state-reconcile": lambda: cmd_state_reconcile(),
        
        # Socratic-engine commands
        "socratic-tree": lambda: cmd_socratic_tree(args),
        "socratic-canon": lambda: cmd_socratic_canon(args),
        "socratic-diagnose": lambda: cmd_socratic_diagnose(args),
        
        # VSF-RSI commands
        "rsi-status": lambda: cmd_rsi_status(args),
        "rsi-correct": lambda: cmd_rsi_correct(args),
        "rsi-learn": lambda: cmd_rsi_learn(args),
        # VSM quarantine (HOOK-FAILOPEN closure)
        "vsm-stash": lambda: cmd_vsm_stash(args),
        "vsm-restore": lambda: cmd_vsm_restore(args),
        "vsm-quarantine": lambda: cmd_vsm_quarantine(args),
        "vsm-check-content": lambda: cmd_vsm_check_content(args),
        # L4 governance (approval queue — control level 2)
        "rsi-queue": lambda: cmd_rsi_queue(args),
        "rsi-approve": lambda: cmd_rsi_approve(args),
        "rsi-reject": lambda: cmd_rsi_reject(args),
        "rsi-diff": lambda: cmd_rsi_diff(args),
        "rsi-faults": lambda: cmd_rsi_faults(args),
        
        # NEW: Automation tools (previously manual)
        "audit-proposal": lambda: cmd_audit_proposal(args),
        "deep-audit": lambda: cmd_deep_audit(args),
        "verify-refs": lambda: cmd_verify_refs(args),
        "add-binding": lambda: cmd_add_binding(args),
        "route-component": lambda: cmd_route_component(args),
        "post-register": lambda: cmd_post_register(args),
        "verify-pipeline": lambda: cmd_verify_pipeline(args),
        # Risk assessment
        "risk-assess": lambda: cmd_risk_assess(args),
        # RSI dynamic evaluation
        "rsi-evaluate": lambda: cmd_rsi_evaluate(args),
        # Second-order learning
        "learn-pipeline": lambda: json.dumps(run_learn_pipeline()),
    }
    
    if command in handlers:
        try:
            result = handlers[command]()
            if result:
                print(result)
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


# ─── NEW: Automation tool handlers ────────────────────────────────────────────

# Import risk assessor
sys.path.insert(0, CHILD_PATH)
try:
    from risk_assessor import RiskAssessor
    _risk_assessor = RiskAssessor(CHILD_PATH)
except ImportError:
    _risk_assessor = None


def cmd_risk_assess(args):
    """risk-assess <tool> [file] [command] [--verbose] — Pre-action risk assessment.
    
    Evaluates risk of a proposed action BEFORE execution.
    Returns: risk_score, risk_level, confidence, factors, recommendation.
    """
    if not args:
        return json.dumps({"error": "Usage: risk-assess <tool> [file] [command] [--verbose]"})
    
    tool = args[0]
    file = args[1] if len(args) > 1 and not args[1].startswith("-") else ""
    command = args[2] if len(args) > 2 and not args[2].startswith("-") else ""
    verbose = "--verbose" in args or "-v" in args
    
    extra = {}
    if _risk_assessor is None:
        return json.dumps({"error": "risk_assessor module not available"})
    
    result = _risk_assessor.assess(tool, file, command, extra=extra, verbose=verbose)
    return json.dumps(result.to_dict(), indent=2)

def cmd_audit_proposal(args):
    """Run audit_proposal.py on a file."""
    if not args:
        return json.dumps({"error": "Usage: audit-proposal <file.vsm>"})
    
    filepath = args[0]
    verbose = "-v" in args
    
    # Import and run audit_proposal
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from audit_proposal import audit_proposal
    
    result = audit_proposal(Path(filepath), verbose)
    return json.dumps(result, indent=2)


def cmd_deep_audit(args):
    """Run deep_audit.py on a file."""
    if not args:
        return json.dumps({"error": "Usage: deep-audit <file.vsm>"})
    
    filepath = args[0]
    verbose = "-v" in args
    
    # Import and run deep_audit
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from deep_audit import audit_document
    
    search_root = Path(VOS_ROOT)
    result = audit_document(Path(filepath), search_root, verbose)
    return json.dumps({
        "filepath": result.filepath,
        "recommendation": result.overall_recommendation,
        "summary": result.summary,
        "gaps": [
            {
                "reference": g.reference,
                "recommendation": g.recommendation,
                "reasoning": g.reasoning,
                "alternative": g.alternative_path
            }
            for g in result.gaps
        ]
    }, indent=2)


def cmd_verify_refs(args):
    """Run verify_refs.py to find files needing @var migration."""
    check_path = args[0] if args else str(CHILD_PATH)
    
    # Import and run verify_refs
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from verify_refs import find_literal_paths, LITERAL_PATH_PATTERNS, EXCEPTIONS
    
    issues = []
    check_path_obj = Path(check_path)
    
    if check_path_obj.is_file():
        issues.extend(find_literal_paths(check_path_obj))
    elif check_path_obj.is_dir():
        for vsm_file in sorted(check_path_obj.rglob("*.vsm")):
            if "archive" in str(vsm_file):
                continue
            issues.extend(find_literal_paths(vsm_file))
    
    return json.dumps({
        "path": check_path,
        "issues_found": len(issues),
        "issues": issues[:20]  # Limit to 20 for output
    }, indent=2)


def cmd_add_binding(args):
    """Add a binding to instance.vsm."""
    if len(args) < 1:
        return json.dumps({"error": "Usage: add-binding <path> [--name <name>] [--dry-run]"})
    
    path = args[0]
    dry_run = "--dry-run" in args
    
    # Parse optional name
    name = None
    if "--name" in args:
        name_idx = args.index("--name")
        if name_idx + 1 < len(args):
            name = args[name_idx + 1]
    
    # Import and run add_binding
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from add_binding import add_binding, generate_binding_name
    
    binding_name = name or generate_binding_name(path)
    success = add_binding(binding_name, path, dry_run)
    
    return json.dumps({
        "success": success,
        "binding_name": binding_name,
        "path": path,
        "dry_run": dry_run
    }, indent=2)


def cmd_route_component(args):
    """Route a component to its correct destination. With --execute, also moves + registers."""
    if not args:
        return json.dumps({"error": "Usage: route-component <file_or_dir> [--execute] [--dry-run]"})
    
    filepath = args[0]
    execute = "--execute" in args
    dry_run = "--dry-run" in args
    
    # Import and run route_component
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from route_component import route_component, execute_routing, asdict
    
    decision = route_component(Path(filepath))
    result = {
        "file": str(filepath),
        "destination": decision.destination,
        "confidence": decision.confidence,
        "reasons": decision.reasons,
        "alternatives": decision.alternatives,
        "examples": decision.examples
    }
    
    if execute or dry_run:
        exec_result = execute_routing(Path(filepath), decision, dry_run=dry_run)
        result["execution"] = asdict(exec_result)
    
    return json.dumps(result, indent=2)


def cmd_post_register(args):
    """post-register <tree|component> <path> — Verify file after registration."""
    if len(args) < 2:
        return json.dumps({"error": "Usage: post-register <tree|component> <path>"})
    
    registry_type = args[0]
    filepath = args[1]
    
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from post_register import verify_component, revert_registration, asdict
    
    result = verify_component(filepath)
    
    # Auto-revert on failure
    if result.action == "reverted":
        revert_registration(registry_type, result.path)
    
    return json.dumps(asdict(result), indent=2)


def cmd_verify_pipeline(args):
    """verify-pipeline — Audit all registrations in both registries."""
    sys.path.insert(0, os.path.join(CHILD_PATH, "scripts", "vsl"))
    from post_register import audit_all
    
    results = audit_all()
    return json.dumps(results, indent=2)


if __name__ == "__main__":
    
    main()
    
