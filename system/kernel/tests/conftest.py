"""conftest — isolate RSI filesystem state per test session.

Upstream vsf_rsi freezes its STATE DIR constants at first import, so the
RSI_*_DIR env vars must point at a tmp dir BEFORE any `import vsf_rsi.*`
runs. pytest imports this conftest before test modules, and rsi_cycle.py
only imports vsf_rsi lazily — so state always lands in tmp_path_factory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

KERNEL_DIR = Path(__file__).resolve().parent.parent
if str(KERNEL_DIR) not in sys.path:
    sys.path.insert(0, str(KERNEL_DIR))


@pytest.fixture(scope="session", autouse=True)
def _isolate_rsi_state(tmp_path_factory):
    base = tmp_path_factory.mktemp("rsi_state")
    os.environ["RSI_QUEUE_DIR"] = str(base / "queue")
    os.environ["RSI_SHADOW_DIR"] = str(base / "shadow")
    os.environ["RSI_ROLLBACK_DIR"] = str(base / "rollback")
    os.environ["RSI_L3_DIR"] = str(base / "l3")
    os.environ["RSI_FAULT_DIR"] = str(base / "faults")
    yield base


@pytest.fixture()
def cycle():
    """Fresh RSICycle with L3 side-effects disabled (pure wiring test)."""
    import rsi_cycle
    old = rsi_cycle.L3_AUTO
    rsi_cycle.L3_AUTO = False
    try:
        yield rsi_cycle.RSICycle()
    finally:
        rsi_cycle.L3_AUTO = old
