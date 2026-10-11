"""CLI for epistemic_graph.

  python3 -m epistemic_graph stats [--no-cache]
  python3 -m epistemic_graph export --format json|dot [--kind K] [--dim K=V] [--edge KIND] [--out P]
  python3 -m epistemic_graph show --kind K [--limit N]
  python3 -m epistemic_graph show --edge KIND [--limit N]

networkx is API-only (in-process notebook use), not a CLI format.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .export import to_dot, to_json
from .graph import build, by_dim, by_edge, by_kind, KINDS, EDGE_KINDS


def _parse_dim(spec: str) -> tuple[str, object]:
    if "=" not in spec:
        raise SystemExit(f"epistemic_graph: bad --dim '{spec}' (want K=V)")
    k, _, v = spec.partition("=")
    try:
        return k, json.loads(v)  # true/false/null/numbers
    except ValueError:
        return k, v


def _emit(graph: dict, fmt: str, out: str | None, name: str) -> int:
    text = (to_dot(graph, name=name) if fmt == "dot"
            else json.dumps(to_json(graph), indent=2, ensure_ascii=False))
    if out:
        with open(out, "w") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        print(f"epistemic_graph: wrote {out}")
    else:
        print(text if text.endswith("\n") else text + "\n", end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="epistemic_graph")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-cache", action="store_true",
                        help="rebuild from sources (skip materialization)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="denominators: sources, kinds, edges",
                   parents=[common])

    ex = sub.add_parser("export", help="full or filtered graph",
                        parents=[common])
    ex.add_argument("--format", choices=("json", "dot"), default="json")
    ex.add_argument("--kind", choices=KINDS, help="vista por kind")
    ex.add_argument("--dim", help="vista por dim, e.g. truth=Truth.TRUE")
    ex.add_argument("--edge", choices=EDGE_KINDS,
                    help="fase-2 vista por edge kind (cross views)")
    ex.add_argument("--out", help="write to file instead of stdout")

    sh = sub.add_parser("show", help="list nodes/edges of one kind",
                        parents=[common])
    sh.add_argument("--kind", choices=KINDS, help="node kind to list")
    sh.add_argument("--edge", choices=EDGE_KINDS,
                    help="edge kind to list (fase-2 vistas)")
    sh.add_argument("--limit", type=int, default=20)

    he = sub.add_parser("health", help="topological baseline snapshot (3a)",
                        parents=[common])
    he.add_argument("--out", help="write JSON to file (default: "
                                  "state/epistemic/graph_health.json)")
    he.add_argument("--stdout", action="store_true",
                    help="print snapshot instead of writing")

    di = sub.add_parser("discover", help="discovery queue (3b, advisory)",
                        parents=[common])
    di.add_argument("--min-score", type=float, default=None,
                    help="threshold (default: MIN_SCORE_PROVISIONAL)")
    di.add_argument("--limit", type=int, default=20)
    di.add_argument("--out", help="write queue JSONL to file")
    di.add_argument("--stdout", action="store_true",
                    help="print queue JSON instead of writing file")

    br = sub.add_parser("bridge", help="tasks x graph bridge (3d, advisory)",
                        parents=[common])
    br.add_argument("--out", help="write bridge JSON to file")
    br.add_argument("--stdout", action="store_true",
                    help="print bridge JSON instead of writing file")
    br.add_argument("--limit", type=int, default=20)

    args = ap.parse_args(argv)
    graph = build(use_cache=not args.no_cache)

    if args.cmd == "stats":
        m = graph["meta"]
        print(f"nodes: {m['nodes_total']} | edges: {m['edges_total']} "
              f"| fingerprint: {m['fingerprint'][:16]} "
              f"| cache_hit: {m.get('cache_hit')}")
        for k, n in m["nodes_by_kind"].items():
            print(f"  node {k}: {n}")
        for k, n in m["edges_by_kind"].items():
            print(f"  edge {k}: {n}")
        f2 = (m.get("sources") or {}).get("fase2")
        if f2:
            print(f"  fase2: {json.dumps(f2, sort_keys=True)}")
        if m.get("skipped"):
            print(f"  skipped: {m['skipped']}")
        return 0

    if args.cmd == "health":
        from .graph_health import health as top_health, write_snapshot
        h = top_health(graph)
        if args.stdout:
            print(json.dumps(h, indent=2, sort_keys=True,
                             ensure_ascii=False))
            return 0
        path = write_snapshot(h, Path(args.out) if args.out else None)
        print(f"epistemic_graph: wrote {path}")
        for name, entry in h["layers"].items():
            dag = (f" dag={entry['is_dag']} cyc={entry['cyclic_sccs']}"
                   if "is_dag" in entry else "")
            print(f"  {name}: n={entry['nodes']} m={entry['edges']} "
                  f"rho={entry['density']} C={entry['clustering_avg']} "
                  f"F={entry['fiedler']}{dag}")
        return 0

    if args.cmd == "discover":
        from .discovery import discover as run_discover, write_queue, \
            MIN_SCORE_PROVISIONAL
        ms = args.min_score if args.min_score is not None \
            else MIN_SCORE_PROVISIONAL
        q = run_discover(graph, min_score=ms)
        if args.stdout:
            print(json.dumps(q, indent=2, sort_keys=True, ensure_ascii=False))
            return 0
        path = write_queue(q, Path(args.out) if args.out else None)
        print(f"epistemic_graph: wrote {path} "
              f"({q['meta']['total_candidates']} candidates)")
        for c in q["candidates"][:args.limit]:
            print(f"  {c['kind']:<18} {c['u'][:40]:<40} -> "
                  f"{c['v'][:40]:<40} score={c['score']} via={c['method']}")
        if q["meta"]["total_candidates"] > args.limit:
            print(f"  ... {q['meta']['total_candidates'] - args.limit} more")
        print("denominators:", json.dumps(q["denominators"], sort_keys=True))
        return 0

    if args.cmd == "bridge":
        from .bridge import bridge_view, write_bridge
        v = bridge_view(graph)
        if args.stdout:
            print(json.dumps(v, indent=2, sort_keys=True, ensure_ascii=False))
            return 0
        path = write_bridge(v, Path(args.out) if args.out else None)
        d = v["denominators"]
        print(f"epistemic_graph: wrote {path}")
        print(f"  tasks: total={d['tasks_total_parsed']} live={d['tasks_live']} "
              f"matched={d['tasks_matched']} unmatched={d['tasks_unmatched']}")
        print(f"  live_by_status: {json.dumps(d['live_by_status'], sort_keys=True)}")
        low = v["report"]["low_connectivity_candidates"]
        print(f"  low_connectivity candidates ({len(low)}): {low[:args.limit]}")
        return 0

    if args.cmd == "show":
        if not args.kind and not args.edge:
            ap.error("show requires --kind or --edge")
        if args.edge:
            view = by_edge(graph, args.edge)
            for e in view["edges"][:args.limit]:
                print(f"{e['source']} --{e['kind']}--> {e['target']} "
                      f"w={e.get('weight', 1)}")
            if len(view["edges"]) > args.limit:
                print(f"... {len(view['edges']) - args.limit} more "
                      f"(of {len(view['edges'])})")
            return 0
        view = by_kind(graph, args.kind)
        for n in view["nodes"][:args.limit]:
            print(f"{n['id']}  {json.dumps(n['dims'], ensure_ascii=False, sort_keys=True)}")
        if len(view["nodes"]) > args.limit:
            print(f"... {len(view['nodes']) - args.limit} more "
                  f"(of {len(view['nodes'])})")
        return 0

    # export
    view = graph
    name = "epistemic"
    if args.kind:
        view = by_kind(graph, args.kind)
        name = f"epistemic_{args.kind}"
    if args.dim:
        dim, value = _parse_dim(args.dim)
        view = by_dim(view, dim, value)
        name = f"{name}__{dim}"
    if args.edge:
        view = by_edge(view, args.edge)
        name = f"{name}__{args.edge}"
    return _emit(view, args.format, args.out, name)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
