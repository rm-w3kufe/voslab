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

# ─── Security lists (S5 policy file; rsi_cycle imports them from here) ──────
# FORBIDDEN_PATHS is resolved per call from access_policy (hot-reload).
# FORBIDDEN_COMMANDS stays static: command patterns are engine constants.
FORBIDDEN_COMMANDS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf .",
    "sudo rm", "chmod 777", ":(){ :|:& };:",
    "mkfs", "dd if=/dev/zero",
    # Child lineage additions (2026-09-10 audit): pipe-to-privilege,
    # etc-redirection, and shell eval are distinct bypass families.
    "| sudo", "> /etc/", "eval(",
]


def _denylist() -> list:
    try:
        from access_policy import load
        return list(load()["read_denylist"])
    except ImportError:  # pragma: no cover - layout fallback
        from system.kernel.access_policy import load
        return list(load()["read_denylist"])


FORBIDDEN_PATHS = [
    "/etc/shadow",
    "/etc/passwd",
    "/root/.ssh",
    "/proc/kcore",
    "/dev/sda",
    "/dev/nvme",
]

_ERROR_OUTCOMES = {"error", "failure", "blocked", "fail"}
_WRITE_TOOLS = {"write", "edit"}

_VSM_HEADER_RE = None


def _vsm_header_re():
    global _VSM_HEADER_RE
    if _VSM_HEADER_RE is None:
        import re
        _VSM_HEADER_RE = re.compile(
            r"⟦\s*\w+\s*\|\s*\w[\w.-]*\s*\|\s*vsm-[\d.]+\s*\|"
            r"\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\s*⟧"
        )
    return _VSM_HEADER_RE


def _find_workspace(start: str = ""):
    """Walk up looking for current_focus.json (never hardcode usernames)."""
    import os
    p = Path(start or os.getcwd()).resolve()
    for _ in range(7):
        if (p / "current_focus.json").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


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
    th = _thresholds()
    if len(hits) >= th["repeat_block"] or \
            (len(hits) >= th["repeat_error_block"] and bad):
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


def _normalize_path(p: str) -> str:
    """Lexical+symlink normalization for security comparison.

    realpath collapses `..`/`.` and resolves symlinks of existing
    components; for missing paths it still normalizes lexically.
    Comparison is separator-aware (no `/root/.ssh-backup` false hits).
    """
    import os
    return os.path.realpath(os.path.abspath(os.path.expanduser(p)))


def _thresholds() -> dict:
    """Live operating thresholds (policy defaults + RSI-governed store)."""
    try:
        from access_policy import operating_thresholds
        live = operating_thresholds()
        return {k: live[k] for k in
                ("repeat_block", "repeat_error_block", "read_warn_bytes")}
    except ImportError:  # pragma: no cover - layout fallback
        from system.kernel.access_policy import operating_thresholds
        live = operating_thresholds()
        return {k: live[k] for k in
                ("repeat_block", "repeat_error_block", "read_warn_bytes")}


def _hits_forbidden(target: str):
    """Return the forbidden prefix hit by target, or None (adversarial-safe).

    Reads the LIVE S5 policy on every call (hot-reload); the static
    FORBIDDEN_PATHS below is only a compat snapshot + fail-closed seed.
    """
    norm = _normalize_path(target)
    for fp in _denylist():
        if norm == fp or norm.startswith(fp + "/"):
            return fp
    return None


def policy_locked(tool: str = "", file: str = "", *args, **kw):
    """REAL: the S5 policy file is CLI-ONLY (S5 decision 2026-09-10).

    No agent tool path may write it — this is what makes S5 authority
    unforgeable from inside the loop: injected text can never become a
    policy write because the path does not exist. Reads stay allowed
    (transparency). S5 edits it in shell; sessions hot-reload on mtime.
    """
    if not file or tool not in _WRITE_TOOLS:
        return _result(True, "policy_locked",
                       {"reason": "no target or non-write tool"})
    try:
        from access_policy import policy_path
    except ImportError:  # pragma: no cover - layout fallback
        from system.kernel.access_policy import policy_path
    locked = _normalize_path(str(policy_path()))
    if _normalize_path(file) == locked:
        return _result(False, "policy_locked",
                       {"policy_file": locked,
                        "reason": "CLI-only: edit in shell, never via tools"})
    return _result(True, "policy_locked", {"file": file})


def write_scope_ok(tool: str = "", file: str = "", *args, **kw):
    """REAL: writes land inside workspace roots only (closed-lab rule).

    Mechanizes the covenant pact (no writing outside ~/vOSlab/ + scratch).
    bash/task skip (too expressive; risk assessor covers them).
    """
    if tool not in _WRITE_TOOLS or not file:
        return _result(True, "write_scope_ok",
                       {"reason": "not a scoped write"})
    try:
        from access_policy import allowed_roots
    except ImportError:  # pragma: no cover - layout fallback
        from system.kernel.access_policy import allowed_roots
    norm = _normalize_path(file)
    for root in allowed_roots():
        if norm == root or norm.startswith(root + "/"):
            return _result(True, "write_scope_ok",
                           {"file": file, "root": root})
    return _result(False, "write_scope_ok",
                   {"file": file, "resolved": norm,
                    "reason": "outside workspace roots"})


def script_domain_ok(script: str = "", file: str = "", *args, **kw):
    """REAL: FALSE when the target sits on a forbidden path."""
    target = script or file
    if not target:
        return _result(True, "script_domain_ok", {"reason": "no target"})
    hit = _hits_forbidden(target)
    if hit:
        return _result(False, "script_domain_ok",
                       {"forbidden_path": hit, "target": target,
                        "resolved": _normalize_path(target)})
    return _result(True, "script_domain_ok",
                   {"target": target, "resolved": _normalize_path(target)})


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


# State predicates (state_consistent + scripts_manifest are REAL, T1.2)
state_scripts_ok = _make_stub("state_scripts_ok")
vsl_scripts_ok = _make_stub("vsl_scripts_ok")
audit_scripts_ok = _make_stub("audit_scripts_ok")
s1_kernel_scripts_ok = _make_stub("s1_kernel_scripts_ok")

# Learning predicates — REAL since T1.2 (defined above)
# (not_redundant, pattern_known, script_safe, script_domain_ok, script_call)

# ─── REAL predicates (T1.2 second wave — state/tasks/naming) ─────────────────

def state_consistent(*args, **kw):
    """REAL: workspace state files parse (focus JSON + log tail JSONL).

    In the blocking pre-check tree: FALSE ONLY on concrete corruption
    (unparseable focus file, unreadable log dir). Missing files = TRUE
    (fresh workspace, nothing to contradict).
    """
    root = _find_workspace()
    if root is None:
        return _result(True, "state_consistent",
                       {"reason": "workspace not found (fail-open)"})
    focus = root / "current_focus.json"
    if focus.exists():
        try:
            import json
            data = json.loads(focus.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return _result(False, "state_consistent",
                               {"corrupt": "focus not a list"})
        except Exception as e:
            return _result(False, "state_consistent",
                           {"corrupt": f"focus unparseable: {e}"[:120]})
    log = root / "logs" / "agent_plugin.jsonl"
    if log.exists():
        try:
            import json
            tail = log.read_text(encoding="utf-8").splitlines()[-5:]
            for line in tail:
                if line.strip():
                    json.loads(line)
        except Exception as e:
            return _result(False, "state_consistent",
                           {"corrupt": f"log tail unparseable: {e}"[:120]})
    return _result(True, "state_consistent", {"checked": ["focus", "log"]})


def task_active(task_ref: str = "", *args, **kw):
    """REAL: TRUE iff there is active work (or the given ref is active)."""
    root = _find_workspace()
    if root is None:
        return _result(True, "task_active",
                       {"reason": "workspace not found (fail-open)"})
    try:
        import json
        data = json.loads((root / "current_focus.json").read_text(
            encoding="utf-8"))
    except Exception:
        return _result(True, "task_active",
                       {"reason": "no readable focus (fail-open)"})
    active = [t for t in data if isinstance(t, dict)
              and t.get("status") == "active"]
    if task_ref:
        hit = any(t.get("ref") == task_ref for t in active)
        return _result(hit, "task_active",
                       {"ref": task_ref, "active": hit,
                        "active_count": len(active)})
    return _result(bool(active), "task_active",
                   {"active_count": len(active)})


def vsm_has_header(file: str = "", *args, **kw):
    """REAL: the file carries a valid VSM header signature."""
    if not file:
        return _result(True, "vsm_has_header", {"reason": "no file"})
    p = Path(file)
    if not p.is_file():
        return _result(False, "vsm_has_header",
                       {"file": file, "reason": "not found"})
    try:
        head = p.read_text(encoding="utf-8")[:2000]
    except Exception as e:
        return _result(False, "vsm_has_header",
                       {"file": file, "reason": f"unreadable: {e}"[:100]})
    found = bool(_vsm_header_re().search(head))
    return _result(found, "vsm_has_header",
                   {"file": file, "has_header": found})


def naming_conforms(file: str = "", *args, **kw):
    """REAL (minimal documented rules): docs/ hosts .vsm[.md] only.

    Rules v1: a bare `.md` (not `.vsm.md`) under `docs/` violates the VSM
    format policy. Everything else passes with the applied rule in evidence.
    """
    if not file:
        return _result(True, "naming_conforms", {"reason": "no file"})
    norm = "/" + file.replace("\\", "/").lstrip("/")
    if "/docs/" in norm and norm.endswith(".md") \
            and not norm.endswith(".vsm.md"):
        return _result(False, "naming_conforms",
                       {"file": file, "rule": "docs-require-vsm"})
    return _result(True, "naming_conforms",
                   {"file": file, "rule": "default-pass"})


READ_WARN_BYTES = 512 * 1024  # fallback default; policy wins


def read_size_ok(file: str = "", *args, **kw):
    """REAL (advisory, never blocks): flag giant reads before they burn context.

    Always TRUE; oversize travels in evidence so the log shows the warn.
    Threshold comes from S5 policy (hot-reload).
    """
    if not file:
        return _result(True, "read_size_ok", {"reason": "no file"})
    try:
        size = Path(file).stat().st_size
    except OSError:
        return _result(True, "read_size_ok",
                       {"file": file, "reason": "stat failed (fail-open)"})
    limit = _thresholds()["read_warn_bytes"]
    if size > limit:
        return _result(True, "read_size_ok",
                       {"file": file, "size": size,
                        "warn": f"oversize read ({size} bytes)"})
    return _result(True, "read_size_ok", {"file": file, "size": size})


def scripts_manifest(*args, **kw):
    """REAL: the scripts-manifest subsystem exists and is reachable.

    Honest signal: the updater referenced by the manifest plugin is
    currently missing → FALSE with evidence (tracked debt, not a block:
    nothing evaluates this predicate in the pre-check tree today).
    """
    root = _find_workspace()
    updater = root / "scripts" / "shared" / "update_scripts_manifest.py" \
        if root else None
    ok = bool(updater and updater.is_file())
    return _result(ok, "scripts_manifest",
                   {"updater": str(updater) if updater else None,
                    "exists": ok})

# Task predicates (task_active is REAL, T1.2)

# System predicates
event_router_ok = _make_stub("event_router_ok")
lifecycle_valid = _make_stub("lifecycle_valid")
gap_free = _make_stub("gap_free")
onboard_complete = _make_stub("onboard_complete")
hook_metrics_ok = _make_stub("hook_metrics_ok")
semantic_mapper_ok = _make_stub("semantic_mapper_ok")
process_staging_ok = _make_stub("process_staging_ok")
load_hooks_ok = _make_stub("load_hooks_ok")

# Naming predicates (REAL since T1.2 second wave)
