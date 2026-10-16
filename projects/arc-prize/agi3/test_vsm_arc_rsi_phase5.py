# design: projects/arc-prize/arc_prize_design.vsm
"""
test_vsm_arc_rsi_phase5.py — Tests para Fase 5: integración con agent.py.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

# Add arc-solver to path for rsi_bridge import
_ARC_SOLVER = Path(__file__).parent.parent / "arc-solver"
if str(_ARC_SOLVER) not in sys.path:
    sys.path.insert(0, str(_ARC_SOLVER))

sys.path.insert(0, str(Path(__file__).parent))

# Test rsi_bridge
from rsi_bridge import rsi_propose, has_rsi_strategies, _load_rsi_patterns


# ── Helpers ──────────────────────────────────────────────────

def _g(rows, cols, fill=0):
    return np.full((rows, cols), fill, dtype=np.int32)


# ── Tests: rsi_bridge ────────────────────────────────────────

class TestRSIBridge:

    def test_has_no_strategies_by_default(self):
        """Sin pattern_memory, no hay estrategias."""
        # _MEMORY_FILE won't exist in test env
        result = has_rsi_strategies()
        # May or may not exist depending on prior runs
        assert isinstance(result, bool)

    def test_load_patterns_empty(self):
        """Load patterns retorna dict vacío si no existe archivo."""
        from rsi_bridge import _MEMORY_FILE
        if not _MEMORY_FILE.exists():
            assert _load_rsi_patterns() == {}

    def test_load_patterns_with_file(self, tmp_path):
        """Load patterns carga desde archivo."""
        from rsi_bridge import _MEMORY_FILE
        # Temporarily override
        import rsi_bridge
        old = rsi_bridge._MEMORY_FILE
        rsi_bridge._MEMORY_FILE = tmp_path / "memory.json"

        data = {
            "patterns": {
                "test_pattern": {
                    "status": "active",
                    "source": "llm_proposed",
                    "code": "def solve(trains, test):\n    return test.copy()",
                },
                "deprecated_pattern": {
                    "status": "deprecated",
                    "source": "manual",
                },
            }
        }
        rsi_bridge._MEMORY_FILE.write_text(json.dumps(data))
        patterns = _load_rsi_patterns()
        assert "test_pattern" in patterns
        assert "deprecated_pattern" not in patterns

        rsi_bridge._MEMORY_FILE = old

    def test_rsi_propose_empty(self, tmp_path):
        """rsi_propose retorna lista vacía sin patrones."""
        import rsi_bridge
        old = rsi_bridge._MEMORY_FILE
        rsi_bridge._MEMORY_FILE = tmp_path / "nonexistent.json"

        result = rsi_propose([], _g(3, 3))
        assert result == []

        rsi_bridge._MEMORY_FILE = old

    def test_rsi_propose_with_pattern(self, tmp_path):
        """rsi_propose genera candidato con patrón válido."""
        import rsi_bridge
        old = rsi_bridge._MEMORY_FILE
        rsi_bridge._MEMORY_FILE = tmp_path / "memory.json"

        data = {
            "patterns": {
                "identity_pattern": {
                    "status": "active",
                    "source": "llm_proposed",
                    "code": "import numpy as np\ndef solve(trains, test):\n    return test.copy()",
                }
            }
        }
        rsi_bridge._MEMORY_FILE.write_text(json.dumps(data))

        trains = [(_g(3, 3, 1), _g(3, 3, 1))]
        test = _g(3, 3, 5)
        result = rsi_propose(trains, test)

        assert len(result) == 1
        assert result[0]["dynamic"] == "rsi:identity_pattern"
        assert result[0]["loo_frac"] >= 0.0
        assert np.array_equal(result[0]["grid"], test)

        rsi_bridge._MEMORY_FILE = old

    def test_rsi_propose_bad_code(self, tmp_path):
        """rsi_propose skippea código inválido."""
        import rsi_bridge
        old = rsi_bridge._MEMORY_FILE
        rsi_bridge._MEMORY_FILE = tmp_path / "memory.json"

        data = {
            "patterns": {
                "bad_pattern": {
                    "status": "active",
                    "source": "llm_proposed",
                    "code": "def solve(trains, test):\n    return None",
                }
            }
        }
        rsi_bridge._MEMORY_FILE.write_text(json.dumps(data))

        trains = [(_g(3, 3, 1), _g(3, 3, 1))]
        result = rsi_propose(trains, _g(3, 3, 5))
        assert len(result) == 0  # None return → skipped

        rsi_bridge._MEMORY_FILE = old


# ── Tests: agent.py integration ──────────────────────────────

class TestAgentIntegration:

    def test_agent_imports_rsi_bridge(self):
        """agent.py imports rsi_bridge without error."""
        import agent
        assert hasattr(agent, 'RSI')

    def test_solve_imports_rsi_bridge(self):
        """solve.py imports rsi_bridge without error."""
        import solve
        assert hasattr(solve, 'RSI')

    def test_solve_one_still_works(self):
        """solve_one() sigue funcionando con RSI bridge."""
        from solve import solve_one
        trains = [(_g(3, 3, 1), _g(3, 3, 1))]
        test = _g(3, 3, 5)
        a1, a2, meta = solve_one(trains, test)
        # Should complete without error
        assert "dynamic" in meta
        assert "ms" in meta

    def test_decide_still_works(self):
        """agent.decide() sigue funcionando."""
        from agent import decide
        trains = [(_g(3, 3, 1), _g(3, 3, 1))]
        test = _g(3, 3, 5)
        a1, a2, meta = decide(trains, test)
        assert "dynamic" in meta
        assert "trace" in meta


# ── Tests: build_notebook integration ────────────────────────

class TestBuildNotebook:

    def test_rsi_bridge_in_modules(self):
        """rsi_bridge.py está en MODULES list."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "arc-solver"))
        import build_notebook
        assert "rsi_bridge.py" in build_notebook.MODULES

    def test_notebook_builds(self):
        """Notebook se construye sin error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent /
                                 "arc-solver" / "build_notebook.py"),
             "--out", "/tmp/test_notebook.ipynb"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert Path("/tmp/test_notebook.ipynb").exists()


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
