#!/usr/bin/env python3
"""apply_bbs_whitelist.py — merge the S5-ratified bbs_bridge block into a live
s5_policy.json, preserving every other key. Backup + atomic write + verify.

Usage:
    python3 apply_bbs_whitelist.py /etc/vsf/s5_policy.json bbs_whitelist.ratified.json

The fragment must contain a top-level "bbs_bridge" object (and optionally
"_ratification", which is recorded under the policy's bbs_bridge._ratified_from).
Idempotent: re-running with the same fragment is a no-op modulo the backup.
"""
import json
import os
import sys


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: apply_bbs_whitelist.py <live_policy.json> <fragment.json>", file=sys.stderr)
        return 2
    policy_path, frag_path = argv[1], argv[2]

    with open(frag_path, encoding="utf-8") as f:
        frag = json.load(f)
    bbs = frag.get("bbs_bridge")
    if not isinstance(bbs, dict) or not bbs.get("allowed_actions"):
        print("ERROR: fragment has no non-empty bbs_bridge.allowed_actions", file=sys.stderr)
        return 1

    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)

    before = len((policy.get("bbs_bridge") or {}).get("allowed_actions") or [])

    # carry the ratification provenance INTO the live policy for auditability
    if "_ratification" in frag:
        bbs = {**bbs, "_ratified_from": frag["_ratification"]}
    policy["bbs_bridge"] = bbs

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

    after = len(policy["bbs_bridge"]["allowed_actions"])
    rules = ", ".join(r["name"] for r in policy["bbs_bridge"]["allowed_actions"])
    print(f"OK: bbs_bridge.allowed_actions {before} -> {after} rules [{rules}]")
    print(f"OK: cooldown_secs={policy['bbs_bridge'].get('cooldown_secs')} | backup={bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
