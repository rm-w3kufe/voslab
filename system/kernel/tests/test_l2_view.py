import os
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
if str(VOSLAB / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))

from gate_suite.gates import l2_view  # noqa: E402


def test_live_l2_view_probe():
    """Behavioral probe A-G on every suite run — view regressions go loud."""
    rc = l2_view.check("")
    assert rc == 0


def test_negative_claimed_freshness_fixture_rejected():
    """A digest claiming freshness without naming its snapshot must always
    be rejected (§5.2)."""
    path = l2_view.negative_case()
    try:
        rc = l2_view.check(path)
        assert rc != 0
    finally:
        if os.path.exists(path):
            os.remove(path)
