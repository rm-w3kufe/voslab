# design: projects/arc-prize/arc_prize_design.vsm
"""
strategy_vsm.py — S1: Wrapper que convierte una función solver en micro-VSM.

Cada estrategia es un VSM recursivo con:
  S5: identidad (nombre, categoría, autor)
  S4: detector (¿cuándo aplicar?)
  S3: invariantes (LOO min, determinismo)
  S2: algedonic (señal de éxito/fallo)
  S1: lógica de transformación

Uso:
    from recognizer import try_crop_content, d_crop
    s = StrategyVSM("crop", try_crop_content, d_crop, "explore-cursor")
    result, signal = s.execute(puzzle)
"""

import time
import traceback
from typing import Callable, Optional, Tuple

import numpy as np

# ── Types ────────────────────────────────────────────────────
Grid = np.ndarray
Trains = list  # list of (input, output) tuples
Puzzle = dict  # {"train": [...], "test": [...]}


class AlgedonicSignal:
    """Señal de dolor/placer que viaja a S2."""
    PAIN = "PAIN"
    PLEASURE = "PLEASURE"
    NEUTRAL = "NEUTRAL"


class StrategyVSM:
    """Micro-VSM: cada estrategia como sistema viable autónomo.

    Attributes:
        # S5: identidad
        name: Nombre de la estrategia
        category: Familia ARC-AGI-3 (explore-cursor, interact-paint, etc.)
        author: "manual" | "llm:<model>" | "rsi:<cycle>"
        created_at: Timestamp ISO

        # S4: detector
        detector: Función que decide si esta estrategia aplica

        # S3: invariantes
        invariants: Dict con umbrales de validación

        # S2: algedonic
        last_signal: Última señal emitida
        signal_history: Historial de señales

        # S1: lógica
        solve: Función solver
    """

    def __init__(
        self,
        name: str,
        solve: Callable,
        detector: Optional[Callable] = None,
        category: str = "unknown",
        author: str = "manual",
        invariants: Optional[dict] = None,
    ):
        # S5: identidad
        self.name = name
        self.category = category
        self.author = author
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # S4: detector
        self.detector = detector

        # S3: invariantes
        self.invariants = invariants or {
            "loo_min": 0.8,
            "deterministic": True,
            "timeout_s": 30,
        }

        # S2: algedonic
        self.last_signal = AlgedonicSignal.NEUTRAL
        self.signal_history: list = []

        # S1: lógica
        self.solve = solve

    # ── S1: Execute ──────────────────────────────────────────

    def execute(self, puzzle: Puzzle, trains: Optional[Trains] = None
                ) -> Tuple[Optional[Grid], str]:
        """Ejecutar estrategia + validar + emitir algedonic.

        Args:
            puzzle: dict con "train" y "test" pairs
            trains: optional trains override (si no, usa puzzle["train"])

        Returns:
            (grid_result, signal_string)
            signal_string: "success:<loo>" | "not_applicable" | "loo_fail:<score>"
                          | "crash:<error>" | "timeout" | "wrong_shape"
        """
        trains = trains or puzzle.get("train", [])

        # S4: detector check
        if self.detector is not None:
            try:
                if not self.detector(trains):
                    return None, "not_applicable"
            except Exception as e:
                self._emit_pain(f"detector_crash:{e}")
                return None, f"detector_crash:{e}"

        # S1: ejecutar solver
        try:
            test_inputs = puzzle.get("test", [])
            if not test_inputs:
                return None, "no_test_inputs"

            result = self.solve(trains, test_inputs[0][0])
            if result is None:
                self._emit_pain("solver_returned_none")
                return None, "solver_returned_none"
        except Exception as e:
            self._emit_pain(f"crash:{e}")
            return None, f"crash:{e}"

        # S3: validar output shape
        if trains:
            expected_shape = trains[0][1].shape
            if result.shape != expected_shape:
                self._emit_pain(f"wrong_shape:{result.shape}!={expected_shape}")
                return None, f"wrong_shape:{result.shape}"

        # S3: LOO verification
        if trains and len(trains) >= 2:
            loo = self._quick_loo(trains)
            if loo < self.invariants["loo_min"]:
                self._emit_pain(f"loo_fail:{loo}")
                return None, f"loo_fail:{loo}"
            signal = f"success:{loo}"
        else:
            signal = "success:no_loo_single_train"

        self._emit_pleasure(signal)
        return result, signal

    # ── S3: Validation helpers ───────────────────────────────

    def _quick_loo(self, trains: Trains) -> float:
        """LOO verification rápido (misma lógica que recognizer.py)."""
        n = len(trains)
        if n < 2:
            return 1.0
        ok = 0
        for i, (inp, out) in enumerate(trains):
            others = trains[:i] + trains[i + 1:]
            try:
                pred = self.solve(others, inp)
                if pred is not None and np.array_equal(pred, out):
                    ok += 1
            except Exception:
                pass
        return ok / n

    def check_determinism(self, puzzle: Puzzle, runs: int = 3) -> bool:
        """Verificar que misma entrada → mismo output."""
        trains = puzzle.get("train", [])
        test_inputs = puzzle.get("test", [])
        if not test_inputs:
            return False

        results = []
        for _ in range(runs):
            try:
                r = self.solve(trains, test_inputs[0][0])
                if r is not None:
                    results.append(r.tobytes())
            except Exception:
                return False

        return len(results) == runs and len(set(results)) == 1

    # ── S2: Algedonic ────────────────────────────────────────

    def _emit_pain(self, detail: str):
        """Señal de dolor → S2."""
        self.last_signal = AlgedonicSignal.PAIN
        self.signal_history.append({
            "signal": AlgedonicSignal.PAIN,
            "detail": detail,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def _emit_pleasure(self, detail: str):
        """Señal de placer → S2."""
        self.last_signal = AlgedonicSignal.PLEASURE
        self.signal_history.append({
            "signal": AlgedonicSignal.PLEASURE,
            "detail": detail,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def pain_count(self) -> int:
        """Número total de señales de dolor."""
        return sum(1 for s in self.signal_history if s["signal"] == AlgedonicSignal.PAIN)

    def pleasure_count(self) -> int:
        """Número total de señales de placer."""
        return sum(1 for s in self.signal_history if s["signal"] == AlgedonicSignal.PLEASURE)

    # ── S5: Identity ─────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serializar a dict (para pattern_memory)."""
        return {
            "name": self.name,
            "category": self.category,
            "author": self.author,
            "created_at": self.created_at,
            "invariants": self.invariants,
            "pain_count": self.pain_count(),
            "pleasure_count": self.pleasure_count(),
            "last_signal": self.last_signal,
        }

    def __repr__(self):
        return (f"StrategyVSM({self.name!r}, cat={self.category}, "
                f"author={self.author}, signals={len(self.signal_history)})")


# ── Registry ─────────────────────────────────────────────────
# Registro global de estrategias VSM
_REGISTRY: dict = {}  # name → StrategyVSM


def register(strategy: StrategyVSM):
    """Registrar estrategia en el pool global."""
    _REGISTRY[strategy.name] = strategy


def get_registry() -> dict:
    """Obtener registry (copia)."""
    return _REGISTRY.copy()


def get_strategy(name: str) -> Optional[StrategyVSM]:
    """Obtener estrategia por nombre."""
    return _REGISTRY.get(name)


# ── Convenience: wrappear funciones existentes ───────────────

def wrap_existing(name: str, solve_fn: Callable, detector_fn: Optional[Callable] = None,
                  category: str = "unknown", author: str = "manual") -> StrategyVSM:
    """Envolver una función solver existente como StrategyVSM.

    Utility para wrappear funciones de recognizer.py sin modificar su código.
    """
    s = StrategyVSM(name, solve_fn, detector_fn, category, author)
    register(s)
    return s
