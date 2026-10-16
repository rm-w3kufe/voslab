# design: projects/arc-prize/arc_prize_design.vsm
"""
test_vsm_arc_rsi_phase1.py — Tests para Fase 1 del VSM-ARC-RSI.

Cubre: pattern_memory.py, strategy_vsm.py, algedonic.py
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from pattern_memory import PatternMemory
from strategy_vsm import StrategyVSM, AlgedonicSignal, wrap_existing, get_registry
from algedonic import Algedonic


# ── Helpers ──────────────────────────────────────────────────

def _mock_detector(trains):
    """Detector que siempre return True."""
    return True

def _mock_detector_false(trains):
    """Detector que siempre return False."""
    return False

def _mock_solver(trains, test):
    """Solver que retorna el test input tal cual (identity)."""
    return test.copy()

def _mock_solver_crash(trains, test):
    """Solver que crashea."""
    raise ValueError("boom")

def _mock_solver_none(trains, test):
    """Solver que retorna None."""
    return None

def _make_grid(rows, cols, fill=0):
    """Crear grid de prueba."""
    return np.full((rows, cols), fill, dtype=np.int32)


# ── Tests: PatternMemory (S5) ───────────────────────────────

class TestPatternMemory:

    def test_empty_init(self):
        pm = PatternMemory()
        assert pm.stats()["total_patterns"] == 0
        assert pm.get_unknowns() == []

    def test_from_dynamics(self):
        """Crea memory desde la lista DYNAMICS real."""
        from recognizer import DYNAMICS
        pm = PatternMemory.from_dynamics(DYNAMICS)
        stats = pm.stats()
        assert stats["total_patterns"] == len(DYNAMICS)
        assert stats["active_patterns"] == len(DYNAMICS)
        # Todas las categorías son strings
        for name, info in pm.patterns.items():
            assert isinstance(info["category"], str)
            assert info["status"] == "active"

    def test_record_solved(self):
        pm = PatternMemory()
        pm.add_pattern("crop", "extraction", "test", ["fn1"])
        pm.record_detected("crop", "puzzle_001")
        pm.record_solved("crop", "puzzle_001")
        assert "puzzle_001" in pm.patterns["crop"]["solved_in"]
        assert pm.patterns["crop"]["precision"] == 1.0

    def test_record_unknown(self):
        pm = PatternMemory()
        pm.record_unknown("puzzle_xyz", hypothesis="rearrangement")
        assert "puzzle_xyz" in pm.unknowns
        assert pm.unknowns["puzzle_xyz"]["status"] == "unsolved"
        assert pm.unknowns["puzzle_xyz"]["hypothesis"] == "rearrangement"

    def test_record_unknown_result(self):
        pm = PatternMemory()
        pm.record_unknown("p001")
        pm.record_unknown_result("p001", "try_crop", 0.5)
        assert pm.unknowns["p001"]["best_score"] == 0.5
        assert "try_crop" in pm.unknowns["p001"]["tried_strategies"]
        # Second try with better score
        pm.record_unknown_result("p001", "try_mirror", 0.9)
        assert pm.unknowns["p001"]["best_score"] == 0.9

    def test_save_load(self, tmp_path):
        pm = PatternMemory()
        pm.add_pattern("test_pat", "cat", "desc", ["fn1"])
        pm.record_unknown("p001")
        path = tmp_path / "test_memory.json"
        pm.save(path)

        pm2 = PatternMemory.load(path)
        assert "test_pat" in pm2.patterns
        assert "p001" in pm2.unknowns
        assert pm2.patterns["test_pat"]["category"] == "cat"

    def test_deprecate(self):
        pm = PatternMemory()
        pm.add_pattern("old_pat", "cat", "desc", [])
        pm.deprecate_pattern("old_pat", "outdated")
        assert pm.patterns["old_pat"]["status"] == "deprecated"
        assert pm.patterns["old_pat"]["deprecated_reason"] == "outdated"
        assert "old_pat" not in pm.get_known_patterns(status="active")

    def test_stats_update(self):
        pm = PatternMemory()
        pm.add_pattern("p1", "cat", "d", [])
        pm.add_pattern("p2", "cat", "d", [])
        pm.record_solved("p1", "puzzle_001")
        pm.record_solved("p1", "puzzle_002")
        pm.record_solved("p2", "puzzle_002")
        stats = pm.stats()
        assert stats["total_solved"] == 2  # puzzle_001 + puzzle_002


# ── Tests: StrategyVSM (S1) ─────────────────────────────────

class TestStrategyVSM:

    def test_basic_init(self):
        s = StrategyVSM("test_strat", _mock_solver, _mock_detector, "test-cat")
        assert s.name == "test_strat"
        assert s.category == "test-cat"
        assert s.last_signal == AlgedonicSignal.NEUTRAL

    def test_execute_success(self):
        grid = _make_grid(3, 3, fill=5)
        puzzle = {
            "train": [(_make_grid(3, 3, 1), _make_grid(3, 3, 1))],
            "test": [(_make_grid(3, 3, 5), None)],
        }
        s = StrategyVSM("identity", _mock_solver, _mock_detector, "test")
        result, signal = s.execute(puzzle)
        assert result is not None
        assert signal.startswith("success:")
        assert s.last_signal == AlgedonicSignal.PLEASURE

    def test_execute_detector_rejects(self):
        puzzle = {"train": [], "test": [(_make_grid(3, 3), None)]}
        s = StrategyVSM("no_match", _mock_solver, _mock_detector_false, "test")
        result, signal = s.execute(puzzle)
        assert result is None
        assert signal == "not_applicable"

    def test_execute_crash(self):
        puzzle = {"train": [], "test": [(_make_grid(3, 3), None)]}
        s = StrategyVSM("crasher", _mock_solver_crash, None, "test")
        result, signal = s.execute(puzzle)
        assert result is None
        assert "crash" in signal
        assert s.last_signal == AlgedonicSignal.PAIN

    def test_execute_none_return(self):
        puzzle = {"train": [], "test": [(_make_grid(3, 3), None)]}
        s = StrategyVSM("nones", _mock_solver_none, None, "test")
        result, signal = s.execute(puzzle)
        assert result is None
        assert signal == "solver_returned_none"

    def test_algedonic_history(self):
        s = StrategyVSM("hist", _mock_solver, None, "test")
        # Simulate some signals
        s._emit_pain("fail1")
        s._emit_pain("fail2")
        s._emit_pleasure("ok1")
        assert s.pain_count() == 2
        assert s.pleasure_count() == 1
        assert len(s.signal_history) == 3

    def test_to_dict(self):
        s = StrategyVSM("my_strat", _mock_solver, category="cat1", author="llm:qwen")
        d = s.to_dict()
        assert d["name"] == "my_strat"
        assert d["category"] == "cat1"
        assert d["author"] == "llm:qwen"

    def test_registry(self):
        _REGISTRY_before = len(get_registry())
        s = StrategyVSM("reg_test", _mock_solver, None, "test")
        wrap_existing("reg_test", _mock_solver, None, "test")
        assert "reg_test" in get_registry()


# ── Tests: Algedonic (S2) ───────────────────────────────────

class TestAlgedonic:

    def test_emit_and_count(self, tmp_path):
        log = tmp_path / "test_algedonic.jsonl"
        a = Algedonic(log)
        a.pain("crop", "loo_fail:0.3")
        a.pleasure("mirror", "success:0.9")
        a.breakthrough("new_dyn", "shrink_square")
        assert a.count("PAIN") == 1
        assert a.count("PLEASURE") == 1
        assert a.count("BREAKTHROUGH") == 1
        assert a.count() == 3

    def test_stuck_detection(self, tmp_path):
        log = tmp_path / "test_stuck.jsonl"
        a = Algedonic(log)
        assert a.check_stuck(3) is False
        assert a.check_stuck(5) is True
        assert a.count("STUCK") == 1
        # Second call doesn't duplicate
        assert a.check_stuck(6) is True
        assert a.count("STUCK") == 2

    def test_persistence(self, tmp_path):
        log = tmp_path / "test_persist.jsonl"
        a1 = Algedonic(log)
        a1.pain("test", "detail1")
        a1.pleasure("test", "detail2")

        a2 = Algedonic(log)
        assert a2.count() == 2
        assert a2.pain_count() == 1

    def test_summary(self, tmp_path):
        log = tmp_path / "test_summary.jsonl"
        a = Algedonic(log)
        a.pain("x", "")
        a.pain("x", "")
        a.pleasure("x", "")
        s = a.summary()
        assert s["pain"] == 2
        assert s["pleasure"] == 1
        assert s["total"] == 3

    def test_clear(self, tmp_path):
        log = tmp_path / "test_clear.jsonl"
        a = Algedonic(log)
        a.pain("x", "")
        a.clear()
        assert a.count() == 0


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
