"""
# design: docs/design/sources/rsi-observer-v1/vsf_rsi_design.vsm (SUT: packages/public/vsf-rsi/vsf_rsi/rsi_socratic_bridge.py)
Tests for enqueue_predicate sha-collision guard (F10 / P-EV-R10).

Lesson source: lote-1 (2026-10-21) registered two DISTINCT findings with
byte-identical template trees — same sha, two names, one shared sha in
activated.json. The guard must fail loud at enqueue time when a tree
collides with a DIFFERENT name holding a live status (pending/approved/
activated), and must NOT block when the status is rejected or when the
finding is encoded inside the tree (unique sha).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vsf_rsi.rsi_socratic_bridge import enqueue_predicate  # noqa: E402

TREE_A = {
    "op": "OR",
    "children": [
        {"predicate": "ctx_has", "args": ["marker_a"],
         "result": {"home": "default", "truth": "finding A"}},
    ],
    "result": {"home": "default", "truth": "tree A"},
}


def _tree_with(marker: str) -> dict:
    """Same shape, distinct finding encoded in child marker → distinct sha."""
    return {
        "op": "OR",
        "children": [
            {"predicate": "ctx_has", "args": [marker],
             "result": {"home": "default", "truth": f"finding {marker}"}},
        ],
        "result": {"home": "default", "truth": "per-finding tree"},
    }


class EnqueueShaGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._qdir = Path(self._tmp.name) / "queue"
        self._old = os.environ.get("RSI_QUEUE_DIR")
        os.environ["RSI_QUEUE_DIR"] = str(self._qdir)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("RSI_QUEUE_DIR", None)
        else:
            os.environ["RSI_QUEUE_DIR"] = self._old
        self._tmp.cleanup()

    def test_same_tree_different_name_raises(self):
        """Identical tree, different name → ValueError (fail loud)."""
        enqueue_predicate("first_name", TREE_A, source="t")
        with self.assertRaises(ValueError) as ctx:
            enqueue_predicate("second_name", dict(TREE_A), source="t")
        self.assertIn("sha collision", str(ctx.exception))
        self.assertIn("first_name", str(ctx.exception))

    def test_finding_in_tree_allows_enqueue(self):
        """Finding encoded in tree → unique sha → both enqueue fine."""
        p1 = enqueue_predicate("pred_one", _tree_with("marker_X"))
        p2 = enqueue_predicate("pred_two", _tree_with("marker_Y"))
        self.assertTrue(Path(p1).exists() and Path(p2).exists())

    def test_rejected_collision_does_not_block(self):
        """Same sha but other entry REJECTED → enqueue allowed."""
        enqueue_predicate("rej_name", TREE_A, source="t")
        # manually flip to rejected (as an S5 rejection would)
        qf = self._qdir / "rej_name.json"
        entry = json.loads(qf.read_text())
        entry["status"] = "rejected"
        qf.write_text(json.dumps(entry))
        p = enqueue_predicate("live_name", dict(TREE_A), source="t")
        self.assertTrue(Path(p).exists())

    def test_same_name_reenqueue_not_blocked_by_guard(self):
        """Same name → pre-existing semantics (G-21 patch, overwrite)."""
        enqueue_predicate("dup_name", TREE_A, source="t")
        p = enqueue_predicate("dup_name", dict(TREE_A), source="t")
        self.assertTrue(Path(p).exists())

    def test_corrupt_other_entry_not_fatal(self):
        """Corrupt unrelated queue file → guard skips it, enqueue OK."""
        enqueue_predicate("good1", _tree_with("marker_x"))
        (self._qdir / "broken.json").write_text("{not json")
        p = enqueue_predicate("good2", _tree_with("marker_y"))
        self.assertTrue(Path(p).exists())


if __name__ == "__main__":
    main()
