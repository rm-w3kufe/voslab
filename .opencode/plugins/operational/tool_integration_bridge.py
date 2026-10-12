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
  # NEW: P1 instrument wiring (read-only graph queries, W1/W2)
  graph-query <stats|show|export> [opts] — Epistemic graph projection
  task-graph <roots|stats|show|unblocks|blocked-by|path|open|dot> [args] — Task DAG
  # NEW: VSF-RSI features
  rsi-status                       — Get observer status
  rsi-correct <failure_json>       — Generate correction
  rsi-learn <tool> <file> <outcome>  — Learn from action
  rsi-queue [status]               — List approval queue (L4 governance)
  rsi-queue-digest                 — Queue grouped by risk class + age (R1)
  caution-signal <src> <msg>       — Advisory pilot signal, propose-only (R5)
  distill-expire [--apply]         — Expiry view / marking, 60d rule (R4)
  pleasure-collapse-check          — Streak-collapse detector, read-only (R7-B)
  rsi-approve <name>               — Human approves queued predicate
  rsi-reject <name> [reason]       — Human rejects queued predicate
  rsi-revoke <name> [reason]       — Revoke activated predicate (quarantine)
  rsi-diff <name>                  — Review current vs proposed tree
  rsi-faults                       — List detected complex faults (L3)
  rsi-thresholds                   — Show live vs policy thresholds
  rsi-threshold-set <key> <int>    — Audited tuning (rules enforced)
  rsi-caution                      — Show caution/viability state
  rsi-caution-clear                — Explicit human clear (audited)
  rsi-verify-chain                 — Verify governance hash-chain integrity
"""
from __future__ import annotations
# stdout redirect removed - using -W ignore instead

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ─── Path setup ────────────────────────────────────────────────────────────────
VOS_ROOT = os.environ.get("VOS_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# S5 containment: vendored sources live INSIDE vOSlab (was ../../state-canon-mcp
# and ../../packages/public/vsf-rsi outside the workspace).
STATE_CANON_PATH = os.path.join(VOS_ROOT, "packages", "public", "state-canon-mcp")
STATE_CANON_VENDOR = os.path.join(STATE_CANON_PATH, "vendor")
RSI_PATH = os.path.join(VOS_ROOT, "packages", "public", "vsf-rsi")
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
    """Query tasks from state-canon via VsmStateProvider.

    Domain "focus" (G-19 rewire 2026-10-03): current_focus.json exposes its
    25 entries under "focus"/"meta" — the "tasks" domain is the
    task_tracking_architecture phase_1 hierarchy, never implemented
    (tasks_count=0), so query_tasks() silently returned [] forever.
    """
    from instances.tasks_provider import VsmStateProvider
    provider = VsmStateProvider(TASKS_VSM)
    return provider.query("focus", filter_dict or {})


def query_sessions(filter_dict: dict | None = None) -> list[dict]:
    """Query sessions from the agent log (S2 rewire 2026-10-03).

    "sessions" was a phantom domain: VsmStateProvider(TASKS_VSM) only
    exposes "focus" — this returned [] forever (same dead-cable class as
    G-19 query_tasks). Real session evidence: logs/agent_plugin.jsonl
    rotates on every session restart (cycle_health._log_rows), so each
    span agent_plugin.jsonl{,.<epoch>.jsonl.gz} IS one session, and its
    action="summary:session.idle" rows are the heartbeat (same source
    cycle_health._idle_cable consumes). Only spans with >=1 heartbeat
    count as confirmed sessions; newest first; filter_dict = equality
    match on record fields. Deterministic (R10): same disk state → same
    list.
    """
    import gzip

    log_dir = os.path.join(VOS_ROOT, "logs")
    log_name = "agent_plugin.jsonl"
    try:
        names = sorted(
            name
            for name in os.listdir(log_dir)
            if name == log_name
            or (name.startswith(log_name + ".") and name.endswith(".gz"))
        )
    except OSError:
        return []
    # Fingerprint cache: full span scan costs ~1.8s (46 gz) and runs inside
    # pipeline-before (hot path, 15s bridge timeout). Rotation touches every
    # mtime/size → fingerprint invalidates automatically; same disk state →
    # same result (R10).
    fingerprint = [
        [name, os.path.getmtime(os.path.join(log_dir, name)),
         os.path.getsize(os.path.join(log_dir, name))]
        for name in names
    ]
    cache_path = os.path.join(log_dir, ".sessions_cache.json")
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("fingerprint") == fingerprint:
            sessions = cached["sessions"]
            if filter_dict and any(
                rec.get(k) != v for k, v in filter_dict.items()
            ):
                return []
            return sessions
    except (OSError, ValueError, KeyError):
        pass  # stale/corrupt cache → recompute

    spans = [os.path.join(log_dir, name) for name in names]
    spans.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    sessions = []
    for path in spans:
        idles: list[str] = []
        last_result = ""
        try:
            if path.endswith(".gz"):
                fh = gzip.open(path, "rt", encoding="utf-8", errors="replace")
            else:
                fh = open(path, encoding="utf-8", errors="replace")
            with fh:
                for line in fh:
                    if '"summary:session.idle"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("action") == "summary:session.idle" and row.get("ts"):
                        idles.append(row["ts"])
                        last_result = str(row.get("result", ""))
        except OSError:
            continue
        if not idles:
            continue  # no heartbeat → not a confirmed session span
        sessions.append(
            {
                "id": os.path.basename(path),
                "started": min(idles),
                "ended": max(idles),
                "idles": len(idles),
                "rotated_at": datetime.fromtimestamp(
                    os.path.getmtime(path), tz=timezone.utc
                ).isoformat(),
                "last_result": last_result,
            }
        )
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {"fingerprint": fingerprint, "sessions": sessions},
                fh,
                ensure_ascii=False,
            )
        os.replace(tmp, cache_path)
    except OSError:
        pass  # cache write best-effort
    if filter_dict and any(
        rec.get(k) != v for k, v in filter_dict.items()
    ):
        return []
    return sessions


def get_recent_actions(n: int = 20) -> list[dict]:
    """Get the last N actions from integration log (for redundancy detection).

    H3: bounded tail-read — the log grows unboundedly (MBs); reading it
    whole per tool call cost ~50ms and worsens forever. Seek to the last
    64KB (>> 20 entries at ~130B each) and parse forward. O(1) in log size.
    """
    if not os.path.exists(INTEGRATION_LOG):
        return []
    TAIL_BYTES = 65536
    try:
        with open(INTEGRATION_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            if size > TAIL_BYTES:
                f.readline()  # drop partial first line
            chunk = f.read().decode("utf-8", errors="replace")
        afters = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("phase") == "after":
                afters.append(rec)
        return afters[-n:]
    except Exception:
        return []


def get_current_task_context(tasks: list[dict]) -> dict:
    """Extract task context: what is the agent supposed to be doing?

    Focus statuses (focus_format contract): active | paused | done.
    active -> in_progress, paused -> open (legacy key names kept for
    consumers); G-19 rewire 2026-10-03 — the old open/in_progress filters
    matched nothing against focus entries, so has_work was always False.
    """
    in_progress = [t for t in tasks if t.get("status") == "active"]
    open_tasks = [t for t in tasks if t.get("status") == "paused"]
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

    # Focus statuses (G-19): active | paused | done — legacy keys kept.
    done = sum(1 for t in tasks if t.get("status") == "done")
    open_ = sum(1 for t in tasks if t.get("status") == "paused")
    in_progress = sum(1 for t in tasks if t.get("status") == "active")

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
import fcntl as _fcntl

RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 20     # max writes per window
_RATE_LIMIT_FILE = _os.path.join(_os.path.dirname(__file__), ".rate_limit.json")
# Separate .lock file (FocusTracker pattern): the whole read-modify-write
# cycle holds LOCK_EX so two sessions (two terminals, same agent) cannot
# both slip under the cap. Lock failure degrades to the old unlocked
# behavior — never to a block (throttle must not brick writes).

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
    """Check if write rate is within limits. Returns (allowed, count).

    flock-guarded: without the lock, two near-simultaneous sessions both
    read count=19, both append, both pass — the certified throttle
    overshoots. With LOCK_EX the cycle is atomic across processes.
    """
    lock_fh = None
    try:
        lock_fh = open(_RATE_LIMIT_FILE + ".lock", "w")
        _fcntl.flock(lock_fh, _fcntl.LOCK_EX)
    except OSError:
        lock_fh = None  # read-only checkout etc.: old unlocked behavior
    try:
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
    finally:
        if lock_fh is not None:
            try:
                _fcntl.flock(lock_fh, _fcntl.LOCK_UN)
                lock_fh.close()
            except OSError:
                pass

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


def _evaluate_tree_with_attribution(tree: dict, context: dict) -> dict:
    """Evaluate a tree via RSICycle, attributing FALSE to child predicates.

    The parent verdict's source is just "op:AND" — callers
    (tool-integration.ts SECURITY_SOURCES) need the child name to
    tell a security block from an advisory one. Children are pure
    and deterministic: evaluate them on the RAW engine (no cycle
    wrappers, so no double record/enqueue/fault-feed side effects).
    Shared by evaluate_action (full tree) and pipeline_before_min.
    """
    result = _cycle.evaluate(tree, context)
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
                # Scripts corpus health (S5 2026-10-02: every script in the
                # RSI pipeline; nothing runs from ~/vsf). Cheap fs census,
                # fail-open only when the workspace itself is absent.
                {"predicate": "scripts_migrated_ok", "args": [], "kwargs": {}},
                {"predicate": "scripts_corpus_manifest_ok", "args": [], "kwargs": {}},
            ]
        }

        # Context for evaluation (don't include command - it's in the tree)
        context = {
            "tasks": tasks,
            "recent_actions": recent_actions,
            "task_context": task_context,
        }

        # Evaluate via RSICycle (attributed — shared helper)
        result = _evaluate_tree_with_attribution(tree, context)

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


def _drain_trust_spill() -> int:
    """Apply Tier1 fast-path trust signals (RAM-LIFECYCLE, alternativa 2).

    The TS Tier1 after-hook appends {file, ok} lines to
    state/rsi/trust_spill.jsonl instead of spawning python per read.
    This drains them into RiskAssessor inside an already-running
    pre_check — piggyback, zero new spawns. Best-effort, capped:
    trust is a soft signal, dropping overflow is safe and documented.

    Parallel-session safe: the spill is CLAIMED with an atomic rename,
    so exactly one session drains each batch — no double-apply, no
    read+truncate race. Stale claims (crashed drainer) are reaped by
    age (>10 min) on the next drain.
    """
    try:
        spill = os.path.join(VOS_ROOT, "state", "rsi", "trust_spill.jsonl")
        if not os.path.exists(spill):
            return 0
        claimed = f"{spill}.drain-{os.getpid()}"
        try:
            os.rename(spill, claimed)
        except (FileNotFoundError, OSError):
            return 0  # lost the claim race (or unreadable) — other side drains
        lines: list[str] = []
        try:
            with open(claimed, encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f if ln.strip()][-2000:]
        finally:
            try:
                os.unlink(claimed)
            except OSError:
                pass
        if not lines:
            return 0
        try:
            sys.path.insert(0, CHILD_PATH)
            from risk_assessor import RiskAssessor
            assessor = RiskAssessor(CHILD_PATH)
        except Exception:
            return 0
        applied = 0
        for ln in lines:
            try:
                e = json.loads(ln)
                assessor.record_outcome(str(e.get("file", "")), bool(e.get("ok")))
                applied += 1
            except Exception:
                continue
        _reap_stale_drain_claims(spill)
        return applied
    except Exception:
        return 0


def _reap_stale_drain_claims(spill: str) -> None:
    """Delete .drain-PID leftovers older than 10 min (crashed drainer)."""
    try:
        base = os.path.basename(spill) + ".drain-"
        parent = os.path.dirname(spill)
        now = _time.time()
        for name in os.listdir(parent):
            if not name.startswith(base):
                continue
            p = os.path.join(parent, name)
            try:
                if now - os.path.getmtime(p) > 600:
                    os.unlink(p)
            except OSError:
                continue
    except Exception:
        pass


def pre_check(context: dict) -> dict:
    """Pre-check: evaluate if action is appropriate BEFORE execution."""
    # Drain Tier1 trust spill first (cheap file, no spawn of its own).
    _drain_trust_spill()
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

def record_pattern(tool: str, file: str, outcome: str,
                   full: bool = False) -> dict:
    """Record a pattern in scenario memory (hot path: record ONLY).

    H3 finding: running the FULL RSI pipeline (record -> adapt -> learn ->
    generate, incl. predicate synthesis) on every tool call costs seconds
    (p95 ~5s). Learning phases belong to the session.idle cadence
    (learn-pipeline command), not the per-action hot path.

    Args:
        full: if True, run the full pipeline (explicit callers only).
            Default False: scenario_memory.record in milliseconds.

    Return shape is stable either way (pipeline keys default when skipped)
    so existing callers (.get with defaults) keep working.
    """
    fault_sig = f"plugin.{tool}.{os.path.basename(file)}"
    if not full:
        try:
            from vsf_rsi.scenario_memory import record
            entry_id = record(
                decision=f"{tool}:{os.path.basename(file)}",
                outcome=outcome,
                correction_path=f"plugin:tool-integration:{tool}",
                fault_signature=fault_sig,
            )
            return {"entry_id": entry_id, "recorded": True,
                    "patterns_found": 0, "predicate_generated": False,
                    "predicate_registered": False, "predicate_name": None,
                    "mode": "record-only"}
        except Exception as e:
            return {"entry_id": None, "recorded": False,
                    "pipeline_error": str(e), "mode": "record-only"}
    try:
        from vsf_rsi.rsi_pipeline import pipeline
        result = pipeline(
            tool=tool,
            command=file,
            outcome=outcome,
            fault_signature=fault_sig,
            quality=1.0 if outcome == "success" else 0.2,
        )
        return {
            "entry_id": result.get("scenario_id"),
            "recorded": result.get("recorded", False),
            "patterns_found": result.get("patterns_found", 0),
            "predicate_generated": result.get("predicate_generated", False),
            "predicate_registered": result.get("predicate_registered", False),
            "predicate_name": result.get("predicate_name"),
            "mode": "full-pipeline",
        }
    except Exception as e:
        # Fallback to simple record if pipeline fails
        from vsf_rsi.scenario_memory import record
        entry_id = record(
            decision=f"{tool}:{os.path.basename(file)}",
            outcome=outcome,
            correction_path=f"plugin:tool-integration:{tool}",
            fault_signature=fault_sig,
        )
        return {"entry_id": entry_id, "recorded": True, "pipeline_error": str(e),
                "mode": "full-pipeline-fallback"}


def match_patterns(fault_signature: str) -> list:
    """Match against recorded patterns."""
    from vsf_rsi.scenario_memory import match
    return match(fault_signature, threshold=0.0)


def review_advisory_thresholds(sketch_path: str | None = None) -> dict:
    """L1 auto-review: propose/apply read_warn_bytes from measured sizes.

    Advisory-only, bounded, audited — the already-approved L1 rule set.
    Needs >=30 samples; otherwise reports waiting (no weak-data moves).
    """
    import math
    sketch = sketch_path or os.path.join(VOS_ROOT, "state", "rsi",
                                         "read_sizes.jsonl")
    sizes = []
    try:
        with open(sketch, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    sizes.append(int(json.loads(line).get("size", 0)))
                except Exception:
                    continue
    except OSError:
        return {"reviewed": False, "reason": "no sketch"}
    if len(sizes) < 30:
        return {"reviewed": False, "reason": f"only {len(sizes)} samples (<30)"}
    sizes.sort()
    p95 = sizes[min(len(sizes) - 1, int(math.ceil(0.95 * len(sizes))) - 1)]
    proposal = max(65536, min(4194304, int(p95 * 2 / 1024) * 1024))
    import sys as _sys9
    _sys9.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
    try:
        from access_policy import operating_thresholds, set_operating_threshold
    except ImportError:
        from system.kernel.access_policy import (
            operating_thresholds, set_operating_threshold)
    current = operating_thresholds()["read_warn_bytes"]
    if proposal == current:
        return {"reviewed": True, "n": len(sizes), "p95": p95,
                "action": "hold", "value": current}
    res = set_operating_threshold("read_warn_bytes", proposal)
    if res.get("ok"):
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "learn",
            "tool": "rsi-threshold-review",
            "file": f"read_warn_bytes={proposal}",
            "outcome": "success",
            "level": "decision",
            "evidence": {"basis": f"p95 of {len(sizes)} reads",
                         "previous": current},
        })
    return {"reviewed": True, "n": len(sizes), "p95": p95,
            "action": "applied" if res.get("ok") else "refused",
            "result": res}


def _ga_weekly_stage() -> dict:
    """G-17: GA/forest wired to a weekly trigger (S1, 2026-10-03).

    Was manual-only: 0 invokers in handlers/kernel, last run Oct 2,
    generated/ stale since Sep7. Now runs from learn-pipeline (session.idle),
    throttled to 7 days via state/rsi/.ga_last — the same marker pattern
    as session-lifecycle's idle throttle. Measured cost: ~0.08s (task_has_work
    converged at 4/10 gens). Output = evolution history on disk; nothing is
    activated (L4 ceiling intact — activation-by-approval via rsi-approve).
    Throttle is wall-clock only → deterministic (R10).
    """
    marker = os.path.join(VOS_ROOT, "state", "rsi", ".ga_last")
    week_s = 7 * 24 * 3600
    try:
        if os.path.exists(marker):
            last = float(open(marker).read().strip() or 0)
            if _time.time() - last < week_s:
                return {"ran": False, "reason": "weekly throttle"}
    except (OSError, ValueError):
        pass  # unreadable marker → run (fail-open, never skip forever)
    try:
        classifier = os.path.join(VOS_ROOT, "scripts", "vsl", "classifier")
        if classifier not in sys.path:
            sys.path.insert(0, classifier)
        from rsi_genetic_algorithm_v2 import RSIGeneticAlgorithmV2

        res = RSIGeneticAlgorithmV2().evolve_forest("task_has_work")
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w") as fh:
                fh.write(str(_time.time()))
        except OSError:
            pass  # best-effort — a missed marker just runs again next idle
        out = {
            "ran": True,
            "generations": res.get("generations"),
            "converged": res.get("converged"),
        }
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "learn",
            "tool": "ga-weekly",
            "file": "rsi_genetic_algorithm_v2",
            "outcome": "success",
            "detail": f"G-17 weekly GA: {out}",
        })
        return out
    except Exception as e:
        return {"ran": False, "error": str(e)[:120]}


def _prune_attestations_stage() -> dict:
    """D-14: attestation retention wired to a weekly trigger (S5 2026-10-05).

    Was zero-retention: ~1000 files/day, 94M on 23k small files, no
    prune/rotate declared anywhere. rmw3 approved window=7d + weekly
    auto-wiring (R17: explicit S5 order on 2026-10-05; first --apply
    deleted 18,061 files under that same order).

    Runs from learn-pipeline (session.idle), throttled to 7 days via
    state/rsi/.attest_prune_last (same marker pattern as .ga_last).
    DRY-RUN semantics live inside prune_attestations.py — here apply=True
    IS the standing order, only within the approved window. Deterministic
    (R10): filename epoch + ts cross-check, newest-100 floor, never
    touches non-attestation files. Throttle wall-clock only.
    """
    marker = os.path.join(VOS_ROOT, "state", "rsi", ".attest_prune_last")
    week_s = 7 * 24 * 3600
    try:
        if os.path.exists(marker):
            last = float(open(marker).read().strip() or 0)
            if _time.time() - last < week_s:
                return {"ran": False, "reason": "weekly throttle"}
    except (OSError, ValueError):
        pass  # unreadable marker → run (fail-open, never skip forever)
    try:
        core = os.path.join(VOS_ROOT, "scripts", "state", "core")
        if core not in sys.path:
            sys.path.insert(0, core)
        from prune_attestations import run as prune_run
        from pathlib import Path as _P

        res = prune_run(_P(os.path.join(VOS_ROOT, "state", "rsi",
                                        "attestations")),
                        keep_days=7, keep_newest=100, apply=True)
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w") as fh:
                fh.write(str(_time.time()))
        except OSError:
            pass  # best-effort — a missed marker just runs again next idle
        out = {
            "ran": True,
            "candidates": res.get("candidates"),
            "deleted": res.get("deleted"),
            "remaining": res.get("total_files"),
        }
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "learn",
            "tool": "attest-prune-weekly",
            "file": "prune_attestations",
            "outcome": "success" if res.get("ok") else "partial",
            "detail": f"D-14 weekly attest prune (7d window): {out}",
        })
        return out
    except Exception as e:
        return {"ran": False, "error": str(e)[:120]}


def _alert_consume_stage() -> dict:
    """1c: session-anchored algedonic consumer (S5 2026-10-05).

    The queue's only consumer was alert_consume --boot, but this host
    suspends instead of rebooting — unacked pain piled up (350 unacked,
    212 older than 24h; evidence 2026-10-05) while health alarms were
    mostly test-leak noise (sealed cb0f383).

    Wired to session.created (session-lifecycle.ts): surface the
    unacked set to the unified log (S5 list semantics), then acknowledge
    entries older than 24h — fresh pain stays unacked and visible until
    a later session consumes it. Read-only observation + ack: safe under
    caution/SAFE; algedonic signals must reach S5 unfiltered (CC-8
    constraint). Deterministic (R10): wall-clock cutoff only.
    """
    try:
        from alerting import AlertMonitor
        from collections import Counter

        monitor = AlertMonitor()
        alerts = monitor._read_alerts()
        unacked = [a for a in alerts if not a.get("acknowledged")]
        if not unacked:
            return {"unacked": 0, "acked_stale": 0, "fresh_remaining": 0}
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        stale_ids = [a["alert_id"] for a in unacked
                     if str(a.get("ts", "")) < cutoff]
        stale_set = set(stale_ids)
        fresh_n = sum(1 for a in unacked if a.get("alert_id") not in stale_set)
        types = dict(Counter(str(a.get("alert_type", "?")) for a in unacked))
        sample = [f"{str(a.get('ts', '?'))[:16]} {a.get('alert_type', '?')}"
                  for a in unacked[-3:]]
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "algedonic",
            "tool": "alert-consume",
            "file": "state/rsi/alerts.jsonl",
            "outcome": "success",
            "detail": (f"unacked={len(unacked)} stale>24h={len(stale_ids)} "
                       f"fresh={fresh_n} types={types} last={sample}"),
        })
        acked = monitor.acknowledge_many(stale_ids) if stale_ids else 0
        if acked:
            log_integration({
                "ts": datetime.now(timezone.utc).isoformat(),
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "phase": "algedonic",
                "tool": "alert-consume-ack",
                "file": "state/rsi/alerts.jsonl",
                "outcome": "success",
                "detail": (f"acked {acked} entries older than 24h; "
                           f"fresh left unacked={fresh_n}"),
            })
        return {"unacked": len(unacked), "acked_stale": acked,
                "fresh_remaining": fresh_n}
    except Exception as e:
        return {"error": str(e)[:120]}


def _abstention_check_stage() -> dict:
    """1d: session-anchored abstention-collapse alarm (§6.3, F4.2).

    Rolling window over tree traces: a sustained zero-abstention rate
    (no UNKNOWN/uncertified verdicts across a full window spanning
    >=24h) is the compliance-bias / gates-captured signature → ONE
    algedonic alert via AlertMonitor._check_abstention_collapse
    (dedup: unacked or <24h same-type suppresses). Runs BEFORE
    alert-consume at session.created so a fresh signal is surfaced in
    the same breath (CC-8: pain reaches S5 unfiltered). Emission only
    to state/rsi/alerts.jsonl — never raises to the caller.
    Deterministic (R10): counts + wall-clock cutoff only.
    """
    try:
        from alerting import AlertMonitor
        monitor = AlertMonitor()
        alerts = monitor._check_abstention_collapse()
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "algedonic",
            "tool": "abstention-check",
            "file": "state/rsi/alerts.jsonl",
            "outcome": "success",
            "detail": ("emitted abstention_collapse: " + alerts[0].detail)
                      if alerts else "abstention window check: no signal",
        })
        return {"emitted": len(alerts),
                "alert_type": "abstention_collapse"}
    except Exception as e:
        return {"error": str(e)[:120]}


def _evolution_daily_stage() -> dict:
    """G-03-B: evolution report auto-run, daily throttle (S5 2026-10-05).

    CC-8.0 exit criterion 1 relied on MANUAL daily runs on a host that
    suspends — runs existed only for 10-01 and 10-03 and the
    '3 consecutive days' count could never survive offline gaps (S5:
    "la dificultad de mantener el conteo ... equipo que se conecta y
    desconecta"). Ratified amend (A) makes the criterion a rolling 7d
    window; this stage (B) makes the cadence heroics-free: run the
    generator at most once per 24h from the learn-pipeline
    (session.idle), throttled via state/rsi/.evolution_daily (same
    marker pattern as .ga_last / .attest_prune_last). Marker written
    ONLY on success — a failed run retries next idle. Subprocess keeps
    the bridge import surface clean; timeout bounded so a hung report
    never blocks the idle cycle. Deterministic (R10): wall-clock
    throttle only.
    """
    marker = os.path.join(VOS_ROOT, "state", "rsi", ".evolution_daily")
    day_s = 24 * 3600
    try:
        if os.path.exists(marker):
            last = float(open(marker).read().strip() or 0)
            if _time.time() - last < day_s:
                return {"ran": False, "reason": "daily throttle"}
    except (OSError, ValueError):
        pass  # unreadable marker → run (fail-open, never skip forever)
    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-m", "vos_kernel.evolution_report"],
            cwd=VOS_ROOT, capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            return {"ran": False, "rc": proc.returncode,
                    "error": (proc.stderr or proc.stdout or "")[:160]}
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w") as fh:
                fh.write(str(_time.time()))
        except OSError:
            pass  # best-effort — a missed marker just runs again next idle
        out = {"ran": True,
               "tail": (proc.stdout or "").strip().splitlines()[-1][:160]
                       if proc.stdout else ""}
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "learn",
            "tool": "evolution-daily",
            "file": "state/epistemic/reports/EVOLUTION.md",
            "outcome": "success",
            "detail": f"G-03-B daily evolution report: {out}",
        })
        return out
    except Exception as e:
        return {"ran": False, "error": str(e)[:120]}



def _pleasure_session_close_stage() -> dict:
    """G-34 P2 (PLEASURE-CHANNEL-001): cierre de sesion limpio -> placer.

    Limpio = current_focus con >=1 entrada y TODAS status=done. Advisory +
    fail-open (proposal GUARD): jamas afecta el pipeline de learn ni toca
    alerts.jsonl (F2). Anti-duplicado por transicion: el snapshot limpio
    se marca en state/cache/.pleasure_close_marker (gitignored) — cada
    idle repetido con el mismo estado NO re-emite.
    """
    try:
        import sys as _sysp
        _fw = os.path.join(VOS_ROOT, "packages", "framework")
        if _fw not in _sysp.path:
            _sysp.path.insert(0, _fw)
        import hashlib
        from vos_kernel.pleasure_emitter import emit
        focus_path = os.path.join(VOS_ROOT, "current_focus.json")
        if not os.path.exists(focus_path):
            return {"emitted": False, "reason": "no focus file"}
        with open(focus_path, encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list) or not entries:
            return {"emitted": False, "reason": "no focus entries"}
        if not all((e or {}).get("status") == "done" for e in entries):
            return {"emitted": False, "reason": "focus not all done"}
        snap = hashlib.sha256("|".join(
            sorted(f"{(e or {}).get('ref', '')}:{(e or {}).get('status', '')}"
                   for e in entries)
        ).encode("utf-8")).hexdigest()[:16]
        marker = os.path.join(VOS_ROOT, "state", "cache",
                              ".pleasure_close_marker")
        if os.path.exists(marker):
            with open(marker, encoding="utf-8") as f:
                if f.read().strip() == snap:
                    return {"emitted": False, "reason": "snapshot unchanged"}
        rec = emit(
            "session_close", True,
            detail=f"{len(entries)} focus done",
            source="learn-pipeline",
            connection="__global__",
            feedback=True,  # P3 hebbiano (fail-open interno)
        )
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(snap)
        return {"emitted": True, "event_id": rec.get("event_id")}
    except Exception as exc:  # fail-open: jamas rompe learn-pipeline
        return {"emitted": False, "reason": f"fail-open: {exc}"[:160]}


def run_learn_pipeline() -> dict:
    """Run the learning pipeline: detect patterns → generate → QUEUE.

    L4 autonomy ceiling (S5): NOTHING generated here is ever activated
    directly. Candidates go to the approval queue; a human approves via
    `rsi-approve` before the cycle loads them (activation-by-approval).

    Call this from session.idle to enable second-order learning.
    Caution suspends generation (observation/recording continue).
    """
    # G-03-B runs FIRST and is carried through every skip return:
    # the evolution report is observation/recording — it continues
    # under caution/SAFE (CC-8: presentation capability never gated).
    evolution_daily = _evolution_daily_stage()
    # G-34 P2: cierre limpio observado en cada idle (antes de los gates
    # de modo — cerrar sesion es observacion, continua bajo caution/SAFE).
    pleasure_close = _pleasure_session_close_stage()
    try:
        import sys as _sys2
        _sys2.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
        try:
            from vsm_viability import evolution_allowed
        except ImportError:
            from system.kernel.vsm_viability import evolution_allowed
        _allowed, _why = evolution_allowed()
        if not _allowed:
            return {"skipped": True, "reason": "caution active",
                    "detail": _why, "evolution_daily": evolution_daily,
                    "pleasure_close": pleasure_close}
        try:
            from vsm_viability import mode_allows, read_mode, rsi_mode
        except ImportError:
            from system.kernel.vsm_viability import (
                mode_allows, read_mode, rsi_mode)
        if rsi_mode() == "SAFE":
            return {"skipped": True, "reason": "RSI_MODE=SAFE",
                    "evolution_daily": evolution_daily,
                    "pleasure_close": pleasure_close}
        if not mode_allows(read_mode(), "learn_pipeline"):
            return {"skipped": True, "reason": "degraded mode",
                    "mode": read_mode(), "evolution_daily": evolution_daily,
                    "pleasure_close": pleasure_close}
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
        try:
            results["threshold_review"] = review_advisory_thresholds()
        except Exception as e:
            results["threshold_review"] = {"reviewed": False,
                                           "reason": f"review error: {e}"[:120]}
        # G-17 (S1): GA/forest weekly stage — wired, throttled, logged.
        results["ga_weekly"] = _ga_weekly_stage()
        # D-14 (S5 2026-10-05): attestation retention — weekly, throttled,
        # apply within the approved 7d window (standing order R17).
        results["attest_prune_weekly"] = _prune_attestations_stage()
        results["evolution_daily"] = evolution_daily
        results["pleasure_close"] = pleasure_close
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

    # Explicit level override (allowlisted): human decisions log as
    # decision, digests as summary — the view_log taxonomy only works
    # if emitters actually emit these levels (2026-09-10 audit).
    _LEVELS = {"activation", "error", "warning", "decision", "summary", "trace"}
    if entry.get("level") in _LEVELS:
        level_override = entry["level"]
    else:
        level_override = None

    # Build detail string
    detail_parts = []
    if entry.get("detail"):
        detail_parts.append(str(entry["detail"])[:200])
    if entry.get("evidence"):
        detail_parts.append(json.dumps(entry["evidence"], default=str)[:200])
    if entry.get("matches"):
        detail_parts.append(f"matches={len(entry['matches'])}")
    detail = " | ".join(detail_parts)
    
    # Determine log level
    if level_override is not None:
        level = level_override
    else:
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
        # P0 session attribution (§11.7): inherited from the opencode
        # process env (set on session.created / tool.execute.before).
        "session_id": os.environ.get("VOS_SESSION_ID") or None,
        "context": entry.get("evidence", {}),
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(unified) + "\n")

    # REVIVAL (dependency map #3): state/integration_log.jsonl had been
    # dead since 08-sep (nothing wrote to it) and its readers
    # (get_recent_actions -> not_redundant, get_session_stats) ran in
    # amnesia. Dual-write with the original schema (ts/date/phase/
    # tool/file/outcome + extras); capped at 1MB (tail 2000 lines).
    # Declared effect: not_redundant sees the past again (threshold 3,
    # 2-with-error) and session-report counts for real. Watch FPs during
    # the first sessions: blocks surface with source not_redundant.
    try:
        now = datetime.now(timezone.utc)
        record = {"ts": entry.get("ts", now.isoformat()),
                  "date": entry.get("date", now.strftime("%Y-%m-%d"))}
        record.update({k: v for k, v in entry.items()
                       if k not in ("ts", "date")})
        ilog = INTEGRATION_LOG
        try:
            if os.path.exists(ilog) and os.path.getsize(ilog) > 1024 * 1024:
                with open(ilog, encoding="utf-8", errors="replace") as f:
                    tail = f.read().splitlines()[-2000:]
                with open(ilog, "w", encoding="utf-8") as f:
                    f.write("\n".join(tail) + ("\n" if tail else ""))
        except OSError:
            pass
        with open(ilog, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass  # integration log must never break the pipeline)


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
                
                # G-21 root fix (2026-10-07): evaluate on the RAW engine
                # with the same enriched context, but WITHOUT the cycle's
                # failure side effects. cycle.evaluate() treats every
                # certified FALSE as a fault: records it, feeds the fault
                # detector, and enqueues fix_op_AND (auto-gen placeholder)
                # on every non-matching tool call — the queue spam
                # diagnosed in G-21 (160/160 rsi_bash_grep evals FALSE =
                # pattern simply doesn't match). Here FALSE means "pattern
                # doesn't match" (decision logic below: IGNORE), not a
                # fault. Same rationale as _evaluate_tree_with_attribution's
                # raw-engine children (no record/enqueue/fault-feed).
                full_ctx = {**context, **cycle._get_state_context()}
                ev = cycle.engine.evaluate(tree, full_ctx, enforce_limits=True)
                truth = ev.truth.name if hasattr(ev.truth, "name") \
                    else str(ev.truth)
                certified = ev.certified
                evidence = ev.evidence or {}
                
                if truth in ("TRUE", "FALSE") and certified:
                    matches.append({
                        "name": pred_name,
                        "truth": truth,
                        "certified": certified,
                        "evidence": evidence,
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


def _capture_json(fn, args):
    """Run a legacy cmd_* in-process, capturing what it would print.

    Multiplex helper (RAM-LIFECYCLE, alternativa 2): the legacy commands
    either print one JSON object or return a JSON string. This captures
    both shapes WITHOUT spawning a new interpreter and WITHOUT touching
    legacy code paths (they stay byte-identical for fallback).
    Returns the parsed dict, or {"error": ...} when nothing parseable.
    """
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    ret = None
    try:
        with redirect_stdout(buf):
            ret = fn(args)
    except Exception as e:
        return {"error": f"capture: {e}"[:200]}
    txt = buf.getvalue().strip()
    if txt and "{" in txt:
        try:
            return json.loads(txt[txt.index("{"):])
        except Exception:
            pass
    if isinstance(ret, str):
        try:
            return json.loads(ret)
        except Exception:
            return {"raw": ret[:200]}
    if isinstance(ret, dict):
        return ret
    if txt:
        return {"raw": txt[:200]}
    return {"ok": True}


def _risk_assess_inner(tool, file, command):
    """Same verdict as cmd_risk_assess, returned (not printed)."""
    try:
        if _risk_assessor is None:
            return None
        return _risk_assessor.assess(tool, file, command, extra={}).to_dict()
    except Exception:
        return None


def pipeline_before_min(context):
    """R2-REDUCIR: minimal blind before — only signals provable blind.

    Archaeology (22k lines): blind risk never exceeded MEDIUM, blind
    pre-check never went FALSE, empty RSI evaluates nothing, stash and
    content-check are unreachable without hook args. The only blind
    signals with teeth: write rate-limit, state_consistent tripwire,
    write_scope_ok. Everything else moved to the informed after-phase.

    RESTORED (was dead in main path): the write rate throttle. It only
    lived in the fallback engine; the RSICycle tree never included it.
    Same certified verdict shape as the fallback predicate.

    Returns {"mode": "min", "preCheck": {ok, socratic}}; the TS skips
    the risk/rsi legs on mode min and enforces the socratic block.
    """
    try:
        _drain_trust_spill()
        tool = context.get("tool", "")
        file = context.get("file", "")
        if _cycle is None:
            return {"mode": "min", "error": "no cycle",
                    "preCheck": {"ok": True, "socratic": {}}}
        if tool in ("write", "edit"):
            allowed, count = _check_rate_limit()
            if not allowed:
                verdict = {
                    "truth": "FALSE", "certified": True,
                    "source": "no_state_conflict",
                    "evidence": {
                        "reason": "rate limit exceeded",
                        "writes_in_window": count,
                        "window_seconds": RATE_LIMIT_WINDOW,
                        "limit": RATE_LIMIT_MAX,
                    },
                    "failed_predicates": ["no_state_conflict"],
                }
                _log_before_entry(tool, file, verdict)
                return {"mode": "min",
                        "preCheck": {"ok": False, "socratic": verdict}}
        tree = {
            "op": "AND",
            "children": [
                {"predicate": "write_scope_ok",
                 "args": [tool, file], "kwargs": {}},
                {"predicate": "state_consistent",
                 "args": [], "kwargs": {}},
            ]
        }
        verdict = _evaluate_tree_with_attribution(tree, {})
        _log_before_entry(tool, file, verdict)
        return {"mode": "min",
                "preCheck": {"ok": verdict.get("truth") != "FALSE",
                             "socratic": verdict}}
    except Exception as e:
        return {"mode": "min", "error": f"pipeline-before-min: {e}"[:200]}


def _log_before_entry(tool, file, eval_result):
    """Single observability line for a before verdict (min and full)."""
    _ev = dict(eval_result.get("evidence", {}) or {})
    if eval_result.get("failed_predicates"):
        _ev["failed_predicates"] = eval_result["failed_predicates"]
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": "before",
        "tool": tool,
        "file": file,
        "outcome": "allowed" if eval_result.get("truth") != "FALSE" else "blocked",
        "truth": eval_result.get("truth", "UNKNOWN"),
        "certified": eval_result.get("certified", False),
        "source": eval_result.get("source", ""),
        "evidence": _ev,
    })


def pipeline_before(context, content=""):
    """Tier2 multiplex: whole before-phase in ONE interpreter.

    Replicates the TS before sequence for state-changing tools:
      vsm-stash (best-effort) → vsm-check-content → pre-check →
      risk-assess + risk log → rsi-evaluate (+rsi log, inside cmd) →
      rsi-match log → advisory log.
    Only runs the risk/rsi legs when context says state-changing
    (same condition the TS used). Returns one dict; the TS enforces
    the identical block messages from it. Any internal failure
    degrades to {"error"} so the TS falls back to the legacy
    per-command sequence — never fail-open, never fail-dead.

    R2-REDUCIR: a blind hook (no file/command per the KEY-DUMP
    contract) takes pipeline_before_min; populated args
    auto-reactivate this full path (dormant code wakes on evidence,
    re-probe rule). Response carries mode min|full.
    """
    try:
        tool = context.get("tool", "")
        file = context.get("file", "")
        command = context.get("command", "")
        state_changing = bool(context.get("is_state_changing"))
        out: dict = {"tool": tool}

        if not file and not command and not content:
            return pipeline_before_min(context)
        out["mode"] = "full"

        # .vsm true prevention (same conditions as the TS hook)
        if tool in ("write", "edit") and file.endswith(".vsm"):
            out["stash"] = _capture_json(cmd_vsm_stash, [file])
        if tool == "write" and file.endswith(".vsm") and content:
            checked = _capture_json(
                cmd_vsm_check_content,
                [json.dumps({"content": content[:100000]})])
            out["content_check"] = checked

        # Pre-check (logs its own before-entry, as always)
        out["preCheck"] = pre_check(context)

        if state_changing:
            risk = _risk_assess_inner(tool, file, command)
            out["risk"] = risk
            if risk:
                _log_action_inner(
                    "before", tool, file or "(no file)",
                    f"risk:{risk.get('risk_level', 'LOW')}",
                    {"risk_score": risk.get("risk_score", 0),
                     "risk_level": risk.get("risk_level", "LOW"),
                     "confidence": risk.get("confidence"),
                     "recommendation": risk.get("recommendation", "proceed"),
                     "summary": risk.get("summary")})
            rsi = _capture_json(cmd_rsi_evaluate, [tool, file or "", command])
            out["rsi"] = rsi
            if isinstance(rsi, dict) and rsi.get("matches"):
                fc = rsi.get("false_count", 0)
                _log_action_inner(
                    "before", tool, file or "(no file)",
                    f"rsi:{'match' if fc > 0 else 'clear'}",
                    {"predicates_evaluated": rsi.get("predicates_evaluated"),
                     "matches": rsi.get("matches"),
                     "should_block": rsi.get("should_block"),
                     "should_warn": rsi.get("should_warn")})

        if out["preCheck"].get("ok"):
            _log_action_inner(
                "before", tool, file or "(no file)", "advisory",
                out["preCheck"].get("socratic", {}))
        return out
    except Exception as e:
        return {"error": f"pipeline-before: {e}"[:200]}


def pipeline_after(tool, file, outcome, context, flags):
    """Tier2 multiplex: whole after-phase in ONE interpreter.

    Replicates the TS after sequence:
      record-action (always) → learn-from-action (.vsm write/edit or
      bash failure) → audit-proposal + verify-refs + rsi + diagnose
      (.vsm write/edit) → route-component + post-register (.py/.ts
      write). Returns one dict; the TS emits the same activation
    lines from it.

    RESTORED (was dead, arity+shape mismatch): the RSI check on .vsm
    writes. The TS used to call rsi-evaluate with [context] (one arg;
    usage-error) and then read .evaluation.truth (wrong shape), so it
    never ran. Here it runs with (tool, file, command) and the TS
    reads the multiplex shape. Intended capability, now live.
    """
    try:
        out: dict = {"tool": tool}
        out["record"] = _capture_json(
            cmd_record_action, [tool, file, outcome, json.dumps(context)])
        is_vsm = bool(flags.get("isVsmWrite"))
        is_bash_fail = bool(flags.get("isBashFailure"))
        is_code = bool(flags.get("isCodeWrite"))
        if is_vsm or is_bash_fail:
            out["learn"] = _capture_json(
                cmd_learn_from_action, [tool, file, outcome])
        if is_vsm:
            _capture_json(cmd_audit_proposal, [file])
            # verify-refs retired (module gone, result was ignored):
            # literal-path migration is covered by gates, not the loop.
            rsi_after = evaluate_rsi_predicates(
                tool, file, context.get("command", ""))
            out["rsiAfter"] = rsi_after
            if rsi_after.get("truth") == "FALSE" or rsi_after.get("should_block"):
                out["diagnosis"] = _capture_json(
                    cmd_socratic_diagnose, [json.dumps(rsi_after)])
        if is_code:
            out["route"] = _capture_json(
                cmd_route_component, [file, "--execute"])
            # post-register retired (module gone): registration without
            # verify claim — plugin-location-valid gate + handler_states
            # test cover the registry instead. No "verified" verdicts.
        return out
    except Exception as e:
        return {"error": f"pipeline-after: {e}"[:200]}


def _log_action_inner(phase, tool, file, outcome, eval_data):
    """Same entry as cmd_log_action, without printing (multiplex use)."""
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "phase": phase,
        "tool": tool,
        "file": file,
        "outcome": outcome,
        "socratic_certified": bool((eval_data or {}).get("certified", False)),
        "socratic_truth": str((eval_data or {}).get("truth", "")),
        "socratic_source": str((eval_data or {}).get("source", "")),
        "socratic_evidence": (eval_data or {}).get("evidence", {}),
    })


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


def get_rsi_fires() -> dict:
    """R2: count learned-pattern + breaker interventions in today's log.

    Scans INTEGRATION_LOG for today's entries whose action/detail shows
    an RSI/socratic/breaker intervention. Same full-scan pattern as
    get_session_stats (created/idle frequency only). Zeroes are a real
    signal (plan success criterion tracks first fire in 30d).
    """
    out = {"blocks_learned": 0, "warns_learned": 0, "blocks_socratic": 0,
           "breaker_loop": 0, "breaker_error": 0}
    if not os.path.exists(INTEGRATION_LOG):
        return out
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(INTEGRATION_LOG) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if not entry.get("date", "").startswith(today):
                    continue
                text = str(entry.get("action", "")) + " " + str(entry.get("detail", ""))
                if "BLOCKED by RSI learned patterns" in text:
                    out["blocks_learned"] += 1
                elif "RSI pattern warning" in text:
                    out["warns_learned"] += 1
                elif "LOOP-BREAKER" in text:
                    out["breaker_loop"] += 1
                elif "ERROR-BURST" in text:
                    out["breaker_error"] += 1
                if "socratic certified FALSE" in text or "certified this action as incorrect" in text:
                    out["blocks_socratic"] += 1
    except OSError:
        pass
    return out


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

    # T4.3 telemetry: read sizes feed threshold calibration (sizes only,
    # never content). Rotated sketch in state/rsi/; predicates stay pure.
    if tool in ("read", "glob") and file:
        try:
            _sz = os.path.getsize(file)
            _sp = os.path.join(VOS_ROOT, "state", "rsi", "read_sizes.jsonl")
            with open(_sp, "a") as _f:
                _f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                     "size": _sz}) + "\n")
        except OSError:
            pass

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

    # 2b. Trust writer (A4): outcomes feed per-file trust for risk factor #8.
    # Success/failure only — never the content. Best-effort.
    try:
        sys.path.insert(0, CHILD_PATH)
        from risk_assessor import RiskAssessor
        RiskAssessor(CHILD_PATH).record_outcome(
            file, outcome in ("success", "ok"))
    except Exception:
        pass

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


def session_report_payload() -> dict:
    """session-report payload (S2 contract repair 2026-10-03).

    session-lifecycle.ts reads report.session.{total,success,failure} on
    session.created and report.tasks.{done,total} / report.tasks.total on
    session.idle — the stats-only shape served after the main()#2 rewrite
    made those accesses TypeError (CommandBridge returned get_session_stats()
    directly). Single source for the CLI handler; deterministic given disk
    state (R10).
    """
    context = get_system_context()
    return {
        "session": get_session_stats(),
        "tasks": context["tasks"],
        "sessions": context["sessions"],
        "rsi_fires": get_rsi_fires(),
    }


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
        # G-19 sibling aliases: TASKS_VSM (current_focus.json) exposes only
        # "focus" — callers ask for phantom domains. "tasks" -> focus
        # (G-19 rewire 2026-10-03); "sessions" -> query_sessions() (G-19
        # sub, W-5 2026-10-07): the provider's "sessions" domain parses
        # session() blocks of the task_tracking phase_1 hierarchy (never
        # built -> always 0), while real session evidence is the log-span
        # scan query_sessions() consumes (same dead-cable class). Unknown
        # domains still return [].
        if domain == "sessions":
            results = query_sessions(filter_dict)
            print(json.dumps(
                {"domain": domain, "count": len(results), "results": results}))
            return
        if domain == "tasks":
            domain = "focus"

        # Query via state-canon
        from instances.tasks_provider import VsmStateProvider
        provider = VsmStateProvider(TASKS_VSM)
        results = provider.query(domain, filter_dict)
        # count: session-lifecycle idle summary reads canonResult.count.
        print(json.dumps({"domain": domain, "count": len(results), "results": results}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_socratic_tree_file(args: list[str]):
    """socratic-tree-file <path> [context_json] — Evaluate a tree file.

    Gap-engine-path fix (found-debt): gap-resolver pointed at a
    scripts/vsl/classifier/socratic_engine.py that does not exist, so
    every gap evaluated to engine-not-found. This mediates file trees
    through the live cycle instead (RBAC operator, audited): .json goes
    straight in, .vsm parses via parse_socratic_block (same loading the
    socratic-engine CLI uses). Path must resolve inside the workspace
    (fail-closed); unknown suffix or missing block returns error JSON,
    never raises.
    """
    if not args:
        print(json.dumps({"error": "usage: socratic-tree-file <path> [context_json]"}))
        return
    try:
        from pathlib import Path as _P
        target = _P(os.path.realpath(os.path.abspath(
            os.path.expanduser(args[0]))))
        root = _P(os.path.realpath(VOS_ROOT))
        if target != root and root not in target.parents:
            print(json.dumps({"error": "tree path outside workspace"}))
            return
        if not target.is_file():
            print(json.dumps({"error": f"tree not found: {args[0]}"}))
            return
        context = json.loads(args[1]) if len(args) > 1 else {}
        if target.suffix == ".json":
            tree = json.loads(target.read_text(encoding="utf-8"))
        else:
            try:
                from socratic_engine.tree import parse_socratic_block
            except ImportError:
                from tree import parse_socratic_block  # type: ignore
            tree = parse_socratic_block(
                target.read_text(encoding="utf-8", errors="replace"))
            if tree is None:
                print(json.dumps({"error": "no socratic(...) block in tree file"}))
                return
        if _cycle:
            result = _cycle.evaluate(tree, context)
        else:
            from socratic_engine import SocraticEngine
            result = SocraticEngine().evaluate(tree, context)
        # home/decision derivation (FND-GAP-TREES-01 fix, 2026-09-29): the
        # gap path (gap-resolver.ts) reads result.home || result.decision,
        # but RSICycle.evaluate returns {certified, truth, source,
        # evidence} with NEITHER — so every present tree evaluated to
        # UNKNOWN downstream. tree_home() routes the winning child's home
        # (None on saw-UNKNOWN per R9). ADDITIVE keys only: raw consumers
        # keep working, gap consumers gain decisions.
        if isinstance(result, dict) and "home" not in result:
            home = None
            try:
                eng = getattr(_cycle, "engine", None)
                if eng is None:
                    from socratic_engine import SocraticEngine as _SE
                    eng = _SE()
                from socratic_engine.tree import tree_home as _tree_home
                home = _tree_home(tree, (context or {}).get("type", ""),
                                  eng, context or {})
            except Exception:
                home = None
            result = {**result, "home": home,
                      "decision": home or "UNKNOWN"}
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)[:200]}))


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
        entries = list_queue(status)
        stats = get_queue_stats()
        # G-21 (S1): inspection must leave a trace — auto_verify asks for a
        # live event in the unified log. Read-only governance, same H3
        # pattern as rsi-approve.
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phase": "governance",
            "tool": "rsi-queue",
            "file": ",".join(str(e.get("name", "")) for e in entries[:5]),
            "outcome": "success",
            "detail": f"inspect status={status} n={len(entries)} stats={stats}",
        })
        print(json.dumps({
            "status_filter": status,
            "entries": entries,
            "stats": stats,
        }, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_pleasure_collapse_check(args: list[str]) -> str:
    """pleasure-collapse-check — R7-B: detect success-streak collapse.

    Reads trailing 50 evaluate-unit events from state/rsi/pleasure.jsonl.
    Collapse = 5+ failures in window (baseline 0.46%: 44/9606; ~20x
    baseline, essentially never spurious). Returns JSON only — NEVER
    acts; the session.idle handler decides (caution-signal advisory).
    READ-ONLY.
    """
    try:
        path = os.path.join(VOS_ROOT, "state", "rsi", "pleasure.jsonl")
        if not os.path.exists(path):
            return json.dumps({"collapse": False, "reason": "no channel file"})
        recs = []
        with open(path, encoding="utf-8") as f:
            for line in f.read().splitlines()[-500:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("unit") == "evaluate":
                    recs.append(r)
        window = recs[-50:]
        fails = sum(1 for r in window if not r.get("success"))
        collapse = fails >= 5
        return json.dumps({
            "collapse": collapse,
            "failures": fails,
            "window": len(window),
            "threshold": 5,
            "note": "RPE-negative excursion pages S5 review via caution-signal (idle handler); no behavior change",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def cmd_caution_signal(args: list[str]):
    """caution-signal <source> <message> — R5 pilot, ADVISORY ONLY.

    Appends a kind=caution_signal candidate (status proposed) to
    state/distill/candidates.jsonl. NEVER touches alerts.jsonl, NEVER
    changes caution mode, NEVER auto-triggers anything — the S5 batch
    triage (R4) is the only path from signal to action. The sandbox
    drill (plan phase C) exercises the alert path without production.
    """
    import hashlib
    if len(args) < 2:
        print(json.dumps({"error": "usage: caution-signal <source> <message>"}))
        return
    try:
        source, message = args[0], args[1]
        now = datetime.now(timezone.utc)
        cid = hashlib.sha256(
            f"{source}|{message}|{now.isoformat()}".encode()).hexdigest()[:16]
        rec = {"id": cid, "kind": "caution_signal", "key": source[:120],
               "count": 1, "evidence": {}, "suggested": message[:300],
               "status": "proposed",
               "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        cand = os.path.join(VOS_ROOT, "state", "distill", "candidates.jsonl")
        with open(cand, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        log_integration({
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "phase": "governance",
            "tool": "caution-signal",
            "file": "",
            "outcome": "success",
            "detail": f"advisory signal from {source}: {message[:120]}",
        })
        print(json.dumps({"ok": True, "id": cid, "advisory": True,
                          "note": "propose-only; S5 triage decides"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_distill_expire(args: list[str]):
    """distill-expire [--apply] — R4: expiry view, optional apply.

    Default (no flags): VIEW ONLY — lists would-expire rows (proposed +
    older than 60d + kind tool_pattern) without touching the ledger.
    With --apply: marks them status=expired (+expired_ts, +expired_rule),
    preserving every other field; timestamped .bak first; atomic replace.
    Reversible: expired rows keep all data, status can be reset to
    proposed. S5 approved the 60d tool_pattern rule 2026-10-12.
    """
    import shutil
    apply = "--apply" in args
    try:
        cand = os.path.join(VOS_ROOT, "state", "distill", "candidates.jsonl")
        if not os.path.exists(cand):
            print(json.dumps({"total": 0, "would_expire": []}))
            return
        now = datetime.now(timezone.utc)
        rows = []
        for line in open(cand, encoding="utf-8").read().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        def age_days(r):
            try:
                ts = datetime.fromisoformat(str(r.get("ts", "")).replace("Z", "+00:00"))
                return (now - ts).days
            except ValueError:
                return -1
        targets = [r for r in rows
                   if r.get("status") == "proposed"
                   and r.get("kind") == "tool_pattern"
                   and age_days(r) > 60]
        if not apply:
            print(json.dumps({
                "total": len(rows),
                "would_expire": [{"id": r.get("id"), "key": str(r.get("key", ""))[:80],
                                  "age_days": age_days(r)} for r in targets],
                "mode": "view-only (pass --apply to mark)",
            }))
            return
        bak = cand + f".bak-{now.strftime('%Y%m%dT%H%M%S')}"
        shutil.copy2(cand, bak)
        marked = 0
        for r in targets:
            r["status"] = "expired"
            r["expired_ts"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            r["expired_rule"] = "60d-proposed-tool_pattern (S5 2026-10-12)"
            marked += 1
        tmp = cand + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, cand)
        log_integration({
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "phase": "governance",
            "tool": "distill-expire",
            "file": "",
            "outcome": "success",
            "detail": f"marked expired={marked} backup={bak}",
        })
        print(json.dumps({"total": len(rows), "marked": marked, "backup": bak}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_queue_digest(args: list[str]):
    """rsi-queue-digest — R1: group pending approvals by risk class + age.

    Classes: threshold-tune (name mentions threshold/adjust/tune),
    tree-patch (entry carries a tree), other. Per entry: name, age_days,
    class, source. Summary: counts per class + oldest age. READ-ONLY.
    """
    try:
        from vsf_rsi.rsi_socratic_bridge import list_queue, get_queue_stats
        entries = list_queue("pending")
        stats = get_queue_stats()
        now = datetime.now(timezone.utc)
        digest = []
        for e in entries:
            name = str(e.get("name", "?"))
            ln = name.lower()
            if any(k in ln for k in ("threshold", "adjust", "tune", "cooldown")):
                cls = "threshold-tune"
            elif e.get("tree"):
                cls = "tree-patch"
            else:
                cls = "other"
            try:
                qts = str(e.get("queued_at", ""))
                qt = datetime.fromisoformat(qts)
                if qt.tzinfo is None:
                    qt = qt.replace(tzinfo=timezone.utc)
                age = (now - qt).days
            except Exception:
                age = -1
            digest.append({"name": name, "age_days": age, "class": cls,
                           "source": str(e.get("source", "?"))})
        by_class: dict = {}
        for d in digest:
            by_class[d["class"]] = by_class.get(d["class"], 0) + 1
        oldest = max((d["age_days"] for d in digest), default=0)
        log_integration({
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "phase": "governance",
            "tool": "rsi-queue-digest",
            "file": "",
            "outcome": "success",
            "detail": f"digest pending={len(digest)} by_class={by_class} oldest_days={oldest}",
        })
        print(json.dumps({
            "pending": len(digest),
            "by_class": by_class,
            "oldest_days": oldest,
            "entries": sorted(digest, key=lambda d: d["age_days"], reverse=True),
            "stats": stats,
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
        if ok:
            _chain_verdict("approve", args[0], True, {})
        # H3: governance actions leave a trace in the unified log.
        # Human approvals are DECISION-level events (view_log taxonomy).
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "governance",
            "tool": "rsi-approve",
            "file": args[0],
            "outcome": "success" if ok else "failure",
            "level": "decision",
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
        if ok:
            _chain_verdict("reject", args[0], False,
                           {"reason": " ".join(args[1:])[:120]})
        # H3: governance actions leave a trace in the unified log.
        # Human rejections are DECISION-level events (view_log taxonomy).
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "governance",
            "tool": "rsi-reject",
            "file": args[0],
            "outcome": "success" if ok else "failure",
            "level": "decision",
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


def cmd_rsi_thresholds(args: list[str]):
    """rsi-thresholds — Show live operating thresholds vs S5 policy."""
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
        from access_policy import load, operating_thresholds
        policy = load()
        print(json.dumps({
            "policy_defaults": policy["thresholds"],
            "operating": {k: v for k, v in operating_thresholds().items()
                          if k != "degraded"},
            "degraded": policy.get("degraded", False),
            "rules": "blocking keys down-only; advisory within [64K, 4M]; "
                     "loosening requires CLI policy edit",
        }))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_threshold_set(args: list[str]):
    """rsi-threshold-set <key> <int> — Audited human tuning (rules enforced)."""
    if len(args) < 2:
        print(json.dumps({"error": "usage: rsi-threshold-set <key> <int>"}))
        return
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
        from access_policy import set_operating_threshold
        try:
            value = int(args[1])
        except ValueError:
            print(json.dumps({"error": "value must be int"}))
            return
        res = set_operating_threshold(args[0], value)
        if res.get("ok"):
            log_integration({
                "ts": datetime.now(timezone.utc).isoformat(),
                "phase": "governance",
                "tool": "rsi-threshold-set",
                "file": f"{args[0]}={value}",
                "outcome": "success",
                "level": "decision",
            })
        print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def _viability_mod():
    import sys as _sys3
    _sys3.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
    try:
        import vsm_viability as _m
    except ImportError:
        import system.kernel.vsm_viability as _m
    return _m


def cmd_rsi_caution(args: list[str]):
    """rsi-caution — Show caution/viability state (Omega)."""
    try:
        mod = _viability_mod()
        state = mod.ViabilityState()
        print(json.dumps({
            "caution": mod.get_caution(),
            "evolution_allowed": mod.evolution_allowed()[0],
        }, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_caution_clear(args: list[str]):
    """rsi-caution-clear — Explicit human clear (audited, no auto-clear)."""
    try:
        mod = _viability_mod()
        res = mod.clear_caution(actor="human:cli")
        log_integration({
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "governance",
            "tool": "rsi-caution-clear",
            "file": "",
            "outcome": "success",
            "level": "decision",
        })
        print(json.dumps(res, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


def cmd_rsi_revoke(args: list[str]):
    """rsi-revoke <name> [reason] — Revoke an ACTIVATED predicate.

    Audit finding: approval exists but no revocation path. Revocation =
    queue entry (any status) -> rejected + pred_dir file (if any) moved
    to quarantine (never deleted). Running engines keep it until restart;
    fresh loads refuse it. Human-governed, audited.
    """
    if not args:
        print(json.dumps({"error": "usage: rsi-revoke <name> [reason]"}))
        return
    import shutil
    name, reason = args[0], " ".join(args[1:]) or "revoked by human"
    out = {"name": name, "queue": None, "pred_dir": None}
    try:
        from vsf_rsi.rsi_socratic_bridge import reject_predicate
        out["queue"] = reject_predicate(name, reason)
    except Exception as e:
        out["queue"] = f"error: {e}"
    try:
        pred = Path(RSI_PREDICATES_DIR) / f"{name}.json"
        if pred.is_file():
            qdir = Path(VOS_ROOT) / "state" / "quarantine"
            qdir.mkdir(parents=True, exist_ok=True)
            dest = qdir / f"{name}.revoked.json"
            shutil.move(str(pred), str(dest))
            out["pred_dir"] = f"quarantined -> {dest.name}"
        else:
            out["pred_dir"] = "no pred_dir file"
    except Exception as e:
        out["pred_dir"] = f"error: {e}"
    log_integration({
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": "governance",
        "tool": "rsi-revoke",
        "file": name,
        "outcome": "success",
        "level": "decision",
    })
    _chain_verdict("revoke", name, False, {"reason": reason[:120]})
    print(json.dumps(out, default=str))


def _verdict_chain_path() -> str:
    return os.path.join(VOS_ROOT, "logs", "verdict_chain.jsonl")


def _chain_verdict(kind: str, name: str, verdict: bool, evidence: dict) -> dict:
    """Hash-chained governance verdicts (C3 PKI interim).

    Each verdict embeds sha256 of the previous line: tampering anywhere
    breaks every later link (detectable by verify below). No ceremony,
    no keys — auditability without PKI weight. Human verdicts only.
    """
    import hashlib as _hl
    chain = _verdict_chain_path()
    prev = "GENESIS"
    try:
        with open(chain, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    prev = _hl.sha256(line.encode()).hexdigest()[:16]
    except OSError:
        pass
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
             "name": name, "verdict": bool(verdict), "evidence": evidence,
             "prev": prev}
    entry["link"] = _hl.sha256(
        json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]
    try:
        with open(chain, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return entry


def cmd_rsi_verify_chain(args: list[str]):
    """rsi-verify-chain — Verify hash-chain integrity of governance verdicts."""
    import hashlib as _hl
    chain = _verdict_chain_path()
    n = 0
    prev = "GENESIS"
    try:
        with open(chain, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if e.get("prev") != prev:
                    print(json.dumps({"ok": False, "break_at": n,
                                      "expected_prev": prev}))
                    return
                prev = _hl.sha256(line.encode()).hexdigest()[:16]
                n += 1
    except OSError:
        print(json.dumps({"ok": True, "entries": 0, "note": "no chain yet"}))
        return
    print(json.dumps({"ok": True, "entries": n}))


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



# ─── RBAC (SEC-001-2 thin slice) ──────────────────────────────────────────
# Role table for bridge commands. observer < operator < governor.
# Governor-only = L4 human governance (approve/reject/revoke, threshold
# tuning, caution clear). Observer = pure reads. Default = operator.
#
# IDENTITY HONESTY: the role travels in VOS_ROLE env. Unset keeps the
# loop working (operator back-compat); a BOGUS value fails closed to
# observer. True identity (who may claim governor) arrives with full
# PKI (deferred); until then governor = S5 in shell (VOS_ROLE=governor).
# The enforcement point + deny-audit are real today, not theater:
# every denial is a rbac_deny security event in the unified log.
#
# S5 override (shell only — tools never write policy): access_policy.json
# may carry {"rbac": {"commands": {cmd: role}}}; unknown roles in policy
# are ignored (fail-safe to the table below).
_RBAC_RANK = {"observer": 0, "operator": 1, "governor": 2}

_RBAC_GOVERNOR_ONLY = {
    "rsi-approve", "rsi-reject", "rsi-revoke",
    "rsi-threshold-set", "rsi-caution-clear",
}

_RBAC_OBSERVER = {
    "session-report", "query-context", "log-distill",
    "state-drift", "state-verify",
    "socratic-canon",
    "graph-query", "task-graph",
    "rsi-queue", "rsi-queue-digest", "caution-signal", "distill-expire", "pleasure-collapse-check", "rsi-diff", "rsi-faults", "rsi-thresholds",
    "rsi-caution", "rsi-verify-chain",
}


def _rbac_role() -> str:
    """Resolve caller role: env, else operator (loop compat), else observer."""
    role = (os.environ.get("VOS_ROLE") or "").strip()
    if not role:
        return "operator"
    return role if role in _RBAC_RANK else "observer"


def _rbac_min_role(command: str) -> str:
    """Minimum role for a command: table, then S5 policy override."""
    if command in _RBAC_GOVERNOR_ONLY:
        need = "governor"
    elif command in _RBAC_OBSERVER:
        need = "observer"
    else:
        need = "operator"
    try:
        sys.path.insert(0, os.path.join(VOS_ROOT, "system", "kernel"))
        try:
            from access_policy import load
        except ImportError:
            from system.kernel.access_policy import load
        override = (load().get("rbac") or {}).get("commands", {})
        if command in override and override[command] in _RBAC_RANK:
            # Policy may only tighten or restate, never invent roles.
            need = override[command]
    except Exception:
        pass
    return need


def cmd_log_distill(args: list[str]) -> str:
    """O-6 trajectory distill (R-3, propose-only) — §6.2.

    Runs scripts/state/monitoring/log_distill.py --json and returns its
    report verbatim. PROPOSE-ONLY: candidates land in
    state/distill/candidates.jsonl; applying any of them requires S5
    ratification (K5 — no skills/ or predicate write path exists).
    Extra args pass through (--dry-run etc.); rc!=0 → error JSON.
    """
    import subprocess as _sp
    script = os.path.join(VOS_ROOT, "scripts", "state", "monitoring",
                          "log_distill.py")
    try:
        proc = _sp.run(
            [sys.executable, script, "--json", *args],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "VOSLAB_PATH": VOS_ROOT})
        if proc.returncode != 0:
            return json.dumps({"error": f"distill rc={proc.returncode}",
                               "stderr": (proc.stderr or "")[-400:]})
        return proc.stdout
    except Exception as exc:  # noqa: BLE001 — bridge must not crash
        return json.dumps({"error": f"distill failed: {exc}"})


_GRAPH_QUERY_SUBS = {"stats", "show", "export"}

_TASK_GRAPH_SUBS = {"roots", "stats", "show", "unblocks", "blocked-by",
                    "path", "open", "dot"}


def cmd_graph_query(args: list[str]) -> str:
    """P1 instrument wiring (W1): read-only passthrough to epistemic_graph CLI.

    graph-query <sub> [opts] — sub ∈ {stats, show, export}. Runs
    `python3 -m epistemic_graph <sub> ...` with packages/framework on
    PYTHONPATH and returns stdout verbatim. Subcommand whitelist prevents
    module-execution abuse. rc!=0 or timeout → error JSON. READ-ONLY:
    never writes state (export --out writes only under /tmp unless the
    caller passes an explicit repo path — callers must not).
    """
    import subprocess as _sp
    if not args or args[0] not in _GRAPH_QUERY_SUBS:
        return json.dumps({"error": "usage: graph-query <stats|show|export> [opts]"})
    env = {**os.environ,
           "PYTHONPATH": os.path.join(VOS_ROOT, "packages", "framework") +
           (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
           "VOSLAB_PATH": VOS_ROOT}
    try:
        proc = _sp.run(
            [sys.executable, "-m", "epistemic_graph", *args],
            capture_output=True, text=True, timeout=60,
            cwd=VOS_ROOT, env=env)
        if proc.returncode != 0:
            return json.dumps({"error": f"graph-query rc={proc.returncode}",
                               "stderr": (proc.stderr or "")[-400:]})
        return proc.stdout or "(empty)"
    except Exception as exc:  # noqa: BLE001 — bridge must not crash
        return json.dumps({"error": f"graph-query failed: {exc}"})


def cmd_task_graph(args: list[str]) -> str:
    """P1 instrument wiring (W2): read-only queries over vsf_graph.py DAG.

    task-graph <roots|stats|show|unblocks|blocked-by|path|open|dot> [args].
    Lazy rebuild: vsf_deps.db is rebuilt when missing or older than
    TASKS.vsm (mtime gate — answers never come from a stale db without
    warning; build output notes the rebuild). Returns stdout verbatim.
    READ-ONLY apart from the db rebuild itself.
    """
    import subprocess as _sp
    if not args or args[0] not in _TASK_GRAPH_SUBS:
        return json.dumps({"error": "usage: task-graph <roots|stats|show|unblocks|blocked-by|path|open|dot> [args]"})
    script = os.path.join(VOS_ROOT, "scripts", "analysis", "vsf_graph.py")
    db = os.path.join(VOS_ROOT, "scripts", "vsf_deps.db")
    tasks = os.path.join(VOS_ROOT, "TASKS.vsm")
    env = {**os.environ, "VOSLAB_PATH": VOS_ROOT}
    try:
        # mtime gate: rebuild when db is missing or older than the source
        rebuild_note = ""
        try:
            stale = (not os.path.exists(db) or
                     (os.path.exists(tasks) and
                      os.path.getmtime(tasks) > os.path.getmtime(db)))
        except OSError:
            stale = True
        if stale:
            rb = _sp.run([sys.executable, script, "build"],
                         capture_output=True, text=True, timeout=90,
                         cwd=VOS_ROOT, env=env)
            rebuild_note = f"[db rebuilt: {(rb.stdout or '').strip()[:120]}]\n" if rb.returncode == 0 \
                else f"[db rebuild FAILED rc={rb.returncode}, answers may be stale]\n"
        proc = _sp.run(
            [sys.executable, script, *args],
            capture_output=True, text=True, timeout=60,
            cwd=VOS_ROOT, env=env)
        if proc.returncode != 0:
            return json.dumps({"error": f"task-graph rc={proc.returncode}",
                               "stderr": (proc.stderr or "")[-400:]})
        return rebuild_note + (proc.stdout or "(empty)")
    except Exception as exc:  # noqa: BLE001 — bridge must not crash
        return json.dumps({"error": f"task-graph failed: {exc}"})


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
        "session-report": lambda: json.dumps(session_report_payload()),
        "query-context": lambda: json.dumps(get_system_context(), indent=2),
        # Migrated from the shadowed COMMANDS table (main()#1 dead): these
        # two silently vanished from the active dispatcher (S2 repair).
        "evaluate-query": lambda: cmd_evaluate_query(args),
        "run-gates": lambda: cmd_run_gates(args),
        
        # State-canon commands
        "state-journal": lambda: cmd_state_journal(args),
        "state-focus": lambda: cmd_state_focus(args),
        "state-drift": lambda: cmd_state_drift(args),
        "state-verify": lambda: cmd_state_verify(args),
        "state-reconcile": lambda: cmd_state_reconcile(),
        
        # Socratic-engine commands
        "socratic-tree": lambda: cmd_socratic_tree(args),
        "socratic-tree-file": lambda: cmd_socratic_tree_file(args),
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
        "rsi-queue-digest": lambda: cmd_rsi_queue_digest(args),
        "caution-signal": lambda: cmd_caution_signal(args),
        "distill-expire": lambda: cmd_distill_expire(args),
        "pleasure-collapse-check": lambda: cmd_pleasure_collapse_check(args),
        "rsi-approve": lambda: cmd_rsi_approve(args),
        "rsi-reject": lambda: cmd_rsi_reject(args),
        "rsi-revoke": lambda: cmd_rsi_revoke(args),
        "rsi-diff": lambda: cmd_rsi_diff(args),
        "rsi-faults": lambda: cmd_rsi_faults(args),
        "rsi-thresholds": lambda: cmd_rsi_thresholds(args),
        "rsi-threshold-set": lambda: cmd_rsi_threshold_set(args),
        "rsi-caution": lambda: cmd_rsi_caution(args),
        "rsi-caution-clear": lambda: cmd_rsi_caution_clear(args),
        "rsi-verify-chain": lambda: cmd_rsi_verify_chain(args),
        
        # NEW: Automation tools (previously manual)
        "audit-proposal": lambda: cmd_audit_proposal(args),
        "deep-audit": lambda: cmd_deep_audit(args),
        "add-binding": lambda: cmd_add_binding(args),
        "route-component": lambda: cmd_route_component(args),
        # Risk assessment
        "risk-assess": lambda: cmd_risk_assess(args),
        # RSI dynamic evaluation
        "rsi-evaluate": lambda: cmd_rsi_evaluate(args),
        # Tier2 multiplex (RAM-LIFECYCLE, alternativa 2): whole
        # before/after phase in one interpreter. Usage:
        #   pipeline-before <context_json> [content_json_or_raw]
        #   pipeline-after <tool> <file> <outcome> <context_json> [flags_json]
        "pipeline-before": lambda: json.dumps(pipeline_before(
            json.loads(args[0]) if args else {},
            (json.loads(args[1]).get("content", "") if len(args) > 1 and args[1].lstrip().startswith("{") else (args[1] if len(args) > 1 else "")))),
        "pipeline-after": lambda: json.dumps(pipeline_after(
            args[0] if len(args) > 0 else "",
            args[1] if len(args) > 1 else "",
            args[2] if len(args) > 2 else "",
            json.loads(args[3]) if len(args) > 3 else {},
            json.loads(args[4]) if len(args) > 4 else {})),
        # Second-order learning
        "learn-pipeline": lambda: json.dumps(run_learn_pipeline()),
        # Algedonic consumption (1c, S5 2026-10-05): surface + ack>24h
        "alert-consume": lambda: json.dumps(_alert_consume_stage()),
        # Algedonic emission (1d, §6.3 F4.2): abstention-collapse alarm
        "abstention-check": lambda: json.dumps(_abstention_check_stage()),
        # O-6 distill (R-3, §6.2): propose-only trajectory→learning
        "log-distill": lambda: cmd_log_distill(args),
        # P1 instrument wiring (W1/W2, read-only graph queries)
        "graph-query": lambda: cmd_graph_query(args),
        "task-graph": lambda: cmd_task_graph(args),
    }

    if command in handlers:
        role = _rbac_role()
        need = _rbac_min_role(command)
        if _RBAC_RANK[role] < _RBAC_RANK[need]:
            # Deny + audit (SEC-001-4 slice): the denial itself is a
            # security event in the unified log (viewable, greppable).
            log_integration({
                "ts": datetime.now(timezone.utc).isoformat(),
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "phase": "rbac_deny",
                "tool": command,
                "file": "",
                "outcome": "blocked",
                "socratic_certified": False,
                "socratic_truth": "",
                "socratic_source": "rbac",
                "socratic_evidence": {"role": role, "required": need},
            })
            print(json.dumps(
                {"error": f"RBAC denied: {command} needs {need} (role={role})"}))
        else:
            # Audit trail (SEC-001-4 slice): every privileged execution
            # (governor command, any role that clears it) lands in the
            # unified log with who-claimed-what. Rare by construction.
            if need == "governor":
                log_integration({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "phase": "rbac_exec",
                    "tool": command,
                    "file": " ".join(args[:2]),
                    "outcome": "executed",
                    "socratic_certified": False,
                    "socratic_truth": "",
                    "socratic_source": "rbac",
                    "socratic_evidence": {"role": role, "required": need},
                })
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
    """Run the canonical VSL validator on a file.

    Reimplemented on scripts/vsl/validator/check.py (validate_vsm_file):
    the old audit_proposal module no longer exists, so this leg degraded
    silently. Same command name (callers are fire-and-forget); returns
    {filepath, valid, errors}. Never raises.
    """
    if not args:
        return json.dumps({"error": "Usage: audit-proposal <file.vsm>"})
    filepath = args[0]
    try:
        import importlib.util
        kpath = os.path.join(VOS_ROOT, "scripts", "vsl", "validator",
                             "check.py")
        spec = importlib.util.spec_from_file_location("vsm_check_live",
                                                      kpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        res = mod.validate_vsm_file(filepath)
        return json.dumps({
            "filepath": filepath,
            "valid": bool(res.get("valid", False)),
            "errors": res.get("errors", []),
        }, indent=2)
    except Exception as e:
        return json.dumps({"filepath": filepath, "valid": None,
                           "error": f"validator degraded: {e}"[:200]})


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


if __name__ == "__main__":
    
    main()
    
