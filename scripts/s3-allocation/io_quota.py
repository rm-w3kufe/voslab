#!/usr/bin/env python3
# design: system/s3-control/thermal-gov-01/amendment_2026-08-02.vsm thread_4
#         (RATIFIED design — io.max per-unit quotas; registry row
#          docs/spec/system_certification/parameter_registry.vsm cgroup)
"""io_quota.py — thread_4 iomax allotment tool (S3 resource boundary).

ROUTE: scripts route via scripts_manifest.vsm (registered regen
2026-10-23); backbone route: manual operator — driver = vos-kernel
session over SSH; entry point: `python3 scripts/s3-allocation/io_quota.py`
(no service registration; bounded, stateless, R17-gated apply commands).
self-gate: scripts/tests test_dyn_llm_grant_p1 pattern (has_gate) n/a —
no gate dependency; verification = cmd_verify runtime probes on n02.

Warm; entity side = host cgroup v2 fs. This tool is the KERNEL-side
record of the allotments + the apply/rollback/verify commands the
operator (vos-kernel over SSH, root n02) must execute. It is NOT a
remote executor — R17: writes to live cgroups happen only via explicit
SSH commands after rmw3 go (first allotment DONE 2026-10-23 clima).

LIVE FACT (verified 2026-10-23):
  LXC 112 (s1-clima) io.max 252:0 wbps=8388608 wiops=1024 enforced,
  dd 24MB direct took 3.04s (=8.3MB/s, cap binding). Persisted in
  /etc/pve/lxc/112.conf -> lxc.cgroup2.io.max (applies on restart).

Footgun (from amendment, must-know before any apply):
  io.weight is a NO-OP unless BFQ scheduler active. io.max DOES work
  regardless of scheduler (verified live). Use io.max only.
  Rootfs device naming: LXC rootfs writes surface as dm (252:x) per
  cgroup io.stat — probe io.stat FIRST, never assume sda.

Usage:
  python3 io_quota.py list                 # allotment table (this file)
  python3 io_quota.py cmd 112              # emit SSH commands for a CT
  python3 io_quota.py verify 112           # exact audit sequence
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allotments — per-thread_4 (RATIFIED): one unit may not unbound-take the
# shared write surface. 8MiB/s ≈ 300x clima's historical sustained write
# (~24KB/s) while bounding the pathological burst that starved LXC 117
# (2026-08-02, 38x volume incident). Rollback ALL: echo max/max.
ALLOTS = {
    #  ct: (device, wbps, wiops, rationale)
    112: ("252:0", 8_388_608, 1024, "clima heavy log-writer — first allotment LANDED 2026-10-23"),
    # próximos (REQUIEREN ventana S5 — son LXCs en PRODUCCION activa):
    110: ("8:0",   8_388_608, 1024, "oolama — pending S5 window (live runner)"),
    117: ("252:0", 8_388_608, 1024, "SOC work holder — pending S5 window (live runner)"),
}

CGROUP_TPL = "/sys/fs/cgroup/lxc/{ct}/io.max"
CONF_TPL = "/etc/pve/lxc/{ct}.conf"


def cmd_apply(ct: int) -> list[str]:
    dev, wbps, wiops, _ = ALLOTS[ct]
    return [
        f"ssh n02 'echo {dev} wbps={wbps} wiops={wiops} > {CGROUP_TPL.format(ct=ct)}",
        f"ssh n02 'echo lxc.cgroup2.io.max: {dev} wbps={wbps} wiops={wiops} "
        f">> {CONF_TPL.format(ct=ct)}",
        f"ssh n02 'cat {CGROUP_TPL.format(ct=ct)}'",
    ]


def cmd_rollback(ct: int) -> list[str]:
    dev, _, _, _ = ALLOTS[ct]
    return [
        f"ssh n02 'echo {dev} wbps=max wiops=max > {CGROUP_TPL.format(ct=ct)}'",
        f"ssh n02 'sed -i /lxc.cgroup2.io.max/d {CONF_TPL.format(ct=ct)}'",
    ]


def cmd_verify(ct: int) -> list[str]:
    dev, wbps, wiops, _ = ALLOTS[ct]
    return [
        f"ssh n02 \"grep -q wbps={wbps} {CGROUP_TPL.format(ct=ct)} && echo ENFORCED\"",
        f"ssh n02 \"grep -q lxc.cgroup2.io.max {CONF_TPL.format(ct=ct)} && echo PERSISTED\"",
        # proof-of-binding: direct DD inside the CT should take ~24s for
        # 192MB at 8MiB/s cap (takes ~1s unlimited) — then clean up.
        f"ssh n02 \"pct exec {ct} -- dd if=/dev/zero of=/root/q bs=1M "
        f"count=192 oflag=direct 2>&1 | tail -1; "
        f"pct exec {ct} -- rm -f /root/q\"",
    ]


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "list"
    if what == "list":
        for ct, (dev, wbps, wiops, why) in ALLOTS.items():
            print(f"  LXC {ct}: io.max {dev} wbps={wbps} wiops={wiops}  # {why}")
        return 0
    if what in ("cmd", "verify", "rollback"):
        ct = int(sys.argv[2])
        if ct not in ALLOTS:
            print(f"no allotment for LXC {ct}; edit ALLOTS first", file=sys.stderr)
            return 2
        fn = {"cmd": cmd_apply, "verify": cmd_verify, "rollback": cmd_rollback}[what]
        for line in fn(ct):
            print(line)
        return 0
    print("usage: io_quota.py [list|cmd|verify|rollback] [ct]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
