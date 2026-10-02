#!/usr/bin/env python3
"""beacon_ca_cutover.py — debt D-12: programmatic beacon CA cutover (S5, 2026-10-02).

The beacon currently runs on the TEST CA (_beacon_ca/, ca 20decff3…). Cutover =
issue the nucleus beacon cert under the REAL offline S5 root (root_pub
1d864429…, root_id ed25519:624e8d3ea2c0c904 == S5_ROOT_PIN), then swap the two
witnesses:
  n01      /opt/vsf-beacon/ca.pubkey.hex   (S5, root session only)
  LXC101   /etc/vsf/beacon_cert.json       (rmw3 via `ssh n02 'pct …'`)
The LXC101 key /etc/vsf/beacon_key.ed25519 is NEVER touched — only the cert's
ca_pubkey_hex and sig change.

Mirrors scripts/s5-governance/covenant_update.py: argparse subcommands,
deterministic, stdlib + repo imports, network only under --remote/--fetch-remote.

Phases:
  plan      [--json] [--remote] [--snapshot PATH]
      Read-only audit → state:
        TEST_CA_LIVE     deployed witnesses pin the off-root (test) CA, no real
                         cert issued yet
        REAL_CERT_ISSUED _beacon_ca/real/ holds a real cert, deployed still off-root
        CUTOVER_DONE     n01 ca == root_pub AND 101 cert ca_pubkey_hex == root_pub
        INCOMPLETE       otherwise — including every run without remote evidence
                         (no --remote and no staged snapshot: remote unknown)
      Without --remote the deployed pin is read from a staged snapshot if one
      exists (_beacon_ca/real/deployed_snapshot.json, or $BEACON_CUTOVER_SNAPSHOT).
  issue     [--fetch-remote] [--cert PATH] [--pubkey-hex HEX] [--node-id ID]
      Interactive ONLY: getpass("S5 root passphrase: ") — never argv, never env.
      Re-signs the node cert under the root → _beacon_ca/real/beacon_cert_real.json
      (0600) + _beacon_ca/real/ca.pubkey.hex (root pub). Self-verifies after the
      write AND runs a negative control (the old test CA must reject the cert).
  swap-plan
      Print the ordered swap blocks: rmw3 stage → S5 block on n01 → rmw3 verify.
      PRINT-ONLY: this phase runs no command of its own.
  verify    [--remote] [--beacon-token T]
      Local: root pin + real cert self-verify. With --remote: n01 ca, 101 cert
      (verify_node_cert against root_pub) and the public beacon health JSON.
      rc=0 iff every checked witness agrees, else rc=1 + VERIFY_FAIL summary.

Beacon cert format (scripts/algedonic/beacon_attestation.py::verify_node_cert):
Ed25519 over _canonical_json({node_id,pubkey_hex,ca_pubkey_hex,issued}) where
_canonical_json = json.dumps(separators=(",",":"), sort_keys=True,
ensure_ascii=False); sig_hex = 128 hex; node_cert.ca_pubkey_hex must equal the
pinned CA pubkey (64 hex).

Timestamps come from the clock — never hardcoded, never :00/T00 shapes.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BEACON_CA_DIR = REPO / "_beacon_ca"
REAL_DIR = BEACON_CA_DIR / "real"
REAL_CERT = REAL_DIR / "beacon_cert_real.json"
REAL_CA_PUB = REAL_DIR / "ca.pubkey.hex"
TEST_CA_PUB = BEACON_CA_DIR / "ca.pubkey.hex"
DEFAULT_SNAPSHOT = REAL_DIR / "deployed_snapshot.json"
ROOT_PUB_DOC = Path.home() / ".vsf" / "s5-root" / "s5_root.pub.json"
ROOT_ENC = Path.home() / ".vsf" / "s5-root" / "s5_root.enc"

N01_CA_PATH = "/opt/vsf-beacon/ca.pubkey.hex"
LXC101_CERT_PATH = "/etc/vsf/beacon_cert.json"

sys.path.insert(0, str(REPO / "scripts" / "algedonic"))
sys.path.insert(0, str(REPO / "scripts" / "state" / "governance"))
import s5_ca  # noqa: E402
from beacon_attestation import _canonical_json, verify_node_cert  # noqa: E402

# Network endpoints (CF passes browser-like UA; Python-urllib gets 1010)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
BEACON_HEALTH = "https://vsf.u2738.org/beacon/health"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes",
            "-o", "ConnectTimeout=10"]

STATES = ("TEST_CA_LIVE", "REAL_CERT_ISSUED", "CUTOVER_DONE", "INCOMPLETE")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NEGATIVE_CA = "00" * 32

# Health on n01 with the unit's own MONITOR_TOKEN: extracted inside the remote
# shell, used for the request, never echoed back.
LOCAL_HEALTH_CMD = (
    'T=$(systemctl show --property=Environment --value vsf-beacon 2>/dev/null '
    '| tr " " "\\n" | sed -n "s/^MONITOR_TOKEN=//p"); '
    'curl -sS --max-time 10 "http://127.0.0.1:8080/health?t=${T}"'
)


# ─── shared plumbing ─────────────────────────────────────────────────────────

def now_utc() -> str:
    """Real UTC timestamp; seconds never forced to :00 (canon gate)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(REPO))
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def _ssh(host: str, remote_cmd: str, timeout: int = 20) -> tuple[int, str]:
    return _run(["ssh", *SSH_OPTS, host, remote_cmd], timeout=timeout)


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of mixed output (pct exec adds noise)."""
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        obj = json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(p: Path) -> str:
    """Repo-relative display path (falls back to absolute for injected paths)."""
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def load_root_pub() -> dict:
    return json.loads(ROOT_PUB_DOC.read_text(encoding="utf-8"))


def check_root_pin(root_doc: dict) -> dict:
    """sha256(root_pub) prefix must reproduce root_id (s5_ca._key_id format)
    and land on the S5_ROOT_PIN pinned in scripts/state/governance/s5_ca.py."""
    try:
        root_pub = root_doc["root_pub"]
        root_id = root_doc["root_id"]
        derived = s5_ca._key_id(bytes.fromhex(root_pub))
    except (KeyError, ValueError, TypeError) as exc:
        return {"ok": False, "root_pub": None, "root_id": None, "derived": None,
                "s5_root_pin": s5_ca.S5_ROOT_PIN, "error": f"unparseable root pub doc: {exc}"}
    pin_ok = not s5_ca.S5_ROOT_PIN or derived == s5_ca.S5_ROOT_PIN
    return {"ok": derived == root_id and pin_ok, "root_pub": root_pub,
            "root_id": root_id, "derived": derived, "s5_root_pin": s5_ca.S5_ROOT_PIN,
            "pin_matches_s5_root_pin": pin_ok, "error": None}


def load_real_cert() -> dict | None:
    try:
        obj = json.loads(REAL_CERT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def load_snapshot(path: Path | None = None) -> dict | None:
    """Staged (previously captured) deployed witnesses for offline plan runs."""
    path = path or Path(os.environ.get("BEACON_CUTOVER_SNAPSHOT") or DEFAULT_SNAPSHOT)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def remote_n01_ca() -> dict:
    rc, out = _ssh("n01", f"cat {N01_CA_PATH}")
    if rc != 0:
        return {"ok": False, "ca": None, "error": out[:200]}
    first = out.split()[0] if out.split() else ""
    if not _HEX64.fullmatch(first):
        return {"ok": False, "ca": None, "error": f"unparseable: {out[:120]}"}
    return {"ok": True, "ca": first, "error": None}


def remote_101_cert() -> dict:
    rc, out = _ssh("n02", f"pct exec 101 -- cat {LXC101_CERT_PATH}")
    if rc != 0:
        return {"ok": False, "cert": None, "error": out[:200]}
    cert = _extract_json(out)
    if cert is None:
        return {"ok": False, "cert": None, "error": f"unparseable: {out[:120]}"}
    if not cert.get("node_id") or not _HEX64.fullmatch(str(cert.get("pubkey_hex", ""))):
        return {"ok": False, "cert": None, "error": "cert missing node_id/pubkey_hex"}
    return {"ok": True, "cert": cert, "error": None}


def classify_state(root_pub: str | None, remote_ca: str | None,
                   remote_cert_ca: str | None, has_real_cert: bool) -> str:
    """Pure state machine. Remote evidence absent/contradictory ⇒ INCOMPLETE
    (the remote is simply not witnessed — never assume it from local files)."""
    if not root_pub or remote_ca is None or remote_cert_ca is None:
        return "INCOMPLETE"
    if remote_ca == root_pub and remote_cert_ca == root_pub:
        return "CUTOVER_DONE"
    if remote_ca == root_pub or remote_cert_ca == root_pub:
        return "INCOMPLETE"          # half-swapped: one witness already on root
    return "REAL_CERT_ISSUED" if has_real_cert else "TEST_CA_LIVE"


# ─── plan ─────────────────────────────────────────────────────────────────────

def phase_plan(args: argparse.Namespace) -> int:
    try:
        root_doc = load_root_pub()
    except (OSError, json.JSONDecodeError) as exc:
        root_doc = {}
        pin = {"ok": False, "root_pub": None, "root_id": None, "derived": None,
               "s5_root_pin": s5_ca.S5_ROOT_PIN, "error": f"{type(exc).__name__}: {exc}"}
    else:
        pin = check_root_pin(root_doc)
    root_pub = pin.get("root_pub")

    deployed: dict = {"checked": bool(args.remote), "source": None,
                      "n01_ca": None, "lxc101": None, "errors": {}}
    if args.remote:
        deployed["source"] = "ssh"
        n01 = remote_n01_ca()
        if n01["ok"]:
            deployed["n01_ca"] = n01["ca"]
        else:
            deployed["errors"]["n01"] = n01["error"]
        c101 = remote_101_cert()
        if c101["ok"]:
            deployed["lxc101"] = c101["cert"]
        else:
            deployed["errors"]["lxc101"] = c101["error"]
    else:
        snap = load_snapshot(Path(args.snapshot) if args.snapshot else None)
        if snap is not None:
            deployed["checked"] = True
            deployed["source"] = "snapshot"
            deployed["n01_ca"] = snap.get("n01_ca")
            deployed["lxc101"] = snap.get("lxc101_cert")

    real_cert = load_real_cert()
    issued: dict = {"dir": _rel(REAL_DIR), "present": real_cert is not None,
                    "cert_path": _rel(REAL_CERT), "sha256": None,
                    "verifies": None, "ca_pubkey_hex": None}
    if real_cert is not None:
        issued["ca_pubkey_hex"] = real_cert.get("ca_pubkey_hex")
        issued["sha256"] = sha256_bytes(REAL_CERT.read_bytes())
        if root_pub:
            ok, reason, _ = verify_node_cert(real_cert, root_pub)
            issued["verifies"] = ok
            issued["verify_reason"] = reason

    state = classify_state(root_pub, deployed["n01_ca"],
                           (deployed["lxc101"] or {}).get("ca_pubkey_hex"),
                           real_cert is not None)

    notes: list[str] = []
    if not deployed["checked"]:
        notes.append("remote witnesses not checked — run plan --remote "
                     "(or stage a deployed_snapshot.json) for the actionable state")
    if deployed["checked"] and deployed["errors"]:
        notes.append("remote fetch failed: "
                     + ", ".join(f"{k}: {v}" for k, v in deployed["errors"].items()))
    test_ca = TEST_CA_PUB.read_text().strip() if TEST_CA_PUB.is_file() else None
    for label, ca in (("n01", deployed["n01_ca"]), ("101", (deployed["lxc101"] or {}).get("ca_pubkey_hex"))):
        if ca and root_pub and ca != root_pub and test_ca and ca != test_ca:
            notes.append(f"{label} CA is neither the root nor the local test CA — investigate")
    if real_cert is not None and issued["verifies"] is False:
        notes.append("staged real cert does NOT verify against the root — re-run issue")

    out = {"state": state, "root_pub": root_pub, "root_id": pin.get("root_id"),
           "pin": pin, "deployed": deployed, "issued_real": issued, "notes": notes}

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    print("  beacon_ca_cutover plan — read-only audit")
    print(f"  state   : {state}")
    mark = "ok  " if pin.get("ok") else "FAIL"
    pin_detail = pin.get("error") or (
        f"{pin.get('derived')} == {pin.get('root_id')}"
        + (" (== S5_ROOT_PIN)" if pin.get("pin_matches_s5_root_pin") else " (S5_ROOT_PIN MISMATCH)"))
    print(f"    [{mark}] root pin       {pin_detail}")
    dmark = "ok  " if deployed["checked"] and not deployed["errors"] else ("—   " if not deployed["checked"] else "FAIL")
    if deployed["checked"]:
        n01_ca = deployed["n01_ca"] or (deployed["errors"].get("n01") or "?")
        cert101 = deployed["lxc101"]
        c_detail = (f"ca={cert101.get('ca_pubkey_hex', '?')[:16]}… "
                    f"node={cert101.get('node_id', '?')} issued={cert101.get('issued', '?')}"
                    if cert101 else (deployed["errors"].get("lxc101") or "?"))
        print(f"    [{dmark}] n01 ca        {(n01_ca or '?')[:16]}…  ({deployed['source']})")
        print(f"    [{dmark}] 101 cert      {c_detail}")
    else:
        print(f"    [{dmark}] deployed      not checked (no --remote, no snapshot)")
    if issued["present"]:
        imark = "ok  " if issued["verifies"] else "FAIL"
        print(f"    [{imark}] issued-real   {issued['cert_path']} sha={issued['sha256'][:16]}… "
              f"ca={str(issued['ca_pubkey_hex'])[:16]}… verifies={issued['verifies']}")
    else:
        print(f"    [—  ] issued-real   {issued['dir']}/ — no real cert yet (run issue)")
    for n in notes:
        print(f"    note: {n}")
    return 0


# ─── issue ────────────────────────────────────────────────────────────────────

def build_real_cert(node_id: str, pubkey_hex: str, ca_pubkey_hex: str, sk,
                    issued: str | None = None) -> dict:
    """Build the signed beacon cert: Ed25519 over _canonical_json(payload) with
    payload = {node_id, pubkey_hex, ca_pubkey_hex, issued} (beacon_attestation
    canonicalisation), sig_hex = 128 hex. `sk` is a cryptography Ed25519 key."""
    payload = {
        "node_id": node_id,
        "pubkey_hex": pubkey_hex,
        "ca_pubkey_hex": ca_pubkey_hex,
        "issued": issued or now_utc(),
    }
    sig_hex = sk.sign(_canonical_json(payload)).hex()
    return {**payload, "sig_hex": sig_hex}


def _write_json_private(path: Path, obj: dict, mode: int) -> None:
    created = not path.parent.is_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(path, mode)  # defeat a permissive umask


def _write_hex(path: Path, hex_str: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(hex_str + "\n")
    os.chmod(path, mode)


def _resolve_source_cert(args: argparse.Namespace) -> tuple[str, str, dict | None, str]:
    """Return (node_id, pubkey_hex, source_cert_or_None, provenance)."""
    if args.pubkey_hex:
        if not _HEX64.fullmatch(args.pubkey_hex):
            sys.exit("  ✗ --pubkey-hex must be 64 lowercase hex chars")
        if not args.node_id:
            sys.exit("  ✗ --node-id required with --pubkey-hex")
        return args.node_id, args.pubkey_hex, None, "offline override (--pubkey-hex)"
    if args.fetch_remote or not args.cert:
        r = remote_101_cert()
        if not r["ok"]:
            sys.exit(f"  ✗ cannot read the deployed cert on LXC101 ({r['error']})\n"
                     f"    offline fallback: --cert PATH or --pubkey-hex HEX")
        cert = r["cert"]
        return cert["node_id"], cert["pubkey_hex"], cert, f"deployed {LXC101_CERT_PATH} (LXC101)"
    path = Path(args.cert)
    try:
        cert = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"  ✗ cannot read --cert {path}: {exc}")
    if not isinstance(cert, dict) or not cert.get("node_id"):
        sys.exit(f"  ✗ --cert {path} has no node_id")
    return cert["node_id"], cert.get("pubkey_hex", ""), cert, f"local file {path}"


def phase_issue(args: argparse.Namespace) -> int:
    # Interactive ONLY: the passphrase exists at a getpass prompt or not at all.
    if not sys.stdin.isatty():
        print("  ✗ `issue` is interactive-only — run it in a terminal and type the "
              "S5 root passphrase at the prompt (never passed via argv or env).",
              file=sys.stderr)
        return 1

    node_id, pubkey_hex, src_cert, provenance = _resolve_source_cert(args)
    if not node_id or not _HEX64.fullmatch(pubkey_hex or ""):
        sys.exit("  ✗ source cert has no usable node_id/pubkey_hex (64 hex)")

    try:
        root_doc = load_root_pub()
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"  ✗ cannot read {ROOT_PUB_DOC}: {exc}")
    pin = check_root_pin(root_doc)
    if not pin["ok"]:
        sys.exit(f"  ✗ root pin failed ({pin.get('error') or pin.get('derived')}) — refusing to issue")
    root_pub = pin["root_pub"]

    if not ROOT_ENC.is_file():
        sys.exit(f"  ✗ encrypted root secret missing: {ROOT_ENC}")

    passphrase = getpass.getpass("S5 root passphrase: ")
    try:
        seed, _backup = s5_ca._load_root_seed(str(ROOT_ENC), passphrase)
        sk = s5_ca._sk_from_seed(seed)
        derived_pub = s5_ca._pub_raw(sk).hex()
    except Exception:
        print("  ✗ S5 root passphrase rejected (or the backup is unreadable) — nothing written.")
        return 1
    if derived_pub != root_pub:
        print("  ✗ decrypted root key does not match s5_root.pub.json — nothing written.")
        return 1

    cert = build_real_cert(node_id, pubkey_hex, root_pub, sk)
    old_ca = ((src_cert or {}).get("ca_pubkey_hex") or "").lower()
    if not _HEX64.fullmatch(old_ca) or old_ca == root_pub:
        old_ca = (TEST_CA_PUB.read_text().strip() if TEST_CA_PUB.is_file() else NEGATIVE_CA)
    if old_ca == root_pub:
        old_ca = NEGATIVE_CA

    existed = REAL_CERT.is_file()
    _write_json_private(REAL_CERT, cert, 0o600)
    _write_hex(REAL_CA_PUB, root_pub, 0o644)

    try:
        written = json.loads(REAL_CERT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        REAL_CERT.unlink(missing_ok=True)
        print(f"  ✗ written cert unreadable ({exc}) — removed, nothing to deploy")
        return 1

    ok, reason, node_pub = verify_node_cert(written, root_pub)
    neg_ok, neg_reason, _ = verify_node_cert(written, old_ca)
    issued_shape_ok = bool(_UTC_TS.fullmatch(str(written.get("issued", ""))))
    if not ok or neg_ok or not issued_shape_ok or node_pub is None or node_pub.hex() != pubkey_hex:
        REAL_CERT.unlink(missing_ok=True)
        REAL_CA_PUB.unlink(missing_ok=True)
        print(f"  ✗ post-write verification failed "
              f"(root={ok}/{reason}, negative-control rejected={not neg_ok}/{neg_reason}, "
              f"issued-shape={issued_shape_ok}) — artifacts removed")
        return 1

    cert_sha = sha256_bytes(REAL_CERT.read_bytes())
    print("  ✓ beacon cert issued under the REAL S5 root"
          + (" (previous staged cert replaced)" if existed else ""))
    print(f"    node_id   : {written['node_id']}")
    print(f"    pubkey    : {written['pubkey_hex']}")
    print(f"    ca_pubkey : {written['ca_pubkey_hex']}  ({pin['root_id']})")
    print(f"    issued    : {written['issued']}")
    print(f"    sig       : {written['sig_hex'][:32]}… (128 hex)")
    print(f"    source    : {provenance}")
    print(f"    wrote     : {_rel(REAL_CERT)}  (0600, sha256 {cert_sha})")
    print(f"    wrote     : {_rel(REAL_CA_PUB)}  (0644, root pub)")
    print(f"    [ok  ] self-verify vs root pubkey — {reason}")
    print(f"    [ok  ] negative control: test CA {old_ca[:16]}… rejects the new cert "
          f"— {neg_reason}")
    print("\n  Next: `beacon_ca_cutover.py swap-plan` (print-only ordered blocks),")
    print("        then run the S5 block on n01 by hand and `verify --remote`.")
    return 0


# ─── swap-plan ────────────────────────────────────────────────────────────────

def phase_swap_plan(args: argparse.Namespace) -> int:
    ts = now_utc()
    ts_compact = re.sub(r"[:\-]", "", ts)
    try:
        pin = check_root_pin(load_root_pub())
        root_pub, root_id = pin["root_pub"], pin["root_id"]
    except (OSError, json.JSONDecodeError, KeyError):
        root_pub, root_id = "?", "?"
    print(f"""\
══════ beacon_ca_cutover swap-plan — root {str(root_pub)[:16]}… ({root_id}) — generated {ts} ══════
  PRINT-ONLY: no command below is run by this tool. Step 2/3 is the S5 block.

── Step 1/3 · rmw3 (local): stage the REAL cert into LXC101 ─────────────────
  # local receipt first
  sha256sum _beacon_ca/real/beacon_cert_real.json
  scp _beacon_ca/real/beacon_cert_real.json n02:/tmp/beacon_cert_real.json
  ssh n02 'sha256sum /tmp/beacon_cert_real.json'   # MUST match the local receipt
  # push the cert + restart the nucleus (cert only — the key is untouched)
  ssh n02 'pct push 101 /tmp/beacon_cert_real.json /etc/vsf/beacon_cert.json'
  ssh n02 'pct exec 101 -- systemctl restart vsf-nucleus-operational'
  # NOTE: /etc/vsf/beacon_key.ed25519 is NOT touched — only ca_pubkey_hex + sig change.
  #       From here until Step 2/3 the nucleus presents a root-signed cert to the
  #       still-test-pinned beacon → births fail closed. That window is safe.

── Step 2/3 · S5 on n01 (root session): swap the pinned CA + restart beacon ─
  sha256sum /opt/vsf-beacon/ca.pubkey.hex          # current = test CA 20decff3…
  cp /opt/vsf-beacon/ca.pubkey.hex /opt/vsf-beacon/ca.pubkey.hex.bak.{ts_compact}
  printf '%s\\n' '{root_pub}' > /opt/vsf-beacon/ca.pubkey.hex
  chown vsf:vsf /opt/vsf-beacon/ca.pubkey.hex && chmod 644 /opt/vsf-beacon/ca.pubkey.hex
  sha256sum /opt/vsf-beacon/ca.pubkey.hex          # receipt (root pub installed)
  systemctl restart vsf-beacon && sleep 3
  curl -s localhost:8080/health                    # beacon up (JSON)

── Step 3/3 · rmw3: verify (rc=0 iff every checked witness agrees) ───────────
  python3 scripts/s5-governance/beacon_ca_cutover.py verify --remote

══════ end swap-plan ══════""")
    return 0


# ─── verify ───────────────────────────────────────────────────────────────────

def _beacon_health(token: str | None) -> dict:
    """Public health JSON through CF; /beacon/health is monitor-token gated, so a
    beacon-authored 404 (public path reaches the app) is accepted as reachability
    and the same health JSON is then read on n01 with the unit's own token —
    which is extracted remotely and never printed."""
    url = BEACON_HEALTH + (f"?t={token}" if token else "")
    rc, out = _run(["curl", "-sS", "-A", UA, "--max-time", "15", url], timeout=20)
    if rc == 0:
        try:
            return {"ok": True, "via": "public", "health": json.loads(out),
                    "note": None, "error": None}
        except json.JSONDecodeError:
            pass
    reaches_app = "vsf.u2738.org" in out and "404" in out
    rc2, out2 = _ssh("n01", LOCAL_HEALTH_CMD, timeout=20)
    if reaches_app and rc2 == 0:
        try:
            note = None if token else (
                "public /beacon/health is monitor-token gated (public path itself "
                "reachable — beacon-authored 404); health JSON read on n01 — pass "
                "--beacon-token or set BEACON_MONITOR_TOKEN to check through CF")
            return {"ok": True, "via": "n01-local", "health": json.loads(out2),
                    "note": note, "error": None}
        except json.JSONDecodeError:
            out2 = f"non-json: {out2[:120]}"
    if not reaches_app:
        return {"ok": False, "via": None, "health": None, "note": None,
                "error": f"public health unreachable: {(out or '?')[:160]}"}
    return {"ok": False, "via": None, "health": None, "note": None,
            "error": f"health unreadable (public token-gated; n01: {out2[:120]})"}


def phase_verify(args: argparse.Namespace) -> int:
    failures: list[str] = []
    print("  beacon_ca_cutover verify — rc=0 iff every checked witness agrees")

    try:
        root_doc = load_root_pub()
    except (OSError, json.JSONDecodeError) as exc:
        root_doc, pin = {}, {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                             "root_id": None, "root_pub": None}
    else:
        pin = check_root_pin(root_doc)
    root_pub = pin.get("root_pub")
    if pin.get("ok"):
        print(f"    [ok  ] root pin            {pin['root_id']} (root_pub {root_pub[:16]}…)")
    else:
        print(f"    [FAIL] root pin            {pin.get('error') or pin.get('derived')}")
        failures.append("root.pin")

    real_cert = load_real_cert()
    if real_cert is None:
        print(f"    [FAIL] issued-real cert    {_rel(REAL_CERT)} missing — run issue")
        failures.append("issued_real.cert")
    elif not root_pub:
        print("    [FAIL] issued-real cert    unverifiable (no root pub)")
        failures.append("issued_real.cert")
    else:
        ok, reason, _ = verify_node_cert(real_cert, root_pub)
        print(f"    [{'ok  ' if ok else 'FAIL'}] issued-real cert    {reason}")
        if not ok:
            failures.append("issued_real.cert")

    if args.remote and root_pub:
        n01 = remote_n01_ca()
        n01_ok = bool(n01["ok"]) and n01["ca"] == root_pub
        print(f"    [{'ok  ' if n01_ok else 'FAIL'}] n01 ca.pubkey.hex   "
              f"{(n01['ca'] or n01['error'])[:16]}…")
        if not n01_ok:
            failures.append("n01.ca_pubkey_hex")

        c101 = remote_101_cert()
        if not c101["ok"]:
            c101_ok = False
            print(f"    [FAIL] 101 beacon_cert     {c101['error'][:80]}")
        else:
            cert = c101["cert"]
            v_ok, v_reason, _ = verify_node_cert(cert, root_pub)
            c101_ok = cert.get("ca_pubkey_hex") == root_pub and v_ok
            print(f"    [{'ok  ' if c101_ok else 'FAIL'}] 101 beacon_cert     "
                  f"ca={str(cert.get('ca_pubkey_hex'))[:16]}… verify_node_cert(root): {v_reason}")
        if not c101_ok:
            failures.append("101.beacon_cert")

        token = (args.beacon_token or os.environ.get("BEACON_MONITOR_TOKEN")
                 or os.environ.get("MONITOR_TOKEN"))
        h = _beacon_health(token)
        if h["ok"]:
            print(f"    [ok  ] beacon health ({h['via']})  "
                  f"{json.dumps(h['health'], sort_keys=True)[:120]}")
            if h["note"]:
                print(f"    note: {h['note']}")
        else:
            print(f"    [FAIL] beacon health       {h['error']}")
            failures.append("beacon.health")
    elif args.remote:
        print("    [FAIL] remote witnesses     skipped (no usable root pub)")
        failures.extend(["n01.ca_pubkey_hex", "101.beacon_cert"])
    else:
        print("    [—  ] remote witnesses     not checked (no --remote)")

    if failures:
        print(f"\n  VERIFY_FAIL: {', '.join(failures)}")
        return 1
    print("\n  ✓ verify: every checked witness agrees.")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="beacon_ca_cutover",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="read-only audit → state")
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--remote", action="store_true",
                        help="fetch deployed witnesses (ssh n01 + n02/pct 101)")
    p_plan.add_argument("--snapshot", default=None,
                        help="staged deployed-witness snapshot (default: "
                             "_beacon_ca/real/deployed_snapshot.json or "
                             "$BEACON_CUTOVER_SNAPSHOT)")

    p_issue = sub.add_parser("issue", help="sign the beacon cert under the S5 root "
                                           "(interactive: getpass prompt only)")
    p_issue.add_argument("--fetch-remote", action="store_true",
                         help="read node_id/pubkey from LXC101 (default when no source given)")
    p_issue.add_argument("--cert", default=None,
                         help="PATH to a local beacon_cert.json to re-sign")
    p_issue.add_argument("--pubkey-hex", default=None,
                         help="offline override: 64-hex node pubkey (with --node-id)")
    p_issue.add_argument("--node-id", default=None,
                         help="node_id for --pubkey-hex (deployed value: vsf_nucleus)")

    sub.add_parser("swap-plan", help="print the ordered swap blocks (print-only)")

    p_ver = sub.add_parser("verify", help="battery; rc=0 iff every checked witness agrees")
    p_ver.add_argument("--remote", action="store_true",
                       help="+ n01 ca, 101 cert, public beacon health")
    p_ver.add_argument("--beacon-token", default=None,
                       help="monitor token for the public /beacon/health JSON "
                            "(else $BEACON_MONITOR_TOKEN / $MONITOR_TOKEN)")

    args = ap.parse_args(argv)
    return {"plan": phase_plan, "issue": phase_issue,
            "swap-plan": phase_swap_plan, "verify": phase_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
