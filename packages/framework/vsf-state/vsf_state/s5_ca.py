#!/usr/bin/env python3
"""s5_ca — the OFFLINE S5 certificate authority for AX-STATE (correction C1, G_keylife).

The AX-STATE attester signs state.db snapshots with an on-host *component* key. On-host keys protect
AT-REST only: an attacker who takes the host takes the key and can re-sign forged state. The fix
(Ax_TwoLevelAttestation, attested_state_primitive.vsm §keys + DSN-EVC-01 M2) is a SECOND level:

    S5_root (OFFLINE)  ⊢  component_key  ⊢  attestation

The root keypair lives where the attacker does not — your WSL box + a USB backup, NEVER on an LXC.
Only the root PUBLIC key is embedded in the verifier. The root issues short-lived CERTIFICATES binding
each component pubkey, and a signed REVOCATION LIST (CRL). The verifier trusts a signer iff a valid,
unrevoked, in-date cert chains it to the embedded root pubkey. The load-bearing control is REVOCATION:
if the host key leaks, you revoke it offline and every signature it ever makes is rejected.

Design constraints from the canon:
  - M1 / Ax_NoObscurity (Kerckhoffs): NO obfuscation. Security = transparency + a verifiable root.
  - M2: trust ROOT is OFFLINE; the public artifact (CRL) gives FRESHNESS/REVOCATION only; authority is
        the SIGNATURE, never a URL/host (the same pattern as the covenant-hash anchor against n01).
  - Key custody at rest = passphrase-derived encryption (scrypt+AESGCM). NOT HashiCorp Vault (SPOF).
  - The secret is NEVER written in clear: only s5_root.enc (encrypted) exists at rest; ceremony ops
        decrypt it in memory on a passphrase prompt and discard it.

This tool runs OFFLINE (your WSL box) — it is the ceremony, not part of the n02 runtime. Pure stdlib +
`cryptography`. The state.db verifier (state_attest.py) consumes the artifacts this produces; the
self-test (`--selftest`) exercises the whole chain in memory and runs on the sandbox (108), never WSL.

Subcommands:
  init-root  --enc OUT.enc --pub OUT.pub.json            mint the root; write encrypted secret + clear pubkey
  restore    --enc OUT.enc                               prove a backup decrypts (recovery drill); writes nothing
  issue-cert --enc R.enc --component-pub HEX --role NAME --scope a,b,c [--days 365] --out CERT.json
  revoke     --enc R.enc --crl CRL.json --key-id ID [--reason TEXT] [--next-days 7]
  verify     --pub R.pub.json [--cert CERT.json] [--crl CRL.json]   offline sanity check (no passphrase)
  expiring   --ca-dir DIR [--days 30]                               days-to-expiry per cert (nonzero exit if any near)
  --selftest                                             in-memory round-trip of the whole chain
"""
import sys
import json
import hashlib
import datetime


# The offline S5 root fingerprint, PINNED in code (G_genesis). CANONICAL HOME — every verifier
# (state_attest.load_ca_trust, witness_verify) must pin THIS value. Public (sha256 of a pubkey) → safe
# to commit (M1 NoObscurity). A root whose fingerprint ≠ this is rejected; matching it needs the offline
# private key. Set from the root_id printed by `init-root`. "" ⇒ pin disabled (pre-ceremony / tests).
S5_ROOT_PIN = "ed25519:624e8d3ea2c0c904"

# Clock-skew margin: certs are back-dated not_before by this so a freshly-issued cert is not briefly
# "not yet valid" on a verifier whose clock differs from the offline issuer's (WSL vs n02).
CERT_SKEW_S = 300

# ── canonical signing payload (injective: tag + length-prefix every field, like state_attest) ──────
DOMAIN_CERT = b"VSF-S5-CERT-v1"
DOMAIN_CRL = b"VSF-S5-CRL-v1"
DOMAIN_APPROVAL = b"VSF-S5-APPROVAL-v1"   # L3 double-loop approval (reframe / PSI L3)
_T_NAME, _T_STR, _T_ITEM = 0x01, 0x02, 0x03


def _frame(tag, b):
    return bytes([tag]) + len(b).to_bytes(4, "big") + b


def _payload(domain, fields):
    """fields = ordered list of (name, value); value is str|int or a list. Order is FIXED by the caller
    (never sort) so the signed bytes are unambiguous and stable."""
    out = bytearray(domain)
    for name, val in fields:
        out += _frame(_T_NAME, name.encode("utf-8"))
        if isinstance(val, list):
            out += len(val).to_bytes(4, "big")
            for item in val:
                out += _frame(_T_ITEM, str(item).encode("utf-8"))
        else:
            out += _frame(_T_STR, str(val).encode("utf-8"))
    return bytes(out)


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc).timestamp()


def _key_id(pub_raw):
    """Same scheme as state_attest's signer id → a component's key_id here == its signer there."""
    return "ed25519:" + hashlib.sha256(pub_raw).hexdigest()[:16]


# ── at-rest encryption of the root secret: scrypt(passphrase) → AES-GCM over the 32-byte seed ───────
def _scrypt_key(passphrase, salt, n):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(passphrase.encode("utf-8"))


def encrypt_seed(seed32, passphrase, n=2 ** 17):
    """Returns the encrypted-backup dict. n=2**17 ≈ a fraction of a second; bump for a stronger root."""
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _scrypt_key(passphrase, salt, n)
    ct = AESGCM(key).encrypt(nonce, seed32, b"vsf-s5-root")
    return {"kdf": "scrypt", "n": n, "r": 8, "p": 1, "salt": salt.hex(),
            "nonce": nonce.hex(), "ct": ct.hex()}


def decrypt_seed(blob, passphrase):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _scrypt_key(passphrase, bytes.fromhex(blob["salt"]), int(blob["n"]))
    return AESGCM(key).decrypt(bytes.fromhex(blob["nonce"]), bytes.fromhex(blob["ct"]), b"vsf-s5-root")


def _load_root_seed(enc_path, passphrase):
    with open(enc_path, encoding="utf-8") as f:
        backup = json.load(f)
    seed = decrypt_seed(backup, passphrase)  # raises on a wrong passphrase / tampered file
    return seed, backup


def _sk_from_seed(seed32):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(seed32)


def _pub_raw(sk):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


# ── the three signed artifacts ──────────────────────────────────────────────────────────────────
def make_root(passphrase, n=2 ** 17):
    """Mint a fresh S5 root. Returns (enc_backup_dict, pub_doc_dict). The clear seed never leaves here."""
    import os
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption)
    sk = Ed25519PrivateKey.generate()
    seed = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = _pub_raw(sk)
    root_id = _key_id(pub_raw)
    created = _now_iso()
    enc = {"v": 1, "type": "vsf-s5-root-backup", "root_id": root_id,
           "root_pub": pub_raw.hex(), "created": created,
           "restore": "python3 s5_ca.py restore --enc THIS_FILE   (prompts the passphrase)"}
    enc.update(encrypt_seed(seed, passphrase, n))
    pub_doc = {"v": 1, "type": "vsf-s5-root-pub", "root_id": root_id,
               "root_pub": pub_raw.hex(), "created": created}
    return enc, pub_doc


def issue_cert(seed32, component_pub_hex, role, scope, days=365):
    sk = _sk_from_seed(seed32)
    root_id = _key_id(_pub_raw(sk))
    comp_pub = bytes.fromhex(component_pub_hex)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Back-date not_before by a skew margin: the issuer (offline WSL) and the verifier (n02) have
    # independent clocks, and a cert minted "now" must not be briefly-not-yet-valid on the verifier.
    not_before = now - datetime.timedelta(seconds=CERT_SKEW_S)
    cert = {"v": 1, "type": "vsf-s5-cert", "key_id": _key_id(comp_pub),
            "component_pub": comp_pub.hex(), "role": role, "scope": list(scope),
            "not_before": not_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "not_after": (now + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "root_id": root_id}
    cert["sig"] = sk.sign(_cert_payload(cert)).hex()
    return cert


def _cert_payload(c):
    return _payload(DOMAIN_CERT, [
        ("v", c["v"]), ("type", c["type"]), ("key_id", c["key_id"]),
        ("component_pub", c["component_pub"]), ("role", c["role"]), ("scope", c["scope"]),
        ("not_before", c["not_before"]), ("not_after", c["not_after"]), ("root_id", c["root_id"])])


def make_or_update_crl(seed32, crl, key_id=None, reason="", next_days=7):
    """Add key_id to the CRL (idempotent) and re-sign with the root. crl=None → a fresh empty CRL."""
    sk = _sk_from_seed(seed32)
    root_id = _key_id(_pub_raw(sk))
    now = datetime.datetime.now(datetime.timezone.utc)
    if crl is None:
        crl = {"v": 1, "type": "vsf-s5-crl", "root_id": root_id, "revoked": []}
    if key_id and not any(r["key_id"] == key_id for r in crl["revoked"]):
        crl["revoked"].append({"key_id": key_id, "since": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "reason": reason})
    crl["issued_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    crl["next_update"] = (now + datetime.timedelta(days=next_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    crl["root_id"] = root_id
    crl["sig"] = sk.sign(_crl_payload(crl)).hex()
    return crl


def _crl_payload(c):
    revoked = [f"{r['key_id']}|{r['since']}|{r['reason']}" for r in c["revoked"]]
    return _payload(DOMAIN_CRL, [
        ("v", c["v"]), ("type", c["type"]), ("root_id", c["root_id"]),
        ("issued_at", c["issued_at"]), ("next_update", c["next_update"]), ("revoked", revoked)])


# ── L3 approval token (reframe axiom/topology OR PSI L3) — signed by the offline S5 root ────────────
# The kernel cannot self-grant human approval (A5/D4-L3). The human signs this token offline; the
# nucleus verifies it against the SAME pinned root it uses for AX-STATE/witness. Default-deny: no valid
# token ⇒ no L3 change. See docs/spec/s5_approval_channel/spec.vsm.
def _approval_payload(t):
    return _payload(DOMAIN_APPROVAL, [
        ("v", t["v"]), ("type", t["type"]), ("proposal_id", t["proposal_id"]),
        ("proposal_hash", t["proposal_hash"]), ("decision", t["decision"]),
        ("nonce", t["nonce"]), ("not_before", t["not_before"]),
        ("not_after", t["not_after"]), ("root_id", t["root_id"]),
    ])


def make_approval(seed32, proposal_id, proposal_hash, decision, ttl_s=3600):
    """Sign an L3 double-loop approval with the offline S5 root. Binds proposal_id + proposal_hash so
    the token cannot be replayed against a DIFFERENT proposal; a fresh nonce + a bounded validity window
    guard reuse. decision ∈ {"approve","deny"}."""
    import os
    sk = _sk_from_seed(seed32)
    root_id = _key_id(_pub_raw(sk))
    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = now - datetime.timedelta(seconds=CERT_SKEW_S)  # same skew margin as certs
    tok = {"v": 1, "type": "vsf-s5-approval", "proposal_id": str(proposal_id),
           "proposal_hash": str(proposal_hash), "decision": str(decision),
           "nonce": os.urandom(16).hex(),
           "not_before": not_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "not_after": (now + datetime.timedelta(seconds=ttl_s)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "root_id": root_id}
    tok["sig"] = sk.sign(_approval_payload(tok)).hex()
    return tok


def verify_approval(tok, root_pub_raw, now_epoch=None):
    """True iff the token's sig verifies under the embedded root pubkey AND it is within its validity
    window. The CONSUMER (reframe.rs) additionally enforces decision=="approve", proposal_hash matches
    the pending proposal, and the nonce is unseen (anti-replay)."""
    if not _verify_sig(root_pub_raw, _approval_payload(tok), tok["sig"]):
        return False
    now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now_epoch is None else now_epoch
    try:
        return _parse_iso(tok["not_before"]) <= now <= _parse_iso(tok["not_after"])
    except (KeyError, ValueError):
        return False


# ── verification: the half the n02 host runs (no secret, only the embedded root pubkey) ─────────────
def _verify_sig(pub_raw, payload, sig_hex):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(bytes.fromhex(sig_hex), payload)
        return True
    except InvalidSignature:
        return False


def verify_cert(cert, root_pub_raw):
    return _verify_sig(root_pub_raw, _cert_payload(cert), cert["sig"])


def verify_crl(crl, root_pub_raw):
    return _verify_sig(root_pub_raw, _crl_payload(crl), crl["sig"])


def build_trust(root_pub_doc, certs, crl=None, now_epoch=None, warn_days=30):
    """The C1 trust-set the verifier uses INSTEAD of bare 'signer ∈ a hand-listed set'. A component
    key is trusted iff: its cert verifies against the embedded root pubkey, the cert is in-date, and
    the key_id is not in a (root-signed) CRL. Returns (trusted, notes) where trusted = {key_id:
    component_pub_raw} and notes = list of (level, reason) the caller may surface (CRL staleness, etc).
    Every rejection here makes the signer ABSENT → the attester's existing ATTEST_FORGERY fires (C5)."""
    now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now_epoch is None else now_epoch
    root_pub = bytes.fromhex(root_pub_doc["root_pub"])
    root_id = root_pub_doc["root_id"]
    notes = []
    revoked = set()
    if crl is not None:
        if not verify_crl(crl, root_pub):
            notes.append(("FORGERY", "CRL signature does not verify against the root — IGNORING the CRL"))
        elif crl.get("root_id") != root_id:
            notes.append(("FORGERY", f"CRL root_id {crl.get('root_id')} ≠ embedded root — IGNORING"))
        else:
            revoked = {r["key_id"] for r in crl.get("revoked", [])}
            try:
                if now > _parse_iso(crl["next_update"]):
                    notes.append(("STALE", f"CRL past next_update {crl['next_update']} (revocations may be missing)"))
            except (KeyError, ValueError):
                notes.append(("STALE", "CRL has no parseable next_update"))
    trusted = {}
    for cert in certs:
        kid = cert.get("key_id")
        if cert.get("root_id") != root_id or not verify_cert(cert, root_pub):
            notes.append(("REJECT", f"cert {kid} does not chain to the embedded root")); continue
        try:
            if not (_parse_iso(cert["not_before"]) <= now <= _parse_iso(cert["not_after"])):
                notes.append(("REJECT", f"cert {kid} outside validity window")); continue
        except (KeyError, ValueError):
            notes.append(("REJECT", f"cert {kid} has unparseable validity")); continue
        if kid in revoked:
            notes.append(("REJECT", f"cert {kid} is REVOKED")); continue
        trusted[kid] = bytes.fromhex(cert["component_pub"])
        # A1d: pre-warn while the cert is STILL valid but within warn_days of not_after — the verifier
        # screams ATTEST_FORGERY the instant it expires, so surface it LOUDLY before that cliff.
        try:
            secs_left = _parse_iso(cert["not_after"]) - now
            if 0 < secs_left <= warn_days * 86400:
                notes.append(("EXPIRING", f"cert {kid} expires in {int(secs_left // 86400)}d "
                              f"({cert['not_after']}) — re-issue before it FORGERY-fails"))
        except (KeyError, ValueError):
            pass
    return trusted, notes


# ── ITEM_3.2 — NATS delivery helpers ───────────────────────────────────────────────────────────
def _nats_raw_connect(host, port):
    """Open a raw TCP NATS connection, consume INFO, send CONNECT. Returns socket."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((host, port))
    s.recv(4096)  # INFO
    s.sendall(b'CONNECT {"verbose":false,"name":"vsf-s5-ca-approval"}\r\n')
    return s


def _nats_publish_token(token: dict, vsf_id: str, nats_host: str, nats_port: int) -> None:
    """ITEM_3.2 — Publish a signed approval token to vsf.<id>.s5.approval_token via raw NATS."""
    subject = f"vsf.{vsf_id}.s5.approval_token"
    body = json.dumps(token).encode()
    try:
        s = _nats_raw_connect(nats_host, nats_port)
        s.sendall(f"PUB {subject} {len(body)}\r\n".encode() + body + b"\r\n")
        s.flush() if hasattr(s, "flush") else None
        import time; time.sleep(0.2)  # let the server process
        s.close()
        print(f"✓ Token published → {subject}")
    except Exception as e:
        print(f"✗ NATS publish failed: {e}")
        print(f"  Token written to file only — deliver manually or retry with --publish")


def _nats_listen_approval_requests(vsf_id: str, nats_host: str, nats_port: int) -> None:
    """ITEM_3.2 — Subscribe to vsf.<id>.s5.approval_request and display pending L3 proposals.
    Displays each proposal for review. Press Ctrl-C to exit.
    To approve: python3 s5_ca.py approve --enc R.enc --proposal-id ID --proposal-hash HASH --out T.json --publish
    """
    import socket, time
    subject = f"vsf.{vsf_id}.s5.approval_request"
    sub_id = "s5-ca-listen-1"
    print(f"[s5-ca listen] watching {subject} on {nats_host}:{nats_port}")
    print(f"  To approve: python3 s5_ca.py approve --enc R.enc --proposal-id ID --proposal-hash HASH --out T.json --publish")
    print(f"  Ctrl-C to exit\n")

    def run_once():
        s = _nats_raw_connect(nats_host, nats_port)
        s.settimeout(30)
        s.sendall(f"SUB {subject} {sub_id}\r\n".encode())
        buf = b""
        last_ping = time.time()
        while True:
            try:
                chunk = s.recv(65536)
                if not chunk:
                    raise ConnectionError("closed")
                buf += chunk
            except socket.timeout:
                if time.time() - last_ping > 20:
                    s.sendall(b"PING\r\n")
                    last_ping = time.time()
                continue
            i = 0
            while i < len(buf):
                if buf[i:i+4] == b"PING":
                    end = buf.find(b"\r\n", i)
                    if end < 0: break
                    s.sendall(b"PONG\r\n"); i = end + 2; continue
                if buf[i:i+4] in (b"PONG", b"+OK "):
                    end = buf.find(b"\r\n", i)
                    if end < 0: break
                    i = end + 2; continue
                if buf[i:i+3] == b"MSG":
                    end = buf.find(b"\r\n", i)
                    if end < 0: break
                    header = buf[i:end].decode(errors="replace")
                    parts = header.split()
                    try:
                        size = int(parts[-1])
                    except Exception:
                        i = end + 2; continue
                    body_start = end + 2
                    if len(buf) < body_start + size + 2:
                        break
                    body = buf[body_start:body_start + size]
                    i = body_start + size + 2
                    try:
                        proposal = json.loads(body.decode())
                    except Exception:
                        print("[s5-ca listen] non-JSON payload — skipping"); continue
                    _display_proposal(proposal)
                    continue
                end = buf.find(b"\r\n", i)
                if end < 0: break
                i = end + 2
            buf = buf[i:]

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            print("\n[s5-ca listen] exiting")
            break
        except Exception as e:
            print(f"[s5-ca listen] connection error: {e} — reconnecting in 5s")
            time.sleep(5)


def _display_proposal(proposal: dict) -> None:
    pid = proposal.get("proposal_id", "?")
    phash = proposal.get("content_hash", "?")
    kind = proposal.get("kind", "?")
    rationale = proposal.get("rationale", "?")
    staged = proposal.get("staged_at", "?")
    ttl = proposal.get("ttl_s", "?")
    token_sub = proposal.get("token_subject", "?")
    print(f"""
╔══════════════════════════════════════════════════════════════════════╗
  L3 APPROVAL REQUEST — VSF S5 CONSOLE
  proposal_id:   {pid}
  kind:          {kind}
  staged_at:     {staged}
  ttl_s:         {ttl}
  content_hash:  {phash[:32]}…
  rationale:     {rationale}
  token_subject: {token_sub}

  To APPROVE:
    python3 s5_ca.py approve --enc R.enc \\
      --proposal-id {pid} \\
      --proposal-hash {phash} \\
      --out /tmp/tok.json --publish

  To DENY:
    python3 s5_ca.py approve --enc R.enc \\
      --proposal-id {pid} \\
      --proposal-hash {phash} \\
      --decision deny --out /tmp/tok.json --publish
╚══════════════════════════════════════════════════════════════════════╝
""", flush=True)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────
def _opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _write_json(path, obj, mode=0o644):
    import os
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def main():
    import os
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "init-root":
        import getpass
        enc_path = _opt("--enc"); pub_path = _opt("--pub")
        if not enc_path or not pub_path:
            print("usage: init-root --enc OUT.enc --pub OUT.pub.json"); return 2
        if os.path.exists(enc_path):
            print(f"REFUSING: {enc_path} exists — minting a new root would orphan everything signed by the old one.")
            print("Move it aside deliberately if you really mean to re-bootstrap the trust root."); return 1
        p1 = getpass.getpass("New S5-root passphrase (you will need this to issue/revoke; back it up): ")
        if len(p1) < 12:
            print("REFUSING: use a passphrase of at least 12 characters."); return 1
        if p1 != getpass.getpass("Repeat passphrase: "):
            print("Passphrases do not match."); return 1
        enc, pub_doc = make_root(p1)
        _write_json(enc_path, enc, mode=0o600)   # the encrypted secret — keep locally + copy to USB
        _write_json(pub_path, pub_doc, mode=0o644)  # the public key — deploy this to the host verifier
        print(f"✓ S5 root minted.  root_id = {pub_doc['root_id']}")
        print(f"  ENCRYPTED SECRET → {enc_path}   (0600; COPY THIS TO A USB and keep it offline)")
        print(f"  PUBLIC KEY       → {pub_path}   (deploy to the host: this is what the verifier embeds)")
        print("  The clear private key was NEVER written to disk. Lose the passphrase = lose the ability")
        print("  to issue/revoke (already-signed certs keep verifying). Run `restore` now as a recovery drill.")
        return 0

    if cmd == "restore":
        import getpass
        enc_path = _opt("--enc")
        if not enc_path:
            print("usage: restore --enc OUT.enc"); return 2
        seed, backup = _load_root_seed(enc_path, getpass.getpass("S5-root passphrase: "))
        got = _key_id(_pub_raw(_sk_from_seed(seed)))
        ok = got == backup["root_id"]
        print(f"{'✓' if ok else '✗'} decrypted; recovered root_id = {got}"
              + ("" if ok else f"  ≠ stored {backup['root_id']} (CORRUPT)"))
        print("  (nothing was written — this only proves the backup + passphrase recover the root.)")
        return 0 if ok else 1

    if cmd == "issue-cert":
        import getpass
        enc_path = _opt("--enc"); comp = _opt("--component-pub"); role = _opt("--role")
        scope = (_opt("--scope") or "").split(",") if _opt("--scope") else []
        days = int(_opt("--days", "365")); out = _opt("--out")
        if not (enc_path and comp and role and scope and out):
            print("usage: issue-cert --enc R.enc --component-pub HEX --role NAME --scope a,b,c [--days 365] --out CERT.json"); return 2
        seed, _ = _load_root_seed(enc_path, getpass.getpass("S5-root passphrase: "))
        cert = issue_cert(seed, comp, role, scope, days)
        _write_json(out, cert)
        print(f"✓ cert issued for {cert['key_id']} (role={role}, {days}d) → {out}")
        return 0

    if cmd == "revoke":
        import getpass
        enc_path = _opt("--enc"); crl_path = _opt("--crl"); kid = _opt("--key-id")
        reason = _opt("--reason", ""); next_days = int(_opt("--next-days", "7"))
        if not (enc_path and crl_path):
            print("usage: revoke --enc R.enc --crl CRL.json [--key-id ID] [--reason TEXT] [--next-days 7]"); return 2
        seed, _ = _load_root_seed(enc_path, getpass.getpass("S5-root passphrase: "))
        crl = json.load(open(crl_path, encoding="utf-8")) if os.path.exists(crl_path) else None
        crl = make_or_update_crl(seed, crl, kid, reason, next_days)
        _write_json(crl_path, crl)
        print(f"✓ CRL re-signed ({len(crl['revoked'])} revoked, next_update {crl['next_update']}) → {crl_path}"
              + (f"\n  added {kid}" if kid else " (no key added — freshness refresh only)"))
        return 0

    if cmd == "approve":
        import getpass
        enc_path = _opt("--enc"); pid = _opt("--proposal-id"); phash = _opt("--proposal-hash")
        decision = _opt("--decision", "approve"); ttl = int(_opt("--ttl-s", "3600")); out = _opt("--out")
        # ITEM_3.2: optional NATS publish after signing
        nats_publish_flag = "--publish" in args
        nats_host = _opt("--nats-host", os.environ.get("NATS_HOST", "10.10.20.20"))
        nats_port = int(_opt("--nats-port", os.environ.get("NATS_PORT", "4222")))
        vsf_id = _opt("--vsf-id", os.environ.get("VSF_ID", "alpha"))
        if not (enc_path and pid and phash and out):
            print("usage: approve --enc R.enc --proposal-id ID --proposal-hash HEX "
                  "[--decision approve|deny] [--ttl-s 3600] --out TOKEN.json "
                  "[--publish [--nats-host H] [--nats-port P] [--vsf-id ID]]"); return 2
        if decision not in ("approve", "deny"):
            print("--decision must be 'approve' or 'deny'"); return 1
        seed, _ = _load_root_seed(enc_path, getpass.getpass("S5-root passphrase: "))
        tok = make_approval(seed, pid, phash, decision, ttl)
        _write_json(out, tok)
        print(f"✓ S5 approval signed: proposal={pid} decision={decision} ttl={ttl}s → {out}")
        print(f"  binds proposal_hash={phash[:16]}… ; valid until {tok['not_after']} (default-deny otherwise)")
        if nats_publish_flag:
            _nats_publish_token(tok, vsf_id, nats_host, nats_port)
        return 0

    if cmd == "listen":
        # ITEM_3.2 — subscribe to vsf.<id>.s5.approval_request and present proposals for review.
        # Usage: python3 s5_ca.py listen [--vsf-id alpha] [--nats-host H] [--nats-port P]
        nats_host = _opt("--nats-host", os.environ.get("NATS_HOST", "10.10.20.20"))
        nats_port = int(_opt("--nats-port", os.environ.get("NATS_PORT", "4222")))
        vsf_id = _opt("--vsf-id", os.environ.get("VSF_ID", "alpha"))
        _nats_listen_approval_requests(vsf_id, nats_host, nats_port)
        return 0

    if cmd == "expiring":
        # A1d: report days-to-expiry for every cert in a CA dir (offline, no passphrase). Run it in WSL
        # to know when to re-issue; the verifiers also pre-warn (build_trust EXPIRING) within warn_days.
        import datetime
        ca_dir = _opt("--ca-dir"); days = int(_opt("--days", "30"))
        if not ca_dir:
            print("usage: expiring --ca-dir DIR [--days 30]"); return 2
        pub = json.load(open(os.path.join(ca_dir, "s5_root.pub.json"), encoding="utf-8"))
        root_pub = bytes.fromhex(pub["root_pub"])
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        cert_dir = os.path.join(ca_dir, "certs")
        files = sorted(f for f in os.listdir(cert_dir) if f.endswith(".json")) if os.path.isdir(cert_dir) else []
        print(f"root_id = {pub['root_id']}   warn < {days}d")
        worst = 0  # 0 ok, 1 expiring, 2 expired/bad
        for fn in files:
            c = json.load(open(os.path.join(cert_dir, fn), encoding="utf-8"))
            sig_ok = verify_cert(c, root_pub)
            left = (_parse_iso(c["not_after"]) - now) / 86400
            flag = "EXPIRED" if left < 0 else ("EXPIRING" if left <= days else "ok")
            worst = max(worst, 2 if (left < 0 or not sig_ok) else (1 if left <= days else 0))
            print(f"  [{flag:8}] {c.get('key_id')}  role={c.get('role')}  exp={c.get('not_after')}"
                  f"  ({left:.0f}d)" + ("" if sig_ok else "  ⚠ SIG-BAD"))
        if not files:
            print("  (no certs in this CA dir)")
        return worst  # nonzero exit if anything is expiring/expired — usable in a cron/check

    if cmd == "verify":
        pub = json.load(open(_opt("--pub"), encoding="utf-8"))
        root_pub = bytes.fromhex(pub["root_pub"])
        print(f"root_id = {pub['root_id']}")
        if _opt("--cert"):
            c = json.load(open(_opt("--cert"), encoding="utf-8"))
            print(f"  cert {c['key_id']}: {'✓ chains to root' if verify_cert(c, root_pub) else '✗ BAD'}")
        if _opt("--crl"):
            c = json.load(open(_opt("--crl"), encoding="utf-8"))
            print(f"  CRL: {'✓ signed by root' if verify_crl(c, root_pub) else '✗ BAD'} "
                  f"({len(c.get('revoked', []))} revoked, next_update {c.get('next_update')})")
        if _opt("--approval"):
            t = json.load(open(_opt("--approval"), encoding="utf-8"))
            print(f"  approval {t.get('proposal_id')}: "
                  f"{'✓ signed by root + in-window' if verify_approval(t, root_pub) else '✗ BAD'} "
                  f"(decision={t.get('decision')}, exp={t.get('not_after')})")
        return 0

    if cmd == "--selftest":
        return _selftest()

    print(__doc__.strip().splitlines()[0])
    print("\nsubcommands: init-root | restore | issue-cert | revoke | approve | listen | verify | expiring | --selftest")
    print("run with no args or see the module docstring for full usage.")
    return 2


def _selftest():
    """In-memory round-trip of the whole chain. Runs on the sandbox (108), never WSL. Low scrypt n for speed."""
    import tempfile
    import os
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    pw = "correct horse battery staple"
    # mint a root with a fast KDF (selftest only) by encrypting a known seed
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    sk = Ed25519PrivateKey.generate()
    seed = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    root_pub = _pub_raw(sk)
    root_id = _key_id(root_pub)
    enc = {"v": 1, "type": "vsf-s5-root-backup", "root_id": root_id, "root_pub": root_pub.hex(),
           "created": _now_iso()}
    enc.update(encrypt_seed(seed, pw, n=2 ** 14))
    pub_doc = {"v": 1, "type": "vsf-s5-root-pub", "root_id": root_id, "root_pub": root_pub.hex()}

    # 1. backup round-trips with the right passphrase, fails with the wrong one
    check("backup decrypts with correct passphrase", decrypt_seed(enc, pw) == seed)
    try:
        decrypt_seed(enc, "wrong passphrase here"); check("wrong passphrase rejected", False)
    except Exception:
        check("wrong passphrase rejected", True)
    # tampered ciphertext (flip a byte) must fail the AEAD tag
    bad = dict(enc); bad["ct"] = ("00" if enc["ct"][:2] != "00" else "11") + enc["ct"][2:]
    try:
        decrypt_seed(bad, pw); check("tampered backup rejected", False)
    except Exception:
        check("tampered backup rejected", True)

    # 2. a component key + its cert chains to the root
    comp_sk = Ed25519PrivateKey.generate()
    comp_pub = _pub_raw(comp_sk)
    cert = issue_cert(seed, comp_pub.hex(), "vsf-state-attest",
                      ["statedb.deploys", "statedb.coupling_registry", "statedb.audits"], days=365)
    check("cert verifies against root", verify_cert(cert, root_pub))
    check("cert key_id == component signer id", cert["key_id"] == _key_id(comp_pub))
    # a cert re-signed by a DIFFERENT root must not verify against ours
    other = Ed25519PrivateKey.generate()
    other_seed = other.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    forged = issue_cert(other_seed, comp_pub.hex(), "vsf-state-attest", ["statedb.deploys"])
    check("foreign-root cert rejected", not verify_cert(forged, root_pub))

    # 3. build_trust: valid cert → trusted; component signer id present
    trusted, notes = build_trust(pub_doc, [cert])
    check("valid cert → key in trust set", cert["key_id"] in trusted and trusted[cert["key_id"]] == comp_pub)

    # 4. expired cert → NOT trusted
    expired = issue_cert(seed, comp_pub.hex(), "vsf-state-attest", ["statedb.deploys"], days=-1)
    t2, _ = build_trust(pub_doc, [expired])
    check("expired cert → not trusted", cert["key_id"] not in t2)

    # 5. revocation: a CRL listing the key → NOT trusted
    crl = make_or_update_crl(seed, None, cert["key_id"], "host suspected compromised", next_days=7)
    check("CRL verifies against root", verify_crl(crl, root_pub))
    t3, _ = build_trust(pub_doc, [cert], crl)
    check("revoked cert → not trusted", cert["key_id"] not in t3)

    # 6. L3 approval token: signs + verifies; foreign-root + expired + tamper all rejected
    appr = make_approval(seed, "reframe-2026-06-22-abc", "de" * 32, "approve", ttl_s=3600)
    check("approval verifies against root", verify_approval(appr, root_pub))
    forged_appr = make_approval(other_seed, "reframe-2026-06-22-abc", "de" * 32, "approve")
    check("foreign-root approval rejected", not verify_approval(forged_appr, root_pub))
    expired_appr = make_approval(seed, "p2", "ab" * 32, "approve", ttl_s=-1)
    check("expired approval rejected", not verify_approval(expired_appr, root_pub))
    tampered_appr = dict(appr); tampered_appr["decision"] = "deny"   # flip decision, keep old sig
    check("tampered approval (decision flip) rejected", not verify_approval(tampered_appr, root_pub))
    # a forged CRL (signed by the wrong root) is IGNORED → key stays trusted, with a FORGERY note
    forged_crl = make_or_update_crl(other_seed, None, cert["key_id"], "fake", 7)
    t4, notes4 = build_trust(pub_doc, [cert], forged_crl)
    check("forged CRL ignored (key still trusted)", cert["key_id"] in t4)
    check("forged CRL raises a FORGERY note", any(n[0] == "FORGERY" for n in notes4))

    # 6. stale CRL → key still trusted but a STALE note is raised
    stale = make_or_update_crl(seed, None, None, "", next_days=-1)  # next_update already past
    _, notes6 = build_trust(pub_doc, [cert], stale)
    check("stale CRL raises a STALE note", any(n[0] == "STALE" for n in notes6))

    # 6b. A1d: a cert within warn_days of expiry → trusted BUT an EXPIRING note; a 365d cert → none.
    soon = issue_cert(seed, comp_pub.hex(), "vsf-state-attest", ["statedb.deploys"], days=10)
    t_soon, notes_soon = build_trust(pub_doc, [soon], None, warn_days=30)
    check("near-expiry cert still trusted", soon["key_id"] in t_soon)
    check("near-expiry cert → EXPIRING note", any(n[0] == "EXPIRING" for n in notes_soon))
    _, notes_far = build_trust(pub_doc, [cert], None, warn_days=30)  # cert is 365d
    check("365d cert → no EXPIRING note", not any(n[0] == "EXPIRING" for n in notes_far))

    # 7. on-disk round-trip: init-style write + verify subcommand parity
    tmp = tempfile.mkdtemp(prefix="s5ca-")
    _write_json(os.path.join(tmp, "c.json"), cert)
    reread = json.load(open(os.path.join(tmp, "c.json")))
    check("cert survives json round-trip (canonical payload stable)", verify_cert(reread, root_pub))
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    print("# s5_ca --selftest — offline CA chain (mint/backup/cert/revoke/trust)")
    for n, ok, d in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else ""))
    print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("## SELFTEST: ✗ NOT MET — do NOT run the real ceremony yet.")
        return 1
    print("## SELFTEST: ✓ MET — the offline CA chain is sound. Cleared to mint the real root in WSL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
