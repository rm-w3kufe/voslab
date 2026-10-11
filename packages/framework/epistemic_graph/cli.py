"""CLI for epistemic_graph.

  python3 -m epistemic_graph stats [--no-cache]
  python3 -m epistemic_graph export --format json|dot [--kind K] [--dim K=V] [--out P]
  python3 -m epistemic_graph show --kind K [--limit N]

networkx is API-only (in-process notebook use), not a CLI format.
"""
from __future__ import annotations

import argparse
import json
import sys

from .export import to_dot, to_json
from .graph import build, by_dim, by_kind, KINDS


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
    ex.add_argument("--out", help="write to file instead of stdout")

    sh = sub.add_parser("show", help="list nodes of one kind", parents=[common])
    sh.add_argument("--kind", required=True, choices=KINDS)
    sh.add_argument("--limit", type=int, default=20)

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
        if m.get("skipped"):
            print(f"  skipped: {m['skipped']}")
        return 0

    if args.cmd == "show":
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
    return _emit(view, args.format, args.out, name)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
