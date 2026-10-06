"""Negative-control harness for gate-suite.

The defect we found in vsf's `checks/plugin-location-valid` was a BROKEN
negative control: it could not discriminate a violating artifact from a valid
one, so the gate was effectively a no-op. This harness makes that impossible
to ship unnoticed.

Each gate registers:
  - name:           unique gate id
  - check(path):    runs the gate on an artifact; returns 0 if ACCEPTED,
                    nonzero if REJECTED
  - negative_case:  builds an artifact the gate MUST reject, returns its path

`run_negative_controls()` proves every gate is NECESSARY: it feeds each gate
its own negative case and asserts the gate REJECTS it. If a gate accepts its
negative case (exit 0), the harness fails — exactly catching the vsf defect.

Logging:
  Gate evaluations are logged to logs/agent_plugin.jsonl in unified JSONL format.
  NC rejection reports go to stderr labeled [NC:<gate>] (G-35) so fixture
  noise stays visible without masquerading as live failures.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _log_gate_eval(gate_name: str, result: str, passed: bool, detail: str = "") -> None:
    """Append a gate evaluation record to the unified JSONL log."""
    try:
        # Use environment variable or default to cwd/logs
        log_path = Path(os.environ.get("VOS_LOG_DIR", Path.cwd() / "logs")) / "agent_plugin.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": None,
            "level": "activation",
            "source": gate_name,
            "event_type": "gate.evaluate",
            "event_id": f"gate:{gate_name}:{datetime.now(timezone.utc).timestamp():.0f}",
            "action": f"negative_control: {gate_name}",
            "result": result,
            "detail": detail,
            "context": {"passed": passed},
        }

        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never throw


@dataclass
class Gate:
    name: str
    check: "callable[[str], int]"          # path -> exit code (0 accept, !=0 reject)
    negative_case: "callable[[], str]"     # () -> path to artifact that MUST be rejected


GATES: list[Gate] = []


def register(name: str, check, negative_case) -> None:
    """Register a gate with its negative-control case."""
    GATES.append(Gate(name, check, negative_case))


def _cleanup(path: str) -> None:
    if path.startswith(tempfile.gettempdir()):
        try:
            os.remove(path)
        except OSError:
            pass


def run_negative_controls() -> int:
    """Return 0 if ALL gates reject their negative cases; else 1.

    A nonzero return means at least one gate is a no-op (broken negative
    control) and must not ship.

    G-35 (2026-10-06): each gate's rejection report is captured and
    re-emitted with an [NC:<gate>] prefix. The report must stay visible —
    it proves WHY the fixture was rejected (epistemic value intact) — but
    it is fixture noise by design and must never be mistakable for a live
    failure (cry-wolf: unlabeled NC lines cost a full diagnosis pass on
    the 2026-10-06 boot before the one real red gate was found).
    """
    failed: list[str] = []
    print(
        "NEGATIVE CONTROL DETAIL — expected fixture rejections "
        "(by design; verdict follows the block)",
        file=sys.stderr,
    )
    for g in GATES:
        path = g.negative_case()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            rc = g.check(path)
        _cleanup(path)
        for line in buf.getvalue().splitlines():
            print(f"[NC:{g.name}] {line}", file=sys.stderr)
        passed = rc != 0
        if rc == 0:
            failed.append(g.name)
        _log_gate_eval(
            g.name,
            "ok" if passed else "error",
            passed,
            detail=f"negative_control: exit_code={rc}",
        )
    if failed:
        print(
            "NEGATIVE CONTROL FAIL — gates that do NOT catch their own "
            f"negative case (no-op defect): {failed}"
        )
        return 1
    print(f"NEGATIVE CONTROL PASS — {len(GATES)} gates verified necessary")
    return 0


# ── F3a: live-check manifest cache (REFS-OPT-001) ────────────────────────────
# ALWAYS_COLD: checks whose result can change WITHOUT any tracked file
# changing. Their inputs are external hosts, gitignored state, wall-clock,
# empty (untrackable) directories, or process env. They run on EVERY live
# pass — cached results would be stale by construction.
#
# The complement (cacheable) was certified by a strace ground-truth audit of
# all 81 checks (2026-10-06, traces /tmp/opencode/trace_*.log): every open
# resolves to a tracked file, /tmp, or sys — plus source re-reads for
# stat()/wall-clock surfaces strace cannot see.
ALWAYS_COLD: frozenset = frozenset({
    "agent-plugin-log-valid",        # reads ignored logs/agent_plugin.jsonl (appended during runs)
    "algedonic-queue-consumed",      # reads ignored state/rsi/alerts.jsonl
    "attestations-retention",        # ignored attestations dir + record age (wall-clock)
    "beacon-endpoint-contract",      # reads ignored state/_beacon_ca material
    "bindings-valid",                # observes ignored system/* dir existence
    "claude-md-decouple",            # greps ~/.bashrc content (external to repo)
    "crl-expiry-proximity",          # ssh to n02 + wall-clock CRL expiry
    "dir-schema-valid",              # empty untrackable dir + external ~/vsf
    "evolution-cadence-window",      # wall-clock 7-day report window
    "incident-registry-valid",       # ssh remote incident state
    "instance-start-preconditions",  # observes ignored system/* dir existence
    "inst-validation-rules",         # observes ignored system/* dir existence
    "kernel-write-audit-wired",      # reads ignored logs/agent_plugin.jsonl
    "manifest-dest-integrity",       # external ~/vsf manifest copies
    "plugin-location-valid",         # external ${VSF_ROOT:-~/vsf}/.opencode
    "r15-envelope-valid",            # glob reads ignored .md/.vsm (focus_details, vsf-rsi docs)
    "r7-rules-table-cleanup",        # ssh remote rules table
    "rectif-boot-ontology-prose-valid",  # external ~/vsf/docs
    "relocate-vsm-valid",            # external ~/vsf files
    "regulation-monitor",            # env VSF_STATE_DB + live invariant state
    "shadow-divergences-explained",  # shadow.jsonl content (excluded from dirty) + 7d window
    "spec-kernel-domain",            # imports external state-canon-mcp
    "tasks-census-converge",         # imports external state-canon-mcp
    "tasks-reconcile-enforced",      # external ${VSF_ROOT:-~/vsf}/TASKS.vsm
    "version-change-plan",           # existence of empty untrackable dir
    "vsl-gate-valid",                # external ${VSF_ROOT:-~/vsf} plugin file
    "vsf-knowledge-complete",        # external ~/vsf/docs
    "vslline-manifest-valid",        # external state-canon-mcp + ~/vsf
    "workspaces-health",             # stat() external workspace roots
})

# Every cold check must document WHY it cannot be cached (test-asserted).
_COLD_REASONS: dict[str, str] = {
    "agent-plugin-log-valid": "ignored self-log, volatile during runs",
    "algedonic-queue-consumed": "ignored alerts queue",
    "attestations-retention": "ignored store + age",
    "beacon-endpoint-contract": "ignored CA material",
    "bindings-valid": "ignored system/* dirs",
    "claude-md-decouple": "~/.bashrc content",
    "crl-expiry-proximity": "external ssh + wall-clock",
    "dir-schema-valid": "untrackable dir + external ~/vsf",
    "evolution-cadence-window": "wall-clock window",
    "incident-registry-valid": "external ssh state",
    "instance-start-preconditions": "ignored system/* dirs",
    "inst-validation-rules": "ignored system/* dirs",
    "kernel-write-audit-wired": "ignored self-log",
    "manifest-dest-integrity": "external ~/vsf",
    "plugin-location-valid": "external ~/vsf/.opencode",
    "r15-envelope-valid": "ignored .md/.vsm content",
    "r7-rules-table-cleanup": "external ssh state",
    "rectif-boot-ontology-prose-valid": "external ~/vsf/docs",
    "relocate-vsm-valid": "external ~/vsf",
    "regulation-monitor": "env VSF_STATE_DB + live invariants",
    "shadow-divergences-explained": "shadow excluded from dirty + 7d window",
    "spec-kernel-domain": "external state-canon-mcp",
    "tasks-census-converge": "external state-canon-mcp",
    "tasks-reconcile-enforced": "external ~/vsf/TASKS.vsm",
    "version-change-plan": "untrackable empty dir",
    "vsl-gate-valid": "external ~/vsf plugin file",
    "vsf-knowledge-complete": "external ~/vsf/docs",
    "vslline-manifest-valid": "external state-canon-mcp + ~/vsf",
    "workspaces-health": "stat() external roots",
}

CACHE_VERSION = 1
CACHE_GATE = "run_gates_live"
SHADOW_REL = "state/epistemic/shadow.jsonl"  # D-24: excluded from dirty
_MAX_PARALLEL = 16


def _cache_enabled() -> bool:
    """Kill switch: run_gates --no-cache sets VOS_GATES_CACHE=0."""
    return os.environ.get("VOS_GATES_CACHE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _repo_root() -> Path:
    # harness.py lives at <root>/packages/framework/gate_suite/harness.py
    return Path(__file__).resolve().parents[3]


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(cwd or _repo_root()),
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _dirty_modulo_shadow() -> bool:
    """True iff the working tree differs from HEAD beyond shadow.jsonl.

    Untracked files count (showUntrackedFiles=all makes the answer
    config-independent); empty directories are invisible to git — that is
    exactly why dir-schema-valid / version-change-plan stay in ALWAYS_COLD.
    """
    out = _git("-c", "status.showUntrackedFiles=all", "status", "--porcelain")
    return any(
        line.strip()
        for line in out.splitlines()
        if not line.endswith(SHADOW_REL)
    )


def _tree_hash() -> str:
    return _git("rev-parse", "HEAD^{tree}").strip()


def _manifest_path() -> Path:
    override = os.environ.get("VOS_GATES_CACHE_PATH")
    if override:
        return Path(override)
    return _repo_root() / "state" / "cache" / "run_gates_live.json"


def _load_manifest() -> dict | None:
    try:
        with open(_manifest_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_manifest(tree: str, entries: dict) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "gate": CACHE_GATE,
        "tree": tree,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _run_check(check: Path) -> tuple[str, int]:
    """Run one check; returns (name, exit_code)."""
    try:
        proc = subprocess.run(
            ["bash", str(check), ""],
            capture_output=True, text=True, timeout=60,
        )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = 124
    except OSError:
        rc = 126
    return check.name, rc


def _run_parallel(checks: list[Path]) -> list[tuple[str, int]]:
    """Run the cold set concurrently; output order stays deterministic
    (ThreadPoolExecutor.map preserves input order — logs replay sorted)."""
    if not checks:
        return []
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(checks))) as pool:
        return list(pool.map(_run_check, checks))


def run_live_checks(checks_dir: "Path | str | None" = None) -> int:
    """Run every shipped check in packages/public/vsf-checks/checks against
    the live workspace (empty target = self-audit).

    G-11 closed 2026-10-03: run_gates previously proved gates necessary
    (negative controls) but never verified the actual workspace — 39 of 65
    checks were red unnoticed. Returns 0 iff every check passes; each run is
    logged to the unified log so the instrument set self-observes.

    F3a manifest cache (REFS-OPT-001, approved contract proposal §5.1):
    - Partition: ALWAYS_COLD (29 checks whose inputs are NOT captured by the
      git tree — external hosts, ignored state, wall-clock, env) vs
      cacheable (52 — every input is tracked / tmp / sys; strace-audited,
      81 traces under /tmp/opencode/trace_*.log).
    - Dirty gate: `git status --porcelain` (untracked=all) modulo
      state/epistemic/shadow.jsonl (D-24: tracked but volatile by design).
      Dirty => BYPASS total: no manifest read, no manifest write.
    - Key: (CACHE_VERSION, git HEAD^{tree}) + gate name + the cacheable set
      itself. Green run only => manifest written (a red run never poisons
      the cache: failures must re-run).
    - Warm run: NC (sequential, always cold) + ALWAYS_COLD in parallel
      (read-only / /tmp fixtures) + one honest `live:cache_hit` summary
      record — no fabricated per-check records for skipped checks.
    - Kill switch: run_gates --no-cache or env VOS_GATES_CACHE=0.
    """
    checks_root = (
        Path(checks_dir)
        if checks_dir is not None
        else Path(__file__).resolve().parents[2] / "public" / "vsf-checks" / "checks"
    )
    if not checks_root.is_dir():
        print(f"LIVE CHECKS FAIL — checks dir missing: {checks_root}")
        return 1
    # bash runs them by name; skip only docs (README).
    checks = sorted(
        p for p in checks_root.iterdir() if p.is_file() and not p.name.endswith(".md")
    )
    cold = [p for p in checks if p.name in ALWAYS_COLD]
    cacheable = [p for p in checks if p.name not in ALWAYS_COLD]

    # ── cache state ──────────────────────────────────────────────────────
    enabled = _cache_enabled()
    dirty = _dirty_modulo_shadow() if enabled else False
    tree = _tree_hash() if (enabled and not dirty) else ""
    manifest = _load_manifest() if (enabled and not dirty) else None
    cacheable_names = [p.name for p in cacheable]
    hit = bool(
        manifest
        and manifest.get("version") == CACHE_VERSION
        and manifest.get("gate") == CACHE_GATE
        and manifest.get("tree") == tree
        and set((manifest.get("entries") or {}).keys()) == set(cacheable_names)
    )

    # ── phase 1: ALWAYS_COLD — runs in every mode, in parallel ──────────
    # Parallel-safe by construction: the cold set is read-only on the
    # workspace (its own fixtures live in /tmp), and NOTHING appends to
    # logs/agent_plugin.jsonl while the pool runs (log writes happen after
    # the join), so the log readers inside the pool see a stable file.
    cold_results = _run_parallel(cold)
    for name, rc in cold_results:
        _log_gate_eval(
            f"live:{name}",
            "ok" if rc == 0 else "error",
            rc == 0,
            detail=f"live: exit_code={rc}",
        )

    # ── phase 2: cacheable — skipped on a clean-tree manifest hit ───────
    results: list[tuple[str, int]] = list(cold_results)
    if not hit:
        for check in cacheable:
            name, rc = _run_check(check)
            results.append((name, rc))
            _log_gate_eval(
                f"live:{name}",
                "ok" if rc == 0 else "error",
                rc == 0,
                detail=f"live: exit_code={rc}",
            )

    failed = [(n, rc) for n, rc in results if rc != 0]
    passed = len(results) - len(failed)

    # ── phase 3: persist the manifest (green + enabled + clean only) ────
    if enabled and not dirty and not failed and not hit:
        _save_manifest(
            tree,
            {name: {"rc": rc, "at": datetime.now(timezone.utc).isoformat()}
             for name, rc in results if name not in ALWAYS_COLD},
        )
        _log_gate_eval(
            "live:cache_saved",
            "ok",
            True,
            detail=f"tree={tree[:12]} entries={len(cacheable)}",
        )

    if failed:
        print(f"LIVE CHECKS FAIL — {len(failed)}/{len(results)} red:")
        for name, rc in failed:
            print(f"  rc={rc:>3}  {name}")
        return 1
    if hit:
        _log_gate_eval(
            "live:cache_hit",
            "ok",
            True,
            detail=f"tree={tree[:12]} cold={len(cold)} cached={len(cacheable)}",
        )
        print(
            f"LIVE CHECKS PASS — {len(cold)} cold + {len(cacheable)} cached "
            f"green [tree {tree[:12]}]"
        )
        return 0
    print(f"LIVE CHECKS PASS — {passed} checks green")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_negative_controls())
