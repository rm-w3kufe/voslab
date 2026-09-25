#!/usr/bin/env python3
"""infra_watch.py — drift check: live n02 files vs versioned overlays.

Single-source rule (S5 2026-09-24): every file under /usr/local/bin,
/opt/vsf-*, /root/vsf-scripts on n02 must have a versioned source in
infra/overlays/<lxc>/. This script compares live sha256 against
manifest.json and FAILS on drift, missing files, or unregistered files.

Usage: python3 scripts/ops/infra_watch.py [--json]
Requires: SSH tunnel to n02 (root@n02 via ProxyJump n01).
Exit 0 = in sync; 1 = drift detected or unreachable.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "infra" / "overlays" / "manifest.json"
SSH = ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", "root@n02"]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ssh_out(*args: str, timeout: int = 60) -> str | None:
    try:
        r = subprocess.run([*SSH, *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def check_lxc(lxc: str, spec: dict, findings: list) -> None:
    live = ssh_out(
        f"pct exec {lxc} -- md5sum {' '.join(spec['files'].keys())} "
        "2>&1")
    if live is None:
        findings.append({"lxc": lxc, "issue": "unreachable"})
        return
    seen = set()
    for line in live.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1].startswith("md5sum:"):
            continue
        digest, remote = parts[0], parts[1]
        seen.add(remote)
        want = spec["files"].get(remote)
        if want is None:
            findings.append({"lxc": lxc, "issue": "unregistered-live-file",
                             "file": remote})
        elif want["md5"] != digest:
            findings.append({"lxc": lxc, "issue": "drift", "file": remote,
                             "live": digest, "manifest": want["md5"]})
    for remote, want in spec["files"].items():
        if remote not in seen:
            findings.append({"lxc": lxc, "issue": "missing-live",
                             "file": remote})


def run() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    findings: list = []
    for lxc, spec in manifest["lxcs"].items():
        check_lxc(lxc, spec, findings)
    return {"ok": not findings, "findings": findings,
            "lxcs_checked": sorted(manifest["lxcs"])}


def main() -> int:
    try:
        r = run()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)[:200]}))
        return 1
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2))
    elif r["ok"]:
        print(f"infra-watch OK: {r['lxcs_checked']} in sync with overlays")
    else:
        print("infra-watch FAIL:")
        for f in r["findings"]:
            print("  ", f)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
