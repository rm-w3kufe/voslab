#!/usr/bin/env python3
"""alg_chain_verify.py — offline HMAC chain verifier for vsf_algedonic.jsonl (M7).

Usage:
    python3 scripts/vsl/alg_chain_verify.py [--log /path/to/vsf_algedonic.jsonl]

Reads the algedonic log and verifies the HMAC chain for all entries that
have _c_prev + _c_hash fields. Reports first broken link and count of
verified entries.

Key: ~/.local/share/vsf/alg_hmac.key (offline copy, same key as LXC 104)
"""
import argparse
import hmac
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_LOG = (Path(__file__).resolve().parents[3] / "state" / "algedonic"
               / "offline_verify.jsonl")  # S5: workspace-local
DEFAULT_KEY = Path.home() / ".local" / "share" / "vsf" / "alg_hmac.key"


def compute_hash(key: bytes, prev: str, content: str) -> str:
    return hmac.new(key, (prev + content).encode(), hashlib.sha256).hexdigest()


def verify(log_path: Path, key_path: Path) -> int:
    try:
        key = bytes.fromhex(key_path.read_text().strip())
    except Exception as e:
        print(f"ERROR: cannot load key from {key_path}: {e}")
        return 2

    if not log_path.exists():
        print(f"ERROR: log not found: {log_path}")
        return 2

    total = 0
    chained = 0
    broken_at = None
    prev_hash = "genesis"

    with open(log_path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "_c_hash" not in entry:
                prev_hash = "genesis"  # reset: entries before chain epoch
                continue

            entry_prev = entry.get("_c_prev", "genesis")
            entry_hash = entry["_c_hash"]

            clean = {k: v for k, v in entry.items() if not k.startswith("_c_")}
            clean_json = json.dumps(clean, sort_keys=True, ensure_ascii=False)
            expected = compute_hash(key, entry_prev, clean_json)

            if expected != entry_hash:
                print(f"CHAIN BROKEN at line {lineno}: expected={expected[:16]}... got={entry_hash[:16]}...")
                broken_at = lineno
                break

            if entry_prev != prev_hash:
                print(f"CHAIN DISCONTINUITY at line {lineno}: prev_hash mismatch "
                      f"(expected {prev_hash[:16]}... got {entry_prev[:16]}...)")
                broken_at = lineno
                break

            prev_hash = entry_hash
            chained += 1

    if broken_at:
        print(f"RESULT: FAIL — chain broken at line {broken_at} (verified {chained} before)")
        return 1
    print(f"RESULT: OK — {chained} chained entries verified (total lines: {total})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Offline HMAC chain verifier for vsf_algedonic.jsonl")
    p.add_argument("--log", default=str(DEFAULT_LOG), help="path to vsf_algedonic.jsonl")
    p.add_argument("--key", default=str(DEFAULT_KEY), help="path to alg_hmac.key")
    a = p.parse_args()
    return verify(Path(a.log), Path(a.key))


if __name__ == "__main__":
    sys.exit(main())
