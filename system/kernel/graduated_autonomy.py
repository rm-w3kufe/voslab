"""graduated_autonomy.py — Earned per-class autonomy (Tranche B1).

Upstream s5_policy_core graduated_autonomy, adapted: each autonomy class
earns trust (tau) from measured outcomes; graduation is PROPOSED via the
approval queue, never self-granted (S5 ratifies — the ceiling holds).

Classes: l1_thresholds, l2_wrappers, l3_strategies.
tau update: +0.02 per clean session window, -0.20 per caution/fault event,
bounds [0, 1], start 0.5. Graduate proposal at tau>=0.90 with >=20
samples and zero-breach window (mirrors upstream W/N criteria, adapted).
Auto-demote: any caution event zeroes the window counter.

No auto-activation anywhere in this module: it measures + proposes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CLASSES = ("l1_thresholds", "l2_wrappers", "l3_strategies")
GRADUATE_TAU = 0.90
GRADUATE_SAMPLES = 20


def _store_path() -> Path:
    env = os.environ.get("RSI_TAU_FILE")
    if env:
        return Path(env)
    ws = Path(os.getcwd()).resolve()
    for _ in range(7):
        if (ws / "current_focus.json").is_file():
            break
        if ws.parent == ws:
            break
        ws = ws.parent
    return ws / "state" / "rsi" / "tau.json"


def _load() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        p = _store_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def get_tau() -> dict:
    """Current tau per class (defaults 0.5, no file needed)."""
    data = _load()
    return {c: float(data.get(c, {}).get("tau", 0.5)) for c in CLASSES}


def record_window(clean: bool) -> dict:
    """Record one observation window. clean=False = caution/fault event."""
    data = _load()
    for c in CLASSES:
        entry = data.get(c, {"tau": 0.5, "samples": 0, "breaches": 0})
        try:
            tau = float(entry.get("tau", 0.5))
            samples = int(entry.get("samples", 0))
        except (TypeError, ValueError):
            tau, samples = 0.5, 0
        if clean:
            tau = min(1.0, tau + 0.02)
            samples += 1
        else:
            tau = max(0.0, tau - 0.20)
            samples = 0  # breach resets the window (auto-demote pressure)
        data[c] = {"tau": round(tau, 3), "samples": samples,
                   "updated": datetime.now(timezone.utc).isoformat()}
    _save(data)
    return get_tau()


def graduation_candidates() -> list:
    """Classes meeting graduate criteria (proposal only, never auto)."""
    data = _load()
    out = []
    for c in CLASSES:
        entry = data.get(c, {})
        try:
            if (float(entry.get("tau", 0)) >= GRADUATE_TAU
                    and int(entry.get("samples", 0)) >= GRADUATE_SAMPLES):
                out.append(c)
        except (TypeError, ValueError):
            continue
    return out
