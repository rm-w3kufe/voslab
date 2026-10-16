# design: projects/arc-prize/arc_prize_design.vsm
"""
rsi_orchestrator.py — S2: Ciclo RSI completo (observe→orient→decide→act→feedback).

Orquesta el ciclo de mejora autónoma:
  OBSERVE:  seleccionar puzzles unknown
  ORIENT:   LLM analiza y propone hipótesis
  DECIDE:   priorizar por impacto/confianza
  ACT:      validar y commit
  FEEDBACK: registrar resultado, algedonic signals

Uso:
    from rsi_orchestrator import RSIOrchestrator
    rsi = RSIOrchestrator()
    result = rsi.run_cycle(puzzles)
    session = rsi.run_session(max_cycles=10)
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from pattern_memory import PatternMemory
from strategy_sandbox import StrategySandbox
from strategy_validator import StrategyValidator, ValidationResult
from llm_proposer import LLMProposer, Hypothesis
from algedonic import Algedonic

# ── Types ────────────────────────────────────────────────────
Grid = np.ndarray
Trains = list
Puzzle = dict


@dataclass
class RSICycleResult:
    """Resultado de un ciclo RSI."""
    cycle_num: int
    puzzles_analyzed: int
    hypotheses_generated: int
    hypotheses_validated: int
    strategies_promoted: int
    strategies_rejected: int
    duration_ms: float
    improvements: list = field(default_factory=list)  # estrategias promovidas
    rejections: list = field(default_factory=list)    # razones de rechazo
    stuck: bool = False


@dataclass
class RSISessionResult:
    """Resultado de una sesión RSI completa."""
    total_cycles: int
    total_improvements: int
    total_rejections: int
    cycles: list = field(default_factory=list)  # list[RSICycleResult]
    stuck_at_cycle: Optional[int] = None
    duration_ms: float = 0.0


class RSIOrchestrator:
    """S2: Orquestador del ciclo RSI.

    Conecta S4 (LLM), S3 (validator), S5 (pattern_memory), S1 (strategies).

    Args:
        llm_proposer: LLMProposer para análisis
        sandbox: StrategySandbox para ejecución segura
        validator: StrategyValidator para validación
        pattern_memory: PatternMemory para persistencia
        algedonic: Algedonic para señales
        max_hypotheses_per_cycle: máximo de hipótesis a evaluar por ciclo
        batch_size: cuántos puzzles seleccionar por ciclo
        stuck_threshold: ciclos sin mejora antes de STUCK
    """

    def __init__(self, llm_proposer: Optional[LLMProposer] = None,
                 sandbox: Optional[StrategySandbox] = None,
                 validator: Optional[StrategyValidator] = None,
                 pattern_memory: Optional[PatternMemory] = None,
                 algedonic: Optional[Algedonic] = None,
                 max_hypotheses_per_cycle: int = 5,
                 batch_size: int = 10,
                 stuck_threshold: int = 5):
        self.llm = llm_proposer or LLMProposer()
        self.sandbox = sandbox or StrategySandbox()
        self.validator = validator or StrategyValidator()
        self.memory = pattern_memory or PatternMemory()
        self.algedonic = algedonic or Algedonic()
        self.max_hypotheses = max_hypotheses_per_cycle
        self.batch_size = batch_size
        self.stuck_threshold = stuck_threshold

        self._cycle_count = 0
        self._cycles_without_improvement = 0
        self._total_improvements = 0

    # ── Main entry points ────────────────────────────────────

    def run_cycle(self, puzzles: list, cycle_num: Optional[int] = None
                  ) -> RSICycleResult:
        """Ejecutar un ciclo RSI completo.

        Args:
            puzzles: lista de puzzles para analizar
            cycle_num: número de ciclo (auto-increment si None)

        Returns:
            RSICycleResult con resultado del ciclo
        """
        if cycle_num is None:
            self._cycle_count += 1
            cycle_num = self._cycle_count
        else:
            self._cycle_count = cycle_num

        start = time.monotonic()
        result = RSICycleResult(
            cycle_num=cycle_num,
            puzzles_analyzed=0,
            hypotheses_generated=0,
            hypotheses_validated=0,
            strategies_promoted=0,
            strategies_rejected=0,
            duration_ms=0,
        )

        # ── OBSERVE ──────────────────────────────────────────
        batch = self._observe(puzzles)
        result.puzzles_analyzed = len(batch)

        if not batch:
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # ── ORIENT ───────────────────────────────────────────
        hypotheses = self._orient(batch)
        result.hypotheses_generated = len(hypotheses)

        # ── DECIDE ───────────────────────────────────────────
        ranked = self._decide(hypotheses)

        # ── ACT ──────────────────────────────────────────────
        for pid, hyp in ranked[:self.max_hypotheses]:
            promoted, detail = self._act(hyp, batch)
            if promoted:
                result.strategies_promoted += 1
                result.improvements.append({
                    "name": hyp.text[:50],
                    "confidence": hyp.confidence,
                    "detail": detail,
                })
            else:
                result.strategies_rejected += 1
                result.rejections.append({
                    "name": hyp.text[:50],
                    "reason": detail,
                })

        # ── FEEDBACK ─────────────────────────────────────────
        self._feedback(result)

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    def run_session(self, puzzles: list, max_cycles: int = 10
                    ) -> RSISessionResult:
        """Ejecutar una sesión RSI completa.

        Args:
            puzzles: puzzles disponibles
            max_cycles: máximo de ciclos

        Returns:
            RSISessionResult con resumen de la sesión
        """
        session_start = time.monotonic()
        session = RSISessionResult(total_cycles=0, total_improvements=0,
                                   total_rejections=0)

        for i in range(max_cycles):
            cycle = self.run_cycle(puzzles, cycle_num=i + 1)
            session.cycles.append(cycle)
            session.total_cycles += 1
            session.total_improvements += cycle.strategies_promoted
            session.total_rejections += cycle.strategies_rejected

            # Stuck detection
            if self._cycles_without_improvement >= self.stuck_threshold:
                session.stuck_at_cycle = i + 1
                self.algedonic.stuck(self._cycles_without_improvement,
                                     f"session stuck at cycle {i+1}")
                break

            # No more unknowns
            if not self.memory.get_unknowns():
                break

        session.duration_ms = (time.monotonic() - session_start) * 1000
        return session

    # ── OBSERVE ──────────────────────────────────────────────

    def _observe(self, puzzles: list) -> list:
        """Seleccionar batch de puzzles para analizar.

        Prioriza:
        1. Puzzles no analizados aún
        2. Puzzles con patrones similares a los resueltos
        """
        unknowns = set(self.memory.get_unknowns())

        # Filter to puzzles we haven't analyzed yet
        candidates = []
        for p in puzzles:
            pid = p.get("id", str(id(p)))
            if pid in unknowns or pid not in self.memory.unknowns:
                candidates.append(p)

        # Register new unknowns
        for p in candidates[:self.batch_size]:
            pid = p.get("id", str(id(p)))
            if pid not in self.memory.unknowns:
                self.memory.record_unknown(pid)

        return candidates[:self.batch_size]

    # ── ORIENT ───────────────────────────────────────────────

    def _orient(self, batch: list) -> list:
        """LLM analiza puzzles y genera hipótesis."""
        hypotheses = []

        for puzzle in batch:
            pid = puzzle.get("id", str(id(puzzle)))

            # Check if LLM is available
            if not self.llm.is_available():
                # Fallback: create a basic hypothesis from features
                from llm_proposer import extract_features
                trains = puzzle.get("train", [])
                features = extract_features(trains)
                hyp = Hypothesis(
                    text=f"Unknown pattern: {features.shape_change} shape, "
                         f"{features.color_change} colors",
                    code="",
                    confidence=0.1,
                    rationale="LLM not available, feature-based guess",
                    features_used={
                        "shape_change": features.shape_change,
                        "color_change": features.color_change,
                    },
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                hypotheses.append((pid, hyp))
                continue

            # LLM analysis
            hyp = self.llm.propose(puzzle, self.memory)
            if hyp is not None:
                hypotheses.append((pid, hyp))
                self.memory.record_unknown(pid, hypothesis=hyp.text)

        return hypotheses

    # ── DECIDE ───────────────────────────────────────────────

    def _decide(self, hypotheses: list) -> list:
        """Priorizar hipótesis por impacto estimado.

        Score = 0.6 * confidence + 0.4 * feature_novelty
        """
        scored = []
        for pid, hyp in hypotheses:
            # Feature novelty: how different from known patterns
            novelty = self._compute_novelty(hyp)
            score = 0.6 * hyp.confidence + 0.4 * novelty
            scored.append((score, pid, hyp))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(pid, hyp) for _, pid, hyp in scored]

    def _compute_novelty(self, hyp: Hypothesis) -> float:
        """Qué tan novedoso es el patrón vs los conocidos."""
        if not hyp.features_used:
            return 0.5

        known_features = set()
        for p in self.memory.patterns.values():
            cat = p.get("category", "")
            known_features.add(cat)

        # If the hypothesis category is new, higher novelty
        feat_str = json.dumps(hyp.features_used, sort_keys=True)
        if feat_str in known_features:
            return 0.2
        return 0.7

    # ── ACT ──────────────────────────────────────────────────

    def _act(self, hyp: Hypothesis, batch: list) -> tuple:
        """Validar y promover estrategia si pasa.

        Returns:
            (promoted: bool, detail: str)
        """
        if not hyp.code:
            return False, "no_code"

        # Validate via sandbox + validator
        result = self.validator.validate_from_code(
            hyp.code, batch, name=hyp.text[:30]
        )

        if result.passed:
            # Promote: add to pattern memory
            self.memory.add_pattern(
                name=f"llm_{hyp.text[:20]}",
                category="llm_generated",
                description=hyp.text,
                strategy_fns=["llm_generated"],
                source="llm_proposed",
            )
            self.memory.record_unknown_result(
                hyp.features_used.get("puzzle_id", "?"),
                "llm_proposed",
                result.loo_score,
                status="solved",
            )
            self.algedonic.breakthrough("llm_proposer", hyp.text[:50])
            return True, result.summary()
        else:
            self.algedonic.pain("llm_proposer",
                                f"validation_fail:{result.summary()}")
            return False, result.summary()

    # ── FEEDBACK ─────────────────────────────────────────────

    def _feedback(self, cycle_result: RSICycleResult):
        """Registrar resultado del ciclo y actualizar contadores."""
        if cycle_result.strategies_promoted > 0:
            self._cycles_without_improvement = 0
            self._total_improvements += cycle_result.strategies_promoted
        else:
            self._cycles_without_improvement += 1

        # Save pattern memory
        self.memory.save()

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict:
        """Estado actual del orquestador."""
        return {
            "cycles_run": self._cycle_count,
            "total_improvements": self._total_improvements,
            "cycles_without_improvement": self._cycles_without_improvement,
            "stuck_threshold": self.stuck_threshold,
            "unknowns_remaining": len(self.memory.get_unknowns()),
            "patterns_active": len(self.memory.get_known_patterns()),
            "algedonic_summary": self.algedonic.summary(),
            "llm_available": self.llm.is_available(),
        }
