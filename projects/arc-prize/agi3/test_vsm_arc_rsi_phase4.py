# design: projects/arc-prize/arc_prize_design.vsm
"""
test_vsm_arc_rsi_phase4.py — Tests para Fase 4: rsi_orchestrator (S2).
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from rsi_orchestrator import RSIOrchestrator, RSICycleResult, RSISessionResult
from pattern_memory import PatternMemory
from strategy_sandbox import StrategySandbox
from strategy_validator import StrategyValidator
from llm_proposer import LLMProposer
from algedonic import Algedonic


# ── Helpers ──────────────────────────────────────────────────

def _g(rows, cols, fill=0):
    return np.full((rows, cols), fill, dtype=np.int32)


def _make_puzzle(pid, inp, out):
    """Crear puzzle dict con id."""
    return {
        "id": pid,
        "train": [(np.array(inp, dtype=np.int32), np.array(out, dtype=np.int32))],
        "test": [(np.array(inp, dtype=np.int32), None)],
    }


def _make_temp_dir():
    return tempfile.mkdtemp()


# ── Tests: RSICycleResult ────────────────────────────────────

class TestRSICycleResult:

    def test_create(self):
        r = RSICycleResult(
            cycle_num=1, puzzles_analyzed=5, hypotheses_generated=3,
            hypotheses_validated=1, strategies_promoted=1,
            strategies_rejected=2, duration_ms=100.0,
        )
        assert r.cycle_num == 1
        assert r.strategies_promoted == 1
        assert r.stuck is False


# ── Tests: RSIOrchestrator ───────────────────────────────────

class TestRSIOrchestrator:

    def _make_rsi(self, tmp_path):
        """Crear RSI con componentes test."""
        mem = PatternMemory()
        mem.record_unknown("p1")
        mem.record_unknown("p2")
        mem.record_unknown("p3")
        mem.save(tmp_path / "memory.json")

        algedonic = Algedonic(tmp_path / "algedonic.jsonl")
        llm = LLMProposer(url="http://localhost:99999")  # unavailable
        sandbox = StrategySandbox()
        validator = StrategyValidator(min_generalization=1)

        return RSIOrchestrator(
            llm_proposer=llm,
            sandbox=sandbox,
            validator=validator,
            pattern_memory=mem,
            algedonic=algedonic,
            max_hypotheses_per_cycle=3,
            batch_size=5,
            stuck_threshold=3,
        )

    def test_observe_registers_unknowns(self, tmp_path):
        """Observe registra puzzles como unknowns."""
        rsi = self._make_rsi(tmp_path)
        puzzles = [
            _make_puzzle("p1", [[1, 2]], [[2, 1]]),
            _make_puzzle("p2", [[3, 4]], [[4, 3]]),
            _make_puzzle("new_puzzle", [[5, 6]], [[6, 5]]),
        ]
        batch = rsi._observe(puzzles)
        assert len(batch) == 3
        assert "new_puzzle" in rsi.memory.unknowns

    def test_orient_without_llm(self, tmp_path):
        """Orient genera hipótesis básicas sin LLM."""
        rsi = self._make_rsi(tmp_path)
        puzzles = [_make_puzzle("p1", [[1, 2]], [[2, 1]])]
        batch = rsi._observe(puzzles)
        hypotheses = rsi._orient(batch)
        assert len(hypotheses) == 1
        pid, hyp = hypotheses[0]
        assert pid == "p1"
        assert hyp.confidence == 0.1  # fallback confidence

    def test_decide_sorts_by_confidence(self, tmp_path):
        """Decide ordena hipótesis por score."""
        rsi = self._make_rsi(tmp_path)
        from llm_proposer import Hypothesis
        h1 = Hypothesis(text="low", code="", confidence=0.2, rationale="")
        h2 = Hypothesis(text="high", code="", confidence=0.9, rationale="")
        ranked = rsi._decide([("p1", h1), ("p2", h2)])
        assert ranked[0][0] == "p2"  # high confidence first

    def test_act_rejects_no_code(self, tmp_path):
        """Act rechaza hipótesis sin código."""
        rsi = self._make_rsi(tmp_path)
        from llm_proposer import Hypothesis
        hyp = Hypothesis(text="test", code="", confidence=0.5, rationale="")
        promoted, detail = rsi._act(hyp, [])
        assert not promoted
        assert detail == "no_code"

    def test_act_rejects_bad_code(self, tmp_path):
        """Act rechaza código que falla validación."""
        rsi = self._make_rsi(tmp_path)
        from llm_proposer import Hypothesis
        hyp = Hypothesis(
            text="bad code",
            code="def solve(trains, test): return None",
            confidence=0.5,
            rationale="",
        )
        puzzles = [_make_puzzle("p1", [[1, 2]], [[2, 1]])]
        promoted, detail = rsi._act(hyp, puzzles)
        assert not promoted

    def test_cycle_with_no_llm(self, tmp_path):
        """Ciclo completo sin LLM (fallback mode)."""
        rsi = self._make_rsi(tmp_path)
        puzzles = [
            _make_puzzle("p1", [[1, 2]], [[2, 1]]),
            _make_puzzle("p2", [[3, 4]], [[4, 3]]),
        ]
        result = rsi.run_cycle(puzzles)
        assert isinstance(result, RSICycleResult)
        assert result.puzzles_analyzed >= 1
        # Without LLM, hypotheses have empty code → all rejected
        assert result.strategies_promoted == 0
        assert result.strategies_rejected >= 1

    def test_session_stops_at_stuck(self, tmp_path):
        """Session para en stuck threshold."""
        rsi = self._make_rsi(tmp_path)
        puzzles = [_make_puzzle("p1", [[1, 2]], [[2, 1]])]
        session = rsi.run_session(puzzles, max_cycles=10)
        # Should stop at stuck_threshold (3) since no improvements
        assert session.stuck_at_cycle is not None
        assert session.stuck_at_cycle <= 3

    def test_session_stops_at_max_cycles(self, tmp_path):
        """Session para en max_cycles."""
        rsi = self._make_rsi(tmp_path)
        rsi._cycles_without_improvement = 0  # reset
        # Increase stuck threshold so it doesn't trigger
        rsi.stuck_threshold = 100
        puzzles = [_make_puzzle("p1", [[1, 2]], [[2, 1]])]
        session = rsi.run_session(puzzles, max_cycles=3)
        assert session.total_cycles == 3

    def test_status(self, tmp_path):
        """Status retorna dict con métricas."""
        rsi = self._make_rsi(tmp_path)
        s = rsi.status()
        assert "cycles_run" in s
        assert "total_improvements" in s
        assert "unknowns_remaining" in s
        assert "llm_available" in s
        assert s["llm_available"] is False

    def test_feedback_updates_counters(self, tmp_path):
        """Feedback actualiza contadores de mejora."""
        rsi = self._make_rsi(tmp_path)
        # Cycle with no improvements
        r1 = RSICycleResult(
            cycle_num=1, puzzles_analyzed=0, hypotheses_generated=0,
            hypotheses_validated=0, strategies_promoted=0,
            strategies_rejected=0, duration_ms=0,
        )
        rsi._feedback(r1)
        assert rsi._cycles_without_improvement == 1

        # Cycle with improvement
        r2 = RSICycleResult(
            cycle_num=2, puzzles_analyzed=0, hypotheses_generated=0,
            hypotheses_validated=0, strategies_promoted=1,
            strategies_rejected=0, duration_ms=0,
        )
        rsi._feedback(r2)
        assert rsi._cycles_without_improvement == 0
        assert rsi._total_improvements == 1

    def test_algedonic_stuck_signal(self, tmp_path):
        """Stuck detection emite señal algedonic."""
        rsi = self._make_rsi(tmp_path)
        rsi._cycles_without_improvement = 5
        rsi.algedonic.check_stuck(5)
        assert rsi.algedonic.count("STUCK") >= 1


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
