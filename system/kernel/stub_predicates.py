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

    LAYER CONTRACT (R3, 2026-10-12): this is L1 — exact-key redundancy
    (same tool+file+command). The coarse backstop lives in
    tool-integration.ts before-hook (same-tool bursts with varied args +
    error storms, in-process, no IO). First throw wins per call.
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

    Mechanizes the covenant pact (no writing outside workspace root + scratch).
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

def _ws_file(*parts) -> tuple:
    """Workspace-relative existence check. Returns (root, path, exists)."""
    from pathlib import Path as _P
    root = _find_workspace()
    if root is None:
        return None, _P("/nonexistent"), False
    p = root.joinpath(*parts)
    return root, p, p.is_file()


def state_scripts_ok(*args, **kw):
    """REAL: session scan + plugin log present and scan executable."""
    root = _find_workspace()
    if root is None:
        return _result(False, "state_scripts_ok",
                       {"reason": "workspace not found"})
    scan = root / "scripts" / "state" / "core" / "session_learning_scan.sh"
    logger = root / "scripts" / "state" / "agent-plugin-log"
    import os as _os
    ok = scan.is_file() and _os.access(scan, _os.X_OK) and logger.is_file()
    return _result(ok, "state_scripts_ok",
                   {"scan": str(scan), "logger": str(logger), "exists": ok})


def vsl_scripts_ok(*args, **kw):
    """REAL: VSL toolchain files present (validator + parser + classifier)."""
    root = _find_workspace()
    if root is None:
        return _result(False, "vsl_scripts_ok",
                       {"reason": "workspace not found"})
    need = ["scripts/vsl/validator/check.py",
            "scripts/vsl/parser/vsl_parser.py"]
    missing = [n for n in need if not (root / n).is_file()]
    clf = root / "scripts" / "vsl" / "classifier"
    clf_py = len(list(clf.glob("*.py"))) if clf.is_dir() else 0
    ok = not missing and clf_py > 0
    return _result(ok, "vsl_scripts_ok",
                   {"missing": missing, "classifier_py": clf_py})


def audit_scripts_ok(*args, **kw):
    """REAL (honest FALSE): audit legs missing — tracked debt, not a block.

    audit_proposal.py / verify_refs.py / post_register.py do not exist
    (bridge after-legs degrade silently). Nothing evaluates this in the
    pre-check tree today; parse_query reports it truthfully.
    """
    root = _find_workspace()
    if root is None:
        return _result(False, "audit_scripts_ok",
                       {"reason": "workspace not found"})
    need = ["scripts/vsl/audit_proposal.py",
            "scripts/vsl/verify_refs.py",
            "scripts/vsl/post_register.py"]
    missing = [n for n in need if not (root / n).is_file()]
    return _result(not missing, "audit_scripts_ok",
                   {"missing": missing,
                    "debt": "bridge audit legs degrade silently" if missing else None})


def s1_kernel_scripts_ok(*args, **kw):
    """REAL: S1 kernel surface present (cycle + predicates + engine pkg)."""
    root = _find_workspace()
    if root is None:
        return _result(False, "s1_kernel_scripts_ok",
                       {"reason": "workspace not found"})
    files_ok = all((root / n).is_file() for n in
                   ["system/kernel/rsi_cycle.py",
                    "system/kernel/stub_predicates.py"])
    try:
        import socratic_engine as _se  # noqa: F401
        pkg_ok = True
    except ImportError:
        pkg_ok = False
    return _result(files_ok and pkg_ok, "s1_kernel_scripts_ok",
                   {"files": files_ok, "engine_pkg": pkg_ok})

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


def prior_failure(tool: str = "", file: str = "", command: str = "",
                  *args, **kw):
    """REAL: TRUE if the same action failed recently (memory routing).

    Reads recent_actions from kwargs or injected _context. Powers the
    memory_classify nesting pattern: history routes the decision.
    """
    recent = kw.get("recent_actions", []) or []
    ctx = kw.get("_context", {}) or {}
    if not recent and isinstance(ctx, dict):
        recent = ctx.get("recent_actions", []) or []
    key = (tool or "", file or "", command or "")
    for e in recent:
        if not isinstance(e, dict):
            continue
        if ((str(e.get("tool", "")), str(e.get("file", "")),
             str(e.get("command", ""))) == key
                and str(e.get("outcome", "")).lower() in _ERROR_OUTCOMES):
            return _result(True, "prior_failure",
                           {"key": list(key), "outcome": e.get("outcome")})
    return _result(False, "prior_failure", {"key": list(key)})


def scripts_manifest(*args, **kw):
    """REAL: the scripts-manifest subsystem exists and is reachable.

    2026-10-02: the updater shipped with the vsf→vOSlab scripts corpus
    migration (scripts/shared/update_scripts_manifest.py) — TRUE when the
    subsystem is present, FALSE with the path as evidence otherwise.
    """
    root = _find_workspace()
    updater = root / "scripts" / "shared" / "update_scripts_manifest.py" \
        if root else None
    ok = bool(updater and updater.is_file())
    return _result(ok, "scripts_manifest",
                   {"updater": str(updater) if updater else None,
                    "exists": ok})


# ─── Migrated vsf scripts corpus (S5 order 2026-10-02) ──────────────────────
# "todos los scripts tienen que integrarse al pipeline socratic engine RSI;
#  nada corre desde ~/vsf." Families = every top-level dir of the migrated
#  ~/vsf/scripts/ tree; _beacon_ca rides along (gen_test_ca relative paths).

_MIGRATED_SCRIPT_FAMILIES = (
    "algedonic", "analysis", "audit", "deploy", "exp", "legacy",
    "llm", "plan", "s1-kernel", "s3-allocation", "s4-orchestration",
    "s5-governance", "shared", "state", "tests", "vsl",
)


def scripts_migrated_ok(*args, **kw):
    """REAL: full vsf→vOSlab scripts corpus present (families + beacon CA).

    Fail-open on missing workspace (fresh clone, same rule as
    state_consistent); FALSE only on concrete evidence — an absent or
    empty family directory, or the missing _beacon_ca sibling.
    """
    root = _find_workspace()
    if root is None:
        return _result(True, "scripts_migrated_ok",
                       {"reason": "workspace not found (fail-open)"})
    sdir = root / "scripts"
    missing = [f for f in _MIGRATED_SCRIPT_FAMILIES
               if not (sdir / f).is_dir()]
    empty = [f for f in _MIGRATED_SCRIPT_FAMILIES
             if (sdir / f).is_dir() and not any((sdir / f).iterdir())]
    ca_ok = (root / "_beacon_ca").is_dir()
    ok = not missing and not empty and ca_ok
    return _result(ok, "scripts_migrated_ok",
                   {"missing": missing, "empty": empty,
                    "beacon_ca": ca_ok,
                    "families_expected": len(_MIGRATED_SCRIPT_FAMILIES)})


def scripts_corpus_manifest_ok(*args, **kw):
    """REAL: full-corpus manifest exists, parses, covers every family.

    Manifest = system/instance/vsf-instance-v1/scripts_manifest.vsm
    (generated by scripts/shared/update_scripts_manifest.py). Family
    lines are the machine contract: `family:<name>:<file_count>`.
    Fail-open only when the workspace itself is not found.
    """
    root = _find_workspace()
    if root is None:
        return _result(True, "scripts_corpus_manifest_ok",
                       {"reason": "workspace not found (fail-open)"})
    mf = root / "system" / "instance" / "vsf-instance-v1" / \
        "scripts_manifest.vsm"
    if not mf.is_file():
        return _result(False, "scripts_corpus_manifest_ok",
                       {"missing": str(mf),
                        "hint": "run scripts/shared/update_scripts_manifest.py"})
    covered = set()
    try:
        for line in mf.read_text(encoding="utf-8").splitlines():
            if line.startswith("family:"):
                parts = line.split(":")
                if len(parts) >= 3 and parts[1]:
                    covered.add(parts[1])
    except OSError as e:
        return _result(False, "scripts_corpus_manifest_ok",
                       {"unreadable": str(e)[:120]})
    missing = [f for f in _MIGRATED_SCRIPT_FAMILIES if f not in covered]
    return _result(not missing, "scripts_corpus_manifest_ok",
                   {"manifest": str(mf), "covered": len(covered),
                    "missing_families": missing})

# Task predicates (task_active is REAL, T1.2)

# System predicates (REAL since stubs audit: existence/health, never blocks —
# none sits in the pre-check tree; parse_query reports them truthfully).

def event_router_ok(*args, **kw):
    """REAL: router file + handlers registered + states sidecar parses."""
    import json as _json
    root = _find_workspace()
    if root is None:
        return _result(False, "event_router_ok",
                       {"reason": "workspace not found"})
    router = root / ".opencode" / "plugins" / "operational" / "vsf-event-router.ts"
    try:
        text = router.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    regs = text.count("registerHandler(")
    sidecar = root / ".opencode" / "plugins" / "operational" / "handler_states.json"
    try:
        states = _json.loads(sidecar.read_text(encoding="utf-8"))
        sidecar_ok = isinstance(states.get("handlers"), dict)
    except Exception:
        sidecar_ok = False
    ok = regs >= 10 and sidecar_ok
    return _result(ok, "event_router_ok",
                   {"registrations": regs, "sidecar": sidecar_ok})


def lifecycle_valid(*args, **kw):
    """REAL: focus file parses as a list (lifecycle ground truth)."""
    import json as _json
    root = _find_workspace()
    if root is None:
        return _result(False, "lifecycle_valid",
                       {"reason": "workspace not found"})
    try:
        data = _json.loads((root / "current_focus.json").read_text(
            encoding="utf-8"))
        ok = isinstance(data, list)
        return _result(ok, "lifecycle_valid",
                       {"entries": len(data) if ok else 0})
    except Exception as e:
        return _result(False, "lifecycle_valid", {"error": str(e)[:120]})


def gap_free(*args, **kw):
    """REAL: every gap definition parses (names the bad file)."""
    import json as _json
    root = _find_workspace()
    if root is None:
        return _result(False, "gap_free", {"reason": "workspace not found"})
    gdir = root / ".opencode" / "plugins" / "operational" / "gap-definitions"
    if not gdir.is_dir():
        return _result(False, "gap_free", {"reason": "no gap-definitions dir"})
    bad = []
    n = 0
    for p in sorted(gdir.glob("*.gap.json")):
        n += 1
        try:
            _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            bad.append(p.name)
    scope = "definitions health only (tree eval path is separate debt)"
    return _result(not bad, "gap_free",
                   {"checked": n, "bad": bad, "scope": scope})


def onboard_complete(*args, **kw):
    """REAL: repo marker + plugin list non-empty (bootstrapped checkout)."""
    import json as _json
    root = _find_workspace()
    if root is None:
        return _result(False, "onboard_complete",
                       {"reason": "workspace not found"})
    marker = (root / ".vos-root").exists()
    try:
        plugins = _json.loads((root / "opencode.json").read_text(
            encoding="utf-8")).get("plugin", [])
        plugged = isinstance(plugins, list) and len(plugins) > 0
    except Exception:
        plugged = False
    return _result(marker and plugged, "onboard_complete",
                   {"marker": marker, "plugins": plugged})


def hook_metrics_ok(*args, **kw):
    """REAL: analytics pipeline present (handler + event log + live log)."""
    root = _find_workspace()
    if root is None:
        return _result(False, "hook_metrics_ok",
                       {"reason": "workspace not found"})
    parts = [(root / ".opencode" / "plugins" / "operational" / "handlers"
              / "hook-analytics.ts").is_file(),
             (root / ".opencode" / "shared" / "event-log.ts").is_file(),
             (root / "logs" / "agent_plugin.jsonl").is_file()]
    return _result(all(parts), "hook_metrics_ok",
                   {"handler": parts[0], "event_log": parts[1],
                    "live_log": parts[2]})


def semantic_mapper_ok(*args, **kw):
    """REAL: semantic mapper module present in vsf-tools."""
    root = _find_workspace()
    if root is None:
        return _result(False, "semantic_mapper_ok",
                       {"reason": "workspace not found"})
    p = root / "packages" / "public" / "vsf-tools" / "vsf_tools" / "semantic_mapper.py"
    return _result(p.is_file(), "semantic_mapper_ok", {"path": str(p)})


def process_staging_ok(*args, **kw):
    """REAL (honest FALSE): process_staging never migrated to vOSlab.

    Tracked debt, not a block: nothing evaluates this in the pre-check
    tree today; parse_query reports it truthfully.
    """
    return _result(False, "process_staging_ok",
                   {"reason": "no process_staging in vOSlab (never migrated)",
                    "debt": "port or drop explicitly"})


def load_hooks_ok(*args, **kw):
    """REAL: plugin surface loads (count + registry parses)."""
    import json as _json
    root = _find_workspace()
    if root is None:
        return _result(False, "load_hooks_ok",
                       {"reason": "workspace not found"})
    mods = root / ".opencode" / "plugins" / "operational"
    n = len(list(mods.glob("*.ts"))) if mods.is_dir() else 0
    try:
        _json.loads((root / ".opencode" / "plugins" / "registry.json")
                    .read_text(encoding="utf-8"))
        reg_ok = True
    except Exception:
        reg_ok = False
    return _result(n >= 10 and reg_ok, "load_hooks_ok",
                   {"modules": n, "registry": reg_ok})

# Naming predicates (REAL since T1.2 second wave)
