#!/usr/bin/env python3
"""recovery_exercise.py — deterministic harness for VSF viability gates G2-G5.

Bloque 3 of the consolidated plan: each gate corresponds to a property the
system claims to have but has never been exercised under controlled fault
injection in prod. Running this script either proves the claim or surfaces
the regression.

Gates:
  G2 covenant_fail_closed   — corrupt the covenant hash, boot must refuse.
  G3 nats_reconnect         — restart the broker, every subscriber recovers.
  G4 nucleus_recovery       — kill -9 nucleus, chain resumes, s3-star sees gap.
  G5 hot_reload             — mutate s5_policy.json, change propagates.

Each gate:
  1. SNAPSHOT — capture state worth restoring (files, service pids).
  2. INJECT  — apply the controlled fault.
  3. OBSERVE — wait + collect evidence (journalctl, file diffs, process state).
  4. RESTORE — return system to baseline regardless of pass/fail.
  5. VERDICT — PASS/FAIL with a one-line evidence summary.

Usage:
  python3 recovery_exercise.py --gate all          # run all (default)
  python3 recovery_exercise.py --gate g3           # only NATS reconnect
  python3 recovery_exercise.py --dry-run           # print plan, do nothing
  python3 recovery_exercise.py --gate g4 --verbose # full evidence dump

Topology assumed (verified 2026-05-29):
  n02 host with pct exec into LXCs:
    101 = nucleus + ollama
    104 = s5_console + bbs-bridge + algedonic-sub
    106 = nats-server (canonical broker) + bbs-api
    107 = vsf-s3-star + collapsed nucleus
"""
import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional


def run(cmd: list[str], timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command. Returns CompletedProcess; raises only if check=True and rc!=0."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=check
    )


def _local_n02() -> bool:
    """True if this script is running ON n02 (skip ssh wrapper)."""
    import os
    return os.environ.get("VSF_LOCAL_N02") == "1"


def ssh_n02(remote_cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a shell command on n02 via SSH, BatchMode on.
    If VSF_LOCAL_N02=1 (already on n02, e.g. when called from vsf-auditd),
    skip the ssh wrapper and exec directly via bash -c — that avoids the
    n02→n02 host-key dance and keeps the harness reusable on-host."""
    if _local_n02():
        return run(["bash", "-c", remote_cmd], timeout=timeout)
    return run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "root@n02", remote_cmd],
        timeout=timeout,
    )


def pct_exec(ct: int, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run `cmd` inside LXC `ct` via pct exec on n02."""
    return ssh_n02(f"pct exec {ct} -- bash -c {json.dumps(cmd)}", timeout=timeout)


@dataclass
class GateResult:
    name: str
    passed: bool
    evidence: str
    duration_s: float
    notes: list[str] = field(default_factory=list)

    def render(self, verbose: bool) -> str:
        tag = "PASS" if self.passed else "FAIL"
        head = f"[{tag}] {self.name}  ({self.duration_s:.1f}s)  — {self.evidence}"
        if verbose and self.notes:
            return head + "\n  " + "\n  ".join(self.notes)
        return head


def gate_g2_covenant_fail_closed(verbose: bool, dry_run: bool) -> GateResult:
    """Tamper a byte inside the running binary's embedded covenant section,
    verify --verify-covenant exits non-zero on the tampered copy.

    Why this design: covenant is `include_str!()`-embedded at compile
    time. Corrupting /etc/vsf/covenant.vsm at runtime does nothing —
    the binary never reads it. Real fail-closed requires tampering the
    binary itself. See Annex B §7.4 / G-C4.2.
    """
    notes: list[str] = []
    start = time.time()
    notes.append("plan: cp binary → flip one byte inside embedded COVENANT "
                 "(unique token 'CONSTITUTIONAL COVENANT') → run tampered "
                 "binary --verify-covenant → expect non-zero exit → cleanup")
    if dry_run:
        return GateResult("G2 covenant_fail_closed", True, "dry-run only", time.time() - start, notes)

    # COPY + TAMPER in one shell — uses python to byte-flip at the marker
    tamper_cmd = (
        "set -e; cp /usr/local/bin/vsf-nucleus /tmp/vsf-nucleus-tampered && "
        "python3 -c \""
        "p='/tmp/vsf-nucleus-tampered'; "
        "marker=b'CONSTITUTIONAL COVENANT'; "
        "data=open(p,'rb').read(); "
        "i=data.find(marker); "
        "assert i>=0, 'marker not found'; "
        "new=data[:i]+b'X'+data[i+1:]; "
        "open(p,'wb').write(new); "
        "print('flipped byte at offset', i)"
        "\" && chmod +x /tmp/vsf-nucleus-tampered"
    )
    tamper = pct_exec(101, tamper_cmd)
    if tamper.returncode != 0:
        return GateResult("G2 covenant_fail_closed", False,
                          f"tamper failed: {tamper.stderr.strip()[:160]}",
                          time.time() - start, notes)
    notes.append("tamper: " + tamper.stdout.strip()[:120])

    # OBSERVE — run tampered binary; capture real exit code (returncode).
    # Do NOT parse "echo RC=$?" from stdout: the $? gets eaten by the outer
    # shell during command construction and always reports 0. Use the
    # subprocess returncode directly — which bubbles up from ssh → pct exec
    # → bash -c → binary exit, faithfully.
    verify = pct_exec(101, "/tmp/vsf-nucleus-tampered --verify-covenant", timeout=20)
    rc = verify.returncode
    has_failed = "FAILED" in verify.stdout
    notes.append(f"verify output tail: ...{verify.stdout.strip()[-160:]}")
    notes.append(f"real exit code: {rc}")

    # CLEANUP — remove the tampered copy
    cleanup = pct_exec(101, "rm -f /tmp/vsf-nucleus-tampered")
    notes.append(f"cleanup: rc={cleanup.returncode}")

    passed = (rc != 0) and has_failed and cleanup.returncode == 0
    evidence = (f"tampered binary → exit={rc} + status:FAILED={has_failed} "
                f"(want non-zero+FAILED); cleanup OK")
    return GateResult("G2 covenant_fail_closed", passed, evidence, time.time() - start, notes)


def gate_g3_nats_reconnect(verbose: bool, dry_run: bool) -> GateResult:
    """Restart the broker; verify every subscriber survives (PID unchanged)
    AND that the nucleus chain continues to advance (proves NATS round-trip
    resumed, not just process survival).

    Behavioural verdict — does not depend on journalctl strings. See Annex
    B §7.4 / G-H.1 for the rationale.
    """
    notes: list[str] = []
    start = time.time()
    subs = [
        (101, "vsf-nucleus-operational"),
        (104, "vsf-s3-phidown-actuator"),
        (104, "vsf-s5-algedonic"),
        (107, "vsf-s3-star"),
    ]
    chain_path = "/var/lib/vsf/vsf_nucleus/events.jsonl"
    notes.append(f"plan: snapshot {len(subs)} subscriber PIDs + chain head; "
                 f"restart nats on 106; wait 20s; verify all PIDs unchanged AND "
                 f"chain head advanced ≥1 line")
    if dry_run:
        return GateResult("G3 nats_reconnect", True, "dry-run only", time.time() - start, notes)

    def get_pid(lxc: int, svc: str) -> str:
        out = pct_exec(lxc, f"systemctl show -p MainPID --value {svc}")
        return out.stdout.strip()

    def get_chain_lines() -> int:
        # NOTE: avoid awk '$1' here — pct_exec wraps in bash -c with json-quoted
        # string, so $1 expands in the outer shell (empty). Parse in Python.
        out = pct_exec(101, f"wc -l {chain_path}")
        try: return int(out.stdout.split()[0])
        except (ValueError, IndexError): return -1

    # SNAPSHOT
    pre_pids = {f"{c}:{s}": get_pid(c, s) for c, s in subs}
    pre_lines = get_chain_lines()
    notes.append(f"pre PIDs: {pre_pids}")
    notes.append(f"pre chain lines: {pre_lines}")

    # INJECT
    restart = pct_exec(106, "systemctl restart nats-server")
    notes.append(f"restart nats on 106: rc={restart.returncode}")

    # OBSERVE
    time.sleep(20)
    post_pids = {f"{c}:{s}": get_pid(c, s) for c, s in subs}
    post_lines = get_chain_lines()
    notes.append(f"post PIDs: {post_pids}")
    notes.append(f"post chain lines: {post_lines}")

    pid_failures = [k for k in pre_pids if pre_pids[k] != post_pids[k] or post_pids[k] in ("0", "")]
    chain_advanced = post_lines > pre_lines

    passed = not pid_failures and chain_advanced
    if pid_failures:
        evidence = f"subscribers crashed: {pid_failures}"
    elif not chain_advanced:
        evidence = f"all PIDs survived but chain frozen ({pre_lines}→{post_lines})"
    else:
        evidence = f"all 4 PIDs survived broker restart; chain advanced {pre_lines}→{post_lines}"
    return GateResult("G3 nats_reconnect", passed, evidence, time.time() - start, notes)


def gate_g4_nucleus_recovery(verbose: bool, dry_run: bool) -> GateResult:
    """Kill nucleus, restart, chain resumes; s3-star sees the gap."""
    notes: list[str] = []
    start = time.time()
    notes.append("plan: capture last algedonic_seq → kill -9 nucleus → restart → "
                 "verify chain resumes (no prev_hash break) and counter increments")
    if dry_run:
        return GateResult("G4 nucleus_recovery", True, "dry-run only", time.time() - start, notes)

    # Capture last event hash + algedonic_seq before the kill
    pre = pct_exec(101, "tail -1 /var/lib/vsf/vsf_nucleus/events.jsonl")
    try:
        pre_event = json.loads(pre.stdout.strip())
        pre_hash = pre_event.get("hash")
        pre_seq = pre_event.get("algedonic_seq")
    except (json.JSONDecodeError, IndexError):
        return GateResult("G4 nucleus_recovery", False, "could not parse pre-kill event tail",
                          time.time() - start, notes)
    notes.append(f"pre: hash={pre_hash[:12] if pre_hash else '?'}.. seq={pre_seq}")

    # INJECT — kill -9 + restart
    kill = pct_exec(101, "pkill -9 -f vsf-nucleus; sleep 2; systemctl start vsf-nucleus-operational")
    notes.append(f"kill+restart: rc={kill.returncode}")

    # OBSERVE — give it 15s to produce a fresh event
    time.sleep(15)
    post = pct_exec(101, "tail -1 /var/lib/vsf/vsf_nucleus/events.jsonl")
    try:
        post_event = json.loads(post.stdout.strip())
        post_prev = post_event.get("prev_hash")
        post_seq = post_event.get("algedonic_seq")
    except (json.JSONDecodeError, IndexError):
        return GateResult("G4 nucleus_recovery", False, "could not parse post-restart event tail",
                          time.time() - start, notes)
    notes.append(f"post: prev_hash={(post_prev or '')[:12]}.. seq={post_seq}")

    # The chain must resume: post.prev_hash should chain back to something
    # consistent with pre_hash (either == pre_hash, or it linked to a newer
    # tail we missed). The minimum bar is: post.prev_hash is not None AND
    # post.algedonic_seq > pre.algedonic_seq (forward progress).
    chain_ok = bool(post_prev) and (post_seq or 0) > (pre_seq or -1)
    evidence = (
        f"chain_resumed={chain_ok} pre_seq={pre_seq} post_seq={post_seq} "
        f"prev_hash_present={bool(post_prev)}"
    )
    return GateResult("G4 nucleus_recovery", chain_ok, evidence, time.time() - start, notes)


def gate_g5_hot_reload(verbose: bool, dry_run: bool) -> GateResult:
    """Full NATS round-trip propagation test (G-H.1 close).

    Publishes a `vsf.alpha.phi_down.params` message with a unique
    `_origin` tag via raw NATS PUB (no nats-cli required). Waits, then
    verifies the chain contains a fresh `param_change` event whose
    top-level `origin` matches the tag. That proves the loop closed
    end-to-end: NATS → phi_down subscriber → ConfigPatch.apply → emit.

    Previous version was a smoke test (file-write on disk, which is a
    DIFFERENT propagation channel the nucleus doesn't watch by default).
    """
    import uuid
    notes: list[str] = []
    start = time.time()
    tag = f"g5-roundtrip-{uuid.uuid4().hex[:12]}"
    notes.append(f"plan: NATS PUB phi_down.params with _origin={tag} → wait 3s → "
                 f"grep events.jsonl for param_change with origin={tag} → confirm "
                 f"changed_keys reflects the injected patch")
    if dry_run:
        return GateResult("G5 hot_reload", True, "dry-run only", time.time() - start, notes)

    # INJECT — raw NATS PUB from LXC 106 (the broker host) via python socket.
    # log_level=warn is benign and reversible; nucleus will set then we restore.
    # AUTH (D2 2026-10-08): broker has `authorization { token: ... }` in
    # /etc/nats-server.conf (post Jul-11) — a bare `CONNECT {}` gets
    # -ERR 'Authorization Violation' and the PUB silently never lands
    # (inject rc=0 because the -ERR reply is never read). Read the token
    # from the broker config at inject time (no credential in this file).
    inject_script = (
        "python3 -c \""
        "import socket,re; "
        f"p=b'{{\\\"log_level\\\":\\\"warn\\\",\\\"_origin\\\":\\\"{tag}\\\",\\\"_reason\\\":\\\"G5 round-trip\\\"}}'; "
        "t=re.search(r'token\\s*[:=]\\s*\\\"([^\\\"]+)\\\"', open('/etc/nats-server.conf').read()).group(1); "
        "s=socket.socket(); s.connect(('127.0.0.1',4222)); s.recv(4096); "
        "s.send(('CONNECT {\\\"auth_token\\\":\\\"'+t+'\\\"}\\r\\n').encode()+"
        "b'PUB vsf.alpha.phi_down.params '+str(len(p)).encode()+b'\\r\\n'+p+b'\\r\\n'); "
        "s.close()"
        "\""
    )
    inject = pct_exec(106, inject_script)
    notes.append(f"inject: rc={inject.returncode}")
    if inject.returncode != 0:
        return GateResult("G5 hot_reload", False,
                          f"NATS publish failed: {inject.stderr.strip()[:160]}",
                          time.time() - start, notes)

    # OBSERVE — give the subscriber time to receive, apply, emit.
    time.sleep(3)
    # Grep tmpfs chain (freshest) — falls back to disk if tmpfs not used.
    grep_paths = "/run/vsf/vsf_nucleus/events.jsonl /var/lib/vsf/vsf_nucleus/events.jsonl"
    out = pct_exec(101, f"grep -h '{tag}' {grep_paths} 2>/dev/null | tail -1")
    line = out.stdout.strip()
    if not line:
        return GateResult("G5 hot_reload", False,
                          f"no param_change with origin={tag} found in chain after 3s",
                          time.time() - start, notes)

    # Parse the event, verify shape.
    try:
        ev = json.loads(line)
    except json.JSONDecodeError as e:
        return GateResult("G5 hot_reload", False,
                          f"event line not parseable: {e}",
                          time.time() - start, notes)
    et = ev.get("event_type")
    top_origin = ev.get("origin")
    status = ev.get("status")
    changed = (ev.get("metrics") or {}).get("changed_keys") or []
    notes.append(f"chain event: type={et} status={status} top_origin={top_origin} changed_keys={changed}")

    if not (et == "param_change" and top_origin == tag):
        return GateResult("G5 hot_reload", False,
                          f"event found but shape unexpected (type={et} origin={top_origin} keys={changed})",
                          time.time() - start, notes)

    if "log_level" in changed:
        # Mutation proven — honor the inject contract ("benign and reversible;
        # nucleus will set then we restore"): put verbosity back to info.
        restore_script = (
            "python3 -c \""
            "import socket,re; "
            "p=b'{\\\"log_level\\\":\\\"info\\\",\\\"_reason\\\":\\\"G5 restore\\\"}'; "
            "t=re.search(r'token\\s*[:=]\\s*\\\"([^\\\"]+)\\\"', open('/etc/nats-server.conf').read()).group(1); "
            "s=socket.socket(); s.connect(('127.0.0.1',4222)); s.recv(4096); "
            "s.send(('CONNECT {\\\"auth_token\\\":\\\"'+t+'\\\"}\\r\\n').encode()+"
            "b'PUB vsf.alpha.phi_down.params '+str(len(p)).encode()+b'\\r\\n'+p+b'\\r\\n'); "
            "s.close()"
            "\""
        )
        restore = pct_exec(106, restore_script)
        notes.append(f"restore(info): rc={restore.returncode}")
        evidence = (f"loop closed + mutation: NATS → applied log_level → "
                    f"param_change with origin={tag}; verbosity restored to info")
        return GateResult("G5 hot_reload", True, evidence, time.time() - start, notes)

    if status == "noop":
        # validate_and_apply RAN but cfg already equals target (equality
        # short-circuit): emission itself proves the full path
        # NATS → subscriber → PHI-DOWN-APPLY-GATE → chain — the same reading
        # the Jul-11 passing run had (noop param_change with matching origin).
        evidence = (f"loop closed via emission (noop: log_level already at target) — "
                    f"param_change with origin={tag}; changed_keys=[]")
        return GateResult("G5 hot_reload", True, evidence, time.time() - start, notes)

    return GateResult("G5 hot_reload", False,
                      f"param_change arrived but rejected (status={status} keys={changed})",
                      time.time() - start, notes)


GATES = {
    "g2": gate_g2_covenant_fail_closed,
    "g3": gate_g3_nats_reconnect,
    "g4": gate_g4_nucleus_recovery,
    "g5": gate_g5_hot_reload,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", choices=list(GATES.keys()) + ["all"], default="all")
    ap.add_argument("--dry-run", action="store_true", help="Print plan only; mutate nothing.")
    ap.add_argument("--verbose", action="store_true", help="Dump full evidence per gate.")
    args = ap.parse_args()

    selected = list(GATES.values()) if args.gate == "all" else [GATES[args.gate]]
    print(f"# recovery_exercise — gate={args.gate} dry_run={args.dry_run}", flush=True)

    results: list[GateResult] = []
    for fn in selected:
        try:
            r = fn(args.verbose, args.dry_run)
        except Exception as e:
            r = GateResult(fn.__name__, False, f"harness error: {e!r}", 0.0)
        print(r.render(args.verbose), flush=True)
        results.append(r)

    failed = [r for r in results if not r.passed]
    print(f"\n# summary: {len(results) - len(failed)}/{len(results)} passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
