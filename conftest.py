"""Make the gate-suite package importable in tests regardless of pytest version."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "packages", "framework"))
