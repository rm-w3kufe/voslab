#!/usr/bin/env python3
"""
update_manifest_sha.py — SHA_DRIFT prevention: keep coupling manifest binary_sha
in sync with what was actually deployed.

Usage:
  python3 scripts/shared/update_manifest_sha.py <manifest.json> <new_sha256>

Updates the audit_map.identity_proof.binary_sha field. Reads manifest from
repository path, writes updated version back. Exit codes: 0 = updated OR
already in sync (no-op is success — the tool's goal is sync, and the deploy
caller under `set -e` must not abort on it); 2 = real failure (manifest
missing, field path missing, bad arguments). Previously no-op returned 1,
which aborted deploy_bundle.sh mid-run before the G6 sink step (2026-10-01).

Called by deploy_bundle.sh after each binary deploy step.
Coordinate: `grep AUDIT_MAP_SHA_DRIFT deploy_bundle.sh` to see hook sites.
"""

import json
import sys
import os


def update_manifest(manifest_path: str, new_sha: str) -> int:
    """Update binary_sha. Returns 0 if changed or already in sync, 2 on failure."""
    if not os.path.isfile(manifest_path):
        print(f"update_manifest_sha: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    # Navigate to the binary_sha field
    current_sha = None
    try:
        current_sha = manifest["audit_map"]["identity_proof"]["binary_sha"]
    except KeyError:
        print(f"update_manifest_sha: manifest missing audit_map.identity_proof.binary_sha path",
              file=sys.stderr)
        return 2

    if current_sha == new_sha:
        print(f"update_manifest_sha: {os.path.basename(manifest_path)} — SHA unchanged (no-op)")
        return 0

    manifest["audit_map"]["identity_proof"]["binary_sha"] = new_sha

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"update_manifest_sha: {os.path.basename(manifest_path)} — SHA updated {current_sha[:16]}… → {new_sha[:16]}…")
    return 0


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <manifest.json> <sha256>", file=sys.stderr)
        sys.exit(2)

    manifest_path = sys.argv[1]
    new_sha = sys.argv[2].strip()

    if len(new_sha) != 64 or not all(c in "0123456789abcdef" for c in new_sha):
        print(f"update_manifest_sha: invalid SHA256: {new_sha}", file=sys.stderr)
        sys.exit(2)

    rc = update_manifest(manifest_path, new_sha)
    sys.exit(rc)


if __name__ == "__main__":
    main()
