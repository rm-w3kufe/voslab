#!/usr/bin/env python3
"""witness_verify — CA-rooted verification of the nucleus φ↑ witness sidecar (C1 for PROD-A1b).

The nucleus signs each Merkle-head checkpoint with its witness Ed25519 key (PROD-A1b →
events.witness.jsonl). The temp check (_witness_verify_check.py) trusted the `issuer_pubkey_hex`
embedded IN the statement — circular: ANY key self-verifies, so a host-compromise that swaps the
witness key forges undetected. This verifier roots trust in the OFFLINE S5 CA, exactly like the
state.db attester (C1, Ax_TwoLevelAttestation): the witness key is trusted iff a cert chains it to the
PINNED offline root (s5_ca.S5_ROOT_PIN, G_genesis), is in-date, and is NOT in the root-signed CRL.

External vantage (Ax_AttestationSeparation): this runs OFF the nucleus (host / auditor / 108) — the
node verifying φ↑ needs only the pinned root pubkey, never the nucleus's secret. cryptography is not on
101, which is fine: the verifier belongs with the auditor, not the attested party.

Reuses s5_ca (build_trust + the pin) deployed beside it. Pure stdlib + cryptography. --selftest gates
the CA logic on a synthetic root+cert+witness without touching any node.
"""
import sys
import json
import base64
import os
import importlib.util

# Resolve LXC IDs from topology.json (clone-portable)
sys.path.insert(0, str(os.environ.get("VOSLAB_PATH", os.path.dirname(__file__))))
from topology_resolve import resolve_lxc as _resolve_lxc


# Findings: (category, severity, detail). Severities on topology_reconcile's scale; all DEGRADE (C5) —
# a witness-verify failure must never halt the auditor, only scream.
SEV = {"WITNESS_FORGERY": 9.0, "WITNESS_BADSIG": 9.0, "WITNESS_UNCERTIFIED": 8.0,
       "WITNESS_HEAD_ABSENT": 6.0, "WITNESS_DEGRADED": 3.0, "WITNESS_CRL": 5.0,
       "WITNESS_CERT_EXPIRING": 4.0}  # A1d: pre-warn before the witness cert FORGERY-fails at expiry


def _import_s5ca():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "s5_ca.py"), "/usr/local/bin/s5_ca.py", "/usr/local/lib/vsf/s5_ca.py"):
        if os.path.exists(cand):
            spec = importlib.util.spec_from_file_location("s5_ca", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def _load_ca(ca_dir, s5, now_epoch, pin):
    """Build {key_id: pubkey} from the host's CA artifacts, pinned to the offline root (G_genesis).
    Returns (trusted, notes). Mirrors state_attest.load_ca_trust so both verifiers trust identically."""
    pub_path = os.path.join(ca_dir, "s5_root.pub.json")
    if not os.path.exists(pub_path):
        return {}, [("WITNESS_UNCERTIFIED", "no CA root present — cannot verify witness provenance")]
    root_pub_doc = json.load(open(pub_path, encoding="utf-8"))
    got_id = s5._key_id(bytes.fromhex(root_pub_doc["root_pub"]))
    if root_pub_doc.get("root_id") != got_id:
        return {}, [("WITNESS_FORGERY", f"root self-id mismatch ({root_pub_doc.get('root_id')} ≠ {got_id})")]
    if pin and got_id != pin:
        return {}, [("WITNESS_FORGERY", f"root {got_id} ≠ pinned {pin} — s5-ca dir swapped?")]
    certs = []
    cert_dir = os.path.join(ca_dir, "certs")
    if os.path.isdir(cert_dir):
        for fn in sorted(os.listdir(cert_dir)):
            if fn.endswith(".json"):
                certs.append(json.load(open(os.path.join(cert_dir, fn), encoding="utf-8")))
    crl_path = os.path.join(ca_dir, "s5_crl.json")
    crl = json.load(open(crl_path, encoding="utf-8")) if os.path.exists(crl_path) else None
    trusted, raw_notes = s5.build_trust(root_pub_doc, certs, crl, now_epoch)

    def _cat(lvl):
        if lvl in ("STALE", "FORGERY"):
            return "WITNESS_CRL"
        if lvl == "EXPIRING":
            return "WITNESS_CERT_EXPIRING"
        return "WITNESS_DEGRADED"
    notes = [(_cat(lvl), r) for lvl, r in raw_notes]
    return trusted, notes


def verify_statements(statements, ca_dir, now_epoch=None, pin=None, heads=None, s5=None):
    """Verify the LATEST witness statement against the CA. Returns a list of findings (all DEGRADE).
    A statement is sound iff its issuer key is CA-certified (chains to the pinned root, in-date,
    unrevoked) AND its Ed25519 signature over the 32 canonical_hash bytes verifies under that key.
    `heads` (optional) = the set of real chain heads in events.jsonl → confirms the attested head is real."""
    import time
    findings = []

    def add(cat, detail):
        findings.append((cat, SEV.get(cat, 5.0), detail))

    if s5 is None:
        s5 = _import_s5ca()
    if s5 is None:
        add("WITNESS_DEGRADED", "s5_ca module not found — cannot build CA trust")
        return findings
    if pin is None:
        pin = s5.S5_ROOT_PIN
    now = time.time() if now_epoch is None else now_epoch
    if not statements:
        add("WITNESS_DEGRADED", "no witness statements present")
        return findings

    trusted, notes = _load_ca(ca_dir, s5, now, pin)
    for cat, detail in notes:
        add(cat, detail)

    stmt = statements[-1]
    try:
        issuer_pub = bytes.fromhex(stmt["issuer_pubkey_hex"])
    except (KeyError, ValueError) as e:
        add("WITNESS_DEGRADED", f"statement has no usable issuer pubkey: {e}")
        return findings
    kid = s5._key_id(issuer_pub)

    # C1 essence: the witness key must be CA-CERTIFIED — NOT merely self-consistent with the statement.
    if kid not in trusted:
        add("WITNESS_FORGERY", f"witness key {kid} is NOT certified by the pinned root (uncertified/expired/revoked)")
    elif trusted[kid] != issuer_pub:
        add("WITNESS_FORGERY", f"witness key_id {kid} certified to a DIFFERENT pubkey (collision/mismatch)")
    else:
        # the key is trusted → check the signature it claims over the attested head
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
            msg = bytes.fromhex(stmt["event_canonical_hash"])
            try:
                Ed25519PublicKey.from_public_bytes(issuer_pub).verify(
                    base64.b64decode(stmt["signature_b64"]), msg)
            except InvalidSignature:
                add("WITNESS_BADSIG", "signature does not verify under the certified witness key")
        except ImportError:
            add("WITNESS_DEGRADED", "cryptography not available — cannot check the signature here")
        except Exception as e:
            add("WITNESS_DEGRADED", f"signature check error: {e}")

    if heads is not None and stmt.get("event_canonical_hash") not in heads:
        add("WITNESS_HEAD_ABSENT", "attested head is not a real head in events.jsonl (forged head?)")
    return findings


def _read_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def _read_heads(path):
    heads = set()
    with open(path, encoding="utf-8", errors="ignore") as f:
        for l in f:
            try:
                h = json.loads(l).get("hash")
                if h:
                    heads.add(h)
            except Exception:
                pass
    return heads


# ── A1c: algedonic emit (the SAME dual-channel contract as state_attest.emit_algedonic / the g6 sink
# on 104 dedups by source_id/category). Reliable inbox append (pct exec 104) + best-effort NATS PUB (106).
INBOX_LXC, INBOX_PATH, NATS_LXC = _resolve_lxc("s5_console"), "/alerts/operator_inbox.log", _resolve_lxc("nats")


def emit_algedonic(category, severity, instance, detail):
    import subprocess
    import json as _j
    import datetime
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts}  S3-WITNESS {category}  {instance} — {detail}"
    safe = line.replace("'", "")
    subprocess.run(["bash", "-c",
        f"pct exec {INBOX_LXC} -- bash -c \"mkdir -p /alerts && echo '{safe}' >> {INBOX_PATH}\""],
        capture_output=True, timeout=20)
    payload = _j.dumps({"severity": severity, "source_id": "s3_witness_verify",
                        "category": category, "instance": instance, "detail": detail, "ts": ts})
    py = ("import socket\n"
          f"p={payload!r}.encode()\n"
          "s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',4222)); s.recv(4096)\n"
          "s.send(b'CONNECT {}\\r\\n'); "
          f"s.send(b'PUB vsf.alpha.algedonic.{category} '+str(len(p)).encode()+b'\\r\\n'+p+b'\\r\\n')\n"
          "s.close()")
    subprocess.run(["bash", "-c", f"pct exec {NATS_LXC} -- python3 -c {py!r}"],
                   capture_output=True, timeout=20)
    return line


def main():
    if "--selftest" in sys.argv:
        return _selftest()
    if "--verify" in sys.argv:
        def opt(flag, default=None):
            return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default
        sidecar = opt("--sidecar", "/var/lib/vsf/vsf_nucleus/events.witness.jsonl")
        ca_dir = opt("--ca-dir", "/var/lib/vsf/s5-ca")
        events = opt("--events")  # optional; reading 226k+ lines is heavy — only if asked
        emit = "--emit" in sys.argv  # A1c: dual-channel algedonic per finding (the periodic monitor)
        stmts = _read_jsonl(sidecar)
        heads = _read_heads(events) if events and os.path.exists(events) else None
        findings = verify_statements(stmts, ca_dir, heads=heads)
        last = stmts[-1] if stmts else {}
        print(f"# witness_verify --verify — CA-rooted φ↑ witness check (sidecar={sidecar}, ca_dir={ca_dir}, emit={emit})")
        print(f"#   statements={len(stmts)}  last_head={last.get('event_canonical_hash','-')[:24]}…"
              f"  issuer={last.get('issuer_pubkey_hex','-')[:16]}…"
              + ("  [head-presence checked]" if heads is not None else "  [head-presence skipped]"))
        if emit:
            for cat, sev, detail in findings:
                emit_algedonic(cat, sev, "statedb.nucleus_witness", detail)
        if not findings:
            print("  ✓ witness key CA-certified (chains to pinned root) + signature verifies — TRUSTED")
            print("## RESULT: 0 findings — φ↑ witness is rooted in the offline S5 CA.")
            return 0
        for cat, sev, detail in findings:
            print(f"  ⚠ [{cat} sev={sev}] {detail}")
        print(f"## RESULT: {len(findings)} finding(s) (all DEGRADE, never halt — C5; emitted={emit}).")
        return 0 if emit else 1  # monitor mode never fails the unit (emits + keeps the timer alive)
    print("usage: witness_verify.py [--verify [--sidecar PATH] [--ca-dir DIR] [--events PATH] [--emit] | --selftest]")
    print("  runs OFF the nucleus (host/auditor) — needs only the pinned root pubkey + the CA artifacts.")
    print("  --emit: dual-channel algedonic per finding (inbox-104 + NATS-106) — the periodic monitor mode.")
    return 2


def _selftest():
    """Synthetic root + cert + witness key + signed statements → prove the CA gate. No node touched."""
    s5 = _import_s5ca()
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    if s5 is None:
        print("  [FAIL] s5_ca importable beside witness_verify")
        print("\n## RESULT: 0 passed, 1 failed\n## SELFTEST: ✗ — deploy s5_ca.py beside this file.")
        return 1

    import tempfile
    import shutil
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

    tmp = tempfile.mkdtemp(prefix="witness-ca-")
    ca_dir = os.path.join(tmp, "s5-ca")
    os.makedirs(os.path.join(ca_dir, "certs"))
    now = s5._parse_iso(s5._now_iso())

    # offline root
    rsk = Ed25519PrivateKey.generate()
    seed = rsk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    root_pub = rsk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    root_id = s5._key_id(root_pub)
    json.dump({"v": 1, "type": "vsf-s5-root-pub", "root_id": root_id, "root_pub": root_pub.hex()},
              open(os.path.join(ca_dir, "s5_root.pub.json"), "w"))
    json.dump(s5.make_or_update_crl(seed, None, None, "", 30), open(os.path.join(ca_dir, "s5_crl.json"), "w"))

    # the witness key (the nucleus's), and a cert for it
    wsk = Ed25519PrivateKey.generate()
    wpub = wsk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    cert = s5.issue_cert(seed, wpub.hex(), "vsf-nucleus-witness", ["phi_up.witness"], days=365)
    json.dump(cert, open(os.path.join(ca_dir, "certs", "nucleus-witness.json"), "w"))

    def stmt_for(sk, pub, head_hex):
        sig = sk.sign(bytes.fromhex(head_hex))
        return {"event_canonical_hash": head_hex, "attested_at": s5._now_iso(),
                "issuer": s5._key_id(pub), "issuer_pubkey_hex": pub.hex(),
                "signature_b64": base64.b64encode(sig).decode()}

    head = "ab" * 32
    good = [stmt_for(wsk, wpub, head)]

    # 1. certified witness + valid sig → zero findings
    f1 = verify_statements(good, ca_dir, now_epoch=now, pin=root_id, s5=s5)
    check("certified witness + valid sig → 0 findings", f1 == [], str([c[0] for c in f1]))

    # 2. an UNCERTIFIED witness key (no cert) → WITNESS_FORGERY
    foreign_sk = Ed25519PrivateKey.generate()
    foreign_pub = foreign_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    f2 = verify_statements([stmt_for(foreign_sk, foreign_pub, head)], ca_dir, now_epoch=now, pin=root_id, s5=s5)
    check("uncertified witness key → WITNESS_FORGERY", "WITNESS_FORGERY" in {c[0] for c in f2})

    # 3. certified key but TAMPERED signature → WITNESS_BADSIG
    bad = dict(good[0]); bad["signature_b64"] = base64.b64encode(wsk.sign(bytes.fromhex("cd" * 32))).decode()
    f3 = verify_statements([bad], ca_dir, now_epoch=now, pin=root_id, s5=s5)
    check("certified key, wrong-message sig → WITNESS_BADSIG", "WITNESS_BADSIG" in {c[0] for c in f3})

    # 4. REVOKED witness key → WITNESS_FORGERY
    json.dump(s5.make_or_update_crl(seed, None, s5._key_id(wpub), "compromised", 30),
              open(os.path.join(ca_dir, "s5_crl.json"), "w"))
    f4 = verify_statements(good, ca_dir, now_epoch=now, pin=root_id, s5=s5)
    check("revoked witness key → WITNESS_FORGERY", "WITNESS_FORGERY" in {c[0] for c in f4})

    # 5. wrong PIN (swapped CA dir) → WITNESS_FORGERY
    f5 = verify_statements(good, ca_dir, now_epoch=now, pin="ed25519:0000000000000000", s5=s5)
    check("wrong pin → WITNESS_FORGERY", "WITNESS_FORGERY" in {c[0] for c in f5})

    # 6. head-presence: attested head absent from the chain → WITNESS_HEAD_ABSENT (restore clean CRL)
    json.dump(s5.make_or_update_crl(seed, None, None, "", 30), open(os.path.join(ca_dir, "s5_crl.json"), "w"))
    f6 = verify_statements(good, ca_dir, now_epoch=now, pin=root_id, heads={"ff" * 32}, s5=s5)
    check("attested head not in chain → WITNESS_HEAD_ABSENT", "WITNESS_HEAD_ABSENT" in {c[0] for c in f6})
    f6b = verify_statements(good, ca_dir, now_epoch=now, pin=root_id, heads={head}, s5=s5)
    check("attested head present in chain → 0 findings", f6b == [], str([c[0] for c in f6b]))

    # 7. A1d: a near-expiry witness cert → still TRUSTED (no FORGERY) but a WITNESS_CERT_EXPIRING warning
    soon_cert = s5.issue_cert(seed, wpub.hex(), "vsf-nucleus-witness", ["phi_up.witness"], days=10)
    json.dump(soon_cert, open(os.path.join(ca_dir, "certs", "nucleus-witness.json"), "w"))  # replace
    f7 = verify_statements(good, ca_dir, now_epoch=now, pin=root_id, heads={head}, s5=s5)
    f7cats = {c[0] for c in f7}
    check("near-expiry witness cert → WITNESS_CERT_EXPIRING", "WITNESS_CERT_EXPIRING" in f7cats)
    check("near-expiry cert NOT treated as forgery/badsig",
          "WITNESS_FORGERY" not in f7cats and "WITNESS_BADSIG" not in f7cats)

    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    print("# witness_verify --selftest — CA-rooted φ↑ witness trust")
    for n, ok, d in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else ""))
    print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("## SELFTEST: ✗ NOT MET — do NOT cut over the witness verifier.")
        return 1
    print("## SELFTEST: ✓ MET — witness trust chains to the pinned offline root; uncertified/revoked/")
    print("##           bad-sig/wrong-pin all caught. Cleared to issue the witness cert + deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
