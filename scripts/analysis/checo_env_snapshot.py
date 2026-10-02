#!/usr/bin/env python3
"""
CH.e — CHECO environment snapshot.
Reads real operational signals from the running VSF system and emits a
checo_env/1.0 JSON vector for use by the S4 CHECO narrator.

Signals read (all from LXC 101 where this script is expected to run):
  - /proc/pressure/cpu          — PSI cpu stall info (W4b input proxy)
  - /proc/pressure/memory       — PSI memory stall info
  - /sys/class/thermal/...      — CPU temperature (thermal zone 0)
  - events.jsonl tail           — last telemetry: stasis, trust, variety

Usage:
    python3 checo_env_snapshot.py            # emit JSON to stdout
    python3 checo_env_snapshot.py --brief    # one-line summary
"""

import json, os, sys, time
from pathlib import Path

EVENTS_JSONL = os.environ.get(
    "EVENTS_JSONL", "/var/lib/vsf/vsf_nucleus/events.jsonl"
)
THERMAL_BASE = Path("/sys/class/thermal")
PSI_CPU      = Path("/proc/pressure/cpu")
PSI_MEM      = Path("/proc/pressure/memory")

# Thermal normalisation: [T_COLD, T_HOT] → [0, 1]
T_COLD, T_HOT = 30.0, 80.0


def _read_psi(path: Path) -> dict:
    """Parse /proc/pressure/{cpu,memory} → {'avg10': float, 'avg60': float, 'avg300': float}."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith("some"):
                parts = dict(p.split("=") for p in line.split()[1:] if "=" in p)
                return {
                    "avg10":  float(parts.get("avg10",  0)),
                    "avg60":  float(parts.get("avg60",  0)),
                    "avg300": float(parts.get("avg300", 0)),
                }
    except (OSError, ValueError):
        pass
    return {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0}


def _read_thermal() -> dict:
    """Read all thermal zones; return zone0 (CPU) + the max non-zero."""
    zones = {}
    if THERMAL_BASE.exists():
        for zone in sorted(THERMAL_BASE.iterdir()):
            temp_path = zone / "temp"
            try:
                c = int(temp_path.read_text().strip()) / 1000.0
                zones[zone.name] = c
            except (OSError, ValueError):
                pass
    z0 = zones.get("thermal_zone0", 0.0)
    # non-zero non-spike reading (ignore 0 and extreme values)
    valid = [v for v in zones.values() if 1.0 < v < 110.0]
    primary = z0 if z0 > 1.0 else (max(valid) if valid else 0.0)
    normalized = max(0.0, min(1.0, (primary - T_COLD) / (T_HOT - T_COLD)))
    return {
        "primary_c":  round(primary, 1),
        "zone0_c":    round(z0, 1),
        "normalized": round(normalized, 3),
    }


def _read_last_telemetry() -> dict:
    """Read the most recent invariant_check event from events.jsonl."""
    result = {
        "stasis_last": None, "trust1_last": None,
        "var1_last": None, "synthetic_load": None,
        "event_type": None, "ts": None,
    }
    try:
        p = Path(EVENTS_JSONL)
        if not p.exists():
            return result
        # Read last 8KB to find latest invariant_check
        size = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("event_type") == "invariant_check":
                    m = ev.get("metrics", {})
                    result.update({
                        "stasis_last":   m.get("stasis_last"),
                        "trust1_last":   m.get("trust1_last"),
                        "var1_last":     m.get("var1_last"),
                        "synthetic_load": m.get("synthetic_load"),
                        "event_type":    "invariant_check",
                        "ts":            ev.get("ts"),
                    })
                    break
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return result


def _env_class(cpu_avg10: float) -> str:
    if cpu_avg10 < 5.0:
        return "nominal"
    if cpu_avg10 < 20.0:
        return "loaded"
    return "stressed"


def snapshot() -> dict:
    """Collect all signals and return checo_env/1.0 dict."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    cpu_psi = _read_psi(PSI_CPU)
    mem_psi = _read_psi(PSI_MEM)
    thermal = _read_thermal()
    telem   = _read_last_telemetry()

    # W4b magnitude: PSI cpu avg10 in % → [0,1]. Clamp at 50% = full pressure.
    w4b_mag = round(min(1.0, cpu_psi["avg10"] / 50.0), 4)

    return {
        "schema":  "checo_env/1.0",
        "ts":      ts,
        "thermal": thermal,
        "pressure": {
            "cpu_psi_avg10":  round(cpu_psi["avg10"], 3),
            "cpu_psi_avg60":  round(cpu_psi["avg60"], 3),
            "cpu_psi_avg300": round(cpu_psi["avg300"], 3),
            "mem_psi_avg10":  round(mem_psi["avg10"], 3),
            "w4b_magnitude":  w4b_mag,
        },
        "telemetry": {
            "stasis_last":    telem["stasis_last"],
            "trust1_last":    telem["trust1_last"],
            "var1_last":      telem["var1_last"],
            "synthetic_load": telem["synthetic_load"],
            "last_event_ts":  telem["ts"],
        },
        "env_class":       _env_class(cpu_psi["avg10"]),
        "hardware_thermal_ref": 0.9377,  # EXP-CA-01 Alt D reference
    }


def brief(env: dict) -> str:
    p = env["pressure"]
    t = env["thermal"]
    tl = env["telemetry"]
    return (
        f"env={env['env_class']}  "
        f"cpu_psi={p['cpu_psi_avg10']:.2f}%  "
        f"w4b={p['w4b_magnitude']:.4f}  "
        f"temp={t['primary_c']}°C  "
        f"stasis={tl['stasis_last']:.4f}  "
        f"trust={tl['trust1_last']}"
    )


if __name__ == "__main__":
    env = snapshot()
    if "--brief" in sys.argv:
        print(brief(env))
    else:
        print(json.dumps(env, indent=2))
