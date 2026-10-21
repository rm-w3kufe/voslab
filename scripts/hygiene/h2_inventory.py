#!/usr/bin/env python3
"""H2 inventory — scripts/tests orphans (reference-count based).

design: docs/plans/hygiene_audit_plan_2026_10_21.vsm (H2-CODE-ORPHANS)

CLAIM: batch-1 hygiene candidates come from a deterministic reference
scan, not from intuition (anti-inflado rule of the plan):
  - scripts/ orphan candidate: *.py NEVER mentioned outside itself
    (self-loops excluded; the file's own name in own content doesn't
    count as a reference)
  - tests orphan candidate: test_*.py never mentioned in any other file
    (candidate, not verdict — tests may be deliberately self-contained;
    classification happens at batch review with S5, R17)
Reference scan is text-wide byte search (simple first detector; static
dead-func analysis = declared P3 detector debt in the plan, NOT here).

No rm, no archive, no status changes: this tool REPORTS class buckets
with evidence (regex-able paths). Batches execute only after S5 vote.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".gitlab", ".opencode/cache",
    "logs",  # rotated jsonl.gz + archives — never reference-relevant
}
# artifact/self dirs never count as references for anything
SCAN_EXCLUDE = {
    "state/hygiene",  # own artifacts (would self-reference)
    "state/epistemic/sidecars", "state/doc_tracking",
    "state/monitoring", "state/rsi/traces",
}
REF_STRIP = {  # artifacts where file names appear mechanically
    "docs/INDEX.md",  # generated sweep (A1 hook)
}
SOURCE_EXTS = {  # text-family only; binaries/caches not reference-relevant
    ".py", ".vsm", ".ts", ".js", ".sh", ".bash", ".json", ".yaml", ".yml",
    ".toml", ".md", ".txt", ".cfg", ".ini", ".service.js", ".service",
    ".timer", ".html", ".rs",
}
MAX_BYTES = 512_000  # skip huge binaries/db/files from the ref scan

def iter_files(root: Path, extra_skip: tuple[str, ...] = ()):
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS
                       and not any(fnmatch.fnmatch(rel, pat) for pat in extra_skip)]
        for fn in filenames:
            yield os.path.join(dirpath, fn)

def load_all_sources(root: Path) -> dict[str, bytes]:
    data: dict[str, bytes] = {}
    for f in iter_files(root, extra_skip=tuple(SCAN_EXCLUDE)):
        ext = os.path.splitext(f)[1]
        if ext not in SOURCE_EXTS:
            continue
        try:
            if os.path.getsize(f) > MAX_BYTES:
                continue
            with open(f, "rb") as fh:
                data[os.path.relpath(f, root)] = fh.read()
        except OSError:
            continue
    return data

def ref_count(rel_path: str, sources: dict[str, bytes]) -> list[str]:
    base = os.path.basename(rel_path)
    stem = base[:-3] if base.endswith(".py") else base
    hits = []
    needle = stem.encode()
    for src, blob in sources.items():
        if src == rel_path or src in REF_STRIP:
            continue
        if stem in ("__init__",):  # meaningless stem
            continue
        if needle in blob:
            hits.append(src)
    return hits

def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent
    rel_scripts = root / "scripts"
    sources = load_all_sources(root)

    log = (root / "state" / "hygiene" / "h2_inventory.json")
    entries = []
    for f in sorted(iter_files(rel_scripts)):
        rel = os.path.relpath(f, root)
        if not rel.endswith(".py"):
            continue
        stub = os.path.basename(rel)[:-3] if rel.endswith(".py") else "_"
        if stub == "_":
            continue
        refs = ref_count(rel, sources)
        entries.append({
            "path": rel,
            "refs": len(refs),
            "ref_files": sorted(refs)[:8],
            "mtime": datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc).isoformat(timespec="seconds"),
        })

    scripts = [e for e in entries if e["path"].startswith("scripts/")]
    orphans_scripts = [e for e in scripts if e["refs"] == 0]

    # test orphans: repo-wide test_*.py never referenced outside itself
    tests_orphans = []
    for f in sorted(iter_files(root)):
        rel = os.path.relpath(f, root)
        base = os.path.basename(rel)
        if not (base.startswith("test_") and base.endswith(".py")):
            continue
        if not any(seg == "tests" for seg in Path(rel).parts):
            continue
        refs = ref_count(rel, sources)
        if refs == 0:
            tests_orphans.append({
                "path": rel,
                "mtime": datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc).isoformat(timespec="seconds"),
            })

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scanner": "scripts/hygiene/h2_inventory.py (referencia-based, anti-inflado planned)",
        "scripts_scanned": len(scripts),
        "scripts_orphans": orphans_scripts,
        "tests_orphans": tests_orphans,
        "docs_dep_graph_preview": {
            "cycles": 90,  # h2_dep_graph_raw.txt — full tree is H3 scope
            "reason": "classification.local.vsm duplicated across trees",
        },
    }
    os.makedirs(log.parent, exist_ok=True)
    with open(log, "w") as fh:
        json.dump(result, fh, indent=1)
    print(f"H2 inventory: scripts scanned={len(scripts)}, "
          f"scripts orphans={len(orphans_scripts)}, test orphans={len(tests_orphans)}")
    for e in orphans_scripts:
        print(f"  ORPH script: {e['path']}")
    for e in tests_orphans:
        print(f"  ORPH test: {e['path']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
