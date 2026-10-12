#!/usr/bin/env python3
"""apply_bbs_whitelist.py — merge the S5-ratified phidown_actuator block into a live
s5_policy.json, preserving every other key. Backup + atomic write + verify.

(PHIDOWN-ACTUATOR-FULL-RENAME 2026-10-12: canonical key is now
"phidown_actuator". Fragments carrying the legacy "bbs_bridge" key are
still accepted and migrated on write. Filename kept for reference stability.)

Usage:
    python3 apply_bbs_whitelist.py /etc/vsf/s5_policy.json phidown_whitelist.ratified.json

The fragment must contain a top-level "phidown_actuator" object (legacy
"bbs_bridge" accepted) with non-empty allowed_actions (and optionally
"_ratification", recorded under phidown_actuator._ratified_from).
Idempotent: re-running with the same fragment is a no-op modulo the backup.
"""
import json
import os
import sys

CANON_KEY = "phidown_actuator"
LEGACY_KEY = "bbs_bridge"


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: apply_bbs_whitelist.py <live_policy.json> <fragment.json>", file=sys.stderr)
        return 2
    policy_path, frag_path = argv[1], argv[2]

    with open(frag_path, encoding="utf-8") as f:
        frag = json.load(f)
    cfg = frag.get(CANON_KEY)
    if cfg is None and isinstance(frag.get(LEGACY_KEY), dict):
        cfg = frag.get(LEGACY_KEY)  # legacy fragment → migrate on write
    if not isinstance(cfg, dict) or not cfg.get("allowed_actions"):
        print(f"ERROR: fragment has no non-empty {CANON_KEY}.allowed_actions", file=sys.stderr)
        return 1

    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)

    before = len((policy.get(CANON_KEY) or {}).get("allowed_actions") or [])

    # carry the ratification provenance INTO the live policy for auditability
    if "_ratification" in frag:
        cfg = {**cfg, "_ratified_from": frag["_ratification"]}
    policy[CANON_KEY] = cfg

    # backup (timestamped, never overwrites a prior backup in the same second twice)
    bak = policy_path + ".bak"
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(json.load(open(policy_path, encoding="utf-8")), f, indent=2)

    # atomic write: temp in the same dir → os.replace
    tmp = policy_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2)
        f.write("\n")
    os.replace(tmp, policy_path)

    after = len(policy[CANON_KEY]["allowed_actions"])
    rules = ", ".join(r["name"] for r in policy[CANON_KEY]["allowed_actions"])
    print(f"OK: {CANON_KEY}.allowed_actions {before} -> {after} rules [{rules}]")
    print(f"OK: cooldown_secs={policy[CANON_KEY].get('cooldown_secs')} | backup={bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
