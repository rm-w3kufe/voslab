"""Make vOSLAB packages importable in tests regardless of pytest version."""
import os
import sys

ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(ROOT, "packages", "framework"))
sys.path.insert(0, os.path.join(ROOT, "packages", "public"))
