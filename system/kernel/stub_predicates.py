"""stub_predicates.py — Predicates for the RSI cycle.

Mix of REAL deterministic predicates (security, redundancy, scripts) and
STUBS (always TRUE) pending real implementations. T1.2 migrated the
blocking-path predicates to real logic; the remaining stubs are advisory.

R10: All predicates must be deterministic (no random, no LLM inference).

Fail-open rule: a predicate in the blocking pre-check tree returns FALSE
only on concrete evidence. Informative predicates always return TRUE and
carry the signal in `evidence` (never block on missing data).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Security lists (single source; rsi_cycle imports them from here) ───────
FORBIDDEN_COMMANDS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf .",
    "sudo rm", "chmod 777", ":(){ :|:& };:",
    "mkfs", "dd if=/dev/zero",
]

FORBIDDEN_PATHS = [
    "/etc/shadow", "/etc/passwd", "/root/.ssh", "/proc/kcore",
    "/dev/sda", "/dev/nvme",
]

_ERROR_OUTCOMES = {"error", "failure", "blocked", "fail"}


def _result(truth: bool, source: str, evidence: dict):
    from socratic_engine import PredicateResult, Truth
    return PredicateResult(
        truth=Truth.TRUE if truth else Truth.FALSE,
        certified=True, evidence=evidence, source=source,
    )


# ─── REAL predicates (T1.2) ─────────────────────────────────────────────────

def not_redundant(tool: str = "", file: str = "", command: str = "",
                  *args, **kw):
    """REAL: FALSE only on a likely retry-loop.

    Blocks when the exact (tool, file, command) already ran >=3 times in
    the recent window, or >=2 times with an error outcome. One legitimate
    retry always passes. Entries lacking `command` only match empty command
    (conservative: never punish what we cannot see).
    """
    recent = kw.get("recent_actions", []) or []
    key = (tool or "", file or "", command or "")
    hits = [
        e for e in recent
        if isinstance(e, dict) and (
            str(e.get("tool", "")), str(e.get("file", "")),
            str(e.get("command", ""))) == key
    ]
    bad = [e for e in hits
           if str(e.get("outcome", "")).lower() in _ERROR_OUTCOMES]
    if len(hits) >= 3 or (len(hits) >= 2 and bad):
        return _result(False, "not_redundant", {
            "redundant": True, "repeats": len(hits),
            "error_repeats": len(bad), "key": list(key),
        })
    return _result(True, "not_redundant", {"repeats": len(hits)})


def pattern_known(*args, **kw):
    """REAL (informative, never blocks): is this fault signature on record?

    Signal travels in evidence ({known, matches}); truth stays TRUE so a
    cold scenario_memory can never pipeline-block legitimate work.
    """
    sig = kw.get("fault_signature", "") or (args[0] if args else "")
    if not sig:
        return _result(True, "pattern_known",
                       {"known": False, "reason": "no signature"})
    try:
        from vsf_rsi.scenario_memory import match
        hits = match(str(sig), threshold=0.0) or []
    except Exception:
        hits = []
    return _result(True, "pattern_known",
                   {"known": bool(hits), "matches": len(hits),
                    "signature": str(sig)[:80]})


def script_safe(command: str = "", *args, **kw):
    """REAL: FALSE on forbidden command patterns (mirrors action_forbidden)."""
    cmd = command or ""
    for f in FORBIDDEN_COMMANDS:
        if f in cmd:
            return _result(False, "script_safe",
                           {"forbidden": f, "command": cmd[:100]})
    return _result(True, "script_safe", {"command": cmd[:100]})


def script_domain_ok(script: str = "", file: str = "", *args, **kw):
    """REAL: FALSE when the target sits on a forbidden path."""
    target = script or file
    if not target:
        return _result(True, "script_domain_ok", {"reason": "no target"})
    for fp in FORBIDDEN_PATHS:
        if target.startswith(fp):
            return _result(False, "script_domain_ok",
                           {"forbidden_path": fp, "target": target})
    return _result(True, "script_domain_ok", {"target": target})


def script_call(script: str = "", *args, **kw):
    """REAL: the referenced script must exist (fail-closed, with evidence)."""
    if not script:
        return _result(True, "script_call", {"reason": "no script"})
    exists = Path(script).is_file()
    return _result(exists, "script_call",
                   {"script": script, "exists": exists})


def _make_stub(name: str, **extra_evidence):
    """Create a stub predicate that always returns TRUE.

    Accepts both positional and keyword arguments for compatibility
    with socratic_engine's calling convention:
        predicate(*resolved_args, **resolved_kwargs)
    """
    def stub_predicate(*args, **kw):
        from socratic_engine import PredicateResult, Truth
        evidence = {"reason": f"{name} stub", **extra_evidence}
        if args:
            evidence["args"] = list(args)
        evidence.update({k: v for k, v in kw.items() if v})
        return PredicateResult(
            truth=Truth.TRUE, certified=True,
            evidence=evidence, source=name
        )
    return stub_predicate


# State predicates
state_consistent = _make_stub("state_consistent")
state_scripts_ok = _make_stub("state_scripts_ok")
vsl_scripts_ok = _make_stub("vsl_scripts_ok")
audit_scripts_ok = _make_stub("audit_scripts_ok")
s1_kernel_scripts_ok = _make_stub("s1_kernel_scripts_ok")
scripts_manifest = _make_stub("scripts_manifest")

# Learning predicates — REAL since T1.2 (defined above)
# (not_redundant, pattern_known, script_safe, script_domain_ok, script_call)

# Task predicates
task_active = _make_stub("task_active")

# System predicates
event_router_ok = _make_stub("event_router_ok")
lifecycle_valid = _make_stub("lifecycle_valid")
gap_free = _make_stub("gap_free")
onboard_complete = _make_stub("onboard_complete")
hook_metrics_ok = _make_stub("hook_metrics_ok")
semantic_mapper_ok = _make_stub("semantic_mapper_ok")
process_staging_ok = _make_stub("process_staging_ok")
load_hooks_ok = _make_stub("load_hooks_ok")

# Naming predicates
naming_conforms = _make_stub("naming_conforms")
vsm_has_header = _make_stub("vsm_has_header")
