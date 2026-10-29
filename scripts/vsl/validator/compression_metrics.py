#!/usr/bin/env python3
"""
compression_metrics.py — agregador del compression_ledger.vsm

Lee docs/ledger/compression-ledger-v1/compression_ledger.vsm (formato VSL, una op() por
operación de compresión) y emite la métrica publicable:

  density_FORMA      = 1 − fuse_lines / src_lines          (compression_standard)
  coverage_semantic  = 1 − losses / checks                  (token-diff R4)

Además verifica model≡reality: si el fuse existe en disco, compara sus líneas
reales contra fuse_lines declarado en el ledger (drift = archivo editado sin
actualizar el ledger).

Uso:
  python3 scripts/vsl/compression_metrics.py                # tabla markdown + JSON
  python3 scripts/vsl/compression_metrics.py --json         # solo JSON
  python3 scripts/vsl/compression_metrics.py --check        # exit 1 si hay drift
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Path updated 2026-08-18 (DEBT-COMPRESSION-DRIFT): the socratic tree
# materialization (EXP-SOCRATIC-TREE, ds-30) moved the ledger into
# ledger/compression-ledger-v1/ — the old flat path was stale.
LEDGER = os.path.join(REPO, "docs", "ledger", "compression-ledger-v1", "compression_ledger.vsm")

RE_OP_HEADER = re.compile(r'op\("([^"]+)",\s*date=([\d-]+)\)\s*=\s*\{')


def read_ledger(path=LEDGER):
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")

    # find op() block spans (balanced braces)
    starts = []
    for i, l in enumerate(lines):
        if RE_OP_HEADER.search(l):
            starts.append(i)

    def _span_end(s):
        """end index of the op() block starting at s — brace balance with
        string awareness: '{'/'}' inside double-quoted strings (exclusions,
        decisions, methods) must NOT affect depth. (Bug 2026-08-06: ledger
        strings carrying literal braces, e.g. 'params {' or 'deferred: { }',
        collapsed the balance and truncated the last op's span.)"""
        depth = 0
        in_str = False
        for j in range(s, len(lines)):
            line = lines[j]
            i = 0
            while i < len(line):
                c = line[i]
                if in_str:
                    if c == "\\":
                        i += 2
                        continue
                    if c == '"':
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                i += 1
            if depth == 0:
                return j
        return s  # unbalanced (should not happen) — fail safe to 1-line span

    ops = []
    for s in starts:
        e = _span_end(s)
        ops.append(_parse_op(lines[s:e + 1], RE_OP_HEADER.search(lines[s]).group(1)))

    return ops


def _parse_op(block_lines, op_id):
    text = "\n".join(block_lines)
    # keys: fuse:, src_lines:, fuse_lines:, method:, verify: { ... token_diff: {checks, losses} }
    def field(key):
        m = re.search(rf"\b{key}:\s*([^,\n}}]+)", text)
        return m.group(1).strip().strip('"') if m else None

    def number(key):
        m = re.search(rf"\b{key}:\s*(\d+)", text)
        return int(m.group(1)) if m else None

    # fuse multi-path (COMPRESSION-LEDGER-MULTI-FUSE 2026-08-15): the value
    # may be an array ["a", "b", ...] (multi-fuse), an expression "a → b",
    # "a + b", "{a,b}" (glob/alternatives) or a plain string. field() cuts
    # at the first ',' — it does NOT work for fuse. Dedicated parser:
    def _clean_fuse_token(s):
        """quita comillas, coma trailing y comentario // de un token fuse."""
        s = s.strip().rstrip(",").strip()
        if "//" in s:
            s = s.split("//")[0].strip()
        return s.strip('"').strip()

    fuse_raw = None
    fuse_paths = None
    for line in block_lines:
        m = re.match(r'\s*fuse:\s*(.*?)(?://.*)?$', line)
        if not m:
            continue
        raw = m.group(1).strip()
        if raw.startswith("["):
            # array multi-fuse — may continue on following lines until ']'
            arr = raw
            for cont in block_lines[block_lines.index(line) + 1:]:
                arr += " " + cont.strip()
                if "]" in arr:
                    break
            fuse_raw = _clean_fuse_token(arr)
            items = fuse_raw.strip("[]").split(",")
            fuse_paths = [_clean_fuse_token(x) for x in items if _clean_fuse_token(x)]
        else:
            fuse_raw = _clean_fuse_token(raw)
            if "→" in fuse_raw:
                fuse_paths = [_clean_fuse_token(x) for x in fuse_raw.split("→") if _clean_fuse_token(x)]
            elif "+" in fuse_raw:
                fuse_paths = [_clean_fuse_token(x) for x in fuse_raw.split("+") if _clean_fuse_token(x)]
            else:
                fuse_paths = [fuse_raw]
        break
    action = field("action") or "fuse"
    checks = number("checks")
    losses = number("losses")
    fps = re.search(r"fps:\s*\[(.*?)\]", text, re.S)
    return {
        "id": op_id,
        "fuse": fuse_raw,
        "fuse_paths": fuse_paths,
        "action": action,
        "src_lines": number("src_lines"),
        "fuse_lines": number("fuse_lines"),
        "method": field("method"),
        "checks": checks,
        "losses": losses,
        "fps_note": len(re.findall(r'false positive', fps.group(1), re.I)) if fps else 0,
    }


def live_lines(paths):
    """real line count of the fuse file(s) on disk, or None if no fuse /
    any path missing. Accepts a single path or a list (multi-fuse)."""
    if not paths:
        return None
    if isinstance(paths, str):
        paths = [paths]
    total = 0
    for fuse in paths:
        # array/expression items may carry note suffixes — strip them
        fuse = fuse.strip().strip('"')
        p = os.path.join(REPO, "docs", "spec_revision", fuse)
        if not os.path.exists(p):
            return None
        # Count lines the SAME way the ledger does (wc -l / split-1), not by
        # iterator: a fuse file that ends without a trailing newline counts
        # one EXTRA line under iteration (332 vs 331) but the ledger declares
        # wc-style counts. Fixed 2026-08-18 (DEBT-COMPRESSION-DRIFT): PLAN-01
        # drifted forever because plans_active.vsm lacks a trailing \n.
        data = open(p, encoding="utf-8").read()
        total += len(data.split("\n")) - 1
    return total


def compute(ops):
    rows = []
    for op in ops:
        is_compress = op["src_lines"] and op["src_lines"] > op["fuse_lines"]
        density = 1 - op["fuse_lines"] / op["src_lines"] if is_compress else None
        coverage = 1 - op["losses"] / op["checks"] if op["checks"] else None
        rows.append({
            **op,
            "density": density,
            "coverage": coverage,
            "live_lines": live_lines(op["fuse_paths"]),
            # drift applies ONLY to compression ops that DECLARE fuse_lines
            # (a real fuse with a density contract). Review/certify/RESTRUCT
            # ops (claude_review, CERT, RESTRUCTURE, fold-up) do NOT fuse —
            # their fuse: names the object reviewed, not a density target.
            # fuse_lines=None + live numeric ≠ None was a spurious drift
            # (VSM12-COMPRESSION-DRIFT-BUG, 16 spurious of 40).
            "drift": bool(op["fuse_lines"])
                     and live_lines(op["fuse_paths"]) not in (None, op["fuse_lines"]),
        })
    return rows


def fmt_pct(x):
    return f"{x * 100:.1f}%" if x is not None else "—"


def render_markdown(rows):
    out = []
    out.append("| op | action | fuse | src→fuse | density FORMA | coverage R4 | checks | drift |")
    out.append("|---|--------|------|----------|---------------|-------------|--------|-------|")
    for r in rows:
        src_fuse = f"{r['src_lines']}→{r['fuse_lines']}" if r["src_lines"] else "—"
        drift = f"!{r['live_lines']} (drift)" if r["drift"] else ("✓" if r["live_lines"] else "?")
        out.append(f"| {r['id']} | {r['action']} | {r['fuse']} | {src_fuse} | {fmt_pct(r['density'])} | "
                   f"{fmt_pct(r['coverage'])} | {r['checks']} | {drift} |")
    # aggregates (compression ops only — moves/migrates count no density)
    comp = [r for r in rows if r["density"] is not None]
    total_src = sum(r["src_lines"] for r in comp if r["src_lines"])
    total_fuse = sum(r["fuse_lines"] for r in comp if r["fuse_lines"])
    mean_density = 1 - total_fuse / total_src if total_src else None
    total_checks = sum(r["checks"] for r in rows if r["checks"])
    total_losses = sum(r["losses"] for r in rows if r["losses"])
    mean_coverage = 1 - total_losses / total_checks if total_checks else None
    out.append("")
    out.append(f"**TOTAL** ({len(comp)} ops de compresión): {total_src} → {total_fuse} líneas "
               f"| densidad media {fmt_pct(mean_density)} "
               f"| cobertura R4 {fmt_pct(mean_coverage)} "
               f"({total_checks} checks, {total_losses} pérdidas)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--check", action="store_true", help="exit 1 on ledger/file drift")
    args = ap.parse_args()

    ops = read_ledger()
    rows = compute(ops)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(rows))

    if args.check:
        drifted = [r for r in rows if r["drift"]]
        if drifted:
            print(f"\nDRIFT: {len(drifted)} fuse(s) difieren del ledger: "
                  + ", ".join(f"{r['id']} (disco {r['live_lines']} vs ledger {r['fuse_lines']})" for r in drifted),
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
