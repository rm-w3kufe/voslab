#!/usr/bin/env python3
"""PROD-A1b production check — verify the nucleus witness sidecar against its public key.
Run on LXC 101. Confirms: (1) pubkey file matches statement issuer_pubkey_hex, (2) the Ed25519
signature over the attested canonical_hash bytes verifies, (3) the attested head is a real chain
head present in events.jsonl. Temp check artifact."""
import json, base64, glob, sys

base = "/var/lib/vsf/vsf_nucleus"
stmts = [json.loads(l) for l in open(f"{base}/events.witness.jsonl") if l.strip()]
last = stmts[-1]
print(f"statements: {len(stmts)}  | last attested head: {last['event_canonical_hash'][:24]}…")

# pubkey file (with_extension replaces → witness_key.pub)
pub_candidates = glob.glob(f"{base}/witness_key*.pub")
pub = open(pub_candidates[0]).read().strip() if pub_candidates else None
print(f"pubkey file: {pub_candidates}  matches statement: {pub == last['issuer_pubkey_hex']}")

# cryptographic verify (signature over the 32 raw bytes of the canonical_hash)
ok = None
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    vk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(last['issuer_pubkey_hex']))
    msg = bytes.fromhex(last['event_canonical_hash'])
    vk.verify(base64.b64decode(last['signature_b64']), msg)
    ok = True
except ImportError:
    ok = "no-cryptography-lib"
except Exception as e:
    ok = f"FAIL: {e}"
print(f"signature verifies: {ok}")

# is the attested head a real chain head in events.jsonl?
heads = set()
for l in open(f"{base}/events.jsonl", encoding="utf-8", errors="ignore"):
    try:
        h = json.loads(l).get("hash")
        if h:
            heads.add(h)
    except Exception:
        pass
print(f"attested head present in events.jsonl chain: {last['event_canonical_hash'] in heads}")
