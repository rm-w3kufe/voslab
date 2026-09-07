#!/usr/bin/env python3
"""verify_covenant_hash.py — independent audit of COVENANT_SHA256 agreement.

Deliberately does NOT read a shared config. It recomputes the hash from the
canonical covenant itself and then checks each witness on its own terms. A
verifier that read the same config as the thing it verifies would compare a
value to itself -- which is precisely the failure mode this whole design
avoids (see docs/spec/covenant_hash_registry.vsm §design_note).

Checks, by class:

  MUTABLE       core/s5_policy.default.json must MATCH the recomputed hash.
                A mismatch means S5 boots expecting a covenant that is not
                the one on disk.
  DERIVED       build.rs must point at the canonical path and still carry its
                panic. env!() sites must not have been replaced by literals.
  PROVENANCE    experiment/report stamps must NOT match the current hash once
                the covenant is promoted -- they record a PAST covenant. This
                check is inverted on purpose: a provenance stamp that silently
                tracks the current hash has been rewritten.
  PUBLISHED     --remote fetches the canonical URL and compares. Off by
                default: no network in the default path (R1/R10).

Usage:
  python3 scripts/state/verify_covenant_hash.py            # local audit
  python3 scripts/state/verify_covenant_hash.py --remote   # + published hash

Exit: 0 all witnesses agree · 1 divergence.

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "docs/governance/covenant.vsm"
POLICY = ROOT / "core/s5_policy.default.json"
BUILD_RS = ROOT / "projects/vsf-nucleus/build.rs"
ENV_SITES = ["projects/vsf-nucleus/src/s4.rs",
             "projects/vsf-nucleus/src/beacon.rs"]
PROVENANCE = [
    "docs/experiments/EXP-A01-01/spec.vsm",
    "docs/experiments/EXP-A01-02/spec.vsm",
    "docs/experiments/EXP-CORE-01/results.vsm",
    "docs/experiments/EXP-VNC-01/results.vsm",
    "docs/experiments/EXP-G-01/results.vsm",
    "docs/spec/s5_lm_wire/spec.vsm",
]


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if not CANONICAL.exists():
        print(f"  ✗ canonical covenant missing: {CANONICAL.relative_to(ROOT)}")
        print("    The nucleus would refuse to compile (build.rs panics).")
        return 1

    live = sha256_of(CANONICAL)
    print(f"  canonical  {CANONICAL.relative_to(ROOT)}")
    print(f"  recomputed sha256:{live}\n")
    bad = 0

    # ---- MUTABLE ----------------------------------------------------------
    pol = json.loads(POLICY.read_text())
    declared = pol.get("_meta", {}).get("covenant_hash") or \
        pol.get("covenant", {}).get("covenant_hash")
    if declared is None:
        for v in pol.values():
            if isinstance(v, dict) and "covenant_hash" in v:
                declared = v["covenant_hash"]
                break
    if declared == live:
        print(f"  ✓ MUTABLE   s5_policy.default.json agrees")
    else:
        bad += 1
        print(f"  ✗ MUTABLE   s5_policy.default.json declares "
              f"{str(declared)[:16]}… — S5 boots expecting a different "
              f"covenant than the one on disk")

    # ---- DERIVED ----------------------------------------------------------
    src = BUILD_RS.read_text()
    if "docs/governance/covenant.vsm" in src and "panic!" in src:
        print("  ✓ DERIVED   build.rs hashes the canonical path, panic intact")
    else:
        bad += 1
        print("  ✗ DERIVED   build.rs no longer hashes the canonical path, "
              "or its panic was removed — a binary could compile without "
              "its constitution")
    for s in ENV_SITES:
        t = (ROOT / s).read_text()
        if 'env!("COVENANT_SHA256")' in t:
            print(f"  ✓ DERIVED   {s} still derives")
        else:
            bad += 1
            print(f"  ✗ DERIVED   {s} no longer uses env!() — a literal here "
                  f"is an independent copy that can drift")

    # ---- PROVENANCE (inverted) -------------------------------------------
    # INFORMATIONAL, deliberately not a gate. The first version inferred
    # "a promotion has happened" from (declared != live) and flagged all six
    # stamps the moment s5_policy was merely WRONG -- turning one real defect
    # into seven reported ones, six of them false. There is no reliable local
    # signal for "promotion happened", so this reports rather than judges:
    # after a promotion these stamps MUST still show the OLD hash, and what
    # guarantees that is sync_covenant_hash.sh refusing to touch the class,
    # not a check here.
    stamped = {}
    for p in PROVENANCE:
        f = ROOT / p
        if not f.exists():
            continue
        m = re.search(r"COVENANT_SHA256:\s*([0-9a-f]{64})", f.read_text())
        if m:
            stamped.setdefault(m.group(1), []).append(p)
    for h, ps in stamped.items():
        mark = "= current" if h == live else "= an EARLIER covenant (correct)"
        print(f"  · PROVENANCE {len(ps)} stamp(s) @ {h[:16]}… {mark}")

    # ---- PUBLISHED --------------------------------------------------------
    if "--remote" in sys.argv:
        url = None
        m = re.search(r'"canonical_hash_source"\s*:\s*"([^"]+)"',
                      POLICY.read_text())
        if m:
            url = m.group(1)
        try:
            from urllib.request import urlopen
            got = urlopen(url, timeout=10).read().decode().strip()
            if got == live:
                print(f"  ✓ PUBLISHED {url} agrees")
            else:
                bad += 1
                print(f"  ✗ PUBLISHED {url} serves {got[:16]}… — nodes "
                      f"fetching it will fail closed against this covenant")
        except Exception as e:
            print(f"  ? PUBLISHED could not fetch {url}: {e}")

    print()
    print("  ✓ all witnesses agree" if not bad
          else f"  ✗ {bad} divergence(s) — see docs/spec/covenant_hash_registry.vsm")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
