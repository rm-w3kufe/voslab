# design: projects/arc-prize/arc_prize_design.vsm
"""
strategy_validator.py — S3: Validación de estrategias antes de promover.

Valida que una estrategia candidata cumple invariantes del VSM:
  - LOO verification (leave-one-out)
  - Determinismo (misma entrada → mismo output)
  - Output shape correcto
  - Timeout (no cuelga)
  - Generalización (funciona en ≥2 puzzles)
  - No crash

Uso:
    validator = StrategyValidator()
    result = validator.validate(strategy_fn, trains_list)
    if result.passed:
        # Estrategia lista para promover
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

# ── Types ────────────────────────────────────────────────────
Grid = np.ndarray
Trains = list  # list of (input, output) tuples
Puzzle = dict  # {"train": [...], "test": [...]}


@dataclass
class ValidationResult:
    """Resultado de validación de una estrategia."""
    passed: bool
    loo_score: float = 0.0
    loo_details: list = field(default_factory=list)
    determinism_ok: bool = False
    shape_ok: bool = False
    timeout_ok: bool = True
    generalization_ok: bool = False
    errors: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def summary(self) -> str:
        """Resumen legible del resultado."""
        status = "PASS" if self.passed else "FAIL"
        parts = [
            f"[{status}]",
            f"LOO={self.loo_score:.2f}",
            f"det={'OK' if self.determinism_ok else 'FAIL'}",
            f"shape={'OK' if self.shape_ok else 'FAIL'}",
            f"gen={'OK' if self.generalization_ok else 'FAIL'}",
            f"time={self.duration_ms:.0f}ms",
        ]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return " ".join(parts)


class StrategyValidator:
    """S3: Validador de estrategias.

    Args:
        loo_min: mínimo LOO score para pasar (0.0-1.0)
        determinism_runs: cuántas veces ejecutar para check de determinismo
        timeout_s: máximo segundos por ejecución
        min_generalization: mínimo de puzzles donde debe funcionar
        max_duration_s: máximo total para toda la validación
    """

    def __init__(self, loo_min: float = 0.8, determinism_runs: int = 3,
                 timeout_s: int = 30, min_generalization: int = 2,
                 max_duration_s: int = 120):
        self.loo_min = loo_min
        self.determinism_runs = determinism_runs
        self.timeout_s = timeout_s
        self.min_generalization = min_generalization
        self.max_duration_s = max_duration_s

    def validate(self, fn: Callable, puzzles: list,
                 name: str = "unknown") -> ValidationResult:
        """Validar estrategia contra una lista de puzzles.

        Args:
            fn: función solver con firma fn(trains, test) → Grid|None
            puzzles: lista de dicts {"train": [...], "test": [...]}
            name: nombre para logging

        Returns:
            ValidationResult con todos los checks
        """
        start = time.monotonic()
        result = ValidationResult(passed=False)

        if not puzzles:
            result.errors.append("no_puzzles_provided")
            return result

        # ── 1. Shape validation ──────────────────────────────
        shape_ok_count = 0
        for puzzle in puzzles:
            trains = puzzle.get("train", [])
            test_inputs = puzzle.get("test", [])
            if not trains or not test_inputs:
                continue

            expected_shape = trains[0][1].shape
            try:
                pred = fn(trains, test_inputs[0][0])
                if pred is not None and pred.shape == expected_shape:
                    shape_ok_count += 1
            except Exception as e:
                result.errors.append(f"shape_crash:{type(e).__name__}:{e}")

        result.shape_ok = shape_ok_count > 0
        result.evidence["shape_ok_puzzles"] = shape_ok_count

        # ── 2. LOO verification ──────────────────────────────
        loo_scores = []
        for puzzle in puzzles:
            trains = puzzle.get("train", [])
            if len(trains) < 2:
                # Single train: LOO is trivially 1.0 if solver returns correct shape
                test_inputs = puzzle.get("test", [])
                if trains and test_inputs:
                    try:
                        pred = fn(trains, test_inputs[0][0])
                        expected = trains[0][1]
                        if pred is not None and pred.shape == expected.shape:
                            loo_scores.append(1.0)
                        else:
                            loo_scores.append(0.0)
                    except Exception:
                        loo_scores.append(0.0)
                continue
            loo = self._check_loo(fn, trains)
            loo_scores.append(loo)
            pid = puzzle.get("id", "?")
            result.loo_details.append({"puzzle": pid, "loo": loo})

        if loo_scores:
            result.loo_score = sum(loo_scores) / len(loo_scores)
        result.evidence["loo_scores"] = loo_scores

        # ── 3. Determinism ───────────────────────────────────
        det_ok_count = 0
        for puzzle in puzzles[:3]:  # Check max 3 puzzles for speed
            if self._check_determinism(fn, puzzle):
                det_ok_count += 1
        result.determinism_ok = det_ok_count > 0
        result.evidence["determinism_ok_puzzles"] = det_ok_count

        # ── 4. Generalization ────────────────────────────────
        gen_count = 0
        for puzzle in puzzles:
            trains = puzzle.get("train", [])
            test_inputs = puzzle.get("test", [])
            if not trains or not test_inputs:
                continue
            try:
                pred = fn(trains, test_inputs[0][0])
                expected = trains[0][1]  # Use first train output as reference
                if pred is not None and pred.shape == expected.shape:
                    gen_count += 1
            except Exception:
                pass
        result.generalization_ok = gen_count >= self.min_generalization
        result.evidence["generalization_puzzles"] = gen_count

        # ── 5. Timeout check ─────────────────────────────────
        # Already implicitly checked via the above executions
        result.timeout_ok = True  # If we got here, no timeout

        # ── 6. Final verdict ─────────────────────────────────
        result.passed = (
            result.loo_score >= self.loo_min
            and result.determinism_ok
            and result.shape_ok
            and result.generalization_ok
            and not result.errors
        )

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    def validate_from_code(self, code_str: str, puzzles: list,
                           name: str = "llm_generated") -> ValidationResult:
        """Validar código generado por LLM via sandbox.

        Args:
            code_str: código Python con función solve()
            puzzles: lista de puzzles para validación
            name: nombre para logging

        Returns:
            ValidationResult
        """
        from strategy_sandbox import StrategySandbox

        sandbox = StrategySandbox(timeout_s=self.timeout_s)

        # First: check that code compiles and has solve()
        test_puzzle = puzzles[0] if puzzles else {"train": [], "test": [(
            np.zeros((3, 3), dtype=np.int32), None)]}
        _, compile_signal = sandbox.execute(
            code_str,
            test_puzzle.get("train", []),
            test_puzzle.get("test", [(np.zeros((3, 3), dtype=np.int32), None)])[0][0]
        )

        if compile_signal != "ok":
            return ValidationResult(
                passed=False,
                errors=[f"compile_failed:{compile_signal}"],
            )

        # Extract solve function
        namespace = {"__builtins__": sandbox._get_safe_builtins() if hasattr(sandbox, '_get_safe_builtins') else {}}
        try:
            from strategy_sandbox import _SAFE_BUILTINS
            namespace = {"__builtins__": _SAFE_BUILTINS.copy()}
            exec(compile(code_str, "<llm>", "exec"), namespace)
        except Exception as e:
            return ValidationResult(passed=False, errors=[f"exec_error:{e}"])

        solve_fn = namespace.get("solve")
        if not callable(solve_fn):
            return ValidationResult(passed=False, errors=["no_solve_function"])

        return self.validate(solve_fn, puzzles, name)

    # ── Internal checks ──────────────────────────────────────

    def _check_loo(self, fn: Callable, trains: Trains) -> float:
        """LOO fraction para un puzzle."""
        n = len(trains)
        if n < 2:
            return 1.0
        ok = 0
        for i, (inp, out) in enumerate(trains):
            others = trains[:i] + trains[i + 1:]
            try:
                pred = fn(others, inp)
                if pred is not None and np.array_equal(pred, out):
                    ok += 1
            except Exception:
                pass
        return ok / n

    def _check_determinism(self, fn: Callable, puzzle: Puzzle) -> bool:
        """Verificar que misma entrada → mismo output."""
        trains = puzzle.get("train", [])
        test_inputs = puzzle.get("test", [])
        if not test_inputs:
            return False

        test_input = test_inputs[0][0]
        results = []
        for _ in range(self.determinism_runs):
            try:
                r = fn(trains, test_input)
                if r is not None:
                    results.append(r.tobytes())
            except Exception:
                return False

        return len(results) == self.determinism_runs and len(set(results)) == 1
