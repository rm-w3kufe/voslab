#!/usr/bin/env python3
"""K live monitor — tails events.jsonl and prints rolling K statistics.

Refreshes every N seconds. Uses ANSI cursor to redraw in place.
No external deps (stdlib + sys).

Usage:
  python3 k_monitor.py [--path events.jsonl] [--interval 5] [--window 300]

  --window N   rolling window in seconds for rate computation (default 300s = 5min)
  --interval N refresh cadence in seconds (default 5)

Reads from the SAME events.jsonl that GATE_3 will analyze, so what you see here
is what the Markov + bootstrap analysis will see.
"""
import argparse
import json
import os
import sys
import time
from collections import deque, Counter
from datetime import datetime

PHI_UP = {"kernel_tick", "anomaly_detected", "phase_complete", "tool_run",
          "thermal_wait", "signal_escalated", "invariant_check", "drift_alert",
          "finding_emitted"}
STATE_CHANGE = {"phase_complete", "bounded_self_correction"}
S5_DECISION = {"s4-analysis", "s4_analysis", "s5_decision"}
PARAM_CHANGE = {"param_change"}

ANSI_CLEAR = "\033[2J\033[H"
ANSI_CLR_EOL = "\033[K"


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def follow(path):
    """Generator yielding lines as they appear (a la tail -F).
    Handles file rotation and waits if file missing."""
    last_inode = None
    f = None
    while True:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            time.sleep(1)
            continue
        if f is None or st.st_ino != last_inode:
            if f:
                f.close()
            f = open(path, "r")
            last_inode = st.st_ino
        line = f.readline()
        if not line:
            time.sleep(0.2)
            continue
        yield line


class Monitor:
    def __init__(self, window_secs):
        self.window = window_secs
        self.events = deque()  # (ts_epoch, event_type, system_id)
        # Pairs to compute τ
        self.last_s4_ts = None
        self.tau_samples = deque(maxlen=200)
        self.s5_decisions = 0
        self.param_changes = 0

    def ingest(self, line):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return
        ts = parse_ts(e.get("ts", ""))
        if ts is None:
            return
        et = e.get("event_type", "?")
        sid = e.get("system_id", "?")
        self.events.append((ts, et, sid))
        if et in S5_DECISION:
            self.s5_decisions += 1
            self.last_s4_ts = ts
        elif et in PARAM_CHANGE:
            self.param_changes += 1
            if self.last_s4_ts is not None:
                self.tau_samples.append(ts - self.last_s4_ts)
                self.last_s4_ts = None
        self._prune(ts)

    def _prune(self, now):
        cutoff = now - self.window
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()

    def stats(self):
        if not self.events:
            return None
        now = self.events[-1][0]
        cutoff = now - self.window
        windowed = [(t, et, sid) for (t, et, sid) in self.events if t >= cutoff]
        win_secs = max(now - windowed[0][0], 1.0)
        type_counts = Counter(et for (_, et, _) in windowed)
        sys_counts = Counter(sid for (_, _, sid) in windowed)
        phi_up = sum(c for et, c in type_counts.items() if et in PHI_UP)
        state_changes = sum(c for et, c in type_counts.items() if et in STATE_CHANGE)
        # Fallback denominator: if no state_changes events, use kernel_tick as proxy
        if state_changes == 0:
            state_changes = type_counts.get("kernel_tick", 0)
        k_phi_up = (phi_up / state_changes) if state_changes > 0 else float("nan")
        # K_φ↓ over full run, not windowed (low frequency events)
        k_phi_down = (self.param_changes / self.s5_decisions) if self.s5_decisions > 0 else float("nan")
        tau_p99 = None
        tau_mean = None
        if self.tau_samples:
            srt = sorted(self.tau_samples)
            tau_p99 = srt[int(0.99 * (len(srt) - 1))]
            tau_mean = sum(srt) / len(srt)
        return {
            "now": now,
            "win_secs": win_secs,
            "events_in_window": len(windowed),
            "events_per_min": 60.0 * len(windowed) / win_secs,
            "type_counts": type_counts,
            "sys_counts": sys_counts,
            "k_phi_up": k_phi_up,
            "k_phi_down": k_phi_down,
            "s5_total": self.s5_decisions,
            "param_change_total": self.param_changes,
            "tau_mean": tau_mean,
            "tau_p99": tau_p99,
            "tau_n": len(self.tau_samples),
        }


def render(s, path, window_secs):
    sys.stdout.write(ANSI_CLEAR)
    now_str = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")
    print(f"VSF K live monitor — {path}")
    print(f"refreshed {now_str}   window={window_secs}s")
    print("─" * 70)
    if s is None:
        print("waiting for first event...")
        sys.stdout.flush()
        return
    print(f"events in window: {s['events_in_window']:6d}   "
          f"rate: {s['events_per_min']:7.2f}/min")
    print()
    print("by system_id:")
    for sid, c in s["sys_counts"].most_common():
        print(f"  {sid:24s} {c:6d}")
    print()
    print("by event_type (window):")
    for et, c in s["type_counts"].most_common():
        marker = " (φ↑)" if et in PHI_UP else ""
        if et in STATE_CHANGE:
            marker += " [state]"
        print(f"  {et:24s} {c:6d}{marker}")
    print()
    k_up_str = "n/a" if s["k_phi_up"] != s["k_phi_up"] else f"{s['k_phi_up']:.4f}"
    k_down_str = "n/a" if s["k_phi_down"] != s["k_phi_down"] else f"{s['k_phi_down']:.4f}"
    print(f"K_φ↑ (window):         {k_up_str}")
    print(f"K_φ↓ (cumulative):     {k_down_str}    "
          f"(s5={s['s5_total']}, param_change={s['param_change_total']})")
    if s["tau_n"] > 0:
        print(f"τ (s5→param_change):  mean={s['tau_mean']:.2f}s "
              f"p99={s['tau_p99']:.2f}s  n={s['tau_n']}")
        target = "✓ PASS" if s['tau_p99'] <= 30 else "✗ FAIL"
        print(f"  covenant ≤30s:       {target}")
    else:
        print(f"τ: no pairs yet (s5_decisions={s['s5_total']}, param_changes={s['param_change_total']})")
    print()
    if s["k_phi_up"] == s["k_phi_up"]:
        cov_status = "✓ PASS" if s["k_phi_up"] < 0.8 else \
                     "◐ WARN" if s["k_phi_up"] < 1.0 else "✗ FAIL"
        print(f"covenant K<0.8 sanity (mean estimate): {cov_status}")
        print(f"  → for worst-case, see scripts/measurement/markov_analysis.py")
    print()
    print("Ctrl-C to exit")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path",
                    default=os.path.expanduser("~/vsf-measurements/raw/events-window1.jsonl"))
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--window", type=int, default=300)
    args = ap.parse_args()
    mon = Monitor(args.window)
    last_render = 0.0
    try:
        for line in follow(args.path):
            mon.ingest(line)
            now = time.time()
            if now - last_render >= args.interval:
                render(mon.stats(), args.path, args.window)
                last_render = now
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
