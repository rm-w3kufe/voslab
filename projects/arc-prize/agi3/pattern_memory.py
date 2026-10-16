# design: projects/arc-prize/arc_prize_design.vsm
"""
pattern_memory.py — S5: Inventario maestro de patrones conocidos.

Componente S5 del VSM-ARC-RSI. Persiste qué patrones conocemos,
cuáles resuelven puzzles, y qué unknowns quedan por resolver.

Uso:
    pm = PatternMemory.load()  # carga de disco
    pm.record_solved("crop", "abc123")
    pm.record_unknown("abc123", hypothesis="posible rearrangement")
    pm.save()
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

# ── State directory ──────────────────────────────────────────
_STATE_DIR = Path(__file__).parent / "state"
_MEMORY_FILE = _STATE_DIR / "pattern_memory.json"


class PatternMemory:
    """Inventario maestro de patrones (S5)."""

    def __init__(self, data: Optional[dict] = None):
        if data is None:
            data = self._empty()
        self.patterns: dict = data.get("patterns", {})
        self.unknowns: dict = data.get("unknowns", {})
        self.meta: dict = data.get("meta", self._empty_meta())

    # ── Factory ──────────────────────────────────────────────

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PatternMemory":
        """Cargar desde disco. Si no existe, crea vacío."""
        path = path or _MEMORY_FILE
        if path.exists():
            with open(path) as f:
                return cls(json.load(f))
        return cls()

    @classmethod
    def from_dynamics(cls, dynamics: list) -> "PatternMemory":
        """Crear desde la lista DYNAMICS de recognizer.py.

        Cada dynamic es un tuple: (name, detector, strategies, arc3_family)
        """
        pm = cls()
        for name, detector, strategies, family in dynamics:
            strat_names = []
            if strategies:
                strat_names = [s.__name__ for s in strategies]
            pm.patterns[name] = {
                "category": family,
                "description": f"Dynamic: {name}",
                "strategy_fns": strat_names,
                "detected_in": [],
                "solved_in": [],
                "precision": 0.0,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": "manual",
                "status": "active",
            }
        pm._update_meta()
        return pm

    # ── Queries ──────────────────────────────────────────────

    def get_known_patterns(self, status: str = "active") -> list:
        """Retorna patrones activos (o todos si status=None)."""
        if status is None:
            return list(self.patterns.keys())
        return [k for k, v in self.patterns.items() if v.get("status") == status]

    def get_unknowns(self) -> list:
        """Lista de puzzle IDs aún sin resolver."""
        return [
            pid for pid, info in self.unknowns.items()
            if info.get("status") == "unsolved"
        ]

    def get_solved(self) -> list:
        """Lista de puzzle IDs resueltos."""
        solved = set()
        for p in self.patterns.values():
            solved.update(p.get("solved_in", []))
        return list(solved)

    def get_pattern(self, name: str) -> Optional[dict]:
        """Obtener info de un patrón específico."""
        return self.patterns.get(name)

    def stats(self) -> dict:
        """Estadísticas del inventario."""
        self._update_meta()
        return self.meta.copy()

    # ── Mutations ────────────────────────────────────────────

    def record_detected(self, pattern_name: str, puzzle_id: str):
        """Registrar que un patrón detectó un puzzle."""
        if pattern_name not in self.patterns:
            return
        detected = self.patterns[pattern_name].setdefault("detected_in", [])
        if puzzle_id not in detected:
            detected.append(puzzle_id)

    def record_solved(self, pattern_name: str, puzzle_id: str):
        """Registrar que un patrón resolvió un puzzle."""
        if pattern_name not in self.patterns:
            return
        solved = self.patterns[pattern_name].setdefault("solved_in", [])
        if puzzle_id not in solved:
            solved.append(puzzle_id)
        # Actualizar precisión
        det = len(self.patterns[pattern_name].get("detected_in", []))
        sol = len(solved)
        self.patterns[pattern_name]["precision"] = sol / det if det > 0 else 0.0

    def record_unknown(self, puzzle_id: str, hypothesis: str = "",
                       status: str = "unsolved"):
        """Registrar un puzzle como unknown (no resuelto aún)."""
        self.unknowns[puzzle_id] = {
            "hypothesis": hypothesis,
            "tried_strategies": [],
            "best_score": 0.0,
            "status": status,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def record_unknown_result(self, puzzle_id: str, strategy: str,
                              score: float, status: str = "unsolved"):
        """Actualizar resultado de intento sobre un unknown."""
        if puzzle_id not in self.unknowns:
            self.record_unknown(puzzle_id)
        info = self.unknowns[puzzle_id]
        info["tried_strategies"].append(strategy)
        if score > info.get("best_score", 0.0):
            info["best_score"] = score
        info["status"] = status
        info["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def add_pattern(self, name: str, category: str, description: str,
                    strategy_fns: list, source: str = "manual"):
        """Agregar un nuevo patrón al inventario."""
        self.patterns[name] = {
            "category": category,
            "description": description,
            "strategy_fns": strategy_fns,
            "detected_in": [],
            "solved_in": [],
            "precision": 0.0,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": source,
            "status": "active",
        }

    def promote_pattern(self, name: str):
        """Promover patrón a activo."""
        if name in self.patterns:
            self.patterns[name]["status"] = "active"

    def deprecate_pattern(self, name: str, reason: str = ""):
        """Deprecar un patrón."""
        if name in self.patterns:
            self.patterns[name]["status"] = "deprecated"
            self.patterns[name]["deprecated_reason"] = reason

    # ── Persistence ──────────────────────────────────────────

    def save(self, path: Optional[Path] = None):
        """Guardar a disco."""
        path = path or _MEMORY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        self._update_meta()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({
                "patterns": self.patterns,
                "unknowns": self.unknowns,
                "meta": self.meta,
            }, f, indent=2)
        tmp.rename(path)

    # ── Internal ─────────────────────────────────────────────

    def _update_meta(self):
        active = sum(1 for p in self.patterns.values() if p.get("status") == "active")
        solved_ids = set()
        for p in self.patterns.values():
            solved_ids.update(p.get("solved_in", []))
        unsolved = sum(1 for u in self.unknowns.values() if u.get("status") == "unsolved")
        self.meta = {
            "total_patterns": len(self.patterns),
            "active_patterns": active,
            "total_solved": len(solved_ids),
            "total_unknowns": len(self.unknowns),
            "unsolved_remaining": unsolved,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @staticmethod
    def _empty() -> dict:
        return {"patterns": {}, "unknowns": {}, "meta": {}}

    @staticmethod
    def _empty_meta() -> dict:
        return {
            "total_patterns": 0,
            "active_patterns": 0,
            "total_solved": 0,
            "total_unknowns": 0,
            "unsolved_remaining": 0,
            "last_updated": "",
        }
