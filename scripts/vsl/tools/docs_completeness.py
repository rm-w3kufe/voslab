#!/usr/bin/env python3
"""docs_completeness.py — migration-completeness verify (docs_migration circle).

CLAIM: every knowledge file in ~/vsf/docs (outside the frozen snapshot and
runtime junk) is PRESENT in the workspace — same relative path under
docs/, byte-identical content (sha256) somewhere in the repo, or its
continuation is recorded in state/doc_manifest.jsonl (dest exists on
disk; manifest integrity itself is gated by manifest-dest-integrity).
The manifest clause covers locally-EVOLVED knowledge moved by the
docs_lifecycle circles (source sha no longer matches, but the evolved
copy's location is the integrity-verified continuation).

This is the observable invariant behind rmw3's migration order
("completamos la migracion"); doc_manifest.py covers the .vsm subset,
this tool covers ALL knowledge types (.md/.tex/.pdf/.html/figures...).

Exclusions (declared, not silent):
  - docs/spec_revision/   frozen historical snapshot (by design)
  - .index.db, .canon_census.db   runtime databases (RUNTIME doctrine)
  - LaTeX build junk (.aux/.log/.out/.blg/.bbl/.toc/.fls/...)  regenerable
  - gitignored runtime caches are checked by PATH presence only (they
    live on disk; tracking is a separate .gitignore concern)

Env (for fixtures): DOCS_COMPLETE_VSF, DOCS_COMPLETE_WS
Exit: 0 = complete, 1 = missing > 0 (or empty universe = config error)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

JUNK = {".aux", ".log", ".out", ".blg", ".bbl", ".toc", ".fls",
        ".fdb_latexmk", ".spl", ".snm", ".vrb", ".brf", ".db", ".pyc"}
SKIP_DIRS = {"spec_revision"}
SKIP_ROOT = {".index.db", ".canon_census.db"}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_knowledge(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in SKIP_DIRS:
        return False
    if len(rel.parts) == 1 and rel.name in SKIP_ROOT:
        return False
    return rel.suffix.lower() not in JUNK


def _ws_files(ws: Path):
    for f in ws.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            yield f


def run() -> int:
    vsf = Path(os.environ.get("DOCS_COMPLETE_VSF") or Path.home() / "vsf/docs")
    ws = Path(os.environ.get("DOCS_COMPLETE_WS") or Path(__file__).resolve().parents[3])
    docs_root = ws / "docs"

    present, candidates = 0, []
    for f in sorted(vsf.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(vsf)
        if not _is_knowledge(rel):
            continue
        if (docs_root / rel).is_file():
            present += 1
        else:
            candidates.append((rel, f))

    # sha-check only candidates, ws prefetched by file size (fast)
    missing, evolved = [], []
    by_size: dict = {}
    if candidates:
        want_sizes = set()
        for _, f in candidates:
            try:
                want_sizes.add(f.stat().st_size)
            except OSError:
                pass
        for w in _ws_files(ws):
            try:
                if w.stat().st_size in want_sizes:
                    by_size.setdefault(w.stat().st_size, []).append(w)
            except OSError:
                pass
        for rel, f in candidates:
            try:
                s = _sha(f)
            except OSError:
                missing.append(str(rel))
                continue
            hit = False
            for w in by_size.get(f.stat().st_size, []):
                try:
                    if _sha(w) == s:
                        hit = True
                        break
                except OSError:
                    continue
            if not hit:
                # manifest continuity: evolved knowledge relocated by the
                # docs_lifecycle circles (dest verified by doc_manifest verify)
                mpath = ws / "state" / "doc_manifest.jsonl"
                cont = False
                if mpath.is_file():
                    # manifest ids are rooted at ~/vsf ("docs:" prefix);
                    # completeness iterates ~/vsf/docs — try both forms
                    raw = str(rel).replace("/", ":")
                    mids = (raw, "docs:" + raw)
                    try:
                        for line in mpath.open():
                            e = json.loads(line)
                            if e.get("id") in mids and e.get("dest"):
                                if (ws / e["dest"]).is_file():
                                    cont = True
                                break
                    except (OSError, json.JSONDecodeError):
                        cont = False
                if cont:
                    evolved.append(str(rel))
                else:
                    missing.append(str(rel))

    total = present + len(candidates)
    out = {
        "ok": (total > 0 and not missing),
        "total_knowledge": total,
        "present_same_path": present,
        "relocated": len(candidates) - len(missing) - len(evolved),
        "present_evolved": evolved,
        "present_evolved_count": len(evolved),
        "missing": missing,
        "missing_count": len(missing),
        "vsf": str(vsf),
    }
    print(json.dumps(out))
    if total == 0:
        print("FAIL: empty knowledge universe (config error?)", file=sys.stderr)
        return 1
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(run())
