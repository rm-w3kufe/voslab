#!/usr/bin/env python3
"""verify_boot_primer.py — staleness detector for the compressed VSL boot
primer (system/boot/{core_boot_primer,regulation_layer,
hard_rules}.vsm).

Problem this exists to prevent: the primer was hand-written (2026-08-03) by
compressing 5 canonical source files. If any of those sources change and
nobody updates the primer, it silently drifts and becomes exactly the kind
of stale, wrongly-cited document this whole project spent a session finding
and fixing elsewhere (CLAUDE.md's dead links, README's decommissioned
opsroom instructions, BRIEFING.vsf.md's wrong VSL version pin, the A5/A8/D7
axiom collisions). This script does NOT verify the primer's CONTENT is
correct (that requires human/agent judgment) -- it verifies the primer's
content has been RE-CHECKED since each source last changed, by comparing
source-file hashes against a manifest written at the last verification.

Usage:
  python3 scripts/vsl/validator/verify_boot_primer.py            # check (default)
  python3 scripts/vsl/validator/verify_boot_primer.py --update   # re-baseline after
                                                          # manually verifying
                                                          # the primer still
                                                          # matches its sources

Exit codes: 0 = clean (all sources match the last-verified manifest).
            1 = STALE (>=1 source changed since last verification) or the
                manifest doesn't exist yet (--update required first).

Deterministic, stdlib-only. No LLM in this path (R10).

Paths updated 2026-08-06: PH-00 moved the boot files from docs/spec/
agent_protocol/vsl_*_v1.vsm → docs/spec_revision/system/boot/*.vsm (renamed
without _v1 suffix). PH-03-S5 + boot-absorb moved covenant.vsm from
docs/governance/ → docs/spec_revision/system/boot/covenant.vsm. The manifest
path and SOURCE_MAP below now reflect the post-move paths.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# SINGLE TRACK — system/boot IS production (promoted 2026-08-11).
#
# Prior shape: TWO TRACKS, deliberately separate. `production` pointed at
# docs/spec/agent_protocol/ (the files CLAUDE.md, BRIEFING.vsf.md, RULES.md
# and the OpenCode config actually read at boot) and was BLOCKING;
# `spec_revision` pointed at docs/spec_revision/system/boot/ (the v2
# consolidated body: covenant absorbed, D4-Ln namespace fixed, per-doc
# versioning) and was ADVISORY while it was built.
#
# Why the shape existed: on 2026-08-06 the script had been repointed WHOLLY
# at spec_revision, so production lost its staleness cover entirely. It went
# unnoticed that docs/governance/covenant.vsm — the source build.rs hashes
# into COVENANT_SHA256, and whose absence makes the nucleus refuse to
# compile — had been removed from production by the restructure. The guard
# reported clean throughout, because it was no longer looking there.
#
# Ratified 2026-08-11 (rmw3 + DS): the boot package files (CLAUDE.md,
# RULES.md, .opencode/agent/vsf-s3-planner.md) now
# reference docs/spec_revision/system/boot/ directly. (BRIEFING.vsf.md was
# deleted 2026-08-12 — fully redistributed: role content into the agent .md,
# protocol into canon/skills; opencode.json instructions now ["RULES.md"].)
# The old
# docs/spec/agent_protocol/ copies are retired as reference targets (the
# files still exist on disk, unmaintained). Per the old note: the production
# track was DELETED, not merged — this single track is the v2 body, blocking.

TRACKS: dict[str, dict] = {
    "production": {
        "blocking": True,
        "manifest": "system/boot/.primer_sources_manifest.json",
        "map": {
            "system/boot/core_boot_primer.vsm": [
                "docs/spec/vsm_notation_spec.md",
                "system/boot/covenant.vsm",
                "system/boot/communication_protocol.vsm",
                # comms{} is compressed from the code, not from any doc: a
                # MSG_TYPES or origin() change here drifts the primer silently.
                "scripts/vsl/tools/envelope.py",
            ],
            "system/boot/regulation_layer.vsm": [
                "docs/governance/covenant_ops.vsm",
            ],
            # DIRECTION NOTE (2026-08-10): read this pairing as COHERENCE, not
            # authorship. hard_rules.vsm is the normative DEFINITION and
            # RULES.md is the annotated mirror that cites it — the reverse of
            # what this file's header docstring ("compressing N canonical
            # source files") describes. The guard is still correct and still
            # wanted: either side changing means the other must be re-read.
            # It just no longer implies RULES.md is the source of truth. Do
            # not "fix" this by deleting the pairing.
            "system/boot/hard_rules.vsm": [
                "RULES.md",
            ],
        },
    },
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes(track: dict) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for primer, sources in track["map"].items():
        out[primer] = {}
        for src in sources:
            p = ROOT / src
            out[primer][src] = sha256_of(p) if p.exists() else "MISSING"
    return out


def load_manifest(track: dict) -> dict | None:
    mp = ROOT / track["manifest"]
    return json.loads(mp.read_text()) if mp.exists() else None


def write_manifest(track: dict, hashes: dict) -> None:
    mp = ROOT / track["manifest"]
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")


def check_track(name: str, track: dict) -> int:
    """Return 1 if this track is stale, else 0. Never exits."""
    tag = "BLOCKING" if track["blocking"] else "advisory"
    manifest = load_manifest(track)
    if manifest is None:
        print(f"  [{name}/{tag}] no manifest yet — run --update to baseline")
        return 1 if track["blocking"] else 0

    now = current_hashes(track)
    problems = []
    for primer, sources in track["map"].items():
        for src in sources:
            old = manifest.get(primer, {}).get(src)
            new = now[primer][src]
            if new == "MISSING":
                problems.append(f"MISSING: {src}  (required by {primer})")
            elif old is None:
                problems.append(f"NEW SOURCE not in manifest: {src}")
            elif old != new:
                problems.append(f"STALE: {src}  ({old[:12]}… != {new[:12]}…)")

    if not problems:
        print(f"  ✓ [{name}/{tag}] sources unchanged since last verification")
        return 0

    print(f"  ✗ [{name}/{tag}]")
    for pr in problems:
        print(f"      {pr}")
    return 1


def check() -> int:
    rc = 0
    for name, track in TRACKS.items():
        stale = check_track(name, track)
        if stale and track["blocking"]:
            rc = 1
    if rc:
        print()
        print("  Action: re-read the changed source(s), confirm (or fix) the")
        print("  primer's corresponding section, then re-run with --update.")
        print("  Do NOT --update without re-checking the content — that")
        print("  defeats the point (R4: a claim of verification is not")
        print("  evidence of verification). Only the production track blocks;")
        print("  spec_revision is reported for visibility while it is built.")
    return rc


def update() -> int:
    for name, track in TRACKS.items():
        hashes = current_hashes(track)
        missing = [f"{pm} <- {s}" for pm, ss in hashes.items()
                   for s, h in ss.items() if h == "MISSING"]
        if missing and track["blocking"]:
            print(f"  ✗ ABORT [{name}]: source file(s) not found:")
            for m in missing:
                print(f"      {m}")
            return 1
        write_manifest(track, hashes)
        n = sum(len(v) for v in hashes.values())
        print(f"  ✓ [{name}] manifest updated ({n} source hashes)")
    return 0


def main() -> int:
    if "--update" in sys.argv:
        return update()
    return check()


if __name__ == "__main__":
    sys.exit(main())
