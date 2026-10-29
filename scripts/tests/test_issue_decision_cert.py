#!/usr/bin/env python3
# design: docs/design/sources/driver-topology-v1/driver_topology.vsm
"""test_issue_decision_cert.py — ceremony tooling tests (no secrets touched).
design: docs/design/sources/driver-topology-v1/driver_topology.vsm

Covers, WITHOUT any production key material:
  - plan() is read-only and always rc 0 (reports readiness, changes nothing)
  - verify() on an empty staging dir fails loud (rc 1, nothing to verify)
  - issue --test-ca --generate end to end with a FAKE tty stdin: writes
    cert+pub, self-verifies, negative control passes; artifacts stay inside
    the temp out dir (never the repo _decision_ca/, never committed)
  - issue refuses non-tty stdin (passphrase must never come from a pipe)

The PROD path (real root + real passphrase) is exercised ONLY by rmw3 in a
live terminal — by design it cannot run here. Test mode uses the throwaway
test CA exclusively.
"""
import json
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_GOV = os.path.normpath(os.path.join(_HERE, "..", "s5-governance"))
for _p in (_GOV,
           os.path.normpath(os.path.join(_HERE, "..", "algedonic")),
           os.path.normpath(os.path.join(_HERE, "..", "state", "governance"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import issue_decision_cert as idc


def _ns(**kw):
    args = types.SimpleNamespace(out_dir=None, test_ca=False,
                                 generate=False, pubkey_hex=None,
                                 node_id="s5-operational")
    for k, v in kw.items():
        setattr(args, k, v)
    return args


class _FakeTty:
    def isatty(self):
        return True


def test_plan_is_readonly_and_zero(tmp_path):
    rc = idc.phase_plan(_ns(out_dir=str(tmp_path)))
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_verify_empty_dir_fails_loud(tmp_path, capsys):
    rc = idc.phase_verify(_ns(out_dir=str(tmp_path), test_ca=True))
    assert rc == 1
    assert "no staged cert" in capsys.readouterr().out


def test_issue_refuses_non_tty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", open(os.devnull))
    rc = idc.phase_issue(_ns(out_dir=str(tmp_path), test_ca=True,
                             generate=True))
    assert rc == 1
    assert "interactive-only" in capsys.readouterr().err


def test_issue_test_ca_full_loop(tmp_path, monkeypatch):
    out = os.path.join(str(tmp_path), "staging")
    monkeypatch.setattr(sys, "stdin", _FakeTty())
    rc = idc.phase_issue(_ns(out_dir=out, test_ca=True, generate=True))
    assert rc == 0
    cert_path = os.path.join(out, "s5-operational.cert.json")
    pub_path = os.path.join(out, "ca.pubkey.hex")
    key_path = os.path.join(out, "s5-operational.key")
    assert os.path.isfile(cert_path) and os.path.isfile(pub_path)
    assert oct(os.stat(key_path).st_mode & 0o777) == "0o600"
    cert = json.load(open(cert_path))
    assert cert["node_id"] == "s5-operational"
    assert len(cert["sig_hex"]) == 128
    assert idc.phase_verify(_ns(out_dir=out, test_ca=True)) == 0


def test_prod_paths_untouched_by_test_mode(tmp_path, monkeypatch):
    out = os.path.join(str(tmp_path), "staging")
    monkeypatch.setattr(sys, "stdin", _FakeTty())
    idc.phase_issue(_ns(out_dir=out, test_ca=True, generate=True))
    assert os.path.isfile(os.path.join(out, "s5-operational.cert.json"))
