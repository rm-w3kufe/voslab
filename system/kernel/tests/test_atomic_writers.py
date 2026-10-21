# design: docs/plans/structural_tensions_plan_2026_10_20.vsm (T6-F1: atomic state writers)
"""T6-F1 — state writers must be atomic (tmp + replace), never in-place.

Plan 2026-10-20 T6 evidence: test_evolution_report flaked because the
writer re-wrote the file while the test read it (torn json). The fix
migrates every REWRITE of shared state to unique-pid-tmp + os.replace so
readers observe old-or-new, never partial, and concurrent writers never
share a tmp inode. Append-only jsonl writers (alerts, events, ledgers)
are a different class: single-line appends, out of scope.

This detector locks the migration: it fails if any of the four sites
regresses to an in-place write (text-level, deterministic R10).
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

EVO = REPO / "packages" / "framework" / "vos_kernel" / "evolution_report.py"
CENSUS = REPO / "scripts" / "state" / "monitoring" / "variety_census.py"
SUITE = REPO / "scripts" / "state" / "monitoring" / "scheduled_suite.py"
HARNESS = REPO / "packages" / "framework" / "gate_suite" / "harness.py"


def test_evolution_report_writes_atomic():
    src = EVO.read_text(encoding="utf-8")
    assert src.count("_atomic(") >= 4, "def + 3 call sites expected"  # def +3
    assert 'evolution_latest.json").write_text' not in src
    assert "os.getpid()" in src and "os.replace(tmp, target)" in src


def test_variety_census_writes_atomic():
    src = CENSUS.read_text(encoding="utf-8")
    assert src.count("_atomic_json(") >= 3, "def + 2 call sites expected"
    assert "with open(path, \"w\")" not in src, "report loop regressed in-place"
    assert "with open(BASELINE, \"w\")" not in src, "baseline regressed in-place"


def test_scheduled_suite_stamp_atomic():
    src = SUITE.read_text(encoding="utf-8")
    assert "os.replace(_tmp, STAMP)" in src
    assert "STAMP.write_text" not in src, "stamp regressed to in-place write"


def test_harness_gate_last_results_atomic():
    src = HARNESS.read_text(encoding="utf-8")
    assert "os.replace(_tmp, state_path)" in src
    assert "state_path.write_text" not in src, "gate_last_results regressed"
    # the manifest writer was already the reference idiom — keep it
    assert "tmp.replace(path)" in src
