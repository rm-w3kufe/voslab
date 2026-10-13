#!/usr/bin/env python3
"""test_g5_syshealth_watch.py — G5-reading: consumers fire on deltas only.
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Fixture sysfs/procfs trees under tmp_path (no hardware, no network):
  - throttle deltas fire once with counts; steady state silent
  - PSI threshold fires once (hysteresis flag), stays silent while held,
    clears below 0.7x and can fire again
  - memory/swap thresholds behave the same
  - oom_kill delta fires (sev 6); unchanged silent
  - disk saturation math: doing-io delta / elapsed; cold start silent
  - cold start of the whole run baselines silently (never pages on boot)
  - severities never reach the 8.0 caution veto (self-telemetry discipline)

Deterministic (R10): fixed fixture values, no random, no wall-clock asserts.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MON = os.path.normpath(os.path.join(_HERE, "..", "..", "monitoring"))
if _MON not in sys.path:
    sys.path.insert(0, _MON)

import vsf_syshealth_watch as w


def make_tree(root, throttle=None, pressure=None, meminfo=None,
              vmstat=None, diskstat=None):
    thro = throttle or {}
    for key, val in thro.items():
        p = os.path.join(root, "sys", "devices/system/cpu", key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(str(val) + "\n")
    for res, text in (pressure or {}).items():
        p = os.path.join(root, "proc", "pressure", res)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
    if meminfo is not None:
        p = os.path.join(root, "proc", "meminfo")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(meminfo)
    if vmstat is not None:
        p = os.path.join(root, "proc", "vmstat")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(vmstat)
    if diskstat is not None:
        p = os.path.join(root, "sys", "block", "sda", "stat")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(diskstat)
    return os.path.join(root, "sys"), os.path.join(root, "proc")


def test_throttle_delta_fires_once(tmp_path):
    sysr, _ = make_tree(str(tmp_path),
                        throttle={"cpu0/thermal_throttle/core_throttle_count": 5})
    f, st = w.check_throttle(sysr, None)
    assert f == [] and st
    sysr2, _ = make_tree(str(tmp_path),
                         throttle={"cpu0/thermal_throttle/core_throttle_count": 9})
    f2, st2 = w.check_throttle(sysr2, st)
    assert len(f2) == 1 and f2[0][0] == "cpu_throttle" and f2[0][1] == 5
    assert "+4" in f2[0][2]
    f3, _ = w.check_throttle(sysr2, st2)
    assert f3 == []


def test_psi_hysteresis(tmp_path):
    hot = ("some avg10=60.0 avg60=55.0 avg300=40.0 total=100\n"
           "full avg10=50.0 avg60=45.0 avg300=30.0 total=80\n")
    _, procr = make_tree(os.path.join(str(tmp_path), "hot"),
                         pressure={"io": hot})
    f, flags = w.check_psi(procr, None)
    assert [c for c, _, _ in f] == ["io_pressure"]
    f2, flags2 = w.check_psi(procr, flags)
    assert f2 == []
    cool = ("some avg10=5.0 avg60=10.0 avg300=8.0 total=200\n"
            "full avg10=1.0 avg60=2.0 avg300=1.0 total=150\n")
    _, procr2 = make_tree(os.path.join(str(tmp_path), "cool"),
                          pressure={"io": cool})
    f3, flags3 = w.check_psi(procr2, flags2)
    assert f3 == [] and flags3.get("io/full/avg60") is False
    f4, _ = w.check_psi(procr, flags3)
    assert [c for c, _, _ in f4] == ["io_pressure"]


def test_memory_and_swap(tmp_path):
    mem = ("MemTotal:        8000000 kB\nMemFree:           100000 kB\n"
           "MemAvailable:     500000 kB\nSwapTotal:       4000000 kB\n"
           "SwapFree:         500000 kB\n")
    _, procr = make_tree(str(tmp_path), meminfo=mem)
    f, flags = w.check_memory(procr, None)
    cats = sorted(c for c, _, _ in f)
    assert cats == ["memory_low", "swap_pressure"]
    assert all(s == 5 for _, s, _ in f)
    f2, _ = w.check_memory(procr, flags)
    assert f2 == []


def test_oom_delta_sev6(tmp_path):
    _, procr = make_tree(str(tmp_path), vmstat="oom_kill 0\nnr_free 1\n")
    f, n = w.check_oom(procr, None)
    assert f == [] and n == 0
    _, procr2 = make_tree(str(tmp_path), vmstat="oom_kill 2\nnr_free 1\n")
    f2, n2 = w.check_oom(procr2, n)
    assert len(f2) == 1 and f2[0] == ("oom_kill", 6, "oom_kill +2 (now 2)")
    assert n2 == 2


def test_disk_saturation_math(tmp_path):
    fields = [0.0] * 17
    fields[2], fields[6], fields[9] = 1000.0, 2000.0, 10000.0
    sysr, _ = make_tree(str(tmp_path), diskstat=" ".join(map(str, fields)))
    f, st, _ = w.check_disk(sysr, None, 0.0)
    assert f == [] and st["doing_io_ms"] == 10000.0
    fields[9] = 10000.0 + 0.95 * 300 * 1000
    fields[2], fields[6] = 2000.0, 4000.0
    sysr2, _ = make_tree(str(tmp_path), diskstat=" ".join(map(str, fields)))
    f2, st2, util = w.check_disk(sysr2, st, 300.0)
    assert 89.0 < util < 96.0
    assert [c for c, _, _ in f2] == ["disk_saturated"]
    f3, _, _ = w.check_disk(sysr2, st2, 300.0)
    assert f3 == []


def test_cold_start_baselines_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "LXC_CGROUP_ROOT", os.path.join(str(tmp_path), "nols"))
    monkeypatch.setattr(w, "LXC_IO_LOG", os.path.join(str(tmp_path), "io.jsonl"))
    sysr, procr = make_tree(
        str(tmp_path),
        throttle={"cpu0/thermal_throttle/core_throttle_count": 100},
        pressure={"io": "some avg10=99.0 avg60=99.0 avg300=99.0\n"},
        meminfo="MemAvailable: 1 kB\nSwapTotal: 10 kB\nSwapFree: 0 kB\n",
        vmstat="oom_kill 5\n")
    published = []
    findings, st = w.run(sys_root=sysr, proc_root=procr, state=None,
                         publish=lambda **kw: published.append(kw) or True)
    assert findings == [] and published == []
    assert st["throttle"] and st["oom_kill"] == 5


def test_severities_below_veto(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "LXC_CGROUP_ROOT", os.path.join(str(tmp_path), "nols"))
    monkeypatch.setattr(w, "LXC_IO_LOG", os.path.join(str(tmp_path), "io.jsonl"))
    sysr, procr = make_tree(
        str(tmp_path),
        throttle={"cpu0/thermal_throttle/core_throttle_count": 1},
        pressure={"io": "some avg10=99.0 avg60=99.0 avg300=99.0\n"},
        meminfo="MemAvailable: 1 kB\nSwapTotal: 10 kB\nSwapFree: 0 kB\n",
        vmstat="oom_kill 0\n")
    base, _ = w.run(sys_root=sysr, proc_root=procr, state=None)
    assert base == []
    st = {"throttle": {"cpu0/thermal_throttle/core_throttle_count": 0},
          "psi_flags": {}, "mem_flags": {}, "oom_kill": 0,
          "disk": {"doing_io_ms": 0.0, "sectors": [0.0, 0.0]}}
    findings, _ = w.run(sys_root=sysr, proc_root=procr, state=dict(st),
                        publish=lambda **kw: True)
    assert findings
    assert all(s < 8.0 for _, s, _ in findings)


def test_main_wires_state_through(monkeypatch, tmp_path):
    """Regression: main() must pass loaded state into run(), or every tick
    cold-starts and the instrument runs green forever while the world burns
    (caught live on first scheduled tick — the exact silence class G5 exists
    to kill). First run baselines silently; second run evaluates."""
    import json as _json
    sysr = os.path.join(str(tmp_path), "sys")
    procr = os.path.join(str(tmp_path), "proc")
    os.makedirs(os.path.join(sysr, "devices/system/cpu/cpu0/thermal_throttle"))
    open(os.path.join(sysr, "devices/system/cpu/cpu0/thermal_throttle",
                      "core_throttle_count"), "w").write("0\n")
    os.makedirs(os.path.join(procr, "pressure"))
    open(os.path.join(procr, "pressure", "io"), "w").write(
        "some avg10=60.0 avg60=55.0 avg300=40.0 total=100\n"
        "full avg10=50.0 avg60=45.0 avg300=30.0 total=80\n")
    open(os.path.join(procr, "meminfo"), "w").write(
        "MemTotal: 8000000 kB\nMemAvailable: 7000000 kB\n"
        "SwapTotal: 4000000 kB\nSwapFree: 4000000 kB\n")
    open(os.path.join(procr, "vmstat"), "w").write("oom_kill 0\n")
    os.makedirs(os.path.join(sysr, "block", "sda"), exist_ok=True)
    open(os.path.join(sysr, "block", "sda", "stat"), "w").write(
        " ".join(["0.0"] * 17))
    monkeypatch.setattr(w, "SYS_ROOT", sysr)
    monkeypatch.setattr(w, "PROC_ROOT", procr)
    monkeypatch.setattr(w, "LXC_CGROUP_ROOT", os.path.join(str(tmp_path), "nols"))
    monkeypatch.setattr(w, "LXC_IO_LOG", os.path.join(str(tmp_path), "io.jsonl"))
    state_file = os.path.join(str(tmp_path), "state.json")
    monkeypatch.setattr(w, "STATE_FILE", state_file)
    published = []

    def _fake_publish(**kw):
        published.append(kw)
        return True

    _fake_helper = type("H", (), {"publish": staticmethod(_fake_publish)})()
    monkeypatch.setattr(w, "_load_pub_helper", lambda: _fake_helper)
    assert w.main() == 0
    assert published == []
    assert os.path.isfile(state_file)
    assert _json.load(open(state_file))["throttle"]
    published.clear()
    assert w.main() == 1
    assert [p["category"] for p in published] == ["io_pressure"]


def _lxc_tree(root, counters):
    base = os.path.join(root, "lxc")
    for lxc, (rb, wb) in counters.items():
        d = os.path.join(base, str(lxc))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "io.stat"), "w") as fh:
            fh.write(f"8:0 rbytes={rb} wbytes={wb} rios=10 wios=5\n")
            fh.write("252:0 rbytes=1 wbytes=2 rios=0 wios=0\n")
    return base


def test_lxc_io_deltas_and_log(tmp_path):
    log = os.path.join(str(tmp_path), "io.jsonl")
    r1 = _lxc_tree(str(tmp_path), {"101": (1_000_000_000, 500_000_000)})
    cur = w.check_lxc_io(r1, None, 0.0, log)
    assert cur == {"101": [1000000000, 500000000]}
    assert not os.path.exists(log)
    import json as _json
    _json.dumps(cur)
    r2 = _lxc_tree(str(tmp_path), {"101": (1_000_000_000 + 60 * 1_048_576,
                                           500_000_000 + 60 * 524_288)})
    cur2 = w.check_lxc_io(r2, cur, 60.0, log)
    assert os.path.isfile(log)
    row = _json.loads(open(log).readline())
    assert row["per_lxc"]["101"] == {"r_mb_s": 1.049, "w_mb_s": 0.524}
    assert cur2 == {"101": [1062914560, 531457280]}


def test_lxc_io_tolerates_missing(tmp_path):
    log = os.path.join(str(tmp_path), "io.jsonl")
    r1 = _lxc_tree(str(tmp_path), {"101": (100, 200)})
    os.makedirs(os.path.join(r1, "999"), exist_ok=True)
    cur = w.check_lxc_io(r1, None, 0.0, log)
    assert cur == {"101": [100, 200]}
    assert w.check_lxc_io("/nonexistent-root-xyz", cur, 60.0, log) == cur
    assert not os.path.exists(log)


def test_design_header_present():
    src = open(os.path.join(_MON, "vsf_syshealth_watch.py"),
               encoding="utf-8").read()
    assert "design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm" in src
    src_t = open(os.path.join(_MON, "vsf-syshealth-watch.service"),
                 encoding="utf-8").read()
    assert "design:" in src_t
