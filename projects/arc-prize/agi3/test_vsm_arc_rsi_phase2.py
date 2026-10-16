# design: projects/arc-prize/arc_prize_design.vsm
"""
test_vsm_arc_rsi_phase2.py — Tests para Fase 2: sandbox + llm_proposer.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from strategy_sandbox import StrategySandbox, SecurityError, ValidationError
from llm_proposer import (
    LLMProposer, Hypothesis, PuzzleFeatures,
    extract_features, features_to_text, grid_to_text,
)


# ── Helpers ──────────────────────────────────────────────────

def _g(rows, cols, fill=0):
    return np.full((rows, cols), fill, dtype=np.int32)


# ── Tests: StrategySandbox ───────────────────────────────────

class TestStrategySandbox:

    def test_valid_code(self):
        code = """
def solve(trains, test):
    return test.copy()
"""
        sb = StrategySandbox(timeout_s=5)
        result, signal = sb.execute(code, [], _g(3, 3, 5))
        assert signal == "ok"
        assert result is not None
        assert np.array_equal(result, _g(3, 3, 5))

    def test_invalid_syntax(self):
        code = "def solve("  # syntax error
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "compile_error" in signal or "syntax" in signal.lower()

    def test_no_solve_function(self):
        code = "x = 42"
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert signal == "no_solve_function"

    def test_forbidden_import(self):
        code = """
import os
def solve(trains, test):
    return test.copy()
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "security_error" in signal

    def test_forbidden_open(self):
        code = """
def solve(trains, test):
    open("/etc/passwd")
    return test.copy()
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "security_error" in signal

    def test_timeout(self):
        code = """
import time
def solve(trains, test):
    time.sleep(100)
    return test.copy()
"""
        sb = StrategySandbox(timeout_s=1)
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "timeout" in signal

    def test_crash_handling(self):
        code = """
def solve(trains, test):
    raise ValueError("boom")
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "crash" in signal

    def test_return_none(self):
        code = """
def solve(trains, test):
    return None
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert signal == "returned_none"

    def test_wrong_type(self):
        code = """
def solve(trains, test):
    return "not a grid"
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "wrong_type" in signal

    def test_wrong_dims(self):
        code = """
import numpy as np
def solve(trains, test):
    return np.array([1, 2, 3])
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "wrong_dims" in signal

    def test_non_integer_dtype(self):
        code = """
import numpy as np
def solve(trains, test):
    return np.array([[1.5, 2.5], [3.5, 4.5]])
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(2, 2))
        # Should auto-convert or error
        assert signal in ("ok", "non_integer_dtype")

    def test_with_trains(self):
        code = """
import numpy as np
def solve(trains, test):
    # Simple: copy input to output
    return test.copy()
"""
        trains = [(_g(2, 2, 1), _g(2, 2, 1))]
        sb = StrategySandbox()
        result, signal = sb.execute(code, trains, _g(2, 2, 5))
        assert signal == "ok"

    def test_forbidden_exec(self):
        code = """
def solve(trains, test):
    exec("import os")
    return test.copy()
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3))
        assert "security_error" in signal

    def test_numpy_allowed(self):
        code = """
import numpy as np
def solve(trains, test):
    return np.rot90(test)
"""
        sb = StrategySandbox()
        result, signal = sb.execute(code, [], _g(3, 3, 5))
        assert signal == "ok"
        assert result is not None


# ── Tests: Feature extraction ────────────────────────────────

class TestFeatureExtraction:

    def test_same_shape(self):
        trains = [(_g(3, 3, 1), _g(3, 3, 2))]
        f = extract_features(trains)
        assert f.shape_change == "same"
        assert f.input_colors == 1
        assert f.output_colors == 1

    def test_bigger_output(self):
        trains = [(_g(2, 2, 1), _g(4, 4, 1))]
        f = extract_features(trains)
        assert f.shape_change == "bigger"
        assert f.size_ratio == 4.0

    def test_smaller_output(self):
        trains = [(_g(4, 4, 1), _g(2, 2, 1))]
        f = extract_features(trains)
        assert f.shape_change == "smaller"
        assert f.size_ratio == 0.25

    def test_more_colors(self):
        inp = np.array([[1, 1], [1, 1]], dtype=np.int32)
        out = np.array([[1, 2], [3, 4]], dtype=np.int32)
        f = extract_features([(inp, out)])
        assert f.color_change == "more"

    def test_empty_trains(self):
        f = extract_features([])
        assert f.shape_change == "unknown"

    def test_features_to_text(self):
        f = PuzzleFeatures(
            input_shapes=[(3, 3)], output_shapes=[(3, 3)],
            shape_change="same", input_colors=2, output_colors=2,
            color_change="same", input_objects=1, output_objects=1,
            object_change="same", symmetry="none", size_ratio=1.0,
        )
        text = features_to_text(f)
        assert "same" in text
        assert "2" in text

    def test_grid_to_text(self):
        g = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.int32)
        text = grid_to_text(g)
        assert "1 2 3" in text
        assert "4 5 6" in text


# ── Tests: LLMProposer (sin Ollama) ─────────────────────────

class TestLLMProposer:

    def test_not_available(self):
        """Sin Ollama corriendo, is_available() retorna False."""
        proposer = LLMProposer(url="http://localhost:99999")
        assert proposer.is_available() is False

    def test_propose_returns_none_without_ollama(self):
        """propose() retorna None si Ollama no está disponible."""
        proposer = LLMProposer(url="http://localhost:99999")
        puzzle = {"train": [(_g(3, 3, 1), _g(3, 3, 2))], "test": [(_g(3, 3, 3), None)]}
        result = proposer.propose(puzzle)
        assert result is None

    def test_build_prompt(self):
        """Prompt contains key elements."""
        proposer = LLMProposer()
        puzzle = {"train": [(_g(3, 3, 1), _g(3, 3, 2))], "test": []}
        features = extract_features(puzzle["train"])
        prompt = proposer._build_prompt(puzzle, features)
        assert "ARC puzzle" in prompt
        assert "HYPOTHESIS" in prompt
        assert "def solve" in prompt

    def test_parse_response_valid(self):
        """Parsear respuesta bien formateada."""
        proposer = LLMProposer()
        raw = """HYPOTHESIS: Color inversion
CONFIDENCE: 0.8
RATIONALE: Colors are inverted
CODE:
```python
import numpy as np
def solve(trains, test):
    return 9 - test
```"""
        features = PuzzleFeatures(
            [(3,3)], [(3,3)], "same", 2, 2, "same", 1, 1, "same", "none", 1.0
        )
        h = proposer._parse_response(raw, features)
        assert h is not None
        assert h.confidence == 0.8
        assert "solve" in h.code

    def test_parse_response_no_code(self):
        """Respuesta sin código retorna None."""
        proposer = LLMProposer()
        raw = "HYPOTHESIS: something\nCONFIDENCE: 0.5\nRATIONALE: because"
        features = PuzzleFeatures(
            [(3,3)], [(3,3)], "same", 2, 2, "same", 1, 1, "same", "none", 1.0
        )
        h = proposer._parse_response(raw, features)
        assert h is None


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
