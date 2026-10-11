#!/usr/bin/env python3
"""
vsf-battery-watchdog — standalone host-level power alarm.

Deliberately does NOT touch Ω/S3/S4/S5 (same pattern as vsf-thermal-watchdog).
This is a smoke detector for power loss, not a cybernetic input: it samples
AC status + battery capacity and raises a loud alarm on threshold crossing.

Root cause this exists: found 2026-08-02 that n02 (repurposed laptop hardware,
24/7 production host) had a real, live BAT0 (96% capacity, AC present) and
ZERO monitoring of it. AC loss -> battery drain -> total host death is a hard
BINARY failure with a real countdown, not a slow decline. If AC ever disconnects
with nobody watching, ALL ~15 LXCs go down together with zero warning.

Design: same pattern as vsf-thermal-watchdog.py — cheap, proven, raw sysfs
(no upower dependency). Reads /sys/class/power_supply/{BAT0,AC}/ directly.
"""

import subprocess
import sys
import time
from pathlib import Path

# Thresholds
AC_OFFLINE_ALERT = True          # alert immediately when AC goes offline
BATTERY_WARN_PCT = 20            # warn when on battery below this
BATTERY_ALERT_PCT = 10           # alert when on battery below this
BATTERY_CRITICAL_PCT = 5         # critical when on battery below this

STATE_FILE = Path("/var/lib/vsf-battery-watchdog/last_alert.json")


def read_sysfs(path: str) -> str | None:
    """Read a sysfs file, return stripped content or None on error."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def check_power() -> tuple[str, int, bool]:
    """Returns (status, capacity_pct, ac_online).

    status: 'Full', 'Charging', 'Discharging', 'Not charging', or 'Unknown'
    capacity_pct: battery capacity 0-100, or -1 if unreadable
    ac_online: True if AC is online, False if offline, None if unreadable
    """
    status = read_sysfs("/sys/class/power_supply/BAT0/status") or "Unknown"
    cap_str = read_sysfs("/sys/class/power_supply/BAT0/capacity")
    capacity = int(cap_str) if cap_str and cap_str.isdigit() else -1

    ac_str = read_sysfs("/sys/class/power_supply/AC/online")
    if ac_str is None:
        ac_online = None
    else:
        ac_online = ac_str == "1"

    return status, capacity, ac_online


def raise_alarm(level: str, msg: str) -> None:
    """Loud journal entry at a real priority — makes it a real alarm."""
    priority = {"CRITICAL": "crit", "ALERT": "err", "WARN": "warning"}.get(level, "info")
    full_msg = f"vsf-battery-watchdog: {level} — {msg}"
    subprocess.run(
        ["systemd-cat", "-t", "vsf-battery-watchdog", "-p", priority],
        input=full_msg.encode(),
        check=False,
    )
    print(full_msg, file=sys.stderr)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        f'{{"timestamp": {time.time():.0f}, "level": "{level}", "msg": "{msg}"}}\n'
    )


def main() -> int:
    status, capacity, ac_online = check_power()

    # AC offline — immediate alert regardless of battery level
    if ac_online is False:
        raise_alarm(
            "ALERT",
            f"AC OFFLINE — battery={capacity}% status={status}. "
            f"Host will die when battery drains. ALL LXCs at risk.",
        )
        # If also low battery, escalate to CRITICAL
        if 0 <= capacity <= BATTERY_CRITICAL_PCT:
            raise_alarm(
                "CRITICAL",
                f"AC OFFLINE + BATTERY CRITICAL ({capacity}%). "
                f"Immediate shutdown imminent.",
            )
        return 0

    # AC online but battery discharging (shouldn't happen, but catch it)
    if ac_online and status == "Discharging":
        raise_alarm(
            "WARN",
            f"AC online but battery DISCHARGING ({capacity}%). "
            f"Possible AC adapter issue.",
        )
        return 0

    # On battery (AC offline already handled above; this catches edge cases)
    if not ac_online and 0 <= capacity:
        if capacity <= BATTERY_CRITICAL_PCT:
            raise_alarm("CRITICAL", f"Battery CRITICAL: {capacity}%")
        elif capacity <= BATTERY_ALERT_PCT:
            raise_alarm("ALERT", f"Battery low: {capacity}%")
        elif capacity <= BATTERY_WARN_PCT:
            raise_alarm("WARN", f"Battery warning: {capacity}%")

    # Below thresholds: no output by design — silence on happy path
    return 0


if __name__ == "__main__":
    sys.exit(main())
