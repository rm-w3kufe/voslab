#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm
"""test_g1_algedonic_paths.py — G1: safety-channel publishes really deliver.
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Covers the exact bug class G1 closes (C1 lesson): anonymous CONNECT +
bare subject + swallowed errors delivered nowhere while logs claimed
success. A stub NATS broker (loopback, OS-assigned port — deterministic,
no random, no wall-clock assertions) proves:
  1. categorized subject delivery with full payload (vsf.<id>.algedonic.<cat>)
  2. auth refusal surfaces loud (False + stderr), never silent
  3. refused connection surfaces loud (False + stderr), never silent
  4. the subject is never bare (regression guard for the bug class)
  5. the token is actually sent on the wire (auth is real, not decorative)
  6. kpi/spotcheck sources contain no anonymous CONNECT and route via the
     canonical helper (pattern guards — the old shape must not return)
  7. severity/category misuse fails in tests (ValueError), not in silence

Deterministic (R10): no random anywhere; stub port OS-assigned.
"""
import json
import os
import socket
import sys
import threading

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.normpath(os.path.join(_HERE, "..", "..", "shared"))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import vsf_algedonic_pub as pub


class StubBroker(threading.Thread):
    """Minimal NATS-ish stub: INFO, capture CONNECT/PUB, reply ok or -ERR."""

    def __init__(self, mode="ok"):
        super().__init__(daemon=True)
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.sock.settimeout(10)
        self.connect_line = b""
        self.subjects = []
        self.payloads = []

    def run(self):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(10)
            data = b""
            conn.sendall(b"INFO {}\r\n")
            while b"PING" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            lines = data.split(b"\r\n")
            for i, ln in enumerate(lines):
                if ln.startswith(b"CONNECT"):
                    self.connect_line = ln
                if ln.startswith(b"PUB"):
                    parts = ln.split(b" ")
                    self.subjects.append(parts[1].decode() if len(parts) > 1 else "")
                    if i + 1 < len(lines):
                        try:
                            self.payloads.append(json.loads(lines[i + 1].decode()))
                        except (ValueError, IndexError):
                            pass
            if self.mode == "err":
                conn.sendall(b"-ERR 'Authorization Violation'\r\n")
            else:
                conn.sendall(b"+OK\r\nPONG\r\n")
            conn.close()
        except Exception:
            pass
        finally:
            self.sock.close()


@pytest.fixture()
def broker_ok():
    b = StubBroker(mode="ok")
    b.start()
    yield b
    b.join(timeout=10)


@pytest.fixture()
def broker_err():
    b = StubBroker(mode="err")
    b.start()
    yield b
    b.join(timeout=10)


def _closed_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_publish_delivers_categorized(broker_ok, capsys):
    ok = pub.publish(category="out_of_norm", severity=6,
                     source_id="test-src", detail="stasis low (tick=1)",
                     token="tok", host="127.0.0.1", port=broker_ok.port)
    assert ok is True
    assert broker_ok.subjects == ["vsf.alpha.algedonic.out_of_norm"]
    assert len(broker_ok.payloads) == 1
    p = broker_ok.payloads[0]
    assert p["source_id"] == "test-src"
    assert p["category"] == "out_of_norm"
    assert p["severity"] == 6.0
    assert "ts" in p and p["ts"].endswith("Z")


@pytest.mark.parametrize("cat", ["stall", "spotcheck_violation",
                                 "refresh_probe_failure"])
def test_subject_never_bare(cat):
    b = StubBroker()
    b.start()
    assert pub.publish(category=cat, severity=5, source_id="t",
                       detail="d", token="tok",
                       host="127.0.0.1", port=b.port) is True
    b.join(timeout=10)
    base = "vsf.alpha.algedonic"
    assert b.subjects == [base + "." + cat]


def test_token_sent_on_wire(broker_ok):
    pub.publish(category="stall", severity=7, source_id="t", detail="d",
                token="secret-tok", host="127.0.0.1", port=broker_ok.port)
    assert b"secret-tok" in broker_ok.connect_line


def test_auth_refused_loud(broker_err, capsys):
    ok = pub.publish(category="out_of_norm", severity=6, source_id="t",
                     detail="d", token="bad-tok",
                     host="127.0.0.1", port=broker_err.port)
    assert ok is False
    assert capsys.readouterr().err != ""


def test_conn_refused_loud(capsys):
    ok = pub.publish(category="stall", severity=7, source_id="t",
                     detail="d", token="tok",
                     host="127.0.0.1", port=_closed_port())
    assert ok is False
    assert capsys.readouterr().err != ""


def test_no_token_refuses_anonymous_loud(capsys, monkeypatch):
    monkeypatch.delenv("NATS_TOKEN", raising=False)
    ok = pub.publish(category="stall", severity=7, source_id="t",
                     detail="d", token=None,
                     host="127.0.0.1", port=_closed_port())
    assert ok is False
    err = capsys.readouterr().err
    assert "anonymous" in err.lower()


def test_severity_range_guarded():
    with pytest.raises(ValueError):
        pub.publish(category="stall", severity=99, source_id="t",
                    detail="d", token="x", host="127.0.0.1", port=1)
    with pytest.raises(ValueError):
        pub.publish(category="", severity=5, source_id="t",
                    detail="d", token="x", host="127.0.0.1", port=1)
    with pytest.raises(ValueError):
        pub.publish(category="two words", severity=5, source_id="t",
                    detail="d", token="x", host="127.0.0.1", port=1)


def _read_source(relpath):
    with open(os.path.join(_HERE, "..", "..", relpath), encoding="utf-8") as fh:
        return fh.read()


def test_kpi_no_anonymous_bare():
    src = _read_source("s3-allocation/s3star_kpi.py")
    assert "CONNECT {}" not in src
    assert "vsf_algedonic_pub" in src
    assert "_ALGED_SUBJ" not in src


def test_spotcheck_no_anonymous_bare():
    src = _read_source("state/monitoring/s3star_spotcheck.py")
    assert "CONNECT {}" not in src
    assert "vsf_algedonic_pub" in src


def test_helper_has_no_random():
    import vsf_algedonic_pub as _m
    src = open(_m.__file__, encoding="utf-8").read()
    assert "import random" not in src


_WSROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))


def _read_repo(relpath):
    with open(os.path.join(_WSROOT, relpath), encoding="utf-8") as fh:
        return fh.read()


def test_watchdog_no_bare_subject_both_copies():
    for rel in ("scripts/state/services/service_watchdog.py",
                "packages/framework/vsf-state/vsf_state/service_watchdog.py"):
        src = _read_repo(rel)
        assert "PUB {_ALGED_SUBJ} " not in src
        assert ".{category}" in src


def test_algedonic_pub_token_and_category():
    src = _read_repo("scripts/state/algedonic/algedonic_pub.py")
    assert "NATS_TOKEN" in src
    assert "design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm" in src
    assert "anonymous" in src
    assert "SUBJECT_BASE" in src
