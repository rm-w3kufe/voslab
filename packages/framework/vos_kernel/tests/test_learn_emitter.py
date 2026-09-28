"""Tests for vos_kernel.learn_emitter — EP-3 of EPISTEMIC-CERT-001.

Deterministic only (R10): fixed ledgers, fixed plan parse, injected emitters.
The bridge itself is exercised in the real round (vsctl learn-round), not
here — tests verify sources, status logic, and the emitter contract.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vos_kernel.epistemic import EpicStore, repo_root
from vos_kernel.learn_emitter import (
    build_sources,
    count_learn_events,
    load_live_findings,
    load_retro_learnings,
    round_close,
)

_PLAN = repo_root() / "docs/plans/epistemic_certification_plan.vsm"

_FAKE_PLAN_SECTION = """⟦ fake_plan | PLAN-v1 | vsm-1.2.1 | 2026-09-28T01:00:00Z ⟧

@vsm 1.2.1
@status active

// \u2550\u2550\u2550 9. MATRIX \u2550\u2550\u2550
//   ---------------------------------  -----  --------
//   L1 first lesson                    cap A  M4
//   L2 byte-for-byte claim was         cap B  M3
//       really a DECLARED claim
//   L5 workspace invisible skip        cap C  M7
//   E1 second lesson                   cap D  M3
//
// \u2550\u2550\u2550 10. NON-GOALS \u2550\u2550\u2550
//   nothing here should parse
//   L9 not-a-row (outside section)
"""


def _fnd(fid, guard="G1", guard_status="live", fix="f"):
    return {"id": fid, "symptom": "s", "root_cause": "r", "fix": fix,
            "guard": guard, "guard_status": guard_status, "learn_ref": "T"}


class _Recorder:
    """Fake bridge: captures emits and summary entries."""

    def __init__(self, fail_files=()):
        self.calls: list[tuple[str, str, str]] = []
        self.summaries: list[dict] = []
        self.fail_files = set(fail_files)

    def emit(self, tool, file, outcome):
        if file in self.fail_files:
            raise RuntimeError("injected emit failure")
        self.calls.append((tool, file, outcome))
        return {"ok": True, "rsi": {"recorded": True}}

    def summary(self, entry):
        self.summaries.append(entry)


class TestRealSources(unittest.TestCase):
    """Ledger + plan parses against the real repo data."""

    def test_live_findings_include_exit_learnings(self):
        store = EpicStore(repo_root())
        live = load_live_findings(store)
        ids = {f["id"] for f in live}
        self.assertGreaterEqual(len(live), 4)
        self.assertIn("FND-LC-F16", ids)   # exit: companion F16
        self.assertIn("FND-LC-B10", ids)   # exit: companion B10
        for f in live:
            self.assertEqual(f.get("guard_status"), "live")

    def test_retro_matrix_includes_exit_learnings(self):
        rows = load_retro_learnings(_PLAN)
        ids = [r["id"] for r in rows]
        self.assertGreaterEqual(len(rows), 4)
        self.assertIn("L2", ids)   # exit: byte-for-byte
        self.assertIn("L5", ids)   # exit: workspace-ciego
        self.assertNotIn("L9", ids)  # outside section never leaks
        l2 = next(r for r in rows if r["id"] == "L2")
        self.assertIn("DECLARED", l2["text"])  # continuation merged

    def test_parse_is_deterministic(self):
        self.assertEqual(load_retro_learnings(_PLAN),
                         load_retro_learnings(_PLAN))
        store = EpicStore(repo_root())
        self.assertEqual(build_sources(store, _PLAN),
                         build_sources(store, _PLAN))


class TestFailingSource(unittest.TestCase):
    def test_missing_plan_section_fails_loud(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".vsm", delete=False) as f:
            f.write("no matrix section here\n")
            p = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                load_retro_learnings(p)
        finally:
            p.unlink()

    def test_missing_plan_file_fails_loud(self):
        with self.assertRaises(ValueError):
            load_retro_learnings(Path("/nonexistent/plan.vsm"))


class TestRoundClose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ep3_test_")
        self.root = Path(self.tmp.name)
        self.plan = self.root / "plan.vsm"
        self.plan.write_text(_FAKE_PLAN_SECTION, encoding="utf-8")
        self.store = EpicStore(self.root)
        self.store.append("guards", {"id": "G1", "cmd": ["true"],
                                     "expect": ["x"],
                                     "ts": "2026-09-27T21:00:00Z"})
        self.store.append("findings", _fnd("FND-1"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_green_round_with_m1_ge_4(self):
        rec = _Recorder()
        report = round_close(root=self.root, plan_path=self.plan,
                             emit_fn=rec.emit, summary_fn=rec.summary)
        # 1 live finding + 4 retro rows = 5 (exit needs >= 4)
        self.assertEqual(report["m1"], 5)
        self.assertGreaterEqual(report["m1"], 4)
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["reasons"], [])
        self.assertEqual(report["guard_audit"]["ok"], True)
        # emission order and shape
        self.assertEqual(rec.calls[0],
                         ("round-finding", "FND-1", "guarded:G1"))
        self.assertEqual([c[1] for c in rec.calls[1:]],
                         ["L1", "L2", "L5", "E1"])
        # summary event carries the round contract
        self.assertEqual(len(rec.summaries), 1)
        s = rec.summaries[0]
        self.assertEqual(s["phase"], "round_close")
        self.assertEqual(s["file"], report["round_id"])
        self.assertEqual(s["outcome"], "green")
        self.assertEqual(s["evidence"]["m1"], 5)

    def test_negative_control_fixed_without_guard_is_yellow(self):
        # control negativo (plan EP-3): fixeado sin guard => amarillo
        self.store.append("findings", _fnd("FND-BAD", guard="G-MISSING"))
        rec = _Recorder()
        report = round_close(root=self.root, plan_path=self.plan,
                             emit_fn=rec.emit, summary_fn=rec.summary)
        self.assertEqual(report["status"], "yellow")
        self.assertIn("FND-BAD", report["guard_audit"]["missing"])
        self.assertTrue(any("guard-audit" in r for r in report["reasons"]))
        self.assertEqual(rec.summaries[0]["outcome"], "yellow")

    def test_dry_run_emits_nothing(self):
        rec = _Recorder()
        report = round_close(root=self.root, plan_path=self.plan,
                             dry_run=True, emit_fn=rec.emit,
                             summary_fn=rec.summary)
        self.assertTrue(report["dry_run"])
        self.assertEqual(rec.calls, [])
        self.assertEqual(rec.summaries, [])
        self.assertEqual(report["m1"], 0)
        self.assertEqual(report["sources"]["total"], 5)
        # honest preview: nothing emitted means not green
        self.assertEqual(report["status"], "yellow")

    def test_emit_failure_keeps_rest_and_stays_honest(self):
        rec = _Recorder(fail_files={"L1"})
        report = round_close(root=self.root, plan_path=self.plan,
                             emit_fn=rec.emit, summary_fn=rec.summary)
        self.assertEqual(report["m1"], 4)
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(report["failed"][0]["file"], "L1")
        self.assertTrue(any("emit-failed=1" in r for r in report["reasons"]))

    def test_zero_emit_is_yellow_never_green(self):
        rec = _Recorder()
        rec.emit = self._zero_emit
        report = round_close(root=self.root, plan_path=self.plan,
                             emit_fn=rec.emit, summary_fn=rec.summary)
        self.assertEqual(report["m1"], 0)
        self.assertEqual(report["status"], "yellow")
        self.assertTrue(any("M1=0" in r for r in report["reasons"]))

    @staticmethod
    def _zero_emit(tool, file, outcome):
        raise RuntimeError("all emits refused")


class TestCountLearnEvents(unittest.TestCase):
    def test_counts_only_learn_events_in_window(self):
        with tempfile.TemporaryDirectory(prefix="ep3_log_") as tmp:
            log = Path(tmp) / "agent_plugin.jsonl"
            rows = [
                {"ts": "2026-09-28T01:00:00.100000+00:00",
                 "event_type": "learn"},          # before window
                {"ts": "2026-09-28T01:00:10.100000+00:00",
                 "event_type": "learn"},          # inside
                {"ts": "2026-09-28T01:00:20.100000+00:00",
                 "event_type": "round_close"},    # not a learn event
                {"ts": "not-a-ts", "event_type": "learn"},   # skipped
            ]
            log.write_text("\n".join(json.dumps(r) for r in rows),
                           encoding="utf-8")
            since = _parse_ts("2026-09-28T01:00:05.000000+00:00")
            self.assertEqual(count_learn_events(log, since), 1)

    def test_missing_log_is_zero(self):
        self.assertEqual(
            count_learn_events(Path("/nonexistent/agent_plugin.jsonl"), None),
            0)


def _parse_ts(value: str):
    from vos_kernel.learn_emitter import _parse_ts as fn
    return fn(value)


if __name__ == "__main__":
    unittest.main()
