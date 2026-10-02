"""C3 revocation proof — S5 CA trust set under CRL (debt D-06 FASE C).

Covers:
  - two issued certs are trusted while valid
  - revoking ONE cert rejects exactly that key (the other stays trusted)
  - an expired cert is rejected outside its validity window
  - a foreign-root CRL is ignored (FORGERY note, key stays trusted)
  - CRL signature verifies against the issuing root only

Fast scrypt (n=2**14) — test-only, mirrors s5_ca._selftest.
"""
import pytest

from vsf_state import s5_ca

PW = "correct horse battery staple"
N_FAST = 2 ** 14


@pytest.fixture
def root():
    """Mint a fresh root; returns (seed32, pub_doc) via the public API."""
    enc, pub_doc = s5_ca.make_root(PW, n=N_FAST)
    seed = s5_ca.decrypt_seed(enc, PW)
    return seed, pub_doc


def _component_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    sk = Ed25519PrivateKey.generate()
    return sk, s5_ca._pub_raw(sk)


def test_two_certs_trusted_while_valid(root):
    seed, pub_doc = root
    _, pub_a = _component_key()
    _, pub_b = _component_key()
    cert_a = s5_ca.issue_cert(seed, pub_a.hex(), "role-a", ["scope.x"])
    cert_b = s5_ca.issue_cert(seed, pub_b.hex(), "role-b", ["scope.y"])
    trusted, notes = s5_ca.build_trust(pub_doc, [cert_a, cert_b])
    assert cert_a["key_id"] in trusted
    assert cert_b["key_id"] in trusted
    assert trusted[cert_a["key_id"]] == pub_a
    assert not [n for n in notes if n[0] == "REJECT"]


def test_revocation_rejects_only_the_revoked_key(root):
    seed, pub_doc = root
    _, pub_a = _component_key()
    _, pub_b = _component_key()
    cert_a = s5_ca.issue_cert(seed, pub_a.hex(), "role-a", ["scope.x"])
    cert_b = s5_ca.issue_cert(seed, pub_b.hex(), "role-b", ["scope.y"])

    crl = s5_ca.make_or_update_crl(seed, None, cert_a["key_id"],
                                   "host suspected compromised", next_days=7)
    root_pub = bytes.fromhex(pub_doc["root_pub"])
    assert s5_ca.verify_crl(crl, root_pub)
    assert crl["root_id"] == pub_doc["root_id"]

    trusted, notes = s5_ca.build_trust(pub_doc, [cert_a, cert_b], crl)
    assert cert_a["key_id"] not in trusted
    assert cert_b["key_id"] in trusted  # revocation is exact, not blanket
    assert any(n[0] == "REJECT" and "REVOKED" in n[1] for n in notes)

    # without the CRL the same cert would still be trusted (it is in-date)
    trusted_no_crl, _ = s5_ca.build_trust(pub_doc, [cert_a])
    assert cert_a["key_id"] in trusted_no_crl


def test_expired_cert_rejected(root):
    seed, pub_doc = root
    _, pub_a = _component_key()
    expired = s5_ca.issue_cert(seed, pub_a.hex(), "role-a", ["scope.x"],
                               days=-1)
    trusted, notes = s5_ca.build_trust(pub_doc, [expired])
    assert expired["key_id"] not in trusted
    assert any(n[0] == "REJECT" and "validity" in n[1] for n in notes)


def test_foreign_root_crl_ignored(root):
    seed, pub_doc = root
    _, pub_a = _component_key()
    cert_a = s5_ca.issue_cert(seed, pub_a.hex(), "role-a", ["scope.x"])

    other_enc, _other_doc = s5_ca.make_root(PW, n=N_FAST)
    other_seed = s5_ca.decrypt_seed(other_enc, PW)
    forged_crl = s5_ca.make_or_update_crl(other_seed, None,
                                          cert_a["key_id"], "fake", 7)

    trusted, notes = s5_ca.build_trust(pub_doc, [cert_a], forged_crl)
    assert cert_a["key_id"] in trusted  # forged CRL has no effect
    assert any(n[0] == "FORGERY" for n in notes)
    # and the forged CRL does not verify against OUR root
    assert not s5_ca.verify_crl(forged_crl,
                                bytes.fromhex(pub_doc["root_pub"]))


def test_revoked_key_stays_rejected_after_reissue_of_valid_certs(root):
    """A CRL survives individual cert churn: revoke once, later certs
    for OTHER keys are unaffected while the revoked key_id stays out."""
    seed, pub_doc = root
    _, pub_a = _component_key()
    _, pub_c = _component_key()
    cert_a = s5_ca.issue_cert(seed, pub_a.hex(), "role-a", ["scope.x"])
    crl = s5_ca.make_or_update_crl(seed, None, cert_a["key_id"], "gone")
    cert_c = s5_ca.issue_cert(seed, pub_c.hex(), "role-c", ["scope.z"])
    trusted, _ = s5_ca.build_trust(pub_doc, [cert_a, cert_c], crl)
    assert cert_a["key_id"] not in trusted
    assert cert_c["key_id"] in trusted
    # re-signing the CRL (idempotent update) keeps the revocation
    crl2 = s5_ca.make_or_update_crl(seed, crl, cert_a["key_id"], "gone")
    assert sum(r["key_id"] == cert_a["key_id"]
               for r in crl2["revoked"]) == 1
    trusted2, _ = s5_ca.build_trust(pub_doc, [cert_a, cert_c], crl2)
    assert cert_a["key_id"] not in trusted2
