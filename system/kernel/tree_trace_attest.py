#!/usr/bin/env python3
"""tree_trace_attest — Ed25519 attestation for tree traces (Capa 2).

Signs each tree trace after capture, building a Merkle tree per session.
Verification is independent — only needs the public key, not the private key.

Usage:
    # As a module (imported by rsi_cycle):
    from tree_trace_attest import AttestationSigner
    signer = AttestationSigner()
    attestation = signer.sign_trace(trace)

    # CLI:
    python3 tree_trace_attest.py --sign trace.jsonl
    python3 tree_trace_attest.py --verify attestation.json
    python3 tree_trace_attest.py --selftest
"""
import json
import hashlib
import os
import sys
import time
import base64
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PrivateFormat,
        PublicFormat,
        NoEncryption,
    )
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def _get_voslab_path():
    return Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parent.parent.parent))


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> bytes:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


# ─── Key Management ───────────────────────────────────────────────────────────

@dataclass
class KeyInfo:
    key_id: str           # first 16 chars of pubkey hex
    pubkey_hex: str
    created_at: str
    path: str


class KeyManager:
    """Manages Ed25519 keypairs for attestation.

    Keys are stored in VOSLAB_PATH/state/rsi/keys/:
      - attestation_key.priv  (base64 raw private key)
      - attestation_key.pub   (hex public key)
    """

    def __init__(self, key_dir: Optional[Path] = None):
        self.key_dir = key_dir or (_get_voslab_path() / "state" / "rsi" / "keys")
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self._priv_path = self.key_dir / "attestation_key.priv"
        self._pub_path = self.key_dir / "attestation_key.pub"

    def get_or_create(self) -> tuple:
        """Returns (private_key_bytes, public_key_bytes, key_id)."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required for Ed25519")

        if self._priv_path.exists() and self._pub_path.exists():
            priv_bytes = base64.b64decode(self._priv_path.read_text().strip())
            pub_hex = self._pub_path.read_text().strip()
            pub_bytes = bytes.fromhex(pub_hex)
            key_id = pub_hex[:16]
            return priv_bytes, pub_bytes, key_id

        # Generate new keypair
        sk = Ed25519PrivateKey.generate()
        priv_bytes = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_bytes = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        pub_hex = pub_bytes.hex()
        key_id = pub_hex[:16]

        self._priv_path.write_text(base64.b64encode(priv_bytes).decode())
        self._pub_path.write_text(pub_hex)
        self._priv_path.chmod(0o600)

        return priv_bytes, pub_bytes, key_id

    def get_public(self) -> tuple:
        """Returns (public_key_bytes, key_id) without exposing private key."""
        if not self._pub_path.exists():
            self.get_or_create()
        pub_hex = self._pub_path.read_text().strip()
        pub_bytes = bytes.fromhex(pub_hex)
        return pub_bytes, pub_hex[:16]

    def info(self) -> KeyInfo:
        pub_bytes, key_id = self.get_public()
        return KeyInfo(
            key_id=key_id,
            pubkey_hex=pub_bytes.hex(),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            path=str(self.key_dir),
        )


# ─── Merkle Tree ──────────────────────────────────────────────────────────────

class MerkleTree:
    """Simple Merkle tree for a list of leaf hashes."""

    def __init__(self, leaf_hashes: List[bytes]):
        self.leaves = leaf_hashes
        self.root = self._build(leaf_hashes)

    def _build(self, hashes: List[bytes]) -> bytes:
        if not hashes:
            return b"\x00" * 32
        if len(hashes) == 1:
            return hashes[0]
        # Pad to even length
        if len(hashes) % 2 == 1:
            hashes = hashes + [hashes[-1]]
        next_level = []
        for i in range(0, len(hashes), 2):
            combined = hashes[i] + hashes[i + 1]
            next_level.append(_sha256(combined))
        return self._build(next_level)

    @property
    def root_hex(self) -> str:
        return self.root.hex()

    def proof(self, index: int) -> List[dict]:
        """Generate a Merkle proof for the leaf at `index`."""
        if not self.leaves:
            return []
        proof = []
        level = self.leaves[:]
        pos = index
        while len(level) > 1:
            if len(level) % 2 == 1:
                level = level + [level[-1]]
            sibling = pos ^ 1  # flip last bit
            proof.append({
                "hash": level[sibling].hex(),
                "position": "right" if sibling > pos else "left",
            })
            next_level = []
            for i in range(0, len(level), 2):
                next_level.append(_sha256(level[i] + level[i + 1]))
            level = next_level
            pos = pos // 2
        return proof


# ─── Attestation ──────────────────────────────────────────────────────────────

@dataclass
class TraceAttestation:
    """Signed attestation of a single tree trace."""
    trace_id: str
    trace_hash: str           # SHA-256 of the canonical trace JSON
    tree_shape: str
    final_truth: str
    total_nodes: int
    key_id: str               # first 16 chars of signer pubkey
    signature_b64: str        # Ed25519 signature over trace_hash
    ts: str                   # ISO 8601 UTC


@dataclass
class SessionAttestation:
    """Merkle tree root of all trace attestations in a session."""
    session_id: str
    trace_count: int
    merkle_root: str          # hex
    tree_shape_summary: str   # e.g., "AND(task_has_work, OR(...)) × 5, OR(...) × 3"
    key_id: str
    signature_b64: str        # Ed25519 signature over merkle_root
    ts: str
    traces: List[dict]        # list of TraceAttestation dicts


# ─── Signer ───────────────────────────────────────────────────────────────────

class AttestationSigner:
    """Signs tree traces and builds session Merkle trees."""

    def __init__(self, key_dir: Optional[Path] = None):
        self.key_manager = KeyManager(key_dir)
        self._session_traces: List[TraceAttestation] = []

    def sign_trace(self, trace: dict) -> TraceAttestation:
        """Sign a tree trace. Returns TraceAttestation."""
        priv_bytes, pub_bytes, key_id = self.key_manager.get_or_create()
        sk = Ed25519PrivateKey.from_private_bytes(priv_bytes)

        # Canonical hash of the trace
        trace_canonical = _canonical(trace)
        trace_hash = _sha256_hex(trace_canonical)

        # Sign the hash (Ed25519 signs raw bytes, not hex)
        sig = sk.sign(bytes.fromhex(trace_hash))

        attestation = TraceAttestation(
            trace_id=trace.get("trace_id", "unknown"),
            trace_hash=trace_hash,
            tree_shape=trace.get("tree_shape", ""),
            final_truth=trace.get("final_truth", ""),
            total_nodes=trace.get("total_nodes", 0),
            key_id=key_id,
            signature_b64=base64.b64encode(sig).decode(),
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        self._session_traces.append(attestation)
        return attestation

    def build_session_attestation(self, session_id: str) -> SessionAttestation:
        """Build a Merkle tree over all signed traces in this session."""
        if not self._session_traces:
            raise ValueError("No traces signed in this session")

        priv_bytes, pub_bytes, key_id = self.key_manager.get_or_create()
        sk = Ed25519PrivateKey.from_private_bytes(priv_bytes)

        # Build Merkle tree from trace hashes
        leaf_hashes = [bytes.fromhex(t.trace_hash) for t in self._session_traces]
        tree = MerkleTree(leaf_hashes)

        # Sign the Merkle root
        sig = sk.sign(tree.root)

        # Build summary of tree shapes
        from collections import Counter
        shapes = Counter(t.tree_shape for t in self._session_traces)
        summary = ", ".join(f"{shape} × {count}" for shape, count in shapes.most_common(10))

        session_att = SessionAttestation(
            session_id=session_id,
            trace_count=len(self._session_traces),
            merkle_root=tree.root_hex,
            tree_shape_summary=summary,
            key_id=key_id,
            signature_b64=base64.b64encode(sig).decode(),
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            traces=[asdict(t) for t in self._session_traces],
        )

        return session_att


# ─── Verifier ─────────────────────────────────────────────────────────────────

class AttestationVerifier:
    """Verifies attestation signatures without needing the private key."""

    def __init__(self, pub_key_hex: Optional[str] = None):
        if pub_key_hex:
            self.pub_bytes = bytes.fromhex(pub_key_hex)
            self.key_id = pub_key_hex[:16]
        else:
            km = KeyManager()
            self.pub_bytes, self.key_id = km.get_public()

    def verify_trace(self, attestation: dict) -> dict:
        """Verify a single trace attestation. Returns {ok, reason}."""
        if not HAS_CRYPTO:
            return {"ok": False, "reason": "cryptography library not available"}

        try:
            pub = Ed25519PublicKey.from_public_bytes(self.pub_bytes)
            sig = base64.b64decode(attestation["signature_b64"])
            trace_hash = bytes.fromhex(attestation["trace_hash"])
            pub.verify(sig, trace_hash)
            return {"ok": True, "reason": "signature valid"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def verify_session(self, session_att: dict) -> dict:
        """Verify session Merkle root signature + all trace attestations."""
        if not HAS_CRYPTO:
            return {"ok": False, "reason": "cryptography library not available"}

        results = {"traces_ok": 0, "traces_fail": 0, "merkle_ok": False, "errors": []}

        # Verify each trace attestation
        for trace_att in session_att.get("traces", []):
            r = self.verify_trace(trace_att)
            if r["ok"]:
                results["traces_ok"] += 1
            else:
                results["traces_fail"] += 1
                results["errors"].append(f"trace {trace_att.get('trace_id')}: {r['reason']}")

        # Verify Merkle root
        try:
            leaf_hashes = [bytes.fromhex(t["trace_hash"]) for t in session_att["traces"]]
            tree = MerkleTree(leaf_hashes)
            if tree.root_hex == session_att["merkle_root"]:
                results["merkle_ok"] = True
            else:
                results["errors"].append(f"Merkle root mismatch: expected {tree.root_hex[:16]}..., got {session_att['merkle_root'][:16]}...")
        except Exception as e:
            results["errors"].append(f"Merkle verification error: {e}")

        # Verify session signature over Merkle root
        try:
            pub = Ed25519PublicKey.from_public_bytes(self.pub_bytes)
            sig = base64.b64decode(session_att["signature_b64"])
            pub.verify(sig, bytes.fromhex(session_att["merkle_root"]))
            results["session_sig_ok"] = True
        except Exception as e:
            results["session_sig_ok"] = False
            results["errors"].append(f"Session signature: {e}")

        results["ok"] = (
            results["traces_fail"] == 0
            and results["merkle_ok"]
            and results.get("session_sig_ok", False)
        )
        return results


# ─── Persistence ──────────────────────────────────────────────────────────────

def persist_attestation(attestation: TraceAttestation, directory: Path):
    """Persist a single trace attestation."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{attestation.trace_id}.attest.json"
    path.write_text(json.dumps(asdict(attestation), indent=2))


def persist_session_attestation(att: SessionAttestation, directory: Path):
    """Persist a session attestation (Merkle root + all traces)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"session-{att.session_id}.attest.json"
    path.write_text(json.dumps(asdict(att), indent=2))


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if "--selftest" in sys.argv:
        return _selftest()

    if "--sign" in sys.argv:
        idx = sys.argv.index("--sign")
        trace_file = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not trace_file:
            print("usage: --sign <trace.jsonl>")
            return 1
        signer = AttestationSigner()
        attestations = []
        for line in open(trace_file):
            line = line.strip()
            if not line:
                continue
            trace = json.loads(line)
            att = signer.sign_trace(trace)
            attestations.append(att)
            persist_attestation(att, _get_voslab_path() / "state" / "rsi" / "attestations")
        print(f"Signed {len(attestations)} traces")
        if attestations:
            session_att = signer.build_session_attestation("cli-session")
            persist_session_attestation(session_att, _get_voslab_path() / "state" / "rsi" / "attestations")
            print(f"Session Merkle root: {session_att.merkle_root[:32]}...")
        return 0

    if "--verify" in sys.argv:
        idx = sys.argv.index("--verify")
        att_file = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not att_file:
            print("usage: --verify <attestation.json>")
            return 1
        data = json.load(open(att_file))
        verifier = AttestationVerifier()
        if "traces" in data:
            # Session attestation
            r = verifier.verify_session(data)
            print(f"Session attestation: {'✓ VALID' if r['ok'] else '✗ INVALID'}")
            print(f"  Traces: {r['traces_ok']} ok, {r['traces_fail']} fail")
            print(f"  Merkle: {'✓' if r['merkle_ok'] else '✗'}")
            print(f"  Session sig: {'✓' if r.get('session_sig_ok') else '✗'}")
            for e in r["errors"]:
                print(f"  Error: {e}")
        else:
            # Single trace attestation
            r = verifier.verify_trace(data)
            print(f"Trace attestation: {'✓ VALID' if r['ok'] else '✗ INVALID'} — {r['reason']}")
        return 0

    print("usage: tree_trace_attest.py [--sign <trace.jsonl> | --verify <att.json> | --selftest]")
    return 2


def _selftest():
    """Test key generation, signing, Merkle tree, verification."""
    if not HAS_CRYPTO:
        print("  [FAIL] cryptography library not available")
        return 1

    import tempfile
    import shutil

    tmp = tempfile.mkdtemp(prefix="attest-test-")
    key_dir = Path(tmp) / "keys"
    att_dir = Path(tmp) / "attestations"

    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    try:
        # 1. Key generation
        km = KeyManager(key_dir)
        priv, pub, kid = km.get_or_create()
        check("key generation", len(priv) == 32 and len(pub) == 32, f"priv={len(priv)} pub={len(pub)}")

        # Key persistence
        km2 = KeyManager(key_dir)
        priv2, pub2, kid2 = km2.get_or_create()
        check("key persistence", priv == priv2 and pub == pub2)

        # 2. Sign a trace
        signer = AttestationSigner(key_dir)
        trace = {
            "trace_id": "test-trace-001",
            "tree_shape": "AND(a, b)",
            "final_truth": "Truth.TRUE",
            "total_nodes": 3,
            "nodes": [{"node_id": 0, "type": "operator", "name": "AND", "truth": "TRUE", "certified": True, "evidence": None, "children": [1, 2]}],
        }
        att = signer.sign_trace(trace)
        check("sign trace", att.trace_hash and att.signature_b64, f"hash={att.trace_hash[:16]}...")

        # 3. Verify the signature
        verifier = AttestationVerifier(km.info().pubkey_hex)
        r = verifier.verify_trace(asdict(att))
        check("verify trace", r["ok"], r["reason"])

        # 4. Merkle tree
        trace2 = dict(trace, trace_id="test-trace-002", tree_shape="OR(c, d)")
        att2 = signer.sign_trace(trace2)
        session_att = signer.build_session_attestation("test-session")
        check("session attestation", session_att.merkle_root and session_att.trace_count == 2)

        # 5. Verify session
        r2 = verifier.verify_session(asdict(session_att))
        check("verify session", r2["ok"], str(r2["errors"]))

        # 6. Tamper detection — change a trace_hash
        tampered = asdict(session_att)
        tampered["traces"][0]["trace_hash"] = "00" * 32
        r3 = verifier.verify_session(tampered)
        check("tamper detection", not r3["ok"], "tampered trace should fail")

        # 7. Wrong key detection
        other_km = KeyManager(Path(tmp) / "other_keys")
        other_km.get_or_create()
        wrong_verifier = AttestationVerifier(other_km.info().pubkey_hex)
        r4 = wrong_verifier.verify_trace(asdict(att))
        check("wrong key detection", not r4["ok"], "wrong key should fail")

        # 8. Persistence
        persist_attestation(att, att_dir)
        persist_session_attestation(session_att, att_dir)
        check("persistence", (att_dir / f"{att.trace_id}.attest.json").exists())

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    print("tree_trace_attest --selftest")
    for n, ok, d in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else ""))
    print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
