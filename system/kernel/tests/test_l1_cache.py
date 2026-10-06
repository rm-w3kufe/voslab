import os
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
if str(VOSLAB / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))

from gate_suite.gates import l1_cache  # noqa: E402


def test_live_l1_cache_probe():
    """Behavioral probe A-G on every suite run — invalidation regressions go loud."""
    rc = l1_cache.check("")
    assert rc == 0


def test_negative_ttl_fixture_rejected():
    """Clock-based invalidation must always be rejected (§4.5)."""
    path = l1_cache.negative_case()
    try:
        rc = l1_cache.check(path)
        assert rc != 0
    finally:
        if os.path.exists(path):
            os.remove(path)
