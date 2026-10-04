"""Anti-pantomima battery R1-R11 — single runner (CC-8.0 exit criterion).

Usage:
    python3 -m vos_kernel.real_state_battery [--dry] [--id SUFFIX]

Regenerates state/epistemic/reports/real_state_battery_<date>.json with
one ground-truth verdict per check. Every check runs independently; a
failing check records FAIL with its output tail — the report is emitted
either way (hiding a failure would be the pantomime this battery exists
to catch).

Design (R10): verdicts are deterministic — same system state, same
verdict. Timestamps come from the clock (report identity, not a
predicate). R4b is the built-in negative control: a forged log MUST be
rejected, otherwise R4's PASS proves nothing.

Checks:
  R1  run_gates negative-control battery
  R2  audit_guards(store, run=False) — coverage 1.0
  R3  cycle_health.py live
  R4  agent-log validator vs declared_sources (agent_instruments.vsm SSOT)
  R4b same validator against a forged log (naive ts + undeclared source)
  R5  n02 monitor_reconcile --check (remote ground truth)
  R6  fresh RSICycle() feedback-loop drill (new process)
  R7  boot ontology (type-coherence, authority, hashes, mcp-liveness)
  R8  vsf tasks_validate against ~/vsf/TASKS.vsm (1 advisory tolerated)
  R9  snapshot_runtime_state (runtime state attestation)
  R10 socratic-engine MCP live: socratic_canon_providers
  R11 state-canon MCP live: voslab state_reconcile + infra state_query (n02)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
REPORTS = ROOT / "state/epistemic/reports"
TIMEOUT = 180

NOT_VERIFIED = [
    {"id": "G1-idle-post-fix",
     "why": "post-fix idle dispatch requires an idle event to observe — "
            "watched via cycle_health, not proven by this battery"},
    {"id": "G2-guard-live-run",
     "why": "R2 runs audit_guards(run=False): liveness is sampled, not "
            "exercised end-to-end in-process"},
    {"id": "G3-doc-manifest-stale",
     "why": "doc-manifest staleness is covered by boot-ontology (R7) only "
            "for artifacts it declares"},
    {"id": "G4-claims-cadence",
     "why": "claims/certs cadence is a multi-day property — see evolution "
            "report cadence (G-03), not a point-in-time check"},
]


def _run(cmd, timeout=TIMEOUT, env=None, cwd=None):
    """Run a command -> (rc, output_tail). Never raises (battery must go on)."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=env, cwd=str(cwd) if cwd else str(ROOT),
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out[-1500:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


def _mcp_call(cmd, tool, arguments=None, timeout=30):
    """MCP stdio client (newline-delimited JSON) -> (ok, detail)."""
    try:
        p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
            cwd=str(ROOT), env=dict(os.environ, VOSLAB_PATH=str(ROOT)),
        )
    except OSError as exc:
        return False, str(exc)
    received: list[str] = []
    threading.Thread(
        target=lambda: received.extend(p.stdout), daemon=True
    ).start()
    try:
        for msg in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "real-state-battery",
                                       "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized",
             "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": tool, "arguments": arguments or {}}},
        ):
            p.stdin.write(json.dumps(msg) + "\n")
            p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in list(received):
                d = json.loads(line)
                if d.get("id") == 2:
                    if "result" in d:
                        content = d["result"].get("content", [])
                        text = content[0].get("text", "") if content else ""
                        return True, text[:400]
                    return False, json.dumps(d.get("error", {}))[:300]
            time.sleep(0.3)
        return False, "no response within timeout"
    except Exception as exc:  # noqa: BLE001 — report, never crash the battery
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        p.terminate()


def _check_r1() -> tuple[str, str]:
    rc, out = _run([sys.executable, str(ROOT / "packages/framework/run_gates.py")])
    gates = re.search(r"(\d+) gates verified necessary", out)
    verdict = "PASS" if rc == 0 else "FAIL"
    return verdict, (gates.group(0) if gates else out[-200:]) + f" (rc={rc})"


def _check_r2() -> tuple[str, str]:
    code = (
        "import sys; sys.path.insert(0, %r); "
        "from vos_kernel.epistemic import EpicStore, audit_guards; "
        "r = audit_guards(EpicStore(), run=False); "
        "print(r.get('coverage'), len(r.get('errors') or []), r.get('dead'))"
        % str(ROOT / "packages/framework")
    )
    rc, out = _run([sys.executable, "-c", code])
    m = re.search(r"([\d.]+)\s+(\d+)\s+(\S+)", out.strip().splitlines()[-1] if out else "")
    if rc == 0 and m and float(m.group(1)) == 1.0 and int(m.group(2)) == 0:
        return "PASS", f"coverage {m.group(1)}, errors 0, dead {m.group(3)}"
    return "FAIL", out[-300:]


def _check_r3() -> tuple[str, str]:
    rc, out = _run([sys.executable, str(ROOT / "scripts/vsl/tools/cycle_health.py")])
    return ("PASS" if rc == 0 else "FAIL"), (out.splitlines()[-1] if out else f"rc={rc}")


def _declared_sources() -> str:
    txt = (ROOT / "system/s5-policy/agent-policy/agent-instruments-v1/"
                  "agent_instruments.vsm").read_text(encoding="utf-8")
    return re.search(r'declared_sources: "([^"]+)"', txt).group(1)


def _check_r4() -> tuple[str, str]:
    src = _declared_sources()
    rc, out = _run([sys.executable,
                    str(ROOT / "scripts/state/attestation/check_agent_log.py"),
                    str(ROOT / "logs/agent_plugin.jsonl"), src])
    line = next((l for l in out.splitlines() if "declared" in l), out[-200:])
    return ("PASS" if rc == 0 else "FAIL"), line + f" (rc={rc})"


def _check_r4b() -> tuple[str, str]:
    """Negative control: forged log (naive ts + undeclared source) MUST fail."""
    forged = [
        json.dumps({"ts": "2026-10-02T12:00:00", "source": "not-a-real-source",
                    "event_type": "tool.execute.after", "action": "forged",
                    "result": "ok"}),
        json.dumps({"ts": "2026-10-02T12:00:01Z", "source": "tool-integration",
                    "event_type": "tool.execute.after", "action": "forged",
                    "result": "ok"}),
        "",
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write("\n".join(forged))
        path = fh.name
    try:
        rc, out = _run([sys.executable,
                        str(ROOT / "scripts/state/attestation/check_agent_log.py"),
                        path, _declared_sources()])
    finally:
        os.unlink(path)
    if rc == 1 and ("naive" in out or "undeclared" in out or "not present" in out
                    or "missing" in out or "✗" in out):
        return "PASS", f"forged log rejected (rc={rc}): {out.strip().splitlines()[0][:120]}"
    return "FAIL", f"validator accepted or mis-signalled forged log (rc={rc}): {out[-200:]}"


def _check_r5() -> tuple[str, str]:
    rc, out = _run(["ssh", "n02", "python3 /usr/local/bin/monitor_reconcile.py --check"])
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={rc}"
    return ("PASS" if rc == 0 else "FAIL"), tail + f" (rc={rc})"


def _check_r6() -> tuple[str, str]:
    code = (
        "import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
        "from rsi_cycle import RSICycle; "
        "c = RSICycle(); r = c._maybe_run_feedback_loop(); print('drill-ok', r)"
        % (str(ROOT / "packages/framework"), str(ROOT / "system/kernel"))
    )
    rc, out = _run([sys.executable, "-c", code])
    return ("PASS" if rc == 0 and "drill-ok" in out else "FAIL"), \
        (out.strip().splitlines()[-1] if out else f"rc={rc}") + f" (rc={rc})"


def _check_r7() -> tuple[str, str]:
    rc, out = _run([sys.executable, str(ROOT / "scripts/vsl/validator/verify_boot_ontology.py")])
    return ("PASS" if rc == 0 else "FAIL"), (out.strip()[:200] or f"rc={rc}")


def _check_r8() -> tuple[str, str]:
    rc, out = _run([sys.executable,
                    str(ROOT / "packages/framework/vsf-state/vsf_state/tasks_validate.py"),
                    "--tasks-file", str(pathlib.Path.home() / "vOSlab" / "TASKS.vsm")])
    advisory = "missing/invalid status" in out
    if rc == 0:
        return ("PASS-WITH-1-ADVISORY" if advisory else "PASS"), \
            next((l for l in out.splitlines() if "⚠" in l or "✅" in l),
                 "ok")[:160] + f" (rc={rc})"
    return "FAIL", out[-300:]


def _check_r9() -> tuple[str, str]:
    rc, out = _run([sys.executable, str(ROOT / "scripts/state/monitoring/snapshot_runtime_state.py")])
    return ("PASS" if rc == 0 else "FAIL"), (out.strip().splitlines()[-1] if out else f"rc={rc}")


def _check_r10() -> tuple[str, str]:
    ok, detail = _mcp_call(
        ["python3", str(ROOT / ".opencode/mcp/socratic_mcp_with_bridge.py")],
        "socratic_canon_providers")
    if ok and '"truth": "TRUE"' in detail:
        return "PASS", f"canon_providers: {detail[:160]}"
    if ok and "providers" in detail:
        return "PASS", f"canon_providers (providers listed): {detail[:160]}"
    return "FAIL", detail[:200]


def _check_r11() -> tuple[str, str]:
    """R11 runs BOTH live instances: voslab (local canon) + infra (n02 ops
    over SSH). The infra arg is literal 'root@n02,/path' — comma-separated,
    never interpolated from an env (a prior session's empty $VFS_STATE_DB
    produced 'root@n02,' and looked like an infra gap; it was a bad cmd)."""
    state_canon = pathlib.Path.home() / "state-canon-mcp"
    journal = str(ROOT / "state/journal")
    instances = {
        "voslab": (f"{ROOT}/scripts/state/canon/voslab_instance.py:"
                   f"{ROOT}/current_focus.json"),
        "infra": (f"{state_canon}/instances/ssh_sqlite_ops.py:"
                  "root@n02,/var/lib/vsf-state/state.db"),
    }
    details = []
    for name, spec in instances.items():
        cmd = ["setsid", "-w", "bash", "-ic",
               f'exec python3 "{state_canon}/mcp_server.py" '
               f'--instance "{spec}" --journal "{journal}"']
        tool, args = ("state_reconcile", {}) if name == "voslab" else (
            "state_query", {"domain": "topology", "filter": {"id": 112}})
        ok, detail = _mcp_call(cmd, tool, args, timeout=40)
        details.append((name, ok, detail))
    down = [n for n, ok, _ in details if not ok]
    evidence = "; ".join(f"{n}: {(d or 'OK')[:80]}" for n, ok, d in details)
    if down:
        return "FAIL", f"instances down: {down} | {evidence}"
    return "PASS", f"both instances live | {evidence}"


CHECKS = [
    ("R1-gates", _check_r1, "packages/framework/run_gates.py"),
    ("R2-audit-guards", _check_r2, "epistemic.audit_guards(EpicStore(), run=False)"),
    ("R3-cycle-health", _check_r3, "scripts/vsl/tools/cycle_health.py"),
    ("R4-agent-log-pos", _check_r4,
     "check_agent_log.py logs/agent_plugin.jsonl <declared_sources>"),
    ("R4b-agent-log-sabotage", _check_r4b,
     "same validator against forged log (naive ts + undeclared source)"),
    ("R5-n02-monitor", _check_r5,
     "ssh n02 python3 /usr/local/bin/monitor_reconcile.py --check"),
    ("R6-feedback-drill", _check_r6,
     "fresh process: RSICycle() + _maybe_run_feedback_loop()"),
    ("R7-boot-manifest", _check_r7, "scripts/vsl/validator/verify_boot_ontology.py"),
    ("R8-tasks-validate", _check_r8,
     "vsf_state/tasks_validate.py --tasks-file ~/vsf/TASKS.vsm"),
    ("R9-snapshots", _check_r9, "scripts/state/monitoring/snapshot_runtime_state.py"),
    ("R10-mcp-canon-providers", _check_r10,
     "socratic-engine MCP live: socratic_canon_providers"),
    ("R11-mcp-reconcile", _check_r11,
     "state-canon MCP live: voslab state_reconcile + infra state_query (n02)"),
]


def run_battery() -> dict:
    checks = []
    for cid, fn, cmd in CHECKS:
        try:
            verdict, evidence = fn()
        except Exception as exc:  # noqa: BLE001 — one broken check must not kill the run
            verdict, evidence = "FAIL", f"{type(exc).__name__}: {exc}"
        checks.append({"id": cid, "cmd": cmd, "verdict": verdict,
                       "evidence": evidence})
        print(f"  {verdict:20s} {cid}", flush=True)
    passed = sum(1 for c in checks if c["verdict"].startswith("PASS"))
    now = dt.datetime.now(dt.timezone.utc)
    day = now.strftime("%Y-%m-%d")
    return {
        "ts": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "id": f"BATTERY-REAL-STATE-{day}",
        "purpose": "anti-pantomima: verificar el estado real del sistema con "
                   "ground truth independiente del layer que lo reporta "
                   "(single runner — CC-8.0 exit criterion)",
        "checks": checks,
        "not_verified": NOT_VERIFIED,
        "verdict": f"{passed}/{len(checks)} checks verdes con ground truth;"
                   f"{len(NOT_VERIFIED)} huecos declarados (no esconderlos = "
                   f"parte del exit)",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true",
                    help="run and print, do not write the report")
    ap.add_argument("--id", default=None,
                    help="override report id suffix (default: today UTC)")
    args = ap.parse_args()

    report = run_battery()
    if args.id:
        report["id"] = f"BATTERY-REAL-STATE-{args.id}"
    if args.dry:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    REPORTS.mkdir(parents=True, exist_ok=True)
    day = report["ts"][:10]
    out = REPORTS / f"real_state_battery_{day}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} — {report['verdict']}")
    failed = [c["id"] for c in report["checks"] if not c["verdict"].startswith("PASS")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
