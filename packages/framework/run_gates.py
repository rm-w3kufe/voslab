#!/usr/bin/env python3
"""Run the gate-suite: negative controls + live workspace checks.

Modes:
  run_gates.py           NC + live (full health — rc != 0 if either fails)
  run_gates.py --nc      negative controls only (gate necessary-ness)
  run_gates.py --live    live checks only (workspace self-audit, G-11)
"""
import sys
import os

# Ensure gate_suite is importable
sys.path.insert(0, os.path.dirname(__file__))

# Import gates (this registers them)
import gate_suite.gates  # noqa: F401
from gate_suite.harness import run_negative_controls, run_live_checks

args = set(sys.argv[1:])
do_nc = not args or "--nc" in args
do_live = not args or "--live" in args

rc = 0
if do_nc:
    rc |= run_negative_controls()
if do_live:
    rc |= run_live_checks()
sys.exit(rc)
