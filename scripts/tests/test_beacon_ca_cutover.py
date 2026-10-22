#!/usr/bin/env python3
# design: docs/plans/p3_design_debt_2026_10_20.vsm (SUT: scripts/s5-governance/beacon_ca_cutover.py)
"""test_beacon_ca_cutover.py — tests for the D-12 programmatic beacon CA cutover.

Covers scripts/s5-governance/beacon_ca_cutover.py (plan/issue/swap-plan/verify):
  * plan --json parses, state ∈ {TEST_CA_LIVE, REAL_CERT_ISSUED, CUTOVER_DONE, INCOMPLETE}
  * state classification from synthetic fixtures (pure classify_state + temp-dir
    snapshot/real-cert fixtures injected through module paths and --snapshot)
  * issue is interactive-only (no passphrase flag anywhere; non-tty run refuses)
  * cert build+verify with a throwaway Ed25519 key: verify_node_cert passes for
    the right CA and FAILS for the wrong one (negative control)
  * swap-plan carries the S5-on-n01 block, never claims to run anything
  * verify local only — no --remote (network skipped in tests)

Standalone: python3 scripts/tests/test_beacon_ca_cutover.py → exit 0/1.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "scripts" / "s5-governance" / "beacon_ca_cutover.py"

sys.path.insert(0, str(CLI.parent))
import beacon_ca_cutover as bcc  # noqa: E402

sys.path.insert(0, str(REPO / "scripts" / "algedonic"))
from beacon_attestation import verify_node_cert  # noqa: E402

TEST_CA = "20decff347a2f4ee518479004edc4e2539182537187e2b806f894a58569c06bc"
NODE_PUB = "08ee6d0377abec383de108b923cb960f8acea65c44e32ddc7ddbf9d6322cc062"
AUTO_EXECUTE_BANNED = (
    "auto-execut", "auto execute", "automatically", "will execute",
    "executing", "no user action", "run it for you", "applying the swap",
)

_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    if cond:
        print(f"  PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        _failures += 1
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


def run(args: list[str], timeout: int = 60, stdin=None,
        env: dict | None = None) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       cwd=str(REPO), stdin=stdin, env=env)
    return r.returncode, (r.stdout + r.stderr)


def run_main(argv: list[str]) -> tuple[int, str]:
    """In-process CLI (module paths injectable); captures stdout."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = bcc.main(argv)
    except SystemExit as exc:                      # argparse usage errors
        rc = exc.code if isinstance(exc.code, int) else 1
    return rc, buf.getvalue()


@contextlib.contextmanager
def patched(**kw):
    saved = {k: getattr(bcc, k) for k in kw}
    for k, v in kw.items():
        setattr(bcc, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(bcc, k, v)


@contextlib.contextmanager
def s5_pin_disabled():
    """s5_ca.S5_ROOT_PIN='' is the documented pre-ceremony/test mode: a synthetic
    fixture root derives its own root_id, which cannot equal the real pin."""
    saved = bcc.s5_ca.S5_ROOT_PIN
    bcc.s5_ca.S5_ROOT_PIN = ""
    try:
        yield
    finally:
        bcc.s5_ca.S5_ROOT_PIN = saved


def make_root(tmp: Path) -> tuple[dict, object]:
    """Throwaway S5 root (pub doc on disk + cryptography signing key)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption, PublicFormat)
    sk = Ed25519PrivateKey.generate()
    seed = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    doc = {"v": 1, "type": "vsf-s5-root-pub",
           "root_id": "ed25519:" + hashlib.sha256(pub).hexdigest()[:16],
           "root_pub": pub.hex(), "created": bcc.now_utc()}
    (tmp / "s5_root.pub.json").write_text(json.dumps(doc, indent=2))
    assert len(seed) == 32
    return doc, sk


def main() -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    print("=" * 60)
    print("beacon_ca_cutover.py — D-12 cutover tests")
    print("=" * 60)

    repo_real = REPO / "_beacon_ca" / "real" / "beacon_cert_real.json"
    repo_real_before = repo_real.read_bytes() if repo_real.is_file() else None

    # ── compile ─────────────────────────────────────────────────────────────
    rc, out = run([sys.executable, "-m", "py_compile", str(CLI),
                   str(Path(__file__).resolve())])
    check("py_compile (script + test)", rc == 0, out[-200:])

    # ── plan (local, no network) ────────────────────────────────────────────
    rc, out = run([sys.executable, str(CLI), "plan", "--json"])
    check("plan --json exits 0", rc == 0, f"rc={rc}")
    try:
        d = json.loads(out)
        parsed, perr = True, ""
    except json.JSONDecodeError as e:
        d, parsed, perr = {}, False, str(e)
    check("plan --json parses", parsed, perr)
    state = d.get("state", "")
    check("plan state is a known value", state in bcc.STATES, f"state={state}")
    check("plan local: remote not checked", d.get("deployed", {}).get("checked") is False,
          f"deployed={d.get('deployed')}")
    check("plan reports issued_real block", "issued_real" in d, f"keys={sorted(d)}")
    root_doc_path = Path.home() / ".vsf" / "s5-root" / "s5_root.pub.json"
    if root_doc_path.is_file():
        pin = d.get("pin", {})
        check("plan root pin ok (sha256(root_pub) == root_id)",
              pin.get("ok") is True and pin.get("derived") == pin.get("root_id"),
              f"derived={pin.get('derived')} root_id={pin.get('root_id')}")

    rc, out = run([sys.executable, str(CLI), "plan"])
    check("plan (human) exits 0", rc == 0, f"rc={rc}")
    check("plan (human) prints a known state", any(f"state   : {s}" in out for s in bcc.STATES),
          out.splitlines()[1] if out.strip() else "?")

    rc, out = run([sys.executable, str(CLI), "plan", "--json"],
                  env={**os.environ, "PATH": "/nonexistent"})
    check("plan (no --remote) runs with PATH=/nonexistent (no external command)",
          rc == 0 and json.loads(out).get("state") in bcc.STATES, f"rc={rc}")

    # ── root pin (unit) ─────────────────────────────────────────────────────
    if root_doc_path.is_file():
        doc = json.loads(root_doc_path.read_text())
        pin = bcc.check_root_pin(doc)
        check("check_root_pin: derived == root_id == S5_ROOT_PIN",
              pin["ok"] and pin["derived"] == "ed25519:624e8d3ea2c0c904"
              and pin["pin_matches_s5_root_pin"], f"derived={pin['derived']}")
        tampered = dict(doc, root_id="ed25519:deadbeefdeadbeef")
        check("check_root_pin rejects tampered root_id",
              bcc.check_root_pin(tampered)["ok"] is False,
              str(bcc.check_root_pin(tampered).get("derived")))
        swapped = dict(doc, root_pub="ab" * 32)
        check("check_root_pin rejects swapped root_pub",
              bcc.check_root_pin(swapped)["ok"] is False,
              str(bcc.check_root_pin(swapped).get("derived")))
        garbage = bcc.check_root_pin({"root_pub": "zz", "root_id": "?"})
        check("check_root_pin survives unparseable pub doc", garbage["ok"] is False,
              str(garbage.get("error")))

    # ── state classification (pure function, synthetic fixtures) ────────────
    if root_doc_path.is_file():
        ROOT = json.loads(root_doc_path.read_text())["root_pub"]
    else:
        ROOT = "1d864429a2bb1d4f820f83d147b641be2702112d6c47e5382a854919558568fe"
    fixtures = [
        ("TEST_CA_LIVE", ROOT, TEST_CA, TEST_CA, False),
        ("REAL_CERT_ISSUED", ROOT, TEST_CA, TEST_CA, True),
        ("CUTOVER_DONE", ROOT, ROOT, ROOT, True),
        ("CUTOVER_DONE (no real cert staged)", ROOT, ROOT, ROOT, False),
        ("INCOMPLETE (no remote evidence)", ROOT, None, None, False),
        ("INCOMPLETE (no remote, cert issued)", ROOT, None, None, True),
        ("INCOMPLETE (half-swap n01 only)", ROOT, ROOT, TEST_CA, True),
        ("INCOMPLETE (half-swap 101 only)", ROOT, TEST_CA, ROOT, True),
        ("INCOMPLETE (no root pin)", None, TEST_CA, TEST_CA, True),
    ]
    for name, rp, rca, cca, has_real in fixtures:
        got = bcc.classify_state(rp, rca, cca, has_real)
        expected = name.split(" (")[0]
        check(f"classify {name}", got == expected, f"got={got} want={expected}")

    # ── synthetic fixtures THROUGH the CLI (snapshot + injected real cert) ──
    tmp = tempfile.mkdtemp(prefix="beacon_cut_")
    tmp_path = Path(tmp)
    froot, fsk = make_root(tmp_path)
    syn_pin = bcc.check_root_pin(froot)     # S5_ROOT_PIN still the real one here
    check("check_root_pin rejects a root outside S5_ROOT_PIN",
          syn_pin["ok"] is False and syn_pin["derived"] == syn_pin["root_id"]
          and syn_pin["pin_matches_s5_root_pin"] is False,
          f"derived={syn_pin['derived']} pin={syn_pin['s5_root_pin']}")
    real_cert = bcc.build_real_cert("vsf_nucleus", NODE_PUB, froot["root_pub"], fsk)
    real_path = tmp_path / "beacon_cert_real.json"
    real_path.write_text(json.dumps(real_cert, indent=2, sort_keys=True) + "\n")
    (tmp_path / "ca.pubkey.hex").write_text(froot["root_pub"] + "\n")

    def snap(n01_ca: str, cert_ca: str) -> Path:
        p = tmp_path / f"snap_{n01_ca[:8]}_{cert_ca[:8]}.json"
        p.write_text(json.dumps({
            "saved": bcc.now_utc(), "n01_ca": n01_ca,
            "lxc101_cert": {"node_id": "vsf_nucleus", "pubkey_hex": NODE_PUB,
                            "ca_pubkey_hex": cert_ca, "issued": bcc.now_utc(),
                            "sig_hex": "00" * 64}}))
        return p

    with patched(ROOT_PUB_DOC=tmp_path / "s5_root.pub.json",
                 REAL_CERT=real_path,
                 REAL_CA_PUB=tmp_path / "ca.pubkey.hex"), s5_pin_disabled():
        rc, out = run_main(["plan", "--json", "--snapshot", str(snap(TEST_CA, TEST_CA))])
        j = json.loads(out)
        check("fixture REAL_CERT_ISSUED via plan --snapshot",
              rc == 0 and j["state"] == "REAL_CERT_ISSUED"
              and j["issued_real"]["verifies"] is True,
              f"state={j['state']} verifies={j['issued_real']['verifies']}")

        rc, out = run_main(["plan", "--json", "--snapshot", str(snap(froot["root_pub"], froot["root_pub"]))])
        j = json.loads(out)
        check("fixture CUTOVER_DONE via plan --snapshot",
              rc == 0 and j["state"] == "CUTOVER_DONE", f"state={j['state']}")

        rc, out = run_main(["plan", "--json", "--snapshot", str(snap(froot["root_pub"], TEST_CA))])
        j = json.loads(out)
        check("fixture INCOMPLETE (half-swap) via plan --snapshot",
              rc == 0 and j["state"] == "INCOMPLETE", f"state={j['state']}")

        rc, out = run_main(["plan", "--json", "--snapshot", str(tmp_path / "missing.json")])
        j = json.loads(out)
        check("fixture INCOMPLETE (snapshot unreadable)",
              rc == 0 and j["state"] == "INCOMPLETE", f"state={j['state']}")

        # verify (local) against the synthetic fixtures
        rc, out = run_main(["verify"])
        check("verify local on valid fixture → rc=0",
              rc == 0 and "every checked witness agrees" in out,
              out.strip().splitlines()[-1])

        forged_sk = Ed25519PrivateKey.generate()
        forged = bcc.build_real_cert("vsf_nucleus", NODE_PUB, froot["root_pub"], forged_sk)
        real_path.write_text(json.dumps(forged, indent=2, sort_keys=True) + "\n")
        rc, out = run_main(["verify"])
        check("verify local on foreign-signed cert → VERIFY_FAIL rc=1",
              rc == 1 and "VERIFY_FAIL" in out and "issued_real.cert" in out,
              out.strip().splitlines()[-1])

    rc, out = run([sys.executable, str(CLI), "verify"],
                  env={**os.environ, "PATH": "/nonexistent"})
    expected_rc = 0 if repo_real_before is not None else 1
    check("verify (no --remote) runs with PATH=/no-such-dir (no ssh/curl spawned)",
          rc == expected_rc,
          f"rc={rc} want={expected_rc} tail={out.strip().splitlines()[-1] if out.strip() else '?'}")

    with patched(ROOT_PUB_DOC=tmp_path / "s5_root.pub.json",
                 REAL_CERT=tmp_path / "nope.json",
                 REAL_CA_PUB=tmp_path / "ca.pubkey.hex"), s5_pin_disabled():
        rc, out = run_main(["verify"])
        check("verify local with missing real cert → VERIFY_FAIL rc=1",
              rc == 1 and "VERIFY_FAIL" in out, out.strip().splitlines()[-1])

    # ── issue: interactive-only plumbing ────────────────────────────────────
    rc, out = run([sys.executable, str(CLI), "issue", "--help"])
    check("issue --help exits 0", rc == 0, f"rc={rc}")
    check("issue exposes no passphrase flag",
          "--passphrase" not in out and "--password" not in out
          and "--pw" not in out, "argv clean")
    src = CLI.read_text(encoding="utf-8")
    check("issue prompts via getpass only",
          'getpass.getpass("S5 root passphrase: ")' in src, "prompt literal present")
    check("no argv/env passphrase plumbing in source",
          '"--passphrase"' not in src and "PASSPHRASE" not in src
          and 'environ["S5' not in src, "source clean")
    rc, out = run([sys.executable, str(CLI), "issue"], stdin=subprocess.DEVNULL, timeout=30)
    check("issue refuses a non-tty run (no hang, no prompt, rc=1)",
          rc == 1 and "interactive-only" in out, f"rc={rc} out={out.strip()[:120]}")
    repo_real_after_refusal = repo_real.read_bytes() if repo_real.is_file() else None
    check("issue refusal writes nothing",
          repo_real_after_refusal == repo_real_before,
          "beacon_cert_real.json unchanged/absent")

    # ── cert build + verify with a throwaway key ────────────────────────────
    ca_sk = Ed25519PrivateKey.generate()
    ca_pub = ca_sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    cert = bcc.build_real_cert("vsf_nucleus", NODE_PUB, ca_pub, ca_sk)
    check("build_real_cert field shape",
          set(cert) == {"node_id", "pubkey_hex", "ca_pubkey_hex", "issued", "sig_hex"},
          f"keys={sorted(cert)}")
    check("sig_hex is 128 hex", bool(re.fullmatch(r"[0-9a-f]{128}", cert["sig_hex"])),
          cert["sig_hex"][:16])
    check("issued is a real UTC timestamp shape",
          bool(bcc._UTC_TS.fullmatch(cert["issued"])), cert["issued"])
    ok, reason, node_bytes = verify_node_cert(cert, ca_pub)
    check("verify_node_cert passes with the issuing CA",
          ok and node_bytes is not None and node_bytes.hex() == NODE_PUB, reason)
    bad_ok, bad_reason, _ = verify_node_cert(cert, TEST_CA)
    check("verify_node_cert FAILS for the wrong (test) CA",
          bad_ok is False and "CA mismatch" in bad_reason, bad_reason)
    bad_ok2, bad_reason2, _ = verify_node_cert(cert, "00" * 32)
    check("verify_node_cert FAILS for a junk CA",
          bad_ok2 is False and "CA mismatch" in bad_reason2, bad_reason2)
    tampered = dict(cert, issued="2026-01-01T00:00:00Z")
    t_ok, t_reason, _ = verify_node_cert(tampered, ca_pub)
    check("tampered payload (issued) fails signature verify",
          t_ok is False and "signature" in t_reason, t_reason)
    unsigned = dict(cert); unsigned["sig_hex"] = "ab" * 64
    u_ok, u_reason, _ = verify_node_cert(unsigned, ca_pub)
    check("tampered sig fails", u_ok is False, u_reason)

    # ── swap-plan: print-only, S5-on-n01 block present ──────────────────────
    rc, out = run([sys.executable, str(CLI), "swap-plan"])
    check("swap-plan exits 0", rc == 0, f"rc={rc}")
    check("swap-plan has the S5-on-n01 marker", "S5 on n01" in out, "step 2/3")
    check("swap-plan orders the blocks",
          out.find("Step 1/3") < out.find("S5 on n01") < out.find("Step 3/3"),
          "1 < S5 < 3")
    check("swap-plan stages via pct push 101", "pct push 101" in out, "step 1")
    check("swap-plan restarts the nucleus", "vsf-nucleus-operational" in out, "step 1")
    check("swap-plan backs up + chowns the n01 pin",
          "ca.pubkey.hex.bak." in out and "chown vsf:vsf" in out, "step 2")
    check("swap-plan restarts the beacon", "systemctl restart vsf-beacon" in out, "step 2")
    check("swap-plan states the key is NOT touched",
          "beacon_key.ed25519 is NOT touched" in out, "step 1 note")
    check("swap-plan ends with verify --remote", "verify --remote" in out, "step 3")
    if root_doc_path.is_file():
        root_pub = json.loads(root_doc_path.read_text())["root_pub"]
        check("swap-plan prints the root_pub to install", root_pub in out, root_pub[:16])
    low = out.lower()
    hits = [b for b in AUTO_EXECUTE_BANNED if b in low]
    check("swap-plan has no auto-execute language", not hits, f"hits={hits}")
    check("swap-plan declares PRINT-ONLY", "PRINT-ONLY" in out, "banner")
    rc, out = run([sys.executable, str(CLI), "swap-plan"],
                  env={**os.environ, "PATH": "/nonexistent"})
    check("swap-plan runs with PATH=/nonexistent (runs no external command)",
          rc == 0 and "S5 on n01" in out, f"rc={rc}")

    # ── verify (local CLI against the CURRENT repo state — no network) ──────
    real_exists = (REPO / "_beacon_ca" / "real" / "beacon_cert_real.json").is_file()
    rc, out = run([sys.executable, str(CLI), "verify"])
    if real_exists:
        check("verify (local) rc=0 when a real cert is staged and valid",
              rc == 0 and "every checked witness agrees" in out,
              out.strip().splitlines()[-1])
    else:
        check("verify (local) rc=1 + VERIFY_FAIL while no real cert is staged",
              rc == 1 and "VERIFY_FAIL" in out and "issued_real.cert" in out,
              out.strip().splitlines()[-1])
    check("verify (local) skips remote witnesses",
          "not checked (no --remote)" in out, "remote skipped — no network in tests")

    # ── hygiene ─────────────────────────────────────────────────────────────
    r = subprocess.run(["git", "check-ignore", "-q", "_beacon_ca/real/beacon_cert_real.json"],
                       cwd=str(REPO))
    check("_beacon_ca/real/ output is gitignored", r.returncode == 0,
          "git check-ignore _beacon_ca/real/beacon_cert_real.json")
    repo_real_end = repo_real.read_bytes() if repo_real.is_file() else None
    check("tests never materialize _beacon_ca/real/ in the repo",
          repo_real_end == repo_real_before,
          "beacon_cert_real.json byte-identical to the start of the run")

    for p in tmp_path.iterdir():
        try:
            p.unlink()
        except OSError:
            pass
    try:
        tmp_path.rmdir()
    except OSError:
        pass

    print("=" * 60)
    if _failures:
        print(f"FAILED           ({_failures} check(s))")
        return 1
    print("ALL TESTS PASSED          (exit=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
