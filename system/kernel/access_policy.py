"""access_policy.py — Loader for the S5 access policy (CLI-only config).

Separation: WHAT is forbidden (S5 decision, per-deployment) lives in
system/s5-policy/access_policy.json; HOW it is evaluated lives in the
predicates. Agents can NEVER write the policy file via tools
(`policy_locked` hard-blocks; the human edits it in shell).

Fail-closed: corrupt/missing policy -> restrictive builtin defaults
(the 6 sensitive roots + conservative thresholds). A broken policy must
never silently open the gates (R4: independent check, no self-service).

Hot-reload: re-read when mtime changes, so policy edits apply without
restarts. Reads are O(1) small-file IO with a process cache.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

BUILTIN_DENYLIST = [
    "/etc/shadow",
    "/etc/passwd",
    "/root/.ssh",
    "/proc/kcore",
    "/dev/sda",
    "/dev/nvme",
]

DEFAULT_THRESHOLDS = {
    "read_warn_bytes": 512 * 1024,
    "repeat_block": 3,
    "repeat_error_block": 2,
}

_cache: Dict[str, Any] = {"mtime": None, "policy": None, "path": None}


def policy_path() -> Path:
    """Resolve the policy file: env wins, else workspace walk."""
    env = os.environ.get("ACCESS_POLICY_PATH")
    if env:
        return Path(env)
    p = Path(os.getcwd()).resolve()
    for _ in range(7):
        cand = p / "system" / "s5-policy" / "access_policy.json"
        if cand.is_file():
            return cand
        if p.parent == p:
            break
        p = p.parent
    # last resort: beside this module's workspace layout
    return (Path(__file__).resolve().parent.parent.parent
            / "system" / "s5-policy" / "access_policy.json")


def _validate(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("policy_version") != 1:
        return None
    roots = raw.get("workspace_roots")
    deny = raw.get("read_denylist")
    th = raw.get("thresholds", {})
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
        return None
    if not isinstance(deny, list) or not all(isinstance(d, str) for d in deny):
        return None
    if not isinstance(th, dict):
        return None
    thresholds = dict(DEFAULT_THRESHOLDS)
    for k in thresholds:
        v = th.get(k)
        if isinstance(v, int) and v > 0:
            thresholds[k] = v
    return {"workspace_roots": roots, "read_denylist": deny,
            "thresholds": thresholds, "degraded": False}


def _fail_closed() -> Dict[str, Any]:
    return {"workspace_roots": [], "read_denylist": list(BUILTIN_DENYLIST),
            "thresholds": dict(DEFAULT_THRESHOLDS), "degraded": True}


def load() -> Dict[str, Any]:
    """Load (cached, mtime-checked) policy. Never raises, never opens gates."""
    path = policy_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _fail_closed()
    if _cache["mtime"] == mtime and _cache["path"] == str(path) \
            and _cache["policy"] is not None:
        return _cache["policy"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _fail_closed()
    policy = _validate(raw)
    if policy is None:
        return _fail_closed()
    _cache.update(mtime=mtime, policy=policy, path=str(path))
    return policy


# ─── Operating thresholds (RSI-governed, S5-bounded) ────────────────────────
# The policy file sets DEFAULTS. The operating store (state/rsi/, RSI-
# writable — never the CLI-only policy file) holds live values. Rules:
#   - blocking keys (repeat_*) move DOWN-only (toward stricter, floor 1):
#     RSI may tighten enforcement, never loosen it. Loosening = CLI edit.
#   - advisory keys (read_warn_bytes) move freely within [64K, 4M].
# Auto-tune of blocking keys is NOT implemented (needs observed-outcome
# telemetry — explicit future work, not silent heuristics).
OPERATING_KEYS = ("repeat_block", "repeat_error_block", "read_warn_bytes")
_DOWN_ONLY = {"repeat_block", "repeat_error_block"}
_OPERATING_BOUNDS = {
    "repeat_block": (1, 10),
    "repeat_error_block": (1, 10),
    "read_warn_bytes": (65536, 4194304),
}


def operating_path() -> Path:
    env = os.environ.get("RSI_THRESHOLDS_FILE")
    if env:
        return Path(env)
    ws = workspace_root()
    base = ws if ws is not None else Path(os.getcwd())
    return base / "state" / "rsi" / "thresholds.json"


def operating_thresholds() -> Dict[str, Any]:
    """Live thresholds = policy defaults overridden by operating store."""
    policy = load()
    live = dict(policy["thresholds"])
    try:
        raw = json.loads(operating_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in OPERATING_KEYS:
                v = raw.get(k)
                if isinstance(v, int):
                    lo, hi = _OPERATING_BOUNDS[k]
                    live[k] = max(lo, min(hi, v))
    except Exception:
        pass
    degraded = policy.get("degraded", False)
    return {**live, "degraded": degraded}


def set_operating_threshold(key: str, value: int) -> Dict[str, Any]:
    """Human/audited tuning of one threshold. Enforces direction + bounds.

    Returns {ok, previous, value, reason}. Blocking keys move down-only;
    advisory keys move within bounds. Out-of-rule requests are REFUSED
    (returned, never applied). Callers must audit successful changes.
    """
    if key not in OPERATING_KEYS:
        return {"ok": False, "reason": f"unknown key (want {OPERATING_KEYS})"}
    if not isinstance(value, int):
        return {"ok": False, "reason": "value must be int"}
    live = operating_thresholds()
    previous = live[key]
    lo, hi = _OPERATING_BOUNDS[key]
    if not (lo <= value <= hi):
        return {"ok": False, "previous": previous,
                "reason": f"outside bounds [{lo}, {hi}]"}
    if key in _DOWN_ONLY and value > previous:
        return {"ok": False, "previous": previous,
                "reason": "blocking keys move down-only (stricter); "
                          "loosening requires CLI policy edit"}
    try:
        path = operating_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw: Dict[str, Any] = {}
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                raw = got
        except Exception:
            pass
        raw[key] = value
        path.write_text(json.dumps(raw, indent=2))
    except Exception as e:
        return {"ok": False, "previous": previous,
                "reason": f"persist failed: {e}"}
    return {"ok": True, "previous": previous, "value": value}


def workspace_root() -> Path | None:
    """Auto-detected workspace (vOSlab) for <workspace> expansion."""
    p = Path(os.getcwd()).resolve()
    for _ in range(7):
        if (p / "current_focus.json").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def allowed_roots() -> List[str]:
    """Workspace roots with <workspace> and ${ENV_VAR} expanded. Never empty."""
    policy = load()
    out: List[str] = []
    ws = workspace_root()
    for r in policy["workspace_roots"]:
        if r == "<workspace>":
            if ws is not None:
                out.append(str(ws))
        elif r.startswith("${") and "}" in r:
            # Expand ${VAR:-default} syntax
            var_part = r[2:r.index("}")]
            if ":-" in var_part:
                var_name, default = var_part.split(":-", 1)
                out.append(os.environ.get(var_name, default))
            else:
                out.append(os.environ.get(var_part, ""))
        else:
            out.append(r)
    if ws is not None and str(ws) not in out:
        out.append(str(ws))  # fail-closed: home workspace always allowed
    return out
