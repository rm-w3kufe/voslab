# design: projects/arc-prize/arc_prize_design.vsm
"""
algedonic.py — S2: Señales de dolor/placer del sistema.

El canal algedonic viaja directamente a S5 sin pasar por el loop
normal de coordinación. Señales de breakthrough/stuck llegan al
humano (S5) para que decida.

Señales:
  PAIN:      estrategia falló (LOO < umbral, crash, timeout)
  PLEASURE:  estrategia funcionó (LOO ≥ umbral, commit exitoso)
  BREAKTHROUGH: nueva dinámica activada (+1 resuelto)
  STUCK:     N ciclos sin mejora → necesita intervención S5
  ANOMALY:   comportamiento inesperado (determinismo falla, etc.)

Uso:
    algedonic = Algedonic()
    algedonic.emit("PAIN", "crop", "loo_fail:0.5")
    algedonic.emit("BREAKTHROUGH", "new_dynamic", "shrink_square")
    stuck = algedonic.check_stuck(cycles_without_improvement=5)
"""

import json
import time
from pathlib import Path
from typing import Optional

_STATE_DIR = Path(__file__).parent / "state"
_LOG_FILE = _STATE_DIR / "algedonic_log.jsonl"


class Algedonic:
    """Canal algedonic: señales de dolor/placer → S5."""

    # Tipos de señal
    PAIN = "PAIN"
    PLEASURE = "PLEASURE"
    BREAKTHROUGH = "BREAKTHROUGH"
    STUCK = "STUCK"
    ANOMALY = "ANOMALY"

    # Thresholds
    STUCK_THRESHOLD = 5  # ciclos sin mejora antes de STUCK

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or _LOG_FILE
        self._signals: list = []
        self._load()

    # ── Emit ─────────────────────────────────────────────────

    def emit(self, signal_type: str, source: str, detail: str = "",
             impact: float = 0.0):
        """Emitir señal algedonic.

        Args:
            signal_type: PAIN | PLEASURE | BREAKTHROUGH | STUCK | ANOMALY
            source: nombre de la estrategia o componente
            detail: descripción del evento
            impact: impacto numérico (ej: +1 resuelto, score delta)
        """
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "signal": signal_type,
            "source": source,
            "detail": detail,
            "impact": impact,
        }
        self._signals.append(entry)
        self._append_log(entry)

    def pain(self, source: str, detail: str = ""):
        """Atajo para señal de dolor."""
        self.emit(self.PAIN, source, detail)

    def pleasure(self, source: str, detail: str = ""):
        """Atajo para señal de placer."""
        self.emit(self.PLEASURE, source, detail)

    def breakthrough(self, source: str, detail: str = ""):
        """Atajo para breakthrough (nueva dinámica activada)."""
        self.emit(self.BREAKTHROUGH, source, detail, impact=1.0)

    def stuck(self, cycles: int, detail: str = ""):
        """Atajo para stuck (N ciclos sin mejora)."""
        self.emit(self.STUCK, "rsi_loop", f"cycles={cycles} {detail}")

    def anomaly(self, source: str, detail: str = ""):
        """Atajo para anomalía."""
        self.emit(self.ANOMALY, source, detail)

    # ── Query ────────────────────────────────────────────────

    def recent(self, n: int = 10) -> list:
        """Últimas N señales."""
        return self._signals[-n:]

    def count(self, signal_type: Optional[str] = None) -> int:
        """Contar señales (de un tipo específico si se pide)."""
        if signal_type is None:
            return len(self._signals)
        return sum(1 for s in self._signals if s["signal"] == signal_type)

    def pain_count(self) -> int:
        return self.count(self.PAIN)

    def pleasure_count(self) -> int:
        return self.count(self.PLEASURE)

    def breakthrough_count(self) -> int:
        return self.count(self.BREAKTHROUGH)

    def summary(self) -> dict:
        """Resumen de señales emitidas."""
        return {
            "total": len(self._signals),
            "pain": self.pain_count(),
            "pleasure": self.pleasure_count(),
            "breakthroughs": self.breakthrough_count(),
            "stuck": self.count(self.STUCK),
            "anomalies": self.count(self.ANOMALY),
        }

    # ── Stuck detection ──────────────────────────────────────

    def check_stuck(self, cycles_without_improvement: int) -> bool:
        """¿Está el sistema stuck?

        Retorna True si lleva demasiados ciclos sin mejora.
        Emite señal STUCK si cruza el threshold.
        """
        if cycles_without_improvement >= self.STUCK_THRESHOLD:
            self.stuck(cycles_without_improvement,
                       "no improvement in last cycles")
            return True
        return False

    # ── Persistence ──────────────────────────────────────────

    def _append_log(self, entry: dict):
        """Append al JSONL log (crash-safe)."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _load(self):
        """Cargar señales previas del log."""
        if self.log_path.exists():
            with open(self.log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._signals.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

    def clear(self):
        """Limpiar señales en memoria (no toca disco)."""
        self._signals.clear()

    def reset_log(self):
        """Resetear log completo (CUIDADO: destructivo)."""
        if self.log_path.exists():
            self.log_path.unlink()
        self._signals.clear()
