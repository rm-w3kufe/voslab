#!/usr/bin/env python3
"""covenant_update.py — expedited covenant promotion procedure (S5 2026-10-02).

S5 directive: the covenant update procedure must be expeditious, with the
actions PROGRAMMATIC, driven from the covenant-update socratic tree
(.opencode/plugins/support/trees/covenant-update.tree.vsm via the
covenant-update.gap.json definition). The manual S5 block (root actions on
n01) is printed by `s5-plan` — never executed by this tool.

Composes the existing discipline, does NOT duplicate it:
  vos_kernel.covenant_hash.verify_registry     — offline local audit (anchor:
      recomputed from docs/governance/covenant.vsm, every witness on its own
      terms; see system/boot/covenant_hash_registry.vsm §design_note)
  scripts/state/shared/sync_covenant_hash.sh   — mutable-class writer for
      core/s5_policy.default.json (keeps its provenance refusals)
  scripts/state/attestation/verify_covenant_hash.py — independent audit
      (optional subprocess under --audit)

Phases:
  plan     [--json] [--beacon] [--remote]
      Read-only audit → state:
        DRIFT_LOCAL  local mutable witnesses stale (stage needed)
        STAGED       local consistent, remote witness stale (S5 actions needed)
        CONSISTENT   every checked witness agrees
        VERIFY_FAIL  verify ran and found divergence (verify only)
  stage    [--apply] [--version V] [--note N]
      Write the LOCAL mutable class: s5_policy (via sync_covenant_hash.sh),
      LICENSE:Covenant SHA-256 line, registry current→history promotion.
      Dry-run by default. All guards are count-first/write-last: any
      unexpected shape aborts BEFORE a single byte is written.
  s5-plan  [--hash H]
      Print the ordered promotion blocks: rmw3 distribution + S5 block on
      n01 (beacon) + rebuild/deploy + publish LAST + verify.
  verify   [--beacon] [--remote] [--audit]
      Full battery; rc=0 iff every checked witness agrees.

Deterministic, stdlib-only; network only under --beacon/--remote (R10).
Timestamps come from the clock — never hardcoded, never :00/T00 shapes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CANONICAL = REPO / "docs" / "governance" / "covenant.vsm"
POLICY = REPO / "core" / "s5_policy.default.json"
LICENSE_F = REPO / "LICENSE"
REGISTRY = REPO / "system" / "boot" / "covenant_hash_registry.vsm"
SYNC_SH = REPO / "scripts" / "state" / "shared" / "sync_covenant_hash.sh"

# Network endpoints (CF passes browser-like UA; Python-urllib gets 1010)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
BEACON_HEALTH = "https://vsf.u2738.org/beacon/health"
PUBLISHED_URL = "https://vsf.u2738.org/covenant.hash"

sys.path.insert(0, str(REPO / "packages" / "framework"))
from vos_kernel.covenant_hash import verify_registry  # noqa: E402


def now_utc() -> str:
    """Real UTC timestamp; seconds never forced to :00 (canon gate)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p: Path) -> str | None:
    try:
        import hashlib
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


# ─── plan ─────────────────────────────────────────────────────────────────────

def phase_plan(args: argparse.Namespace) -> int:
    report = verify_registry(vsf_root=REPO, voslab=REPO)
    local_ok = report.consistent
    state = "CONSISTENT" if local_ok else "DRIFT_LOCAL"

    out: dict = {
        "state": state,
        "hash": report.anchor,
        "anchor_source": report.anchor_source,
        "checks": [
            {"name": c.name, "cls": c.cls, "ok": c.ok, "observed": c.observed}
            for c in report.checks
        ],
        "notes": list(report.notes),
        "beacon": None,
        "published": None,
    }

    if args.beacon:
        b = _remote_sha_n01()
        out["beacon"] = b
        if local_ok and b.get("ok") and b.get("sha") != report.anchor:
            state = "STAGED"
        elif local_ok and b.get("ok") is False:
            state = "STAGED"
        out["state"] = state

    if args.remote:
        pub = _published_hash()
        out["published"] = pub
        if state == "CONSISTENT" and pub.get("ok") and pub.get("sha") != report.anchor:
            state = "STAGED"
        elif state == "CONSISTENT" and pub.get("ok") is False:
            state = "STAGED"
        out["state"] = state

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"  state   : {out['state']}")
        print(f"  anchor  : {(report.anchor or '?')[:16]}…  ({_rel(report.anchor_source)})")
        for c in report.checks:
            mark = "ok  " if c.ok else "FAIL"
            print(f"    [{mark}] {c.cls:9s} {c.name}  observed={c.observed}")
        if out["beacon"]:
            b = out["beacon"]
            print(f"    [{'ok  ' if b.get('ok') else 'FAIL'}] beacon n01  sha={(b.get('sha') or b.get('error'))}")
        if out["published"]:
            p = out["published"]
            print(f"    [{'ok  ' if p.get('ok') else 'FAIL'}] published    sha={(p.get('sha') or p.get('error'))}")
        for n in out["notes"]:
            print(f"    note: {n}")
    return 0


def _rel(p: str | None) -> str:
    if not p:
        return "?"
    try:
        return str(Path(p).resolve().relative_to(REPO))
    except ValueError:
        return p


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(REPO))
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def _remote_sha_n01() -> dict:
    """sha256 of the covenant installed on n01's beacon (via ssh)."""
    rc, out = _run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes",
         "-o", "ConnectTimeout=10", "n01",
         "sha256sum /opt/vsf-beacon/covenant.vsm"],
        timeout=20,
    )
    if rc != 0:
        return {"ok": False, "sha": None, "error": out[:200]}
    m = re.match(r"([0-9a-f]{64})", out)
    if not m:
        return {"ok": False, "sha": None, "error": f"unparseable: {out[:120]}"}
    return {"ok": True, "sha": m.group(1), "error": None}


def _published_hash() -> dict:
    rc, out = _run(
        ["curl", "-sS", "-A", UA, "--max-time", "15", PUBLISHED_URL],
        timeout=20,
    )
    if rc != 0:
        return {"ok": False, "sha": None, "error": out[:200]}
    m = re.search(r"([0-9a-f]{64})", out)
    if not m:
        return {"ok": False, "sha": None, "error": f"unparseable: {out[:120]}"}
    return {"ok": True, "sha": m.group(1), "error": None}


def _beacon_health() -> dict:
    rc, out = _run(
        ["curl", "-sS", "-A", UA, "--max-time", "15", BEACON_HEALTH],
        timeout=20,
    )
    if rc != 0:
        return {"ok": False, "error": out[:200]}
    try:
        data = json.loads(out)
        return {"ok": True, "health": data, "error": None}
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-json: {out[:120]}"}


# ─── stage ────────────────────────────────────────────────────────────────────

_LIC_RE = re.compile(r"^Covenant SHA-256: ([0-9a-f]{64})\s*$", re.M)
_CURRENT_RE = re.compile(r"(  current: \{\n)(.*?)(\n  \})", re.S)
_HISTORY_MARK = "\n  history: [\n"


def _read_current(text: str) -> tuple[str, str]:
    """Return (current_block, current_hash) or raise SystemExit (count-guard)."""
    m = _CURRENT_RE.search(text)
    if not m:
        sys.exit("  ✗ registry: no well-formed `current: { … }` block — aborting, nothing written")
    block = m.group(2)
    hm = re.search(r'hash:\s+"([0-9a-f]{64})"', block)
    if not hm:
        sys.exit("  ✗ registry: current block has no 64-hex hash — aborting, nothing written")
    return block, hm.group(1)


def phase_stage(args: argparse.Namespace) -> int:
    if not CANONICAL.is_file():
        sys.exit(f"  ✗ canonical covenant missing: {CANONICAL}")
    anchor = sha256_file(CANONICAL)
    assert anchor

    # ---- gather every mutation first (count-first / write-last) ------------
    plan_lines: list[str] = []
    writes: list[tuple[Path, str]] = []  # (path, new_content)

    # 1. s5_policy — via the existing sync script (dry-run first for report)
    rc, sync_out = _run(["bash", str(SYNC_SH)], timeout=30)
    if rc != 0 and "canonical covenant not found" in sync_out:
        sys.exit(f"  ✗ sync_covenant_hash.sh failed:\n{sync_out}")
    policy_stale = "nothing to do" not in sync_out
    plan_lines.append(
        "core/s5_policy.default.json _meta.covenant_hash"
        + ("  → will update (via sync_covenant_hash.sh --apply)" if policy_stale
           else "  → already current")
    )

    # 2. LICENSE line
    lic_text = LICENSE_F.read_text(encoding="utf-8") if LICENSE_F.is_file() else ""
    lm = _LIC_RE.search(lic_text)
    if lm is None:
        sys.exit("  ✗ LICENSE: no `Covenant SHA-256: <64hex>` line — aborting, nothing written")
    lic_old = lm.group(1)
    if lic_old == anchor:
        plan_lines.append("LICENSE:Covenant SHA-256  → already current")
    else:
        new_line = f"Covenant SHA-256: {anchor}"
        if lic_text.count(lm.group(0)) != 1:
            sys.exit("  ✗ LICENSE: hash line not unique — aborting, nothing written")
        writes.append((LICENSE_F, lic_text.replace(lm.group(0), new_line)))
        plan_lines.append(f"LICENSE:Covenant SHA-256  → {lic_old[:16]}… → {anchor[:16]}…")

    # 3. registry current → history promotion
    reg_text = REGISTRY.read_text(encoding="utf-8") if REGISTRY.is_file() else ""
    if not reg_text:
        sys.exit(f"  ✗ registry missing/unreadable: {REGISTRY}")
    cur_block, cur_hash = _read_current(reg_text)
    if _HISTORY_MARK not in reg_text:
        sys.exit("  ✗ registry: `history: [` marker not found — aborting, nothing written")

    registry_dirty = cur_hash != anchor
    if registry_dirty:
        ts = now_utc()
        note = args.note or "expedited promotion (covenant_update.py stage)"
        vm = re.search(r'version:\s+"([^"]+)"', cur_block)
        old_version = vm.group(1) if vm else "1.2"
        new_version = args.version or old_version
        vsm_marker_m = re.search(r"@vsm [0-9.]+", CANONICAL.read_text(encoding="utf-8"))
        vsm_marker = vsm_marker_m.group(0) if vsm_marker_m else "@vsm 1.2.1"
        if vsm_marker == "@vsm 1.2" or not vsm_marker.startswith("@vsm 1.2.1"):
            sys.exit(f"  ✗ covenant vsl marker {vsm_marker} is not @vsm 1.2.1 — aborting")

        history_entry = (
            "    {\n"
            f'      version:   "{old_version}",\n'
            f'      hash:      "{cur_hash}",\n'
            f'      superseded: "{ts} — {note}",\n'
            f'      changes:   "{note}",\n'
            "    },\n"
        )
        new_current = (
            "  current: {\n"
            f'    hash:      "{anchor}",\n'
            '    covenant:  "docs/governance/covenant.vsm",\n'
            f'    version:   "{new_version}",\n'
            f'    vsl_marker: "{vsm_marker}",\n'
            f'    promoted:  "{ts} — expedited promotion (covenant_update.py stage)",\n'
            "  }"
        )
        reg_new = _CURRENT_RE.sub(
            lambda m: new_current,
            reg_text.replace(_HISTORY_MARK, _HISTORY_MARK + history_entry, 1),
            count=1,
        )
        if reg_new == reg_text:
            sys.exit("  ✗ registry: promotion produced no change — aborting, nothing written")
        writes.append((REGISTRY, reg_new))
        plan_lines.append(
            f"registry current {cur_hash[:16]}… → history; current={anchor[:16]}… (version {old_version}→{new_version})"
        )
    else:
        plan_lines.append("registry.current.hash  → already current")

    # ---- report (dry-run default) -----------------------------------------
    print("  covenant_update stage — LOCAL mutable class")
    print(f"  anchor: {anchor}")
    for line in plan_lines:
        print(f"    {line}")
    print("  NOT touched (order/ownership):")
    print("    n01 /opt/vsf-beacon/covenant.vsm   (S5 block, s5-plan)")
    print("    101 /etc/vsf/covenant.vsm + binary rebuild (s5-plan)")
    print("    published vsf.u2738.org/covenant.hash — LAST, by hand (P7)")

    if not args.apply:
        print("\n  DRY RUN — nothing written. Re-run with --apply.")
        return 0

    # ---- apply -------------------------------------------------------------
    ts = now_utc().replace(":", "").replace("-", "")
    if policy_stale:
        rc, out = _run(["bash", str(SYNC_SH), "--apply"], timeout=30)
        if rc != 0:
            print(out)
            sys.exit("  ✗ sync_covenant_hash.sh --apply failed — policy NOT updated")
        print(f"  ✓ s5_policy updated")
    for path, content in writes:
        bak = path.with_name(path.name + f".bak.{ts}")
        shutil.copy2(path, bak)
        path.write_text(content, encoding="utf-8")
        print(f"  ✓ {path.relative_to(REPO)} updated (backup: {bak.name})")

    # ---- post-write validation (the registry must still parse) ------------
    if registry_dirty:
        rc, out = _run([sys.executable, str(REPO / "scripts" / "vsl" / "validator" / "check.py"),
                        str(REGISTRY)], timeout=30)
        if rc != 0:
            print(out)
            sys.exit("  ✗ registry failed vsm validation after write — RESTORE the .bak and investigate")
        print(f"  ✓ registry validates (vsm check)")

    print("\n  Next: `covenant_update.py s5-plan` — ordered blocks (incl. S5 on n01),")
    print("        then `covenant_update.py verify --beacon --remote`.")
    return 0


# ─── s5-plan ──────────────────────────────────────────────────────────────────

def phase_s5_plan(args: argparse.Namespace) -> int:
    anchor = args.hash or sha256_file(CANONICAL)
    if not anchor:
        sys.exit("  ✗ canonical covenant missing — cannot build s5-plan")
    ts = now_utc()
    ts_compact = re.sub(r"[:\-]", "", ts)
    print(f"""\
══════ covenant_update s5-plan — hash {anchor} — generated {ts} ══════

── Step 1/6 · rmw3 (local): stage the mutable class ──────────────────────
  python3 scripts/s5-governance/covenant_update.py stage --apply

── Step 2/6 · rmw3: distribute the covenant bytes (receipts by sha256) ────
  scp docs/governance/covenant.vsm n01:/tmp/covenant.vsm
  ssh n01 'sha256sum /tmp/covenant.vsm'          # MUST print {anchor}
  scp docs/governance/covenant.vsm n02:/tmp/covenant.vsm
  ssh n02 'pct push 101 /tmp/covenant.vsm /etc/vsf/covenant.vsm'

── Step 3/6 · S5 on n01 (root session): install + restart beacon ─────────
  sha256sum /tmp/covenant.vsm                    # MUST print {anchor} first
  cp /opt/vsf-beacon/covenant.vsm /opt/vsf-beacon/covenant.vsm.bak.{ts_compact}
  cp /tmp/covenant.vsm /opt/vsf-beacon/covenant.vsm
  chown vsf:vsf /opt/vsf-beacon/covenant.vsm && chmod 644 /opt/vsf-beacon/covenant.vsm
  systemctl restart vsf-beacon && sleep 3
  curl -s localhost:8080/health                  # beacon up

── Step 4/6 · rmw3: rebuild nucleus (COVENANT_SHA256 re-derived) + deploy ─
  bash scripts/deploy/deploy_bundle.sh           # build on LXC 108 → push
  ssh n02 'pct exec 101 -- systemctl restart vsf-nucleus-operational'

── Step 5/6 · publish LAST (by hand — fail-closed window closes here) ─────
  echo -n {anchor} > /tmp/covenant.hash
  # upload to the canonical site → https://vsf.u2738.org/covenant.hash
  # (until this lands, every node still fails closed against the OLD
  #  covenant — that is the safe direction; publishing first is not.)

── Step 6/6 · verify (rc=0 iff every witness agrees) ──────────────────────
  python3 scripts/s5-governance/covenant_update.py verify --beacon --remote

══════ end s5-plan ══════""")
    return 0


# ─── verify ──────────────────────────────────────────────────────────────────

def phase_verify(args: argparse.Namespace) -> int:
    report = verify_registry(vsf_root=REPO, voslab=REPO)
    anchor = report.anchor
    failures: list[str] = []

    flag = "CONSISTENT" if report.consistent else "INCONSISTENT"
    print(f"  {flag}  anchor={(anchor or '?')[:16]}…")
    for c in report.checks:
        mark = "ok  " if c.ok else "FAIL"
        print(f"    [{mark}] {c.cls:9s} {c.name}  observed={c.observed}")
        if not c.ok:
            failures.append(c.name)

    if args.beacon:
        b = _remote_sha_n01()
        ok = bool(b.get("ok")) and b.get("sha") == anchor
        print(f"    [{'ok  ' if ok else 'FAIL'}] beacon n01 covenant sha  {b.get('sha') or b.get('error')}")
        if not ok:
            failures.append("beacon.n01.covenant")
        h = _beacon_health()
        h_ok = bool(h.get("ok"))
        if h_ok:
            health = h.get("health") or {}
            print(f"    [ok  ] beacon health  {json.dumps(health, sort_keys=True)[:160]}")
        else:
            print(f"    [FAIL] beacon health  {h.get('error')}")
            failures.append("beacon.health")

    if args.remote:
        p = _published_hash()
        ok = bool(p.get("ok")) and p.get("sha") == anchor
        print(f"    [{'ok  ' if ok else 'FAIL'}] published covenant.hash  {p.get('sha') or p.get('error')}")
        if not ok:
            failures.append("published.covenant_hash")

    if args.audit:
        audit = REPO / "scripts" / "state" / "attestation" / "verify_covenant_hash.py"
        env = dict(os.environ, VSF_ROOT=str(REPO))
        try:
            r = subprocess.run([sys.executable, str(audit)], capture_output=True,
                               text=True, timeout=60, env=env, cwd=str(REPO))
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
            print(tail)
            if r.returncode != 0:
                failures.append("verify_covenant_hash.audit")
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"    [FAIL] independent audit  {exc}")
            failures.append("verify_covenant_hash.audit")

    for n in report.notes:
        print(f"    note: {n}")

    if failures:
        print(f"\n  VERIFY_FAIL: {', '.join(failures)}")
        return 1
    print("\n  ✓ verify: every checked witness agrees.")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="covenant_update", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="read-only audit → state")
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--beacon", action="store_true", help="include n01 beacon witness")
    p_plan.add_argument("--remote", action="store_true", help="include published witness")

    p_stage = sub.add_parser("stage", help="update LOCAL mutable class (dry-run default)")
    p_stage.add_argument("--apply", action="store_true")
    p_stage.add_argument("--version", default=None, help="covenant version for registry.current")
    p_stage.add_argument("--note", default=None, help="promotion note (registry history)")

    p_s5 = sub.add_parser("s5-plan", help="print ordered promotion blocks (incl. S5 on n01)")
    p_s5.add_argument("--hash", default=None)

    p_ver = sub.add_parser("verify", help="full battery; rc=0 iff witnesses agree")
    p_ver.add_argument("--beacon", action="store_true")
    p_ver.add_argument("--remote", action="store_true")
    p_ver.add_argument("--audit", action="store_true",
                       help="+ scripts/state/attestation/verify_covenant_hash.py")

    args = ap.parse_args(argv)
    return {"plan": phase_plan, "stage": phase_stage,
            "s5-plan": phase_s5_plan, "verify": phase_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
