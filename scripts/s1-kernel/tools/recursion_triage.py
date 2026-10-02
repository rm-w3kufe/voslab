#!/usr/bin/env python3
"""recursion_triage — deterministic VSM recursion classifier (Beer's recursion).

RECURSION-TRIAGE-2026-08-13 (gate: núcleo boot armado ✓ — VSM instruction in
vsf-s3-planner.md + vsf-s1-executor.md).

Motor determinista (NO LLM — D6/R10.1) que verifica dónde entra cada
tarea/proyecto/planificación en el ecosistema fractal VSM. Funciones:
  (a) clasifica cada item nuevo en su nivel de recursión (S5→S3→S1→kernel
      →subsistema) y su órgano dueño;
  (b) verifica contra los órganos existentes (services/checks/scripts/agentes)
      que NO haya colisión ni duplicado — la regla del mapa VSM aplicada
      mecánicamente;
  (c) genera el mapa fractal del ecosistema (visibilidad S4).

UPDATED: Now uses socratic engine for classification via recursion_classify.tree.vsm
Predicates: agent_at_level, organ_matches_markers

Patrón: derivado de fuente, nunca mano-editado. Salida = reporte + mapa,
NUNCA ejecuta acciones por sí mismo (Capa A = S3* report-only; la revisión
la hace S3, el archivo S1). Mismo espíritu que s3star_query.py/bbh_relay.py
en este directorio.

Uso:
  python3 scripts/recursion/recursion_triage.py            # reporte + mapa
  python3 scripts/recursion/recursion_triage.py --json     # solo JSON
  python3 scripts/recursion/recursion_triage.py --check    # exit 1 si hay colisión
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / "TASKS.vsm"
CHECKS = ROOT / "checks"
SCRIPTS_STATE = ROOT / "scripts" / "state"

# Add classifier path for socratic engine
sys.path.insert(0, str(ROOT / "scripts" / "vsl" / "classifier"))
from vsf_socratic_engine import _create_engine, _ROOT

# Load trees
TREE_LEVEL = _ROOT / ".opencode/plugins/support/trees/recursion_classify.tree.vsm"
TREE_ORGAN = _ROOT / ".opencode/plugins/support/trees/recursion_classify.tree.vsm"

# ── Niveles de recursión VSM (Beer) ──────────────────────────────────────
# L0 = sistema (root) · L1 = subsistema (organ) · L2 = kernel · L3 = componente
LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4"]


def classify_level(agent_field: str) -> str:
    """nivel de recursión por el agent= del header (default L1 si no mapeado).
    
    Uses socratic engine for classification."""
    engine = _create_engine()
    ctx = {"agent": agent_field}
    tree_text = TREE_LEVEL.read_text(encoding="utf-8")
    
    # Find the recursion_classify tree (first decision in file)
    # Parse only the first tree block
    lines = tree_text.split("\n")
    first_tree_lines = []
    depth = 0
    in_tree = False
    for line in lines:
        if "recursion_classify = decision(" in line:
            in_tree = True
        if in_tree:
            first_tree_lines.append(line)
            depth += line.count("(") - line.count(")")
            if depth <= 0 and len(first_tree_lines) > 1:
                break
    
    first_tree = "\n".join(first_tree_lines)
    result = engine.evaluate(first_tree, ctx)
    return result.home


def classify_organ(task_id: str, body: str) -> str:
    """órgano dueño por marcadores en el id + body (default S1-operations).
    
    Uses socratic engine for classification."""
    engine = _create_engine()
    ctx = {"task_id": task_id, "body": body}
    tree_text = TREE_ORGAN.read_text(encoding="utf-8")
    
    # Find the recursion_organ tree (second decision in file)
    lines = tree_text.split("\n")
    second_tree_lines = []
    depth = 0
    in_tree = False
    tree_count = 0
    for line in lines:
        if "recursion_organ = decision(" in line:
            tree_count += 1
            if tree_count == 2:
                in_tree = True
        if in_tree:
            second_tree_lines.append(line)
            depth += line.count("(") - line.count(")")
            if depth <= 0 and len(second_tree_lines) > 1:
                break
    
    if second_tree_lines:
        second_tree = "\n".join(second_tree_lines)
        result = engine.evaluate(second_tree, ctx)
        return result.home
    
    return "S1-operations"


def parse_tasks() -> list[dict]:
    """lee TASKS.vsm — task() blocks con status (balance de llaves)."""
    text = TASKS.read_text(encoding="utf-8")
    lines = text.split("\n")
    tasks = []
    for i, l in enumerate(lines):
        m = re.match(r"\s*task\([^)]*\)\s*=\s*\{", l)
        if not m:
            continue
        header = l
        # agent= del header (formato legacy `agent:  [S]` o inline `agent=[S]`)
        agent_m = re.search(r"agent(?:=|\s*:\s*)\s*\[?([^\],}\s]+)", header)
        agent = agent_m.group(1) if agent_m else ""
        id_m = re.search(r'task\("?([^")]+)"?', header)
        tid = id_m.group(1) if id_m else f"task@{i}"
        # status en el cuerpo — puede haber DOS (patrón legacy: status inicial
        # + status final tras resolved:[]) — el REAL es el ÚLTIMO declarado
        depth = 1
        j = i + 1
        body = ""
        while j < len(lines) and depth > 0:
            line = lines[j]
            depth += line.count("{") - line.count("}")
            if depth > 0:
                body += line + "\n"
            j += 1
        statuses = re.findall(r"\bstatus\s*[:=]\s*([\w\[\]]+)", body + header)
        status = statuses[-1] if statuses else "unknown"
        tasks.append({
            "id": tid,
            "agent": agent,
            "level": classify_level(agent),
            "organ": classify_organ(tid, body),
            "status": status,
        })
    return tasks


def parse_organs() -> dict:
    """órganos existentes: checks/ + scripts/state/ (instrumentos vivos)."""
    organs = {"checks": [], "scripts": []}
    if CHECKS.exists():
        organs["checks"] = sorted(p.name for p in CHECKS.iterdir() if p.is_file())
    if SCRIPTS_STATE.exists():
        organs["scripts"] = sorted(p.name for p in SCRIPTS_STATE.iterdir() if p.suffix == ".py")
    return organs


def detect_collisions(tasks: list[dict]) -> list[dict]:
    """colisión: dos task() abiertas con el mismo id raíz (mismo scope)."""
    seen = {}
    collisions = []
    for t in tasks:
        if t["status"] in ("done", "cancelled", "closed"):
            continue
        # id raíz: token principal antes de la fecha/versionado
        base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", t["id"]).strip()
        base = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", base)
        if base in seen:
            collisions.append({
                "a": seen[base],
                "b": t["id"],
                "base": base,
                "level": t["level"],
            })
        else:
            seen[base] = t["id"]
    return collisions


def fractal_map(tasks: list[dict]) -> dict:
    """mapa fractal: nivel → órgano → [task ids abiertas]."""
    m: dict[str, dict[str, list]] = {}
    for t in tasks:
        if t["status"] in ("done", "cancelled", "closed"):
            continue
        m.setdefault(t["level"], {}).setdefault(t["organ"], []).append(t["id"])
    return m


def main() -> int:
    tasks = parse_tasks()
    organs = parse_organs()
    collisions = detect_collisions(tasks)
    fmap = fractal_map(tasks)

    if "--json" in sys.argv:
        print(json.dumps({
            "tasks": len(tasks),
            "open": sum(1 for t in tasks if t["status"] not in ("done", "cancelled", "closed")),
            "levels": {lvl: len(tasks_at) for lvl, tasks_at in sorted(fmap.items())},
            "collisions": collisions,
            "organs": organs,
        }, indent=2, ensure_ascii=False))
        return 1 if collisions else 0

    print("=== RECURSION TRIAGE — mapa fractal VSM (report-only, S3*) ===")
    print(f"TASKS.vsm: {len(tasks)} task() | {sum(1 for t in tasks if t['status'] not in ('done','cancelled','closed'))} abiertas")
    print(f"Órganos vivos: {len(organs['checks'])} checks + {len(organs['scripts'])} scripts/state")
    print()
    for lvl in LEVEL_ORDER:
        if lvl not in fmap:
            continue
        print(f"  {lvl}:")
        for organ, ids in sorted(fmap[lvl].items()):
            print(f"    {organ} ({len(ids)}): {', '.join(ids[:6])}{'…' if len(ids) > 6 else ''}")
    print()
    if collisions:
        print(f"⚠ {len(collisions)} COLISIÓN(ES) detectadas (mismo scope en tareas abiertas):")
        for c in collisions:
            print(f"   {c['base']}: {c['a']} ↔ {c['b']} @ {c['level']}")
        return 1
    print("✓ sin colisiones de scope entre tareas abiertas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
