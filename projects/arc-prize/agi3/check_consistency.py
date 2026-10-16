#!/usr/bin/env python3
# design: projects/arc-prize/arc_prize_design.vsm
"""Consistency checker: taxonomy (auto) vs routing table (mano) vs engine.

    python3 arc-agi3/check_consistency.py [--strict]

Verifica: 1) toda dinamica de la taxonomia tiene fila en routing con
mismos n/p1/solved; 2) totales routing == totales taxonomy;
3) toda entrada DYNAMICS del engine declara familia arc3 no vacia;
4) unknown taxonomy == unknown routing. Exit 0 limpio, 1 con diffs.
Contrato D7: taxonomy manda en numeros, routing en mapeo, docs en
narrativa; divergencia = bug (este checker lo hace mecanico).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import recognizer as R  # noqa: E402

ROW = re.compile(r"//\s+(\S+)\s+(\d+)/(\d+)/(\d+)")
TOT = re.compile(r"//\s+Totales:\s+routed\s+(\d+).*?p@1\s+(\d+).*?toolbox\s+(\d+)",
                 re.IGNORECASE)
TAX = re.compile(r"//\s+Taxonomia auto:\s+(\d+)\s+dinamicas,\s+(\d+)\s+resolviendo",
                 re.IGNORECASE)


def main():
    fails = []
    tax = json.load(open(HERE / ".." / "knowledge" / "arc_taxonomy.json"))
    routing = open(HERE / ".." / "knowledge" / "arc_routing_table.vsm").read()
    rows = {m.group(1): tuple(map(int, m.groups()[1:])) for m in ROW.finditer(routing)}
    for d in tax["dynamics"]:
        want = (d["n"], d["p1"], d["solved"])
        got = rows.get(d["name"])
        if got != want:
            fails.append(f"row {d['name']}: taxonomy={want} routing={got}")
    tn = {d["name"] for d in tax["dynamics"]}
    extra = sorted(set(rows) - tn - {"Totales:", "Taxonomia"})
    if extra:
        fails.append(f"routing sin taxonomy: {extra}")
    m = TOT.search(routing)
    t = tax["totals"]
    if m:
        got = tuple(map(int, m.groups()))
        if (got[0], got[2]) != (t["solved"], t["oracle_solved"]):
            fails.append(f"totales: routing={got} taxonomy="
                         f"({t['solved']},p@1,{t['oracle_solved']})")
    mt = TAX.search(routing)
    if mt and (int(mt.group(1)), int(mt.group(2))) != (
            len(tax["dynamics"]),
            sum(1 for d in tax["dynamics"] if d["solved"])):
        fails.append(f"taxonomia-line: routing={mt.groups()} "
                     f"taxonomy folklore difiere")
    nofam = [n for n, _d, f, a in R.DYNAMICS if not a]
    if nofam:
        fails.append(f"DYNAMICS sin familia arc3: {nofam}")
    un = next((d for d in tax["dynamics"] if d["name"] == "unknown"), None)
    if un and rows.get("unknown") != (un["n"], un["p1"], un["solved"]):
        fails.append("unknown diverge (ya cubierto arriba si aplica)")
    if fails:
        print("CONSISTENCY FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"CONSISTENCY PASS: {len(tn)} dinamicas, "
          f"totales {t['solved']}/{t['oracle_solved']}, "
          f"DYNAMICS {len(R.DYNAMICS)} con familia")
    return 0


if __name__ == "__main__":
    sys.exit(main())
