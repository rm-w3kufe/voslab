#!/usr/bin/env python3
"""doc_manifest.py — Manifest + drift verify for .vsm docs (T5.3).

Scope (S5 rmw3 2026-09-09): FULL with curated sync.
  Phase 1 (this script): MANIFEST (inventory with checksums) + VERIFY
    (drift report). Read-only outside vOSlab; writes ONLY inside vOSlab.
  Phase 2 (needs curated critical list + S5): SYNC copies INTO vOSlab
    (docs/canon_mirror/). NEVER writes outside ~/vOSlab/.

Usage:
  doc_manifest.py scan    # (re)build state/doc_manifest.jsonl
  doc_manifest.py verify  # re-checksum + drift report (JSON to stdout)
  doc_manifest.py stats   # counts from the manifest
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
VSF = Path.home() / "vsf"
MANIFEST = VOSLAB / "state" / "doc_manifest.jsonl"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()[:16]


def _category(rel: str) -> str:
    r = rel.lower()
    if "spec_revision" in r or "covenant" in r or "hard_rules" in r:
        return "spec"
    if "plan" in r:
        return "plan"
    if "gate" in r or "polic" in r or "rule" in r:
        return "rule"
    if "tree" in r or "gap" in r:
        return "governance"
    if "session" in r or "log" in r:
        return "record"
    return "guide"


def _collect(root: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"
                       and d != "node_modules"]
        for f in filenames:
            if f.endswith(".vsm"):
                out.append(Path(dirpath) / f)
    return sorted(out)


def cmd_scan() -> int:
    voslab_docs = {p.name: p for p in _collect(VOSLAB)}
    entries = []
    for src in _collect(VSF):
        try:
            checksum = _sha(src)
        except OSError:
            continue
        rel = str(src.relative_to(VSF))
        dest = voslab_docs.get(src.name)
        if dest is None:
            status = "missing"
            dest_rel = None
        else:
            try:
                dest_rel = str(dest.relative_to(VOSLAB))
                status = ("synced" if _sha(dest) == checksum else "modified")
            except OSError:
                dest_rel, status = None, "missing"
        entries.append({
            "id": rel.replace("/", ":"),
            "source": str(src),
            "dest": dest_rel,
            "category": _category(rel),
            "priority": "critical" if _category(rel) in ("spec", "rule") else "medium",
            "sync_mode": "reference",  # phase 2 curates auto/manual per doc
            "status": status,
            "checksum": checksum,
        })
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    print(f"manifest: {len(entries)} vsf docs -> {MANIFEST}")
    return 0


def _load() -> list[dict]:
    if not MANIFEST.exists():
        return []
    out = []
    with open(MANIFEST) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def cmd_verify() -> int:
    drifted, ok, gone = [], 0, 0
    for e in _load():
        src = Path(e["source"])
        if not src.exists():
            gone += 1
            continue
        try:
            current = _sha(src)
        except OSError:
            gone += 1
            continue
        if current != e["checksum"]:
            drifted.append(e["id"])
        else:
            ok += 1
    print(json.dumps({"ok": ok, "drifted": drifted,
                      "drifted_count": len(drifted), "gone": gone}))
    return 0


def cmd_stats() -> int:
    entries = _load()
    by_status: dict[str, int] = {}
    for e in entries:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
    print(json.dumps({"total_vsf": len(entries), "by_status": by_status,
                      "manifest": str(MANIFEST)}))
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("scan", "verify", "stats"):
        print(__doc__.split("Usage:")[1].strip(), file=sys.stderr)
        return 1
    return {"scan": cmd_scan, "verify": cmd_verify,
            "stats": cmd_stats}[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
