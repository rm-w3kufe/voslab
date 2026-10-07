"""vos_kernel.recall_eval — harness E1 de F5 (mini-CTC, r4_lote2 §6).

E1: hit-rate sobre queries de conocimiento local de respuesta conocida,
reportado SIEMPRE con harness divulgado (formato mini-CTC de X5: sin
condiciones no hay número). Este script es evaluación — NO es el módulo
de recall (que jamás escribe); aquí se permite escribir el reporte de
evidencia en state/epistemic/reports/.

Uso:
  python3 packages/framework/vos_kernel/recall_eval.py [--out PATH]

Corpus congelado por build_index() único (todas las queries comparten
índice → mismo set de condiciones para todas las filas).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

_FW = Path(__file__).resolve().parents[1]
if str(_FW) not in sys.path:
    sys.path.insert(0, str(_FW))

from vos_kernel.recall import (  # noqa: E402
    DEFAULT_K, DEFAULT_MAX_HIT_CHARS, DEFAULT_MAX_TOTAL_CHARS,
    ORIGIN_WEIGHTS, Budget, build_index, sanitize, search,
)

# Queries con respuesta conocida local (E1). expect_any = subcadenas
# aceptadas en los srcs del top-k; una coincidencia = hit.
KNOWN: list[dict] = [
    {"q": "pleasure channel algedonico placer milestones",
     "expect_any": ["docs/plans/pleasure_channel_proposal.vsm"]},
    {"q": "NC-21 recall-sanitize negative control",
     "expect_any": ["docs/plans/r4_lote2_proposal.vsm"]},
    {"q": "D-25 repo hermano state-canon guards",
     "expect_any": ["docs/plans/system_backlog.vsm"]},
    {"q": "l2-view probe A-G freshness stamped",
     "expect_any": ["docs/plans/refs_optimization_proposal.vsm"]},
    {"q": "F3a manifest cache warm 15 segundos",
     "expect_any": ["docs/plans/refs_optimization_proposal.vsm"]},
    {"q": "tasa UNKNOWN compliance bias K6",
     "expect_any": ["docs/plans/refs_optimization_proposal.vsm"]},
    {"q": "VOS_SESSION_ID esquema B session_id",
     "expect_any": ["docs/plans/plan_registry.vsm"]},
    {"q": "REFS-OPT-001 foco activo trabajo",
     "expect_any": ["current_focus.json"]},
    {"q": "context rot degradación longitud retrieval",
     "expect_any": ["docs/plans/r4_lote2_proposal.vsm"]},
    {"q": "sanitización delimitadores no-ejecución VOS-RECALL",
     "expect_any": ["docs/plans/r4_lote2_proposal.vsm"]},
    {"q": "learning-cycle-scan session.idle activation",
     "expect_any": ["agent_plugin", "docs/plans/system_backlog.vsm"]},
    {"q": "broken noop gate negative control exit code",
     "expect_any": ["state/distill/candidates.jsonl", "agent_plugin"]},
]


def evaluate(root: Path, k: int = DEFAULT_K,
             max_hit: int = DEFAULT_MAX_HIT_CHARS,
             max_total: int = DEFAULT_MAX_TOTAL_CHARS) -> dict:
    index = build_index(root)
    rows = []
    for i, spec in enumerate(KNOWN, 1):
        scored = search(index, spec["q"])
        block, hits, truncated = sanitize(
            scored, spec["q"],
            Budget(k=k, max_hit_chars=max_hit, max_total_chars=max_total))
        srcs = [h.src for h in hits]
        hit = any(any(sub in src for sub in spec["expect_any"])
                  for src in srcs)
        rows.append({"n": i, "query": spec["q"],
                     "expect": spec["expect_any"], "topk": srcs,
                     "hit": hit, "truncated": truncated,
                    })
    hits_n = sum(1 for r in rows if r["hit"])
    src_module = _FW / "vos_kernel" / "recall.py"
    return {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": {
            "root": str(root),
            "indexed": index.n,
            "by_origin": _counts(index),
            "dropped_fail_closed": dict(index.dropped),
            "log_cap": "10000 newest records (DEFAULT_MAX_LOG_RECORDS)",
            "ref_ts_anchor": index.ref_ts.isoformat(),
        },
        "harness": {
            "k": k, "max_hit_chars": max_hit, "max_total_chars": max_total,
            "ranking": "tf-idf log-damped × origin-weight "
                       + str(ORIGIN_WEIGHTS)
                       + " × freshness 1/(1+age_days/30) con age anclado "
                         "al ts max de la corpus (no a now)",
            "tokenize": r"\w{2,} lower-case, términos únicos",
            "recall_py_sha256_12": hashlib.sha256(
                src_module.read_bytes()).hexdigest()[:12],
            "mode": "evaluación directa build_index→search→sanitize "
                    "(sin env; el serve live es solo para evidencia)",
        },
        "rows": rows,
        "hit_rate": f"{hits_n}/{len(rows)}",
        "hits_n": hits_n,
        "total": len(rows),
    }


def _counts(index) -> dict:
    out: dict[str, int] = {}
    for it in index.items:
        out[it.origin] = out.get(it.origin, 0) + 1
    return out


def to_markdown(res: dict) -> str:
    c, h = res["corpus"], res["harness"]
    lines = [
        "# F5 E1 — recall hit-rate (mini-CTC)",
        "",
        f"- fecha (UTC): {res['date_utc']}",
        f"- corpus: root={c['root']}, indexed={c['indexed']}, "
        f"por origen={c['by_origin']}, fail-closed dropped="
        f"{c['dropped_fail_closed']}",
        f"- límite de log: {c['log_cap']}; ancla de frescura "
        f"(ref_ts)={c['ref_ts_anchor']}",
        f"- k={h['k']}, max_hit_chars={h['max_hit_chars']}, "
        f"max_total_chars={h['max_total_chars']}",
        f"- ranking: {h['ranking']}",
        f"- tokenización: {h['tokenize']}",
        f"- recall.py sha256_12={h['recall_py_sha256_12']}",
        f"- modo: {h['mode']}",
        "",
        "| # | query | esperado | top-k | hit |",
        "|---+-------|----------|-------+-----+-----|",
    ]
    for r in res["rows"]:
        topk = ", ".join(r["topk"][:res["harness"]["k"]]) or "(sin hits)"
        mark = "**SÍ**" if r["hit"] else "no"
        lines.append(
            f"| {r['n']} | {r['query']} | {' / '.join(r['expect'])} "
            f"| {topk} | {mark} |"
        )
    lines += ["", f"**hit-rate: {res['hit_rate']}**", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="F5 E1 eval (mini-CTC)")
    ap.add_argument("--out", default=None,
                    help="ruta del reporte markdown (evidencia §11.9)")
    ap.add_argument("--root", default=None, help="raíz del repo")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else _FW.parents[1]
    res = evaluate(root)
    md = to_markdown(res)
    print(md)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"[evidence] {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
