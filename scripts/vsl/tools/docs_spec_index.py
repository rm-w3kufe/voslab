#!/usr/bin/env python3
"""docs_spec_index — S3* report-only spider for docs/spec_revision/ (SYSTEM-SPEC-INDEX-2026-08-13).

Indexes every .vsm under a root with its metadata — name, type, vsm version,
date, @status, organ, recursion level, branch nature — and answers queries by
ANY field. A document keeps its category (whatever it is) until reviewed and
validated; status never hides it from a query. Report-only (S3*): reads the
corpus, never writes to it; only its own snapshot file.

Diseño (directiva rmw3 2026-08-15, imagen del árbol):
  - cada nodo = (nivel Ln, naturaleza N); la clase se hereda del tronco,
    la naturaleza define la rama.
  - naturaleza derivada de la rama (agent-layer, runtime-s1, kernel-theory,
    instance-config, policy, canon-boot, language...), no del nivel.
  - consulta por CUALQUIER campo: un doc con @status proposed sigue
    consultable; vive donde está previsto hasta ser revisado.

Uso:
  python3 scripts/vsl/docs_spec_index.py                    # resumen (status/organ/nature/level)
  python3 scripts/vsl/docs_spec_index.py --find status=active
  python3 scripts/vsl/docs_spec_index.py --find organ=s3-control
  python3 scripts/vsl/docs_spec_index.py --find nature=runtime-s1
  python3 scripts/vsl/docs_spec_index.py --find level=L2 --find nature=agent-layer
  python3 scripts/vsl/docs_spec_index.py --index [OUT]      # snapshot JSON (para --diff)
  python3 scripts/vsl/docs_spec_index.py --diff [A] [B]     # cambios entre snapshots
  python3 scripts/vsl/docs_spec_index.py --json             # índice completo como JSON
"""
# design: docs/spec_revision/design-sources/r16-spec-v1/SPEC-REVIEW-ARC-DESIGN.vsm
# (R16_impl_with_design — structure design in sandbox/, first
# instantiation of the review arc 2026-08-15)
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = ROOT / "docs" / "spec_revision"
DEFAULT_SNAPSHOT = ROOT / "scripts" / "state" / "cache" / "spec_index_snapshot.json"

# ── cabecera ⟦ name | type | version | date ⟧ ─────────────────────────────
# VSM 1.1 (D2): the date field accepts date-only (2026-08-16) OR ISO 8601
# UTC timestamp (2026-08-16T17:40:00Z) — the generic [^|]+? already captures  # hardcoded-allow: documented format
# both; the strict validator lives in vsl_parser.py RE_DATE/RE_TIMESTAMP.
# (Promoted 2026-08-16, VSM11-PROMOTE-PRIMER.)
RE_HEADER = re.compile(r"⟦\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*⟧")
RE_STATUS = re.compile(r"@status\(V\)\s+(\w+)")
RE_STATUS_LEGACY = re.compile(r"@status\s+(\w+)")
RE_VSM = re.compile(r"@vsm\s+([\d.]+)")

# ── ORGAN por ruta (primer segmento bajo system/ o sandbox/) ─────────────
ORGAN_BY_DIR = {
    "boot": "boot",
    "instance": "instance",
    "kernel": "kernel",
    "s1-operations": "s1-operations",
    "s2-coordination": "s2-coordination",
    "s3-control": "s3-control",
    "s3star-audit": "s3star-audit",
    "s4-intelligence": "s4-intelligence",
    "s5-policy": "s5-policy",
    "ledger": "ledger",
    "learning_records": "learning_records",
    "sandbox": "sandbox",
}

# ── NATURE per branch (directive: branch defines class, not level) ────────
def nature_of(rel_parts: tuple[str, ...]) -> str:
    """nature of the branch from the path segments (relative to system/)."""
    parts = [p for p in rel_parts if p and p not in ("system", "spec_revision")]
    if not parts:
        return "root"
    first = parts[0]
    if first == "boot":
        return "canon-boot"
    if first == "instance":
        return "instance-config" if len(parts) >= 2 and parts[1] in ("infra", "templates") else "instance"
    if first == "kernel":
        return "kernel-theory"
    if first == "s1-operations":
        if len(parts) >= 2 and parts[1].startswith("s1-"):
            return "runtime-s1" if parts[1] != "s1-template" else "template"
        return "s1-pattern"
    if first in ("s2-coordination", "s3-control", "s3star-audit", "s4-intelligence"):
        return first.split("-")[0] + "-organ"
    if first == "s5-policy":
        if len(parts) >= 2 and parts[1] == "agent-policy":
            return "agent-layer"
        if len(parts) >= 2 and parts[1] == "vsl-language":
            return "language"
        return "policy"
    if first == "ledger":
        return "ledger"
    if first == "learning_records":
        return "learning"
    if first == "sandbox":
        return "sandbox"
    return "other"


# ── LEVEL by structural depth (L0=system/, L1=organ, L2=branch...) ───────
def level_of(rel_parts: tuple[str, ...]) -> str:
    parts = [p for p in rel_parts if p and p not in ("system", "spec_revision")]
    depth = len(parts) - 1  # system/X.vsm → 0; system/X/Y.vsm → 1
    return f"L{depth}" if depth <= 4 else "L4+"


def scan(root: Path) -> list[dict]:
    docs = []
    for p in sorted(root.rglob("*.vsm")):
        rel = p.relative_to(root).parts
        text = p.read_text(encoding="utf-8", errors="ignore")
        hm = RE_HEADER.search(text[:400])
        sm = RE_STATUS.search(text)
        if not sm:
            sm = RE_STATUS_LEGACY.search(text)
        vm = RE_VSM.search(text)
        lines = text.count("\n") + 1
        docs.append({
            "path": str(p.relative_to(ROOT)),
            "name": hm.group(1).strip() if hm else p.stem,
            "type": hm.group(2).strip() if hm else "?",
            "version": hm.group(3).strip() if hm else "?",
            "date": hm.group(4).strip() if hm else "?",
            "vsm": vm.group(1) if vm else "?",
            "status": sm.group(1) if sm else "SIN-@status",
            "organ": ORGAN_BY_DIR.get(rel[0], rel[0]) if rel else "?",
            "level": level_of(rel),
            "nature": nature_of(rel),
            "lines": lines,
        })
    return docs


def render_summary(docs: list[dict]) -> str:
    out = []
    out.append(f"=== DOCS SPEC-INDEX — {len(docs)} docs ===")
    for field in ("status", "organ", "nature", "level"):
        counts: dict[str, int] = {}
        for d in docs:
            counts[d[field]] = counts.get(d[field], 0) + 1
        out.append(f"\n[{field}]")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            out.append(f"  {k}: {v}")
    return "\n".join(out)


def find(docs: list[dict], filters: list[tuple[str, str]]) -> list[dict]:
    out = []
    for d in docs:
        if all(d.get(k) == v for k, v in filters):
            out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="docs spec spider (S3* report-only)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--find", action="append", default=[], metavar="field=value")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--index", nargs="?", const=str(DEFAULT_SNAPSHOT), metavar="OUT")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    args = ap.parse_args()

    if args.diff:
        a, b = args.diff
        ja = json.loads(Path(a).read_text(encoding="utf-8"))
        jb = json.loads(Path(b).read_text(encoding="utf-8"))
        da = {x["path"]: x for x in ja}
        db = {x["path"]: x for x in jb}
        added = [p for p in db if p not in da]
        removed = [p for p in da if p not in db]
        changed = [p for p in da if p in db and da[p] != db[p]]
        print(f"diff {a} → {b}: +{len(added)} −{len(removed)} ~{len(changed)}")
        for p in added: print(f"  + {p}")
        for p in removed: print(f"  - {p}")
        for p in changed: print(f"  ~ {p} ({da[p].get('status')} → {db[p].get('status')})")
        return 0

    docs = scan(Path(args.root))

    if args.index:
        Path(args.index).parent.mkdir(parents=True, exist_ok=True)
        Path(args.index).write_text(json.dumps(docs, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✓ snapshot: {args.index} ({len(docs)} docs)")
        return 0

    if args.find:
        filters = []
        for f in args.find:
            if "=" not in f:
                print(f"❌ --find necesita field=value: {f}", file=sys.stderr)
                return 1
            k, v = f.split("=", 1)
            filters.append((k, v))
        res = find(docs, filters)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"=== {len(res)} docs donde {' ∧ '.join(f'{k}={v}' for k, v in filters)} ===")
            for d in res:
                print(f"  [{d['status']:7}] L{d['level'][1]} {d['nature']:16} {d['path']}")
        return 0

    if args.json:
        print(json.dumps(docs, indent=2, ensure_ascii=False))
        return 0

    print(render_summary(docs))
    return 0


if __name__ == "__main__":
    sys.exit(main())