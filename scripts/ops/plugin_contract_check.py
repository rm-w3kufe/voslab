#!/usr/bin/env python3
"""plugin_contract_check.py — D-3+D-4 incident gate (2026-09-23/24).

opencode's loader invokes EVERY function export of plugin[] files as a
Plugin factory (Object.values) and pushes results into the hooks list;
the event-router dispatches over handler objects requiring .events[].
TS types are erased at runtime (Bun), so violations load fine and
explode only at boot/dispatch:

  R1 (RC-1, FAIL): `export default [` — array default: loader throws
      "Plugin export is not a function", whole module lost.
  R2 (RC-2, FAIL): `export [async] function NAME(...): void` (or
      Promise<void>) — invoked as factory, returns undefined, pushed
      into hooks -> N.config + n.provider crashes ("Unexpected server
      error" on resume).
  R3 (D-4 third bug, FAIL): exported `*Handler` object without an
      `events:` field within 40 lines of the export — router filter
      `h.events.includes` throws on 100% of tool calls. Scope: plugin[]
      files AND operational/handlers/*.ts (registered into dispatch).
  R4 (advisory, WARN only): anonymous `export default (async) (` or
      default identifiers without a `: Plugin` annotation — cannot
      verify shape statically; listed for human review.

Usage:
  python3 scripts/ops/plugin_contract_check.py [--selftest] [--json]
Exit 0 = no FAIL findings (warnings allowed); 1 = any FAIL.
--selftest runs inline fixtures: each FAIL rule must fire on its
negative control and stay silent on clean fixtures (gate tests itself).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RE_DEFAULT_ARRAY = re.compile(r"export\s+default\s*\[")
RE_EXPORT_VOID_FN = re.compile(
    r"export\s+(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\([^)]*\)"
    r"\s*:\s*(?:Promise<\s*void\s*>|void\b)")
RE_EXPORT_HANDLER = re.compile(
    r"export\s+const\s+([A-Za-z_]\w*Handler)\b")
RE_ANON_DEFAULT = re.compile(r"export\s+default\s*\(?\s*async\b")
RE_DEFAULT_IDENT = re.compile(r"export\s+default\s+([A-Za-z_]\w*)\s*;?")


def _plugin_files() -> list[Path]:
    cfg = json.loads((ROOT / "opencode.json").read_text())
    out = []
    for p in cfg.get("plugin", []):
        f = ROOT / p
        if f.suffix == ".ts" and f.is_file():
            out.append(f)
    return out


def _handler_files() -> list[Path]:
    d = ROOT / ".opencode" / "plugins" / "operational" / "handlers"
    return sorted(d.glob("*.ts")) if d.is_dir() else []


def check_file(path: Path) -> tuple[list, list]:
    """Return (fails, warns), each a list of {rule, file, line, detail}."""
    fails, warns = [], []
    try:
        src = path.read_text()
    except OSError:
        return [{"rule": "READ", "file": str(path), "line": 0,
                 "detail": "unreadable"}], []
    lines = src.splitlines()
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)  # selftest fixtures live in tmp

    for i, line in enumerate(lines, 1):
        if RE_DEFAULT_ARRAY.search(line):
            fails.append({"rule": "R1", "file": rel, "line": i,
                          "detail": "array default export kills module load"})
        m = RE_EXPORT_VOID_FN.search(line)
        if m:
            fails.append({"rule": "R2", "file": rel, "line": i,
                          "detail": f"void function export '{m.group(1)}' "
                                    "invoked as Plugin -> undefined in hooks"})

    # R3: *Handler exports must carry events: within 40 lines
    for m in RE_EXPORT_HANDLER.finditer(src):
        name = m.group(1)
        start_line = src.count("\n", 0, m.start()) + 1
        window = "\n".join(lines[start_line - 1:start_line + 39])
        if not re.search(r"events\s*:", window):
            fails.append({"rule": "R3", "file": rel, "line": start_line,
                          "detail": f"handler '{name}' without events[] "
                                    "-> router dispatch crash"})

    # R4 advisories (plugin[] files only — caller decides scope)
    if RE_ANON_DEFAULT.search(src):
        warns.append({"rule": "R4", "file": rel, "line": 0,
                      "detail": "anonymous default export: shape "
                                "unverifiable statically, review manually"})
    for m in RE_DEFAULT_IDENT.finditer(src):
        ident = m.group(1)
        if not re.search(rf"\b{re.escape(ident)}\s*:\s*Plugin\b", src) \
           and not re.search(
               rf"(?:function|const)\s+{re.escape(ident)}\b[^{{;}}]*:\s*Plugin\b",
               src):
            warns.append({"rule": "R4", "file": rel,
                          "line": src.count("\n", 0, m.start()) + 1,
                          "detail": f"default '{ident}' without : Plugin "
                                    "annotation — review manually"})
    return fails, warns


def check_repo() -> tuple[list, list]:
    fails, warns = [], []
    seen = set()
    for f in _plugin_files():
        seen.add(f)
        ff, ww = check_file(f)
        fails.extend(ff)
        warns.extend(ww)
    for f in _handler_files():
        if f in seen:
            continue
        src = f.read_text()
        # handlers/*: only R3 applies (not loader-invoked, but dispatched)
        for m in RE_EXPORT_HANDLER.finditer(src):
            name = m.group(1)
            start_line = src.count("\n", 0, m.start()) + 1
            window = "\n".join(src.splitlines()[start_line - 1:
                                                 start_line + 39])
            if not re.search(r"events\s*:", window):
                fails.append({"rule": "R3",
                              "file": str(f.relative_to(ROOT)),
                              "line": start_line,
                              "detail": f"handler '{name}' without events[]"})
    # R1/R2 also apply to handlers/*? No: loader never invokes them.
    # (Documented scope decision.)
    return fails, warns


def selftest() -> int:
    """Negative controls: each FAIL rule must fire; clean must pass."""
    import tempfile
    cases = [
        ("R1", "export default [a, b];\nexport const X = 1;\n", True),
        ("R2", "export function f(h: any): void {}\n", True),
        ("R2", "export async function g(h: any): Promise<void> {}\n", True),
        ("R3", "export const FooHandler = {\n  id: 'x',\n};\n", True),
        ("clean-plugin", "import type { Plugin } from 'x';\n"
         "export const CheckOnWrite: Plugin = async ({directory}: any) => ({\n"
         '  "tool.execute.after": async () => ({}),\n'
         "});\nexport default CheckOnWrite;\n", False),
        ("clean-handler", "export const H: Handler = {\n  id: 'h',\n"
         "  priority: 1,\n  events: ['session.idle'],\n"
         "  classify: async () => true,\n"
         "  execute: async () => ({}) ,\n};\n", False),
        ("clean-factory", "export function make(): Handler {\n"
         "  return { id: 'm', priority: 1, events: ['a'],\n"
         "    classify: async () => true, execute: async () => ({}) };\n"
         "}\n", False),
    ]
    n_fail = 0
    with tempfile.TemporaryDirectory() as td:
        for name, content, expect_fail in cases:
            p = Path(td) / f"{name}.ts"
            p.write_text(content)
            fails, _ = check_file(p)
            got_fail = bool(fails)
            status = "ok" if got_fail == expect_fail else "BROKEN"
            if got_fail != expect_fail:
                n_fail += 1
            print(f"[{status}] {name}: expect_fail={expect_fail} "
                  f"got={got_fail} {[f['rule'] for f in fails]}")
    # live-repo assertion: current tree must pass
    rfails, _ = check_repo()
    live_ok = not rfails
    print(f"[{'ok' if live_ok else 'BROKEN'}] live-repo: "
          f"{len(rfails)} fails")
    if not live_ok:
        for f in rfails:
            print("   ", f)
        n_fail += 1
    print("SELFTEST PASS" if n_fail == 0 else f"SELFTEST FAIL ({n_fail})")
    return 0 if n_fail == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    fails, warns = check_repo()
    out = {"fails": fails, "warns": warns,
           "ok": not fails}
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        for f in fails:
            print(f"FAIL {f['rule']} {f['file']}:{f['line']} — {f['detail']}")
        for w in warns:
            print(f"warn {w['rule']} {w['file']}:{w['line']} — {w['detail']}")
        print("CONTRACT OK" if not fails else
              f"CONTRACT BROKEN ({len(fails)} findings)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
