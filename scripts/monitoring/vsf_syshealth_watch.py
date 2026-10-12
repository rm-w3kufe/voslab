#!/usr/bin/env python3
"""vsf_syshealth_watch.py — read-only host health consumers (G5-reading).
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Wires the EXISTING but unwatched telemetry the thread_5 matrix names as
captured-yet-blind: CPU throttle counters, PSI pressure, memory/swap/OOM,
disk saturation. Battery, disk-space/SMART and CPU-temp already have owners
(battery-watchdog, disk-trend-watch, thermal-watchdog) and are NOT repeated
here; network is negligible per the matrix; fan sensors do not exist.

Read-only by construction: sysfs + procfs reads only, one JSON state file
for deltas/hysteresis, algedonic push on findings. No cgroup writes, no
actuation — quotas (io.max etc.) are the separate S5-windowed G5 step.

Severity discipline: telemetry self-report stays ≤6, never near the 8.0
caution veto (an OOM kill reports 6 as a real failure signal; everything
else 5). First run baselines silently (cold start must not page).
Hysteresis 0.7: alert fires crossing up, clears below 70% of threshold —
no flapping spam; the ledger dedups repeats downstream anyway.

Runs on n02 host (needs /sys + /proc + pct-free reads only).
Schedule (systemd timer, every 5 min — matches watchdog cadence):
    ExecStart=/usr/local/bin/vsf_syshealth_watch.py
"""
import json
import os
import sys
from datetime import datetime, timezone

SYS_ROOT   = os.environ.get("VSF_SYS_ROOT", "/sys")
PROC_ROOT  = os.environ.get("VSF_PROC_ROOT", "/proc")
STATE_FILE = os.environ.get("VSF_SYSHEALTH_STATE",
                            "/var/lib/vsf-syshealth-watch/state.json")

CLEAR_FACTOR = 0.7

# (resource, side, window, threshold, category) — conservative defaults,
# documented tunable; thresholds are routing labels until S5 ratifies
# post-burn-in numbers (variety_note: qualitative, not measured).
PSI_RULES = [
    ("io",     "full", "avg60", 30.0, "io_pressure"),
    ("cpu",    "some", "avg60", 50.0, "cpu_pressure"),
    ("memory", "full", "avg60", 10.0, "memory_pressure"),
]
MEM_AVAILABLE_WARN_KB = 2 * 1024 * 1024
SWAP_FREE_FRACTION_WARN = 0.5
DISK_DEVICE = os.environ.get("VSF_SYSHEALTH_DISK", "sda")
DISK_UTIL_WARN_PCT = 90.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _load_state():
    # Missing/corrupt/empty state reads as None = cold start (baseline
    # silently, never page on unknown). run() treats None as cold; any
    # dict (even partial — .get() defaults cover) evaluates warm.
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            st = json.load(fh)
            return st if isinstance(st, dict) and st else None
    except (OSError, ValueError):
        return None


def _save_state(state) -> None:
    d = os.path.dirname(STATE_FILE)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    state["ts"] = now_iso()
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        print(f"syshealth: state write failed: {exc}", file=sys.stderr)


def check_throttle(sys_root, prev):
    """Delta CPU throttle counters; any increase is a finding (sev 5)."""
    import glob
    findings, cur = [], {}
    files = sorted(glob.glob(os.path.join(
        sys_root, "devices/system/cpu/cpu[0-9]*/thermal_throttle",
        "*_throttle_count")) +
        glob.glob(os.path.join(
            sys_root, "devices/system/cpu/cpu[0-9]*/thermal_throttle",
            "*_total_time_ms")))
    for path in files:
        raw = _read(path)
        if raw is None or not raw.split()[0].isdigit():
            continue
        val = int(raw.split()[0])
        key = os.path.relpath(path, sys_root)
        old = (prev or {}).get(key)
        cur[key] = val
        if old is not None and val > old:
            findings.append(("cpu_throttle", 5,
                             f"{key} +{val - old} (now {val})"))
    return findings, cur


def _parse_pressure(text):
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] not in ("some", "full"):
            continue
        side = parts[0]
        metrics = {}
        for tok in parts[1:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                try:
                    metrics[k] = float(v)
                except ValueError:
                    pass
        out[side] = metrics
    return out


def check_psi(proc_root, prev_flags):
    """Pressure thresholds with hysteresis flags (sev 5)."""
    findings, flags = [], dict(prev_flags or {})
    for res, side, window, thresh, category in PSI_RULES:
        raw = _read(os.path.join(proc_root, "pressure", res))
        val = (_parse_pressure(raw).get(side, {}) if raw else {}).get(window)
        if val is None:
            continue
        key = f"{res}/{side}/{window}"
        flagged = flags.get(key, False)
        if not flagged and val >= thresh:
            flags[key] = True
            findings.append((category, 5,
                             f"{key}={val:.1f} >= {thresh}"))
        elif flagged and val < thresh * CLEAR_FACTOR:
            flags[key] = False
    return findings, flags


def _meminfo(proc_root):
    vals = {}
    raw = _read(os.path.join(proc_root, "meminfo"))
    if not raw:
        return vals
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            vals[parts[0].rstrip(":")] = int(parts[1])
    return vals


def check_memory(proc_root, prev_flags):
    """Available-RAM + swap pressure with hysteresis (sev 5)."""
    findings, flags = [], dict(prev_flags or {})
    mem = _meminfo(proc_root)
    avail = mem.get("MemAvailable")
    if avail is not None:
        if not flags.get("mem_available", False) and avail < MEM_AVAILABLE_WARN_KB:
            flags["mem_available"] = True
            findings.append(("memory_low", 5,
                             f"MemAvailable={avail // 1024}MB < 2048MB"))
        elif flags.get("mem_available", False) and avail >= MEM_AVAILABLE_WARN_KB / CLEAR_FACTOR:
            flags["mem_available"] = False
    total, free = mem.get("SwapTotal", 0), mem.get("SwapFree", 0)
    if total and total > 0:
        frac = free / total
        if not flags.get("swap", False) and frac < SWAP_FREE_FRACTION_WARN:
            flags["swap"] = True
            findings.append(("swap_pressure", 5,
                             f"SwapFree={frac * 100:.0f}% < 50%"))
        elif flags.get("swap", False) and frac >= SWAP_FREE_FRACTION_WARN / CLEAR_FACTOR:
            flags["swap"] = False
    return findings, flags


def check_oom(proc_root, prev_count):
    """Cumulative oom_kill counter; any delta is a real failure signal (sev 6)."""
    findings = []
    raw = _read(os.path.join(proc_root, "vmstat"))
    cur = None
    if raw:
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "oom_kill" and parts[1].isdigit():
                cur = int(parts[1])
                break
    if cur is None:
        return findings, prev_count
    if prev_count is not None and cur > prev_count:
        findings.append(("oom_kill", 6,
                         f"oom_kill +{cur - prev_count} (now {cur})"))
    return findings, cur


def check_disk(sys_root, prev, elapsed_s):
    """Disk saturation via time-doing-io delta; throughput logged, not alerted."""
    findings = []
    cur = {"saturated": bool((prev or {}).get("saturated", False))}
    raw = _read(os.path.join(sys_root, "block", DISK_DEVICE, "stat"))
    if not raw:
        return findings, cur, 0.0
    try:
        fields = [float(x) for x in raw.split()]
    except ValueError:
        return findings, cur, 0.0
    if len(fields) < 11:
        return findings, cur, 0.0
    doing_io_ms = fields[9]
    read_mb_s = writ_mb_s = 0.0
    util = 0.0
    cur = {"doing_io_ms": doing_io_ms}
    old = (prev or {}).get("doing_io_ms")
    if old is not None and elapsed_s and elapsed_s > 0:
        d = doing_io_ms - old
        if d >= 0:
            util = d / (elapsed_s * 1000.0) * 100.0
            cur["util_pct"] = round(util, 1)
            try:
                old_r = (prev or {}).get("sectors", [0, 0])
                r_mb = max(0.0, (fields[2] - old_r[0]) * 512 / 1e6 / elapsed_s)
                w_mb = max(0.0, (fields[6] - old_r[1]) * 512 / 1e6 / elapsed_s)
                read_mb_s, writ_mb_s = round(r_mb, 2), round(w_mb, 2)
            except (IndexError, TypeError):
                pass
    cur["sectors"] = [fields[2], fields[6]]
    flag = (prev or {}).get("saturated", False)
    if not flag and util >= DISK_UTIL_WARN_PCT:
        cur["saturated"] = True
        findings.append(("disk_saturated", 5,
                         f"{DISK_DEVICE} util={util:.0f}% >= 90% "
                         f"(r={read_mb_s}MB/s w={writ_mb_s}MB/s)"))
    elif flag and util < DISK_UTIL_WARN_PCT * CLEAR_FACTOR:
        cur["saturated"] = False
    else:
        cur["saturated"] = flag
    return findings, cur, util


def _load_pub_helper():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "shared"),
                 "/root/vsf-scripts/shared",
                 "/usr/local/lib/vsf"):
        mod = os.path.join(cand, "vsf_algedonic_pub.py")
        if os.path.isfile(mod):
            d = os.path.normpath(cand)
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import vsf_algedonic_pub as _m
                return _m
            except Exception as exc:
                print(f"syshealth: publisher import failed ({mod}): {exc}",
                      file=sys.stderr)
                return None
    return None


def run(sys_root=SYS_ROOT, proc_root=PROC_ROOT, state=None, publish=None):
    """Run all checks. Returns (findings, new_state). Cold start: baseline only."""
    cold = state is None
    st = dict(state or {})
    prev_ts = st.get("ts")
    elapsed = 0.0
    if prev_ts:
        try:
            then = datetime.strptime(prev_ts, "%Y-%m-%dT%H:%M:%SZ")
            elapsed = max(0.0, (datetime.now(timezone.utc).replace(tzinfo=None)
                                - then).total_seconds())
        except ValueError:
            elapsed = 0.0
    findings = []
    if cold:
        # Baseline counters silently: a fresh state must not page. Alert
        # flags are reset (not kept from evaluation) — otherwise the cold
        # run would pre-arm hysteresis and swallow the first real excursion.
        _, st["throttle"] = check_throttle(sys_root, None)
        _, st["psi_flags"] = check_psi(proc_root, None)
        _, st["mem_flags"] = check_memory(proc_root, None)
        _, st["oom_kill"] = check_oom(proc_root, None)
        _, st["disk"], _ = check_disk(sys_root, None, 0.0)
        st["psi_flags"] = {}
        st["mem_flags"] = {}
        st["disk"]["saturated"] = False
        print("syshealth: cold start — baselined, no findings emitted")
        return [], st
    f, st["throttle"] = check_throttle(sys_root, st.get("throttle"))
    findings += [(c, s, d) for c, s, d in f]
    f, st["psi_flags"] = check_psi(proc_root, st.get("psi_flags"))
    findings += [(c, s, d) for c, s, d in f]
    f, st["mem_flags"] = check_memory(proc_root, st.get("mem_flags"))
    findings += [(c, s, d) for c, s, d in f]
    f, st["oom_kill"] = check_oom(proc_root, st.get("oom_kill"))
    findings += [(c, s, d) for c, s, d in f]
    f, st["disk"], _ = check_disk(sys_root, st.get("disk"), elapsed)
    findings += [(c, s, d) for c, s, d in f]
    if publish is not None:
        for category, severity, detail in findings:
            try:
                ok = publish(category=category, severity=severity,
                             source_id="vsf-syshealth-watch", detail=detail)
                print(f"syshealth: algedonic [{category}] delivered={ok}")
            except Exception as exc:
                print(f"syshealth: publish failed [{category}]: {exc}",
                      file=sys.stderr)
    return findings, st


def main() -> int:
    state = _load_state()
    helper = _load_pub_helper()
    if helper is None:
        print("syshealth: canonical publisher unavailable (ship shared/"
              "vsf_algedonic_pub.py alongside this script) — findings go "
              "to stdout/cron log ONLY this run", file=sys.stderr)
    findings, new_state = run(sys_root=SYS_ROOT, proc_root=PROC_ROOT,
                              state=state,
                              publish=(helper.publish if helper else None))
    _save_state(new_state)
    for category, severity, detail in findings:
        print(f"FINDING [{category}/{severity}] {detail}")
    if not findings:
        print("syshealth: nominal — no findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
