#!/usr/bin/env python3
"""checks_manifest.json inventory regen + audit (S4: drift inventory).

The manifest IS the declared instrument set; the checks/ directory is the
observed set. One circle (S4_intelligence) wants both halves:
  regen (default)  rewrite the inventory from the filesystem — curated
                   category/description of known checks are preserved,
                   path+size are refreshed.
  --audit          declared vs observed, no write; rc 1 on any drift
                   (missing/extra/stale size/path). This is the
                   instrument that verifies the instrument set — the
                   check `instrument-set-valid` wraps this mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]          # .../vsf-checks
CHECKS_DIR = PKG / "checks"                        # observed set
MANIFEST = Path(__file__).resolve().parent / "checks_manifest.json"


def observed() -> dict[str, dict]:
    """name -> {path, size} from the filesystem (docs excluded)."""
    out: dict[str, dict] = {}
    if not CHECKS_DIR.is_dir():
        return out
    for p in sorted(CHECKS_DIR.iterdir()):
        if p.is_file() and not p.name.endswith(".md"):
            out[p.name] = {
                "path": f"packages/public/vsf-checks/checks/{p.name}",
                "size": p.stat().st_size,
            }
    return out


def declared_index() -> dict[str, dict]:
    """name -> entry from the manifest (empty dict if unreadable)."""
    try:
        data = json.loads(MANIFEST.read_text())
    except Exception:
        return {}
    checks = data.get("checks", []) if isinstance(data, dict) else []
    return {c.get("name", ""): c for c in checks if isinstance(c, dict) and c.get("name")}


def build() -> dict:
    """Fresh inventory: curated fields kept, path/size renewed."""
    obs = observed()
    old = declared_index()
    checks = []
    for name, info in obs.items():
        prev = old.get(name, {})
        desc = prev.get("description") or ""
        if not desc or desc.startswith("Check: "):
            desc = f"Check: {name}"
        checks.append({
            "name": name,
            # curated categories (e.g. covenant-ops-binds-to -> governance)
            # survive a regen; new checks default to the name's first token.
            "category": prev.get("category") or name.split("-")[0],
            "path": info["path"],
            "size": info["size"],
            "description": desc,
        })
    return {"checks": checks}


def drift_problems() -> list[str]:
    """Declared vs observed as a list of human-readable problems ([] = fresh)."""
    decl = declared_index()
    obs = observed()
    problems = []
    if not decl:
        problems.append(f"manifest unreadable or empty: {MANIFEST}")
    for n in sorted(set(obs) - set(decl)):
        problems.append(f"on disk, missing in manifest: {n}")
    for n in sorted(set(decl) - set(obs)):
        problems.append(f"in manifest, not on disk: {n}")
    for n in sorted(set(decl) & set(obs)):
        if decl[n].get("size") != obs[n]["size"]:
            problems.append(
                f"stale size: {n} manifest={decl[n].get('size')} "
                f"disk={obs[n]['size']}")
        if decl[n].get("path") != obs[n]["path"]:
            problems.append(
                f"stale path: {n} manifest={decl[n].get('path')} "
                f"disk={obs[n]['path']}")
    return problems


def audit() -> int:
    """rc 1 iff the inventory has drifted."""
    problems = drift_problems()
    if problems:
        print(f"INVENTORY DRIFT — {len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"INVENTORY CONSISTENT — {len(observed())} checks, manifest fresh")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", action="store_true",
                    help="declared vs observed, no write, rc1 on drift")
    args = ap.parse_args()
    if args.audit:
        return audit()
    before = json.dumps(sorted(declared_index().values(),
                               key=lambda c: c.get("name", "")),
                        sort_keys=True, default=str)
    data = build()
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    after = json.dumps(data["checks"], sort_keys=True, default=str)
    changed = "no changes" if before == after else "UPDATED"
    print(f"regen: {len(data['checks'])} checks — {changed}")
    # self-audit: the write must leave the inventory consistent
    return audit()


if __name__ == "__main__":
    sys.exit(main())
