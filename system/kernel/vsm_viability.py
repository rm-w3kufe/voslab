"""vsm_viability.py — Omega(RSI-vOSlab) viability + caution governor.

Adapted from child vsm_wrapper.py (design only — that skeleton suspends
evaluate() itself and updates viability by blind +0.01 steps; both are
wrong here). vOSlab corrections:

  1. Caution suspends EVOLUTION (L3 cycles, learn-pipeline generations),
     never OBSERVATION. Blinding evaluation to "be safe" destroys the
     evidence the recovery needs.
  2. Dims come from MEASURED signals (reconciled rsi_identity):
     accuracy  := autonomy drill pass fraction (autonomy_cert.py)
     drift     := |latest - earliest| corpus pass_rate (health_history)
     stability := 1 - std(pass_rate window)
  3. Caution state persists (each tool call is a fresh process).
  4. Clearing requires an explicit human command (rsi-caution-clear,
     audited). No auto-clear, no timeout decay.

OMEGA = { accuracy >= 0.7 ^ drift <= 0.1 ^ stability >= 0.8 }.
"""
from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


OMEGA = {"accuracy_min": 0.7, "drift_max": 0.1, "stability_min": 0.8}


class CautionMode(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"


@dataclass
class ViabilityState:
    accuracy: float = 1.0
    drift: float = 0.0
    stability: float = 1.0

    def is_viable(self) -> bool:
        return (self.accuracy >= OMEGA["accuracy_min"]
                and self.drift <= OMEGA["drift_max"]
                and self.stability >= OMEGA["stability_min"])

    def margin_to_boundary(self) -> float:
        return min(self.accuracy - OMEGA["accuracy_min"],
                   OMEGA["drift_max"] - self.drift,
                   self.stability - OMEGA["stability_min"])

    def to_dict(self) -> dict:
        return {"accuracy": self.accuracy, "drift": self.drift,
                "stability": self.stability,
                "viable": self.is_viable(),
                "margin": round(self.margin_to_boundary(), 4)}


def _state_dir() -> Path:
    ws = Path(os.getcwd()).resolve()
    for _ in range(7):
        if (ws / "current_focus.json").is_file():
            break
        if ws.parent == ws:
            break
        ws = ws.parent
    return ws / "state" / "rsi"


def _caution_path() -> Path:
    env = os.environ.get("RSI_CAUTION_FILE")
    return Path(env) if env else _state_dir() / "caution.json"


def get_caution() -> dict:
    """Read caution state. Missing/corrupt file = INACTIVE (fail-open for
    observation; evolution gates check this explicitly)."""
    try:
        data = json.loads(_caution_path().read_text(encoding="utf-8"))
        if data.get("mode") == CautionMode.ACTIVE.value:
            return {"mode": "active", "since": data.get("since", ""),
                    "reason": data.get("reason", "")}
    except Exception:
        pass
    return {"mode": "inactive"}


def set_caution(reason: str) -> dict:
    """Activate caution (called by measurement, never by evolution)."""
    entry = {"mode": CautionMode.ACTIVE.value, "since": datetime.now(
        timezone.utc).isoformat(), "reason": reason}
    try:
        p = _caution_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(entry, indent=2))
    except Exception:
        pass
    return entry


def clear_caution(actor: str = "human") -> dict:
    """Explicit human clear (audited by the caller). No auto-clear."""
    try:
        p = _caution_path()
        if p.exists():
            p.unlink()
    except Exception:
        pass
    return {"mode": "inactive", "cleared_by": actor,
            "at": datetime.now(timezone.utc).isoformat()}


def evolution_allowed() -> tuple:
    """(allowed: bool, detail: dict) — the single gate for L3/learn/GA."""
    c = get_caution()
    if c["mode"] == "active":
        return False, {"reason": "caution active", "caution": c}
    return True, {}


# Degraded-mode ladder (Tranche B3, psi_protocol adapted):
# nominal -> shed (L3 only) -> quiesce (L3+learn) -> halt (observe only).
# Contracting is automatic (deterministic thresholds); expanding back
# ALWAYS requires human clear (fail-safe asymmetry, no auto-recovery).
def degraded_mode(margin: float, caution_active: bool) -> str:
    """Pure function: viability margin -> operating mode."""
    if caution_active:
        return "halt"
    if margin < 0.0:
        return "halt"
    if margin < 0.02:
        return "quiesce"
    if margin < 0.05:
        return "shed"
    return "nominal"


def mode_allows(mode: str, activity: str) -> bool:
    """What each mode permits. Observation/logging always allowed."""
    if activity in ("observe", "log", "metrics"):
        return True
    if mode == "nominal":
        return True
    if mode == "shed":
        return activity not in ("l3_cycle",)
    if mode == "quiesce":
        return activity not in ("l3_cycle", "learn_pipeline")
    return False  # halt: observe only


def _mode_path() -> Path:
    env = os.environ.get("RSI_MODE_FILE")
    return Path(env) if env else _state_dir() / "mode.json"


def read_mode() -> str:
    """Persisted operating mode (written by viability_check --write-mode)."""
    try:
        mode = json.loads(_mode_path().read_text()).get("mode", "nominal")
        return mode if mode in ("nominal", "shed", "quiesce", "halt") else "nominal"
    except Exception:
        return "nominal"


def write_mode(mode: str) -> str:
    if mode not in ("nominal", "shed", "quiesce", "halt"):
        raise ValueError(f"bad mode: {mode}")
    try:
        p = _mode_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mode": mode}))
    except Exception:
        pass
    return mode


def rsi_mode() -> str:
    """RSI_MODE switch (Tranche B4): CAPABILITY (default) or SAFE.

    SAFE disables generation paths (L3 + learn-pipeline) process-wide,
    keeping evaluation + learning-from-history. Set RSI_MODE=SAFE in env.
    """
    import os as _os
    return "SAFE" if _os.environ.get("RSI_MODE", "").upper() == "SAFE" else "CAPABILITY"


def measure(history_path: Path | None = None,
            cert_results: list | None = None) -> dict:
    """Compute Omega dims from measured signals (pure function)."""
    if history_path is None:
        history_path = _state_dir().parent / "health_history.jsonl"
    series: list[float] = []
    try:
        with open(history_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        series.append(float(json.loads(line)["corpus"]["pass_rate"]))
                    except Exception:
                        continue
    except OSError:
        pass
    window = series[-10:]
    drift = abs(window[-1] - window[0]) if len(window) >= 2 else 0.0
    stability = 1.0 - (statistics.pstdev(window) if len(window) >= 2 else 0.0)
    if cert_results is None:
        accuracy = None
    else:
        accuracy = (sum(1 for r in cert_results if r.get("pass"))
                    / len(cert_results)) if cert_results else None
    state = ViabilityState(
        accuracy=accuracy if accuracy is not None else 1.0,
        drift=round(drift, 4), stability=round(stability, 4))
    return {"omega": OMEGA,
            "dims": {"accuracy": accuracy, "drift": state.drift,
                     "stability": state.stability},
            "inside": state.is_viable() if accuracy is not None else None,
            "margin": state.margin_to_boundary(),
            "series_points": len(window)}
