#!/usr/bin/env python3
# design: docs/spec_revision/sandbox/exp-socratic-tree/socratic_proposal_tree.vsm (EXP-SOCRATIC-TREE)
"""
socratic_hooks.py — PROPUESTA: plugins/hooks como árboles socráticos.
Aplica el mismo método que la clasificación documental a la capa de
instrumentos: cada plugin/hook DECLARA su árbol de decisión (socratic(...)),
los predicados son el cuestionamiento atómico, y un intérprete común decide.

Diseño de decisión (como en la clasificación): cada rama es un AND de
condiciones sobre dimensiones del evento (tool, ext, marker); la primera
rama que responde True gana; else = '?' visible / no-op.

No es código de producción — es la PROPUESTA visual de cómo se vería cada
plugin existente como árbol socrático.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from socratic_engine import SocraticEngine, tree_home


def show_tree(name: str, tree: dict, cases: list[tuple[str, dict, str]]) -> None:
    """Muestra un árbol socrático propuesto + casos de decisión.
    El contexto del evento es un dict de dimensiones: {"tool": ..., "ext": ...}."""
    print(f"\n  {name}:")
    print(f"    op: {tree['op']}")
    for i, c in enumerate(tree["children"]):
        prefix = "├" if i < len(tree["children"]) - 1 else "└"
        if "op" in c:
            conds = c.get("children", [])
            parts = []
            for cc in conds:
                pred = cc.get("predicate", "")
                args = ", ".join(cc.get("args", []))
                op = cc.get("op", "")
                parts.append(f"{pred or op}[{args}]")
            print(f"    {prefix} AND({'; '.join(parts)}) → home: {c.get('home')}")
        else:
            pred = c.get("predicate", "")
            args = ", ".join(c.get("args", []))
            print(f"    {prefix} {pred}[{args}] → home: {c.get('home')}")
    if tree.get("else_home"):
        print(f"    └ else → home: {tree['else_home']}")
    eng = SocraticEngine()
    print(f"    ── casos:")
    for label, ctx, expected in cases:
        got = tree_home(tree, ctx.get("type", ""), eng) if False else _tree_home_ctx(tree, ctx, eng)
        ok = "✓" if got == expected else f"✗ (got {got})"
        print(f"       {label}: {ctx} → {got} {ok}")


def _tree_home_ctx(tree: dict, ctx: dict, engine: SocraticEngine) -> str:
    """Evalúa el árbol con contexto multidimensional (tool, ext, marker…).
    Los args usan $dimension para resolver contra el contexto."""
    if tree is None:
        return "?"
    for child in tree.get("children", []):
        try:
            if _eval_node(child, ctx, engine):
                return child.get("home")
        except (ValueError, KeyError):
            continue
    return tree.get("else_home") or "?"


def _eval_node(node, ctx: dict, engine: SocraticEngine) -> bool:
    if isinstance(node, bool):
        return node
    if "predicate" in node:
        args = []
        for a in node.get("args", []):
            if isinstance(a, str) and a.startswith("$") and a[1:] in ctx:
                args.append(ctx[a[1:]])
            else:
                args.append(a)
        return bool(engine.predicates[node["predicate"]](*args))
    if "op" in node:
        results = [_eval_node(c, ctx, engine) for c in node.get("children", [])]
        return engine.evaluate({"op": node["op"], "children": results})
    return False


def main() -> int:
    print("═" * 78)
    print("PLUGINS/HOOKS COMO ÁRBOLES SOCRÁTICOS — propuesta (no se aplica)")
    print("═" * 78)
    print("Mismo método que la clasificación: cada plugin DECLARA su árbol;")
    print("cada rama = AND de condiciones (dimensiones del evento);")
    print("primera rama True gana; else = '?' visible.")

    # ── 1. vsl-check-on-write: ¿qué hacer tras escribir un .vsm? ──────────
    show_tree(
        "vsl-check-on-write (R18 daemon)",
        {"op": "OR", "children": [
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$tool", "write|edit"]},
                {"predicate": "type_glob", "args": ["$ext", "*.vsm"]},
                {"predicate": "type_glob", "args": ["$marker", "*version (R18)*"]},
            ], "home": "BLOCK (policy breach)"},
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$tool", "write|edit"]},
                {"predicate": "type_glob", "args": ["$ext", "*.vsm"]},
            ], "home": "grammar+encoding check (advisory)"},
        ], "else_home": "no-op"},
        [
            ("write .vsm con violación de versión",
             {"tool": "write", "ext": "x.vsm", "marker": "version (R18)"}, "BLOCK (policy breach)"),
            ("write .vsm con error de grammar",
             {"tool": "write", "ext": "x.vsm", "marker": "grammar"}, "grammar+encoding check (advisory)"),
            ("edit .py (fuera de alcance)",
             {"tool": "edit", "ext": "x.py", "marker": "none"}, "no-op"),
        ],
    )

    # ── 2. vsf-onboard-reminder: ¿recordar el boot? ───────────────────────
    show_tree(
        "vsf-onboard-reminder (D2 fail-safe)",
        {"op": "OR", "children": [
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$event", "session.idle"]},
                {"predicate": "type_glob", "args": ["$manifest_cited", "*boot_manifest.vsm*"]},
            ], "home": "silent (D1 closed)"},
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$event", "session.idle"]},
            ], "home": "remind (D1 breach)"},
        ], "else_home": "no-op"},
        [
            ("idle con manifest citado",
             {"event": "session.idle", "manifest_cited": "yes boot_manifest.vsm"}, "silent (D1 closed)"),
            ("idle sin manifest",
             {"event": "session.idle", "manifest_cited": "no"}, "remind (D1 breach)"),
            ("otro evento",
             {"event": "tool.execute", "manifest_cited": "yes"}, "no-op"),
        ],
    )

    # ── 3. learning-cycle-scan: ¿hay aprendizaje que registrar? ────────────
    show_tree(
        "learning-cycle-scan (S2/S4 observability)",
        {"op": "OR", "children": [
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$event", "session.idle"]},
                {"predicate": "type_glob", "args": ["$drafts", "*.pending/*"]},
            ], "home": "BLOCK (persist IR)"},
            {"op": "AND", "children": [
                {"predicate": "type_glob", "args": ["$event", "session.idle"]},
            ], "home": "run session_learning_scan.sh"},
            {"predicate": "type_glob", "args": ["$novel", "*novel>=*"], "home": "TRIGGER S4"},
        ], "else_home": "no-op"},
        [
            ("idle con draft pendiente",
             {"event": "session.idle", "drafts": "x.pending/y.vsm"}, "BLOCK (persist IR)"),
            ("idle sin drafts",
             {"event": "session.idle", "drafts": "none"}, "run session_learning_scan.sh"),
            ("check stats con novedad",
             {"event": "check", "novel": "novel>=3"}, "TRIGGER S4"),
        ],
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
