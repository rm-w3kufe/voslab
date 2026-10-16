# design: projects/arc-prize/arc_prize_design.vsm
"""
test_vsm_arc_rsi_phase3.py — Tests para Fase 3: strategy_validator (S3).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from strategy_validator import StrategyValidator, ValidationResult


# ── Helpers ──────────────────────────────────────────────────

def _g(rows, cols, fill=0):
    return np.full((rows, cols), fill, dtype=np.int32)


def _make_puzzle(inp, out, test_inp=None):
    """Crear puzzle dict."""
    if test_inp is None:
        test_inp = inp.copy()
    return {
        "train": [(np.array(inp, dtype=np.int32), np.array(out, dtype=np.int32))],
        "test": [(np.array(test_inp, dtype=np.int32), None)],
    }


# ── Mock strategies ──────────────────────────────────────────

def _identity_solver(trains, test):
    """Identity: retorna test tal cual."""
    return test.copy()


def _copy_first_train_solver(trains, test):
    """Copia el primer train output (memorizer)."""
    if trains:
        return trains[0][1].copy()
    return test.copy()


def _crash_solver(trains, test):
    """Siempre crashea."""
    raise ValueError("intentional crash")


def _inverted_solver(trains, test):
    """Invierte colores (9 - value)."""
    return (9 - test).astype(np.int32)


def _slow_solver(trains, test):
    """Solver lento (simula timeout)."""
    import time
    time.sleep(0.1)
    return test.copy()


_non_deterministic_counter = [0]
def _non_det_solver(trains, test):
    """Non-deterministic: returns different results."""
    _non_deterministic_counter[0] += 1
    if _non_deterministic_counter[0] % 2 == 0:
        return test.copy()
    else:
        return (test + 1).astype(np.int32)


# ── Tests: ValidationResult ──────────────────────────────────

class TestValidationResult:

    def test_summary_pass(self):
        r = ValidationResult(passed=True, loo_score=0.9, determinism_ok=True,
                             shape_ok=True, generalization_ok=True)
        s = r.summary()
        assert "[PASS]" in s
        assert "LOO=0.90" in s

    def test_summary_fail(self):
        r = ValidationResult(passed=False, loo_score=0.3)
        s = r.summary()
        assert "[FAIL]" in s


# ── Tests: StrategyValidator ─────────────────────────────────

class TestStrategyValidator:

    def test_identity_passes(self):
        """Identity solver should pass all checks."""
        puzzles = [
            _make_puzzle([[1, 2], [3, 4]], [[1, 2], [3, 4]]),
            _make_puzzle([[5, 6], [7, 8]], [[5, 6], [7, 8]]),
        ]
        v = StrategyValidator(loo_min=0.8)
        r = v.validate(_identity_solver, puzzles, "identity")
        assert r.passed, f"Expected pass, got: {r.summary()}"
        assert r.loo_score == 1.0
        assert r.determinism_ok
        assert r.shape_ok

    def test_crash_fails(self):
        """Crash solver should fail."""
        puzzles = [_make_puzzle([[1]], [[1]])]
        v = StrategyValidator()
        r = v.validate(_crash_solver, puzzles, "crasher")
        assert not r.passed
        assert any("crash" in e for e in r.errors)

    def test_memorizer_loo_fails(self):
        """Memorizer (copy first train) should fail LOO."""
        # With 2+ trains, memorizer fails LOO on held-out pair
        trains = [
            (_g(2, 2, 1), _g(2, 2, 9)),
            (_g(2, 2, 2), _g(2, 2, 8)),
        ]
        puzzle = {
            "train": trains,
            "test": [(_g(2, 2, 3), None)],
        }
        v = StrategyValidator(loo_min=0.8)
        r = v.validate(_copy_first_train_solver, [puzzle], "memorizer")
        assert not r.passed
        assert r.loo_score < 0.8

    def test_inverted_passes(self):
        """Inverted solver should pass (9-x is deterministic and generalizes)."""
        puzzles = [
            _make_puzzle([[1, 2], [3, 4]], [[8, 7], [6, 5]]),
            _make_puzzle([[0, 5], [5, 0]], [[9, 4], [4, 9]]),
        ]
        v = StrategyValidator(loo_min=0.8)
        r = v.validate(_inverted_solver, puzzles, "inverted")
        assert r.passed, f"Expected pass, got: {r.summary()}"
        assert r.loo_score == 1.0
        assert r.determinism_ok

    def test_determinism_fail(self):
        """Non-deterministic solver should fail determinism check."""
        _non_deterministic_counter[0] = 0
        puzzles = [_make_puzzle([[1, 2], [3, 4]], [[1, 2], [3, 4]])]
        v = StrategyValidator(determinism_runs=5)
        r = v.validate(_non_det_solver, puzzles, "nondet")
        assert not r.passed
        assert not r.determinism_ok

    def test_no_puzzles(self):
        """Empty puzzle list should fail."""
        v = StrategyValidator()
        r = v.validate(_identity_solver, [], "empty")
        assert not r.passed
        assert "no_puzzles_provided" in r.errors

    def test_single_train(self):
        """Single train pair: LOO should be 1.0 (trivial)."""
        puzzles = [_make_puzzle([[1, 2]], [[2, 1]])]
        v = StrategyValidator(min_generalization=1)
        r = v.validate(_identity_solver, puzzles, "single")
        assert r.passed
        assert r.loo_score == 1.0

    def test_validate_from_code_valid(self):
        """Validar código válido."""
        code = """
import numpy as np
def solve(trains, test):
    return test.copy()
"""
        puzzles = [
            _make_puzzle([[1, 2], [3, 4]], [[1, 2], [3, 4]]),
            _make_puzzle([[5, 6], [7, 8]], [[5, 6], [7, 8]]),
        ]
        v = StrategyValidator(loo_min=0.8)
        r = v.validate_from_code(code, puzzles, "code_test")
        assert r.passed, f"Expected pass, got: {r.summary()}"

    def test_validate_from_code_crash(self):
        """Validar código que crashea."""
        code = """
def solve(trains, test):
    raise ValueError("boom")
"""
        puzzles = [_make_puzzle([[1]], [[1]])]
        v = StrategyValidator()
        r = v.validate_from_code(code, puzzles, "code_crash")
        assert not r.passed

    def test_validate_from_code_no_solve(self):
        """Validar código sin función solve()."""
        code = "x = 42"
        puzzles = [_make_puzzle([[1]], [[1]])]
        v = StrategyValidator()
        r = v.validate_from_code(code, puzzles, "no_solve")
        assert not r.passed

    def test_validate_from_code_bad_syntax(self):
        """Validar código con syntax error."""
        code = "def solve("
        puzzles = [_make_puzzle([[1]], [[1]])]
        v = StrategyValidator()
        r = v.validate_from_code(code, puzzles, "syntax")
        assert not r.passed

    def test_generalization_threshold(self):
        """Generalization requires ≥ min_generalization puzzles."""
        # Only 1 puzzle, but min_generalization=2
        puzzles = [_make_puzzle([[1, 2], [3, 4]], [[1, 2], [3, 4]])]
        v = StrategyValidator(min_generalization=2)
        r = v.validate(_identity_solver, puzzles, "single_gen")
        assert not r.passed  # fails generalization
        assert not r.generalization_ok

    def test_evidence_populated(self):
        """Evidence dict should be populated after validation."""
        puzzles = [_make_puzzle([[1, 2]], [[1, 2]])]
        v = StrategyValidator()
        r = v.validate(_identity_solver, puzzles, "evidence")
        assert "shape_ok_puzzles" in r.evidence
        assert "loo_scores" in r.evidence
        assert "determinism_ok_puzzles" in r.evidence


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
