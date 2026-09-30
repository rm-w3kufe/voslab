"""CLI for trace_graph.

  python3 -m trace_graph list [--traces PATH]
  python3 -m trace_graph export --tree claim_gate --format dot|json [--out PATH]
  python3 -m trace_graph show --trace TRACE_ID --format dot|json [--traces PATH]

networkx is API-only (in-process notebook use), not a CLI format.
"""
from __future__ import annotations

import argparse
import json
import sys

from .export import to_dot, to_json
from .graph import aggregate, families, per_trace
from .load import load_traces


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace_graph")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--traces", help="override traces JSONL path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="families + trace counts", parents=[common])

    ex = sub.add_parser("export", help="aggregate graph of one tree family",
                        parents=[common])
    ex.add_argument("--tree", required=True, help="family name, e.g. claim_gate")
    ex.add_argument("--format", choices=("dot", "json"), default="dot")
    ex.add_argument("--out", help="write to file instead of stdout")

    sh = sub.add_parser("show", help="exact graph of one trace",
                        parents=[common])
    sh.add_argument("--trace", required=True, help="trace_id")
    sh.add_argument("--format", choices=("dot", "json"), default="dot")
    sh.add_argument("--out", help="write to file instead of stdout")

    args = ap.parse_args(argv)
    traces, skipped = load_traces(args.traces)

    if args.cmd == "list":
        print(f"file: {args.traces or '(default)'} | traces: {len(traces)} "
              f"| skipped: {skipped}")
        for fam, n in families(traces).items():
            print(f"  {fam}: {n}")
        return 0

    if args.cmd == "export":
        agg = aggregate(traces, tree=args.tree)
        if agg["meta"]["traces"] == 0:
            print(f"trace_graph: no traces for family '{args.tree}'",
                  file=sys.stderr)
            return 2
        out = (to_dot(agg, name=args.tree) if args.format == "dot"
               else json.dumps(to_json(agg), indent=2, ensure_ascii=False))
    else:  # show
        match = [t for t in traces if t.get("trace_id") == args.trace]
        if not match:
            print(f"trace_graph: trace '{args.trace}' not found",
                  file=sys.stderr)
            return 2
        g = per_trace(match[0])
        out = (to_dot(g, name=args.trace) if args.format == "dot"
               else json.dumps(to_json(g), indent=2, ensure_ascii=False))

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out if out.endswith("\n") else out + "\n")
        print(f"trace_graph: wrote {args.out}")
    else:
        print(out if out.endswith("\n") else out + "\n", end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
