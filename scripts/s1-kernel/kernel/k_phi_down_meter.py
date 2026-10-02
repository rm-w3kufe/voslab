#!/usr/bin/env python3
"""k_phi_down_meter.py — measure K_φ↓ and τ from the operational ledger.

GATE_3 measurement tooling (closes the tooling half of #75). The infra
already emits the events; what was missing was a script to read them and
compute the metrics. Real measurement still requires real φ↓ traffic
(currently sparse — see Annex B §6).

Definitions (from k_measurement_protocol.md / Annex B §1):

  K_φ↓  =  count(param_change events) / count(s4-analysis events)
            over a sliding time window.

  τ      =  ts(param_change) - ts(preceding s4-analysis matching its origin)
            measured per pair, then summarised (median, p95).

  K_φ↓ ≈ 1 implies every S4 decision crystallises into a parameter change.
  K_φ↓ < 1 implies decisions are dropped or filtered (whitelist, dedup).
  τ is the latency of the control loop closing on itself.

Usage:
  k_phi_down_meter.py --events <path/events.jsonl>            # full file
  k_phi_down_meter.py --events <p> --window 3600              # last 1 h
  k_phi_down_meter.py --events <p> --remote root@n02 --lxc 101 # over ssh
  k_phi_down_meter.py --events <p> --json                     # machine output
"""
import argparse
import json
import os
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from statistics import median


def parse_ts(s):
    # Tolerate trailing Z or +00:00 forms.
    s = s.rstrip("Z")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_events_local(path):
    # errors='replace' so we tolerate the occasional non-UTF8 byte slipped in
    # by an event's free-form `metrics._note`; affected lines just fail the
    # JSON parse below and are skipped.
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_events_remote(host, lxc, path):
    """Tail a remote events.jsonl over SSH."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host]
    if lxc is not None:
        cmd += [f"pct exec {lxc} -- cat {path}"]
    else:
        cmd += [f"cat {path}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _extract_origin(ev):
    """Origin lookup with G-K.2-aware fallback.

    Post-fix events (cycle 2+) carry origin at the TOP level of the JSON.
    Pre-fix events carried it inside `metrics` (and only for `param_change` —
    `s4-analysis` carried `bbs_msg_id` inside metrics, which is the same
    identifier under a different name). Try both, prefer top-level.
    """
    o = ev.get("origin")
    if o:
        return o
    m = ev.get("metrics") or {}
    return m.get("origin") or m.get("bbs_msg_id") or ""


def compute(events_iter, window_s=None, now=None, causal_only=False):
    """Walk events, count s4_analysis and param_change, pair them for τ.

    causal_only: drop events that have no `origin` (top-level or fallback).
    Use this to measure only post-G-K.2 events — gives a system-bounded K_φ↓
    rather than a meter-bounded one.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_s) if window_s else None

    n_s4 = 0
    n_param = 0
    pending_s4 = deque()  # FIFO of unmatched s4_analysis (ts, origin)
    taus = []             # τ values in seconds
    unmatched_param = 0

    for ev in events_iter:
        ts = parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        if cutoff and ts < cutoff:
            continue
        etype = ev.get("event_type", "")
        origin = _extract_origin(ev)
        if causal_only and not origin:
            continue
        # Accept both spellings — the nucleus emits "s4-analysis" today; older
        # specs and some downstream code use "s4_analysis". Treat as the same.
        if etype in ("s4-analysis", "s4_analysis"):
            n_s4 += 1
            pending_s4.append((ts, origin))
        elif etype == "param_change":
            n_param += 1
            # Pair with most recent s4_analysis sharing same origin (or any
            # if no origin tag).
            paired_idx = None
            for i, (s4_ts, s4_origin) in enumerate(pending_s4):
                if not origin or not s4_origin or origin == s4_origin:
                    paired_idx = i
                    break
            if paired_idx is not None:
                s4_ts, _ = pending_s4[paired_idx]
                tau = (ts - s4_ts).total_seconds()
                # Drop negative pairs: they mean an s4_analysis ended up
                # FIFO-ordered after a param_change due to async flush
                # interleaving. They are real pairs but the directionality
                # is artefactual; skipping them is cleaner than reporting
                # a negative "latency". Count separately for transparency.
                if tau >= 0:
                    taus.append(tau)
                else:
                    unmatched_param += 1
                # Remove paired (and anything older — those won't ever pair)
                for _ in range(paired_idx + 1):
                    pending_s4.popleft()
            else:
                unmatched_param += 1

    k = (n_param / n_s4) if n_s4 else None
    tau_stats = None
    if taus:
        srt = sorted(taus)
        p95 = srt[int(0.95 * (len(srt) - 1))]
        tau_stats = {
            "n_pairs": len(taus),
            "median_s": median(taus),
            "min_s": min(taus),
            "max_s": max(taus),
            "p95_s": p95,
        }
    return {
        "window_s": window_s,
        "n_s4_analysis": n_s4,
        "n_param_change": n_param,
        "K_phi_down": k,
        "unmatched_param_change": unmatched_param,
        "tau": tau_stats,
    }


def render_human(result):
    w = result["window_s"]
    print(f"# K_φ↓ measurement {'(window=last %ds)' % w if w else '(full ledger)'}")
    print(f"  s4_analysis events:   {result['n_s4_analysis']}")
    print(f"  param_change events:  {result['n_param_change']}")
    if result["n_s4_analysis"] == 0:
        print("  K_φ↓:                 UNDEFINED (no s4_analysis events in window)")
    else:
        print(f"  K_φ↓:                 {result['K_phi_down']:.3f}")
    print(f"  unmatched param_change: {result['unmatched_param_change']}")
    if result["tau"]:
        t = result["tau"]
        print(f"  τ pairs:              {t['n_pairs']}")
        print(f"  τ median:             {t['median_s']:.3f} s")
        print(f"  τ p95:                {t['p95_s']:.3f} s")
        print(f"  τ range:              {t['min_s']:.3f} → {t['max_s']:.3f} s")
    else:
        print("  τ:                    UNDEFINED (no matched pairs)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", required=True,
                    help="path to events.jsonl (local or, with --remote, remote path)")
    ap.add_argument("--window", type=int, default=None,
                    help="restrict to events in the last N seconds")
    ap.add_argument("--remote", default=None, metavar="HOST",
                    help="SSH host to fetch events from (e.g. root@n02)")
    ap.add_argument("--lxc", type=int, default=None,
                    help="LXC container id on the remote host (used with --remote)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    ap.add_argument("--causal-only", action="store_true",
                    help="drop events without origin (top-level or fallback). "
                         "Gives a system-bounded K_φ↓ over post-G-K.2 events only.")
    args = ap.parse_args()

    if args.remote:
        events = read_events_remote(args.remote, args.lxc, args.events)
    else:
        if not os.path.exists(args.events):
            print(f"events file not found: {args.events}", file=sys.stderr)
            sys.exit(2)
        events = read_events_local(args.events)

    result = compute(events, window_s=args.window, causal_only=args.causal_only)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        render_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
