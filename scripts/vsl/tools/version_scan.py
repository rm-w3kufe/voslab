#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/vsl-encoding-cycle-design-v1/vsl_encoding_cycle_design.vsm
# (R16_impl_with_design — cascada VERSION-COHERENT VSM11, 5/6; el check
#  vsm-version-coherent usa este scanner: replica la detección del parser
#  @vsm≠header SIN parsear el VSL completo — un solo proceso para el corpus)
"""version_scan.py — fast corpus-wide @vsm/header coherence scanner.

Replicates vsl_parser.py's §13.1 header/@vsm coherence detection (lines
94-145) WITHOUT full VSL parsing: reads each .vsm header, finds the first
non-blank/non-comment @vsm declaration, and reports docs where they
differ. One process for the whole corpus (~100× faster than spawning the
full parser per file).

Usage:
  python3 scripts/vsl/version_scan.py [PATH...] [--dist]
    PATHs default to every .vsm under docs/spec_revision (excl. archive).
    Prints:  OK <rel>          (coherent)
             INCOHERENT <rel> <header_ver> <vsm_decl>   (gate failure)
    --dist:  additionally print the header-version distribution.
    Exit:    0 if all coherent, 1 if any incoherent.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "docs", "spec_revision")

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
        for dirpath, _dirnames, filenames in os.walk(CORPUS):
            if "/archive" in dirpath:
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