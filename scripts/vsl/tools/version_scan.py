#!/usr/bin/env python3
# design: docs/design/sources/vsl-encoding-cycle-design-v1/vsl_encoding_cycle_design.vsm
# route: session.idle/pattern-runner (regla version-scan, read-only)
# (R16_impl_with_design — VERSION-COHERENT VSM11 cascade, 5/6; the check
#  vsm-version-coherent uses this scanner: it replicates the parser's
#  @vsm≠header detection WITHOUT parsing full VSL — one process for the corpus)
"""version_scan.py — fast corpus-wide @vsm/header coherence scanner.

Replicates vsl_parser.py's §13.1 header/@vsm coherence detection (lines
94-145) WITHOUT full VSL parsing: reads each .vsm header, finds the first
non-blank/non-comment @vsm declaration, and reports docs where they
differ. One process for the whole corpus (~100× faster than spawning the
full parser per file).

Usage:
  python3 scripts/vsl/tools/version_scan.py [PATH...] [--dist]
    PATHs default to every .vsm under system/ and docs/ (excluding the
    archived spec_revision mirror and docs/archive).
    Prints:  OK <rel>          (coherent)
             INCOHERENT <rel> <header_ver> <vsm_decl>   (gate failure)
    --dist:  additionally print the header-version distribution.
    Exit:    0 if all coherent, 1 if any incoherent.
"""
import os
import re
import sys
from pathlib import Path

# FND-VERSION-SCAN-ROOT-OFFBYONE (P-EV-R3, 2026-10-15): this file lives at
# scripts/vsl/tools/ (4 levels under repo root). The old dirname³ resolved
# ROOT to <repo>/scripts → CORPUS=<repo>/scripts/docs/spec_revision did not
# exist → os.walk yielded NOTHING → the scanner emitted zero lines with
# rc=0 and vsm-version-coherent PASSed vacuously since the tools/ migration.
# parents[3] matches every sibling tool (dep_graph, census, health_scan).
ROOT = Path(__file__).resolve().parents[3]
# 2026-10-28 decomposition: no single docs/spec_revision corpus anymore.
# Scan the live system tree + working docs, skipping archives and mirrors
# (they are historical copies, not the active corpus).
CORPUS_ROOTS = [ROOT / "system", ROOT / "docs"]
SKIP_PARTS = {
    "docs/archive",
    "docs/spec_revision",
    "docs/canon_mirror",
}

# ── same regexes as vsl_parser.py (keep in sync) ───────────────────────────
RE_HEADER = re.compile(r"⟦\s*([^/\s]\S*)\s*\|\s*(\S+)\s*\|\s*vsm-([\d.]+)\s*\|\s*([\dT:\-.]+Z?)\s*⟧")
RE_VERSION = re.compile(r"^@vsm\s+([\d.]+)")
RE_BLANK = re.compile(r"^\s*$")
RE_COMMENT = re.compile(r"^\s*//")


def scan_file(path: str):
    """Return (header_ver, vsm_decl) or (None, None) if no header/@vsm."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None, None

    header_ver = None
    for line in lines:
        m = RE_HEADER.search(line)
        if m:
            header_ver = m.group(3)
            break

    vsm_decl = None
    for line in lines:
        if RE_BLANK.match(line) or RE_COMMENT.match(line) or RE_HEADER.search(line):
            continue
        m = RE_VERSION.match(line)
        if m:
            vsm_decl = m.group(1)
            break

    return header_ver, vsm_decl


def main():
    want_dist = "--dist" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dist"]
    paths = args
    if not paths:
        paths = []
        for corpus in CORPUS_ROOTS:
            if not corpus.exists():
                continue
            for dirpath, _dirnames, filenames in os.walk(corpus):
                rel_dir = os.path.relpath(dirpath, ROOT)
                if any(rel_dir == skip or rel_dir.startswith(skip + "/")
                       for skip in SKIP_PARTS):
                    continue
                for fn in sorted(filenames):
                    if fn.endswith(".vsm"):
                        paths.append(os.path.join(dirpath, fn))
        paths.sort()

    bad = 0
    dist = {}
    for path in paths:
        header_ver, vsm_decl = scan_file(path)
        rel = os.path.relpath(path, ROOT)
        if header_ver:
            dist[header_ver] = dist.get(header_ver, 0) + 1
        if header_ver is None and vsm_decl is None:
            print(f"OK {rel} (no header, no @vsm)")
            continue
        if header_ver is not None and vsm_decl is not None and header_ver != vsm_decl:
            print(f"INCOHERENT {rel} header=vsm-{header_ver} @vsm={vsm_decl}")
            bad += 1
        else:
            print(f"OK {rel}")

    if want_dist:
        print("DISTRIBUTION", " ".join(f"vsm-{k}:{v}" for k, v in sorted(dist.items())))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())