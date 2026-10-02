#!/usr/bin/env python3
"""Measure η₂ RAPL component: sample package energy + CPU attribution over N seconds."""

import time
import sys
import os

RAPL_PKG = "/sys/class/powercap/intel-rapl:0/energy_uj"
RAPL_CORE = "/sys/class/powercap/intel-rapl:0/intel-rapl:0:0/energy_uj"

def read_uj(path):
    with open(path) as f:
        return int(f.read().strip())

def read_host_cpu():
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu "):
                parts = line.strip().split()
                return int(parts[1]) + int(parts[3])
    return 0

def read_lxc_cpu(lxc_id):
    """Read user+system ticks from LXC."""
    r = os.popen(f"pct exec {lxc_id} -- cat /proc/stat 2>/dev/null | grep '^cpu '").read()
    if not r:
        return 0
    parts = r.strip().split()
    return int(parts[1]) + int(parts[3])

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 10

# Sample 1
pkg1 = read_uj(RAPL_PKG)
core1 = read_uj(RAPL_CORE)
h1 = read_host_cpu()
c101_1 = read_lxc_cpu(101)
c110_1 = read_lxc_cpu(110)

time.sleep(DURATION)

# Sample 2
pkg2 = read_uj(RAPL_PKG)
core2 = read_uj(RAPL_CORE)
h2 = read_host_cpu()
c101_2 = read_lxc_cpu(101)
c110_2 = read_lxc_cpu(110)

pkg_j = (pkg2 - pkg1) / 1e6
core_j = (core2 - core1) / 1e6
host_cpu_delta = h2 - h1
lxc101_delta = c101_2 - c101_1
lxc110_delta = c110_2 - c110_1

print(f"=== η₂ RAPL Measurement ({DURATION}s) ===")
print(f"Package energy: {pkg_j:.2f} J")
print(f"Core energy:    {core_j:.2f} J")
print(f"Package power:  {pkg_j/DURATION:.2f} W")
print(f"Core power:     {core_j/DURATION:.2f} W")
print()
print(f"Host CPU delta:    {host_cpu_delta} ticks ({host_cpu_delta/100:.1f} CPU-seconds)")
print(f"LXC 101 CPU delta: {lxc101_delta} ticks ({lxc101_delta/100:.1f} CPU-seconds)")
print(f"LXC 110 CPU delta: {lxc110_delta} ticks ({lxc110_delta/100:.1f} CPU-seconds)")
print()
# CPU time attribution
if host_cpu_delta > 0:
    share_101 = lxc101_delta / host_cpu_delta
    share_110 = lxc110_delta / host_cpu_delta
    attributed = pkg_j * (share_101 + share_110)
    print(f"LXC 101 CPU share: {share_101:.3%}")
    print(f"LXC 110 CPU share: {share_110:.3%}")
    print(f"Combined share:    {share_101 + share_110:.3%}")
    print(f"Attributed energy: {attributed:.2f} J (of {pkg_j:.2f}J pkg)")
    print()
    # η₂ uses decision bits per J
    # Decision bits from earlier: ~2,508,872 bits (411 param_change over 47.7d)
    # Hourly: 2,508,872 / (47.7*24) = ~2,191 bits/hour = ~0.608 bits/sec
    bits_per_hour = 2508872 / (47.7 * 24)
    joules_per_hour = attributed / DURATION * 3600
    eta2 = bits_per_hour / joules_per_hour if joules_per_hour > 0 else float("inf")
    print(f"Decision bits/hour (from AC-M4-REDO): {bits_per_hour:.1f}")
    print(f"Attributed J/hour (extrapolated): {joules_per_hour:.1f}")
    print(f"η₂ = {eta2:.6f} bits/J")
else:
    print("ERROR: host CPU delta is 0")
