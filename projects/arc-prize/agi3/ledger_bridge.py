#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Ledger bridge ARC -> kernel autonomy (D4): sweep results feed RSI metrics.

    python3 arc-agi3/ledger_bridge.py --report <sweep.json> [--record]

Semantica (documentada para no contaminar el learner): cada dinamica
es un predicado `arc/dynamics/<nombre>` con threshold fijo 1.0,
input_value = precision p1/n, expected True (toolbox cubre),
actual = (solved > 0). Namespace aislado: el auto-review de
thresholds solo puede tocar claves arc/ (nunca predicados del
kernel). --dry-run (defecto) imprime sin escribir; --record persiste
via scripts/vsl/classifier/rsi_metrics.py (wrapper upstream, no tocar).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts" / "vsl" / "classifier"))


def rows(report):
    rep = json.load(open(report))
    by_dyn = {}
    for r in rep["rows"]:
        by_dyn.setdefault(r["dynamic"], {"n": 0, "p1": 0, "solved": 0})
        d = by_dyn[r["dynamic"]]
        d["n"] += 1
        d["p1"] += int(bool(r.get("p1")))
        d["solved"] += int(bool(r["solved"]))
    return by_dyn, {k: rep[k] for k in
                    ("n", "solved", "accuracy", "oracle_solved") if k in rep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--record", action="store_true",
                    help="persistir en RSI metrics (defecto: dry-run)")
    a = ap.parse_args()
    by_dyn, tot = rows(a.report)
    events = []
    for name in sorted(by_dyn):
        d = by_dyn[name]
        prec = d["p1"] / d["n"] if d["n"] else 0.0
        events.append((f"arc/dynamics/{name}", 1.0, round(prec, 4),
                       True, d["solved"] > 0, 0.0))
    acc = tot.get("accuracy", 0.0)
    events.append(("arc/era", 1.0, round(acc, 4), True, acc > 0, 0.0))
    print(f"totals: {tot} dynamics: {len(by_dyn)}")
    for e in events:
        print(f"  {e[0]}: prec={e[2]} ok={e[4]}")
    if not a.record:
        print("dry-run: nada persistido (usa --record)")
        return 0
    import rsi_metrics as M
    m = M.RSIMetrics()
    for name, thr, val, exp, act, lat in events:
        m.track_classification(name, thr, val, exp, act, lat)
    print(f"recorded {len(events)} predicates "
          f"(namespace arc/, thresholds fijos 1.0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
