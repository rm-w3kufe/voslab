#!/usr/bin/env python3
"""count_events — conteo CANONICO de eventos del log de activaciones.

P-EV-R6 / hallazgo H3 (amendment EVAL-2026-10-14-01): el conteo por
substring en cualquier campo infla (menciones en detail/context) y no es
comparable entre metodos. Este script fija el metodo canonico:

  CANONICO = campo event_type primario (esquema B vivo), con fallback a
  `hook` (esquema A, archivos .gz rotados). Solo el campo primario cuenta;
  las menciones en otros campos NO.

Uso:
  python3 scripts/logs/count_events.py                 # conteos del vivo
  python3 scripts/logs/count_events.py --since 2026-10-15   # desde fecha
  python3 scripts/logs/count_events.py session.idle gate.evaluate  # especificos

Determinista (R10): mismo log -> mismos numeros. Sin red, sin estado.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "logs" / "agent_plugin.jsonl"


def count_line(line: str) -> str | None:
    """Primary event_type/hook of one JSONL line (schema B then A)."""
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        return None
    et = r.get("event_type") or r.get("hook")
    return et if isinstance(et, str) else None


def ts_of(line: str) -> str:
    try:
        return str(json.loads(line).get("ts", ""))
    except json.JSONDecodeError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("events", nargs="*", help="event types to count (default: top 10)")
    ap.add_argument("--since", default=None, help="ISO date prefix filter (e.g. 2026-10-15)")
    ap.add_argument("--include-rotated", action="store_true",
                    help="also scan logs/*.jsonl.gz (esquema A)")
    args = ap.parse_args()

    files = [LOG]
    if args.include_rotated:
        files += sorted(LOG.parent.glob("*.jsonl.gz"))

    counts: dict[str, int] = {}
    total = 0
    for f in files:
        opener = gzip.open if f.suffix == ".gz" else open
        try:
            fh = opener(f, "rt", encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                if args.since and not (ts_of(line).startswith(args.since)
                                       if line.startswith("{") else True):
                    continue
                et = count_line(line)
                if et is None:
                    continue
                total += 1
                counts[et] = counts.get(et, 0) + 1

    if args.events:
        for e in args.events:
            print(f"{e}: {counts.get(e, 0)}")
    else:
        for et, n in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
            print(f"{et}: {n}")
        print(f"# primary-event lines: {total} (method: event_type/hook primario — "
              f"R6/H3 canonico; substring NO cuenta)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
