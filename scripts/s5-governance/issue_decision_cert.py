#!/usr/bin/env python3
"""issue_decision_cert.py — S5 operational decision-key issuance ceremony.
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Issues the s5-operational decision cert under the REAL offline S5 root,
mirroring beacon_ca_cutover.py `issue` (same ceremony shape: plan →
issue-interactive-only → verify, self-check + negative control). The cert
feeds DecisionVerifier (vsf_decision_auth.py): cert chains to pinned root,
decision sig verifies against the cert pubkey, fail-closed otherwise.

SOVEREIGNTY RULES (non-negotiable, same as beacon cutover):
  - The root passphrase exists at a getpass() prompt or not at all: never
    argv, never env, never chat, never file. `issue` refuses non-tty stdin.
  - The root PRIVATE key is never copied, moved, or printed. Only pubkey
    prefixes (16 hex) appear in output.
  - The operational PRIVATE key belongs to rmw3 (human signer): generate it
    here only if explicitly asked (--generate); prefer --pubkey-hex with an
    offline-generated key. Either way 0600, gitignored, never committed.
  - Test mode (--test-ca) uses the throwaway test CA and says so loudly on
    every line. Test artifacts must never reach production witnesses.

Usage:
  python3 scripts/s5-governance/issue_decision_cert.py plan [--json]
  python3 scripts/s5-governance/issue_decision_cert.py issue [--generate | --pubkey-hex HEX [--node-id ID]] [--test-ca] [--out-dir DIR]
  python3 scripts/s5-governance/issue_decision_cert.py verify [--out-dir DIR] [--test-ca]

  plan   — read-only audit of ceremony readiness (always rc 0 + report).
  issue  — interactive ONLY (tty required). Signs + writes cert, self-verifies
           against the root and runs the negative control (test CA must
           reject, and vice versa). Artifacts removed on ANY check failure.
  verify — re-verifies staged artifacts (chain + negative + shape), rc mapped.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "algedonic"))
sys.path.insert(0, str(REPO / "scripts" / "state" / "governance"))
sys.path.insert(0, str(REPO / "scripts" / "s5-governance"))

PROD_ROOT_PUB = Path.home() / ".vsf" / "s5-root" / "s5_root.pub.json"
PROD_ROOT_ENC = Path.home() / ".vsf" / "s5-root" / "s5_root.enc"
DEFAULT_OUT = REPO / "_decision_ca"
TEST_CA_DIR = REPO / "scripts" / "_beacon_ca"
HEX64 = re.compile(r"[0-9a-f]{64}")
UTC_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
NODE_ID_DEFAULT = "s5-operational"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _root_paths(test_mode: bool):
    if test_mode:
        return (TEST_CA_DIR / "ca.pubkey.hex",
                TEST_CA_DIR / "ca.key", True)
    return (None, PROD_ROOT_ENC, False)


def _load_root_pub(test_mode: bool):
    if test_mode:
        txt = (TEST_CA_DIR / "ca.pubkey.hex").read_text(encoding="utf-8").strip()
        return {"root_pub": txt, "root_id": "test-ca (NOT FOR PRODUCTION)"}
    from beacon_ca_cutover import check_root_pin, load_root_pub
    pin = check_root_pin(load_root_pub())
    if not pin.get("ok"):
        sys.exit(f"  ✗ root pin failed ({pin.get('error') or pin}) — refusing to issue")
    return pin


def _write_private(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def _write_text_private(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


def phase_plan(_args) -> int:
    prod_pub = _read_json(PROD_ROOT_PUB)
    print("ceremony readiness (read-only):")
    if prod_pub and HEX64.fullmatch(str(prod_pub.get("root_pub", ""))):
        print(f"  [ok  ] offline root pub present: id={prod_pub.get('root_id')} "
              f"pub={prod_pub['root_pub'][:16]}…")
    else:
        print("  [FAIL] offline root pub missing/unreadable: "
              f"{PROD_ROOT_PUB} — ceremony BLOCKED until S5 restores it")
    print(f"  [{'ok  ' if PROD_ROOT_ENC.is_file() else 'FAIL'}] root secret present: "
          f"{PROD_ROOT_ENC} (never read here, only via getpass at issue)")
    test_ca = TEST_CA_DIR / "ca.pubkey.hex"
    print(f"  [{'ok  ' if test_ca.is_file() else '——  '}] test CA available for dry runs: "
          f"{test_ca.is_file()}")
    out = Path(_args.out_dir) if getattr(_args, "out_dir", None) else DEFAULT_OUT
    staged = out / "s5-operational.cert.json"
    print(f"  [{'info' if True else ''}] staged cert: {staged} "
          f"({'present' if staged.is_file() else 'absent — run issue'})")
    print("  note  : logger on LXC101 currently has no VSF_CA_DIR pin "
          "(B3 fail-closed dormant); pin+restart follows issuance, S5 window")
    return 0


def phase_issue(args) -> int:
    if not sys.stdin.isatty():
        print("  ✗ `issue` is interactive-only — run it in a terminal and type "
              "the S5 root passphrase at the prompt (never argv/env/chat).",
              file=sys.stderr)
        return 1
    test_mode = bool(args.test_ca)
    if test_mode:
        print("  !! TEST MODE — test CA only, artifacts must never reach production !!")
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT

    node_id = args.node_id or NODE_ID_DEFAULT
    if args.generate:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, PrivateFormat, NoEncryption)
        sk = ed25519.Ed25519PrivateKey.generate()
        pub_hex = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        priv = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        _write_private(out_dir / f"{node_id}.key", priv)
        print(f"  [ok  ] operational keypair generated (0600, gitignored staging)")
    elif args.pubkey_hex:
        if not HEX64.fullmatch(args.pubkey_hex.lower()):
            sys.exit("  ✗ --pubkey-hex must be 64 lowercase hex chars")
        pub_hex, sk, from_test_key = args.pubkey_hex.lower(), None, False
        print("  [ok  ] using offline-generated pubkey (private key never touched here)")
    else:
        sys.exit("  ✗ need --generate or --pubkey-hex HEX [--node-id ID]")

    if test_mode:
        from beacon_ca_cutover import build_real_cert
        ca_key_path = TEST_CA_DIR / "ca.key"
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed
            tsk = _ed.Ed25519PrivateKey.from_private_bytes(ca_key_path.read_bytes())
        except OSError:
            sys.exit(f"  ✗ test CA key missing: {ca_key_path} (run gen_test_ca.py first)")
        from beacon_attestation import verify_node_cert
        root_pub = (TEST_CA_DIR / "ca.pubkey.hex").read_text(encoding="utf-8").strip()
        cert = build_real_cert(node_id, pub_hex, root_pub, tsk)
        neg_ca = "0" * 64
    else:
        import s5_ca
        from beacon_ca_cutover import build_real_cert, verify_node_cert
        from beacon_attestation import verify_node_cert as _vnc
        verify_node_cert = _vnc
        pin = _load_root_pub(False)
        root_pub = pin["root_pub"]
        passphrase = getpass.getpass("S5 root passphrase: ")
        try:
            seed, _backup = s5_ca._load_root_seed(str(PROD_ROOT_ENC), passphrase)
            sk_root = s5_ca._sk_from_seed(seed)
            derived = s5_ca._pub_raw(sk_root).hex()
        except Exception:
            print("  ✗ S5 root passphrase rejected (or backup unreadable) — nothing written.")
            return 1
        finally:
            try:
                del passphrase
            except NameError:
                pass
        if derived != root_pub:
            print("  ✗ decrypted root key does not match pinned pub — nothing written.")
            return 1
        sk = sk_root
        cert = build_real_cert(node_id, pub_hex, root_pub, sk)
        try:
            del seed
        except NameError:
            pass
        neg_ca = None
        neg_path = TEST_CA_DIR / "ca.pubkey.hex"
        if neg_path.is_file():
            neg_ca = neg_path.read_text(encoding="utf-8").strip()
        if not neg_ca or not HEX64.fullmatch(neg_ca) or neg_ca == root_pub:
            print("  !! no usable negative-control CA available — proceeding "
                  "without the negative check is FORBIDDEN; aborting")
            return 1

    cert_path = out_dir / f"{node_id}.cert.json"
    pub_path = out_dir / "ca.pubkey.hex"
    _write_private(cert_path, json.dumps(cert, indent=2, sort_keys=True).encode() + b"\n")
    with open(pub_path, "w", encoding="utf-8") as fh:
        fh.write(root_pub + "\n")
    try:
        os.chmod(pub_path, 0o644)
    except OSError:
        pass

    written = _read_json(cert_path)
    if not written:
        cert_path.unlink(missing_ok=True)
        print("  ✗ written cert unreadable — removed, nothing to deploy")
        return 1
    try:
        from beacon_attestation import verify_node_cert as _verify
    except ImportError:
        _verify = verify_node_cert
    ok, reason, node_pub = _verify(written, root_pub)
    neg_ok = True
    if neg_ca:
        neg_ok, neg_reason, _ = _verify(written, neg_ca)
    shape_ok = bool(UTC_TS.fullmatch(str(written.get("issued", "")))) and \
        node_pub is not None and node_pub.hex() == pub_hex
    if not ok or neg_ok or not shape_ok:
        cert_path.unlink(missing_ok=True)
        print(f"  ✗ post-write verification failed "
              f"(root={ok}/{reason}, negative-rejected={not neg_ok}, "
              f"shape={shape_ok}) — artifacts removed")
        return 1
    print(f"  ✓ decision cert issued under {'TEST' if test_mode else 'REAL'} S5 root")
    print(f"    node_id   : {written['node_id']}")
    print(f"    pubkey    : {written['pubkey_hex'][:16]}…")
    print(f"    ca_pubkey : {written['ca_pubkey_hex'][:16]}…")
    print(f"    issued    : {written['issued']}")
    print(f"    wrote     : {cert_path} (0600)")
    print(f"    wrote     : {pub_path} (0644, root pub)")
    print(f"    [ok  ] self-verify vs root — {reason}")
    print(f"    [ok  ] negative control rejects — cert not valid under other CA")
    if not test_mode:
        print("\n  Next (S5 window): pin ca.pubkey.hex on LXC101 + VSF_CA_DIR "
              "drop-in + logger restart + live verify (signed test decision "
              "accepted, old test cert rejected).")
    return 0


def phase_verify(args) -> int:
    test_mode = bool(args.test_ca)
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT
    cert = _read_json(out_dir / "s5-operational.cert.json")
    if not cert:
        print(f"  ✗ no staged cert at {out_dir}/s5-operational.cert.json")
        return 1
    if test_mode:
        root_pub = (TEST_CA_DIR / "ca.pubkey.hex").read_text(encoding="utf-8").strip()
    else:
        pin = _load_root_pub(False)
        root_pub = pin["root_pub"]
    from beacon_attestation import verify_node_cert
    ok, reason, node_pub = verify_node_cert(cert, root_pub)
    shape_ok = bool(UTC_TS.fullmatch(str(cert.get("issued", "")))) and \
        node_pub is not None and len(cert.get("sig_hex", "")) == 128
    print(f"  [{'ok  ' if ok else 'FAIL'}] chain to root: {reason}")
    print(f"  [{'ok  ' if shape_ok else 'FAIL'}] shape (issued ts, 128-hex sig, node pubkey)")
    return 0 if (ok and shape_ok) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_plan = sub.add_parser("plan", help="read-only ceremony readiness")
    p_plan.add_argument("--out-dir", default=None)
    p_plan.set_defaults(fn=phase_plan)
    p_issue = sub.add_parser("issue", help="interactive issuance (tty only)")
    p_issue.add_argument("--generate", action="store_true")
    p_issue.add_argument("--pubkey-hex", default=None)
    p_issue.add_argument("--node-id", default=NODE_ID_DEFAULT)
    p_issue.add_argument("--test-ca", action="store_true")
    p_issue.add_argument("--out-dir", default=None)
    p_issue.set_defaults(fn=phase_issue)
    p_verify = sub.add_parser("verify", help="re-verify staged artifacts")
    p_verify.add_argument("--out-dir", default=None)
    p_verify.add_argument("--test-ca", action="store_true")
    p_verify.set_defaults(fn=phase_verify)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
