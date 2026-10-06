import os
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
if str(VOSLAB / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(VOSLAB / "packages" / "framework"))

from gate_suite.gates import l0_memo  # noqa: E402


def test_live_l0_memo_probe():
    """Behavioral probe A-E on every suite run — memo regressions go loud."""
    rc = l0_memo.check("")
    assert rc == 0


def test_negative_scope_fixture_rejected():
    """A process-lifetime memo scope must always be rejected (§4.5)."""
    path = l0_memo.negative_case()
    try:
        rc = l0_memo.check(path)
        assert rc != 0
    finally:
        if os.path.exists(path):
            os.remove(path)
