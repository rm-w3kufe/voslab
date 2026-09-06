#!/usr/bin/env python3
"""Run the gate-suite negative controls."""
import sys
import os

# Ensure gate_suite is importable
sys.path.insert(0, os.path.dirname(__file__))

# Import gates (this registers them)
import gate_suite.gates  # noqa: F401
from gate_suite.harness import run_negative_controls

sys.exit(run_negative_controls())
