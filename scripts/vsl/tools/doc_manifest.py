#!/usr/bin/env python3
"""doc_manifest.py — Manifest + drift verify for .vsm docs (T5.3).

Scope (S5 rmw3 2026-09-09): FULL with curated sync.
  Phase 1 (this script): MANIFEST (inventory with checksums) + VERIFY
    (drift report). Read-only outside workspace; writes ONLY inside workspace.
  Phase 2 (needs curated critical list + S5): SYNC copies INTO workspace
    (docs/canon_mirror/). NEVER writes outside $VOSLAB_PATH.

Usage:
  doc_manifest.py scan    # (re)build state/doc_manifest.jsonl
  doc_manifest.py verify  # re-checksum + drift report (JSON to stdout)
  doc_manifest.py stats   # counts from the manifest
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

VOSLAB = Path(os.environ.get("DOC_MANIFEST_VOSLAB")
              or Path(__file__).resolve().parents[3])
VSF = Path(os.environ.get("DOC_MANIFEST_VSF")) if os.environ.get("DOC_MANIFEST_VSF") \
    else Path.home() / "vsf"
MANIFEST = Path(os.environ.get("DOC_MANIFEST")) if os.environ.get("DOC_MANIFEST") \
    else VOSLAB / "state" / "doc_manifest.jsonl"


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


def _resolve_all(root_vsf: Path, root_voslab: Path):
    """Resolve every vsf .vsm to its workspace dest (drift-circle 2026-10-04).

    Root cause fixed: the old resolution took the FIRST basename match
    (`voslab_by_name.setdefault`) — 34 dests received up to 93 sources
    (any spec.vsm -> CHECO-PROJ/spec.vsm, any results.vsm ->
    AC-ETA-REDO/results.vsm), which masked 25 truly-absent files as
    'modified'.  Resolution priority now:
      1. same relative path exists            -> present
      2. content-exact (sha) match elsewhere   -> relocated / mirrored
      3. UNIQUE basename match                 -> relocated|modified|mirrored
      4. >1 basename match, nothing exact      -> unique-max token-overlap
         tiebreak (docs_lifecycle circle: promoted files gained @status,
         losing the vsf sha; generic basenames like spec.vsm then tie —
         rank candidates by shared dirname tokens vs the source rel path,
         split on _ - / excluding generic segments; a UNIQUE maximum
         with >=1 shared token wins, ties stay ambiguous)
      5. >1 basename match, no unique overlap  -> ambiguous (dest=None)
      6. nothing at all                        -> missing
    Returns list of (src, checksum, rel, dest|None, status).
    """
    by_name: dict = {}
    by_sha: dict = {}
    for p in _collect(root_voslab):
        by_name.setdefault(p.name, []).append(p)
        try:
            by_sha.setdefault(_sha(p), []).append(p)
        except OSError:
            pass
    out = []
    for src in _collect(root_vsf):
        try:
            checksum = _sha(src)
        except OSError:
            continue
        rel = str(src.relative_to(root_vsf))
        same = root_voslab / rel
        if same.is_file():
            dest, status = same, "present"
        elif by_sha.get(checksum):
            dest = by_sha[checksum][0]
            status = "mirrored" if "canon_mirror" in str(dest) else "relocated"
        elif len(by_name.get(src.name, [])) == 1:
            dest = by_name[src.name][0]
            try:
                same_bytes = _sha(dest) == checksum
            except OSError:
                same_bytes = False
            if same_bytes:
                status = "mirrored" if "canon_mirror" in str(dest) else "relocated"
            else:
                status = "modified"
        elif by_name.get(src.name):
            # token-overlap tiebreak (see docstring step 4)
            generic = {"spec", "docs", "vsf", "system", "archive",
                       "lifecycle", "vsm", "doc", "plans"}
            def toks(parts):
                out = set()
                for seg in parts:
                    if seg.isdigit():
                        continue
                    for t in re.split(r"[_\-]+", seg):
                        if t and t not in generic:
                            out.add(t)
                return out
            rel_tok = toks(Path(rel).parent.parts)
            best, best_n, ties = None, 0, 0
            for cand in by_name[src.name]:
                n = len(rel_tok & toks(cand.parts[:-1]))
                if n > best_n:
                    best, best_n, ties = cand, n, 1
                elif n and n == best_n:
                    ties += 1
            if best is not None and best_n >= 1 and ties == 1:
                dest = best
                try:
                    same_bytes = _sha(dest) == checksum
                except OSError:
                    same_bytes = False
                status = ("mirrored" if "canon_mirror" in str(dest)
                          else ("relocated" if same_bytes else "modified"))
            else:
                dest, status = None, "ambiguous"
        else:
            dest, status = None, "missing"
        out.append((src, checksum, rel, dest, status))
    return out


def cmd_scan() -> int:
    entries = []
    for src, checksum, rel, dest, status in _resolve_all(VSF, VOSLAB):
        try:
            dest_rel = str(dest.relative_to(VOSLAB)) if dest else None
        except ValueError:
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
    """Integrity verify (drift-circle 2026-10-04).

    Besides source-side checksum drift (report-only), validates the
    DEST side — the invariants the basename-era manifest violated:
      stale:      stored dest != freshly-resolved dest
      collisions: >=2 entries resolving to the same dest file
      unresolved: status ambiguous/missing (content not findable)
      gone_dest:  stored dest path no longer on disk
    Exit 1 when any integrity bucket is non-empty (drift alone stays 0).
    """
    stored = _load()
    by_id = {e["id"]: e for e in stored}
    resolved = _resolve_all(VSF, VOSLAB)
    stale, unresolved, drifted = [], [], []
    dest_owner: dict = {}
    collisions = []
    for src, checksum, rel, dest, status in resolved:
        eid = rel.replace("/", ":")
        e = by_id.get(eid)
        dest_rel = str(dest.relative_to(VOSLAB)) if dest else None
        if e is None:
            stale.append({"id": eid, "reason": "entry-missing", "dest": dest_rel})
            continue
        if e.get("dest") != dest_rel:
            stale.append({"id": eid, "stored": e.get("dest"), "resolved": dest_rel})
        if status in ("ambiguous", "missing"):
            unresolved.append({"id": eid, "status": status})
        if dest_rel:
            if dest_rel in dest_owner:
                collisions.append({"dest": dest_rel,
                                   "ids": [dest_owner[dest_rel], eid]})
            else:
                dest_owner[dest_rel] = eid
        if e.get("checksum") != checksum:
            drifted.append(eid)
    gone_dest = [e["id"] for e in stored
                 if e.get("dest") and not (VOSLAB / e["dest"]).exists()]
    orphan = [e["id"] for e in stored if e["id"] not in
              {r[2].replace("/", ":") for r in resolved}]
    clean = not (stale or collisions or unresolved or gone_dest or orphan)
    print(json.dumps({
        "ok": clean, "entries": len(stored),
        "stale": stale, "stale_count": len(stale),
        "collisions": collisions, "collision_count": len(collisions),
        "unresolved": unresolved, "unresolved_count": len(unresolved),
        "gone_dest": gone_dest, "gone_dest_count": len(gone_dest),
        "orphan": orphan, "orphan_count": len(orphan),
        "source_drifted": drifted, "source_drifted_count": len(drifted),
    }))
    return 0 if clean else 1


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
