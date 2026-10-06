#!/usr/bin/env python3
"""Run the gate-suite: negative controls + live workspace checks.

Modes:
  run_gates.py           NC + live (full health — rc != 0 if either fails)
  run_gates.py --nc      negative controls only (gate necessary-ness)
  run_gates.py --live    live checks only (workspace self-audit, G-11)
  run_gates.py --no-cache   bypass the F3a manifest cache entirely
                         (same as VOS_GATES_CACHE=0; NC is always cold)
"""
import sys
import os

# Ensure gate_suite is importable
sys.path.insert(0, os.path.dirname(__file__))

# Import gates (this registers them)
import gate_suite.gates  # noqa: F401
from gate_suite.harness import (
    run_negative_controls,
    run_live_checks,
    ssh_prewarm_start,
)

args = set(sys.argv[1:])
if "--no-cache" in args:
    # kill switch (contract §5.1): harness reads VOS_GATES_CACHE at call time
    os.environ["VOS_GATES_CACHE"] = "0"
do_nc = not args or "--nc" in args
do_live = not args or "--live" in args

rc = 0
if do_live:
    # ControlMaster prewarm starts HERE so the ~7-8s n02 handshake runs
    # while the negative controls do their 1.3s (contract: warm < 15s)
    ssh_prewarm_start()
if do_nc:
    rc |= run_negative_controls()
if do_live:
    rc |= run_live_checks()
sys.exit(rc)
