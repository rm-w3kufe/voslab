# design: projects/arc-prize/arc_prize_design.vsm
"""
bootstrap_strategies.py — Carga las 3 primeras estrategias como micro-VSMs.

Demuestra el patrón de wrapping de funciones existentes de recognizer.py
como StrategyVSM. Este script se ejecuta una vez para popular el registry.

Uso:
    python3 arc-agi3/bootstrap_strategies.py
"""

import sys
from pathlib import Path

# Asegurar imports
sys.path.insert(0, str(Path(__file__).parent))

from strategy_vsm import StrategyVSM, wrap_existing, get_registry


def bootstrap():
    """Wrappear 3 estrategias existentes como micro-VSMs."""

    # Importar funciones y detectores de recognizer
    from recognizer import (
        try_crop_content, d_crop,
        try_mirror_double, d_mirrordouble,
        try_blockcensus, d_blockcensus,
    )

    # ── 1. Crop (extraction) ─────────────────────────────────
    crop = wrap_existing(
        name="crop",
        solve_fn=try_crop_content,
        detector_fn=d_crop,
        category="explore-cursor",
        author="manual",
    )
    print(f"  ✓ {crop}")

    # ── 2. Mirror Double (transform-bulk) ────────────────────
    mirror = wrap_existing(
        name="mirrordouble",
        solve_fn=try_mirror_double,
        detector_fn=d_mirrordouble,
        category="transform-bulk",
        author="manual",
    )
    print(f"  ✓ {mirror}")

    # ── 3. Block Census (explore-cursor) ─────────────────────
    block = wrap_existing(
        name="blockcensus",
        solve_fn=try_blockcensus,
        detector_fn=d_blockcensus,
        category="explore-cursor",
        author="manual",
    )
    print(f"  ✓ {block}")

    # Resumen
    registry = get_registry()
    print(f"\n  Registry: {len(registry)} estrategias cargadas")
    for name, s in registry.items():
        print(f"    [{s.category}] {name}: "
              f"invariants={s.invariants}, signals={len(s.signal_history)}")


if __name__ == "__main__":
    print("bootstrap_strategies: cargando 3 micro-VSMs...")
    bootstrap()
    print("done.")
