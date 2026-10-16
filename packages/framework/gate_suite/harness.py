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
import shutil
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
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
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
    "extractor-nonvacuous",          # reads ignored state/ (doc_manifest, symbol_table)
    "incident-registry-valid",       # ssh remote incident state
    "instance-start-preconditions",  # observes ignored system/* dir existence
    "inst-validation-rules",         # observes ignored system/* dir existence
    "kernel-write-audit-wired",      # reads ignored logs/agent_plugin.jsonl
    "manifest-dest-integrity",       # external ~/vsf manifest copies
    "plugin-location-valid",         # external ${VSF_ROOT:-~/vsf}/.opencode
    "pleasure-channel",              # ignored state/rsi/pleasure.jsonl (append-only during runs)
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
    "extractor-nonvacuous": "gitignored state/ (doc_manifest, symbol_table)",
    "incident-registry-valid": "external ssh state",
    "instance-start-preconditions": "ignored system/* dirs",
    "inst-validation-rules": "ignored system/* dirs",
    "kernel-write-audit-wired": "ignored self-log",
    "manifest-dest-integrity": "external ~/vsf",
    "plugin-location-valid": "external ~/vsf/.opencode",
    "pleasure-channel": "ignored pleasure ledger (append-only)",
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
# Tracked state/ files with AUTOMATIC writers — excluded from dirty so the
# cache gate measures uncommitted WORK, not un-landed auto-appends:
#   shadow.jsonl            — D-24 (2026-10-06): gap-resolver + daily cycle
#   .session_idle_last      — idle hook timestamp (boot evidence 2026-10-07:
#                             final idle 13:18:50Z rewrote it post-close)
#   candidates.jsonl        — distill propose-only append 13:19:17Z (R-3)
# All three land with the session commit; grep across checks/ confirms no
# check reads their content. Keep in sync with the gate-5 filter in
# checks/child-boot-state-archive-gates (same rationale, same list).
DIRTY_EXCLUDES = (
    "state/epistemic/shadow.jsonl",
    "state/rsi/.session_idle_last",
    "state/distill/candidates.jsonl",
    # dir prefix (trailing /): daily evolution stage rewrites EVOLUTION.md
    # + evolution_latest.json and drops evolution_YYYY-MM-DD.json mid-session
    # (boot evidence 2026-10-07 15:27:28Z; same D-24 rationale, mirrored
    # in child-boot-state-archive-gates gate 5).
    "state/epistemic/reports/",
)
# 4 cores (nproc): 16 workers thrashed the CPU-bound cold checks (measured
# 2026-10-06: agent-plugin-log 11.9s solo -> 16.6s in pool, beacon 5.9 ->
# 10.7). 8 keeps the I/O-bound overlap without the contention tax.
_MAX_PARALLEL = 8

# ── ssh multiplexing (contract <15s) ────────────────────────────────────────
# crl/r7/incident reach n02 via ProxyJump (n01 -> DigitalOcean -> tunnel);
# each raw handshake measured 7-8.5s and crl/incident issue 2 calls, r7
# three — the handshake, not the remote work, set the warm-run floor
# (~15s single check). The three checks carry ControlMaster=auto with THIS
# exact ControlPath (transport-transparent: same auth, same commands); the
# harness pre-opens both slots (rmw3 + root) so the cold pool reuses them.
# Failure mode is degradation to today's direct connection, never
# incorrectness. VOS_SSH_MUX=0 disables (tests use it to stay hermetic).
_SSH_CONTROL_PATH = "/tmp/vos-run-gates-mux-%r@%h:%p"
SSH_MUX_CHECKS = frozenset({
    "crl-expiry-proximity",
    "incident-registry-valid",
    "r7-rules-table-cleanup",
})
_prewarm_lock = False  # ssh_prewarm_start idempotence (single-threaded calls)
_prewarm_targets: tuple[str, ...] = ()


def _mux_enabled() -> bool:
    return os.environ.get("VOS_SSH_MUX", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _mux_targets() -> tuple[str, ...]:
    host = os.environ.get("VSF_N02", "n02")
    return (host, f"root@{host}")


def ssh_prewarm_start() -> None:
    """Open ControlMaster sockets to n02 (rmw3 + root slots) in the
    background. Call BEFORE run_negative_controls so the ~7-8s handshake
    overlaps the NC pass; run_live_checks waits on the slots it needs."""
    global _prewarm_lock, _prewarm_targets
    if _prewarm_lock or not _mux_enabled():
        return
    _prewarm_lock = True
    _prewarm_targets = _mux_targets()
    for target in _prewarm_targets:
        try:
            subprocess.Popen(
                ["ssh", "-M", "-f", "-N",
                 "-o", f"ControlPath={_SSH_CONTROL_PATH}",
                 "-o", "ControlPersist=60",
                 "-o", "ConnectTimeout=5",
                 target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass  # no ssh binary -> checks fall back to direct (today's speed)


def ssh_prewarm_wait(timeout: float = 12.0) -> bool:
    """Block until both master slots answer `ssh -O check` (or timeout).
    Returns False on timeout — callers still submit the checks (direct
    fallback), so a wedged master degrades speed, never correctness."""
    if not _prewarm_targets:
        return False
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        ready = True
        for target in _prewarm_targets:
            try:
                rc = subprocess.run(
                    ["ssh", "-O", "check",
                     "-o", f"ControlPath={_SSH_CONTROL_PATH}",
                     target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).returncode
            except (OSError, subprocess.TimeoutExpired):
                rc = 1
            if rc != 0:
                ready = False
                break
        if ready:
            return True
        if _time.monotonic() >= deadline:
            return False
        _time.sleep(0.2)


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
    """True iff the working tree differs from HEAD beyond DIRTY_EXCLUDES.

    Untracked files count (showUntrackedFiles=all makes the answer
    config-independent); empty directories are invisible to git — that is
    exactly why dir-schema-valid / version-change-plan stay in ALWAYS_COLD.
    An exclude entry ending in '/' is a DIRECTORY prefix (git porcelain
    lists every file under it); exact entries keep endswith semantics.
    """
    out = _git("-c", "status.showUntrackedFiles=all", "status", "--porcelain")

    def _excluded(line: str) -> bool:
        return any(
            (e in line) if e.endswith("/") else line.endswith(e)
            for e in DIRTY_EXCLUDES
        )

    return any(
        line.strip()
        for line in out.splitlines()
        if not _excluded(line)
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



def _pleasure_gate_transitions(results: "list[tuple[str, int]]") -> None:
    """G-34 P2 (PLEASURE-CHANNEL-001): rojo→verde -> evento de placer.

    Advisory + fail-open (proposal GUARD): jamas modifica el rc, jamas
    toca alerts.jsonl (F2). Estado previo en
    state/cache/gate_last_results.json (gitignored, auto-written); la
    PRIMERA corrida (sin baseline) no celebra nada — solo cambios reales.
    El ledger vive en RSI_PLEASURE_FILE (default state/rsi/pleasure.jsonl).
    """
    env_path = os.environ.get("VOS_GATE_TRANSITIONS_FILE")
    state_path = (
        Path(env_path) if env_path
        else Path(__file__).resolve().parents[3] / "state" / "cache"
             / "gate_last_results.json"
    )
    curr = dict(results)
    prev = None
    if state_path.exists():
        try:
            prev = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = None
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(dict(sorted(curr.items())), ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    if not isinstance(prev, dict):
        return  # primera corrida: sin baseline, sin celebracion
    red_to_green = sorted(
        n for n, rc in curr.items()
        if rc == 0 and n in prev and prev[n] != 0
    )
    if not red_to_green:
        return
    from vos_kernel.pleasure_emitter import emit  # framework en path (run_gates/pytest)
    for name in red_to_green:
        emit(
            "gate_run", True,
            detail=f"rojo→verde: {name}",
            source="run_gates",
            connection=f"checks/{name}",
            feedback=True,  # P3: hebbiano (trust spill + pesos, fail-open)
        )


def run_live_checks(checks_dir: "Path | str | None" = None) -> int:
    """Run every shipped check in packages/public/vsf-checks/checks against
    the live workspace (empty target = self-audit).

    G-11 closed 2026-10-03: run_gates previously proved gates necessary
    (negative controls) but never verified the actual workspace — 39 of 65
    checks were red unnoticed. Returns 0 iff every check passes; each run is
    logged to the unified log so the instrument set self-observes.

    F3a manifest cache (REFS-OPT-001, approved contract proposal §5.1):
    - Partition: ALWAYS_COLD (31 checks whose inputs are NOT captured by the
      git tree — external hosts, ignored state, wall-clock, env) vs
      cacheable (52 — every input is tracked / tmp / sys; strace-audited,
      81 traces under /tmp/opencode/trace_*.log; recount on growth:
      2026-10-16 = 84 total = 31 cold + 53 cacheable).
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
    #
    # ssh checks (crl/r7/incident) wait for the multiplexed master slots;
    # local checks start immediately and overlap the handshake. On a
    # prewarm timeout they still run (direct fallback, today's speed).
    local_cold = [p for p in cold if p.name not in SSH_MUX_CHECKS]
    ssh_cold = [p for p in cold if p.name in SSH_MUX_CHECKS]
    if ssh_cold and _mux_enabled():
        ssh_prewarm_start()
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, max(len(cold), 1))) as pool:
        futures = [pool.submit(_run_check, p) for p in local_cold]
        if ssh_cold:
            if _mux_enabled():
                ssh_prewarm_wait()
            futures += [pool.submit(_run_check, p) for p in ssh_cold]
        cold_results = [f.result() for f in futures]
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


    # G-34 P2: transiciones rojo→verde -> placer (advisory, fail-open).
    # Solo corridas con resultados COMPLETOS: un cache hit no trae los
    # cacheables y falsearia transiciones.
    if not hit:
        try:
            _pleasure_gate_transitions(results)
        except Exception:
            pass

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
