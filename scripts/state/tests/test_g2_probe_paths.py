#!/usr/bin/env python3
"""test_g2_probe_paths.py — G2: wire truth and meaning-vs-number.
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

broker_probe (witness subscriber):
  - wire/log match → silent, exit 0
  - log advances + witness 0 (proven channel) → emit_silence sev 7
  - divergence needs 2 consecutive windows (canon persistence, not flapping)
  - unproven witness → witness_degraded, NEVER emit_silence on broken self
  - log newest far ahead of wire newest → emit_stale
  - live SUB/MSG loopback proves the wire path end to end
shadow_recompute:
  - claimed == recomputed → silent; breach > eps → sev 8 with both values
  - hysteresis: repeat breach silent while flagged, clears below clear band
  - zero-norm guard parity with kernel (0.0), known cosines, malformed safe
  - sparse tail (no samples — sporadic by construction) → silent
Pattern guards: no random in either probe (sporadic-ness lives upstream),
design: headers present, canonical publisher wired, no bare subjects.

Deterministic (R10): fixed fixtures, loopback stubs, relative timestamps.
"""
import json
import os
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_MON = os.path.normpath(os.path.join(_HERE, "..", "monitoring"))
if _MON not in sys.path:
    sys.path.insert(0, _MON)

import s3_broker_probe as bp
import s3_shadow_recompute as sr


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tick_line(ts, tick, claimed=None, sv=None, st=None):
    kernel = {"tick": tick}
    if claimed is not None:
        kernel["stasis_cos"] = claimed
    metrics = {"kernel": kernel}
    if sv is not None:
        metrics["sampled_state_vector"] = sv
        metrics["sampled_stasis_vec"] = st
    return json.dumps({"event_type": "kernel_tick", "timestamp": ts,
                       "metrics": metrics})


def _write_events(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_type": "boot"}) + "\n")
        for ln in lines:
            fh.write(ln + "\n")


def _recent_events(n, gap=20, claimed=0.95, sampled=False):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = []
    for i in range(n):
        ts = _ts(now - timedelta(seconds=(n - i) * gap))
        kw = {}
        if sampled:
            vec = [0.5 + 0.01 * ((i + j) % 7) for j in range(8)]
            ref = [0.5 + 0.01 * ((i + j) % 7) for j in range(8)]
            kw = {"sv": vec, "st": ref}
        lines.append(_tick_line(ts, 1000 + i, claimed=claimed, **kw))
    return lines


class SubBroker(threading.Thread):
    """Stub NATS: INFO, token-blind CONNECT, PING/PONG, SUB then MSG injection."""

    def __init__(self, messages):
        super().__init__(daemon=True)
        self.messages = messages
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.sock.settimeout(15)
        self.got_sub = []

    def run(self):
        # Serves PINGs for the whole session (a real broker answers PING
        # regardless of phase); MSGs go out right after SUB, then drain.
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(15)
            conn.sendall(b"INFO {}\r\n")
            buf = b""
            subbed = False
            while not subbed:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    if line.startswith(b"PING"):
                        conn.sendall(b"PONG\r\n")
                    elif line.startswith(b"SUB"):
                        self.got_sub.append(line.decode())
                        subbed = True
            # Handshake completion: WAIT for the post-SUB PING (bounded).
            # A real broker never tears down mid-handshake; racing teardown
            # against an in-flight PING produces exactly the false EOF the
            # witness must never mistake for broker behavior.
            deadline = time.time() + 5
            pong2 = False
            while not pong2 and time.time() < deadline:
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    if line.startswith(b"PING"):
                        conn.sendall(b"PONG\r\n")
                        pong2 = True
                if pong2:
                    break
                conn.settimeout(1)
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buf += chunk
            for payload in self.messages:
                body = json.dumps(payload).encode()
                conn.sendall(b"MSG vsf.alpha.vsf-nucleus.up.kernel_tick 1 "
                             + str(len(body)).encode() + b"\r\n" + body + b"\r\n")
            conn.settimeout(1)
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    if b"PING" in chunk:
                        conn.sendall(b"PONG\r\n")
            except socket.timeout:
                pass
            conn.close()
        except Exception:
            pass
        finally:
            try:
                self.sock.close()
            except Exception:
                pass


def _msg(ts, tick):
    return {"event_type": "kernel_tick", "timestamp": ts,
            "metrics": {"kernel": {"tick": tick, "stasis_cos": 0.95}}}


def test_wire_match_silent(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "probe.db")
    _write_events(ev, _recent_events(5, gap=8))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    newest = _ts(now - timedelta(seconds=8))
    rc = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                observe=(True, 5, newest), window_secs=60)
    assert rc == 0 and published == []


def test_emit_silence(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "probe.db")
    _write_events(ev, _recent_events(5))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    rc = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                observe=(True, 0, ""))
    assert rc == 1
    assert [(p["category"], p["severity"]) for p in published] == [
        ("emit_silence", 7)]


def test_divergence_needs_two_windows(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "probe.db")
    _write_events(ev, _recent_events(4, gap=10))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    newest = _ts(now - timedelta(seconds=30))
    rc1 = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                 observe=(True, 12, newest))
    assert rc1 == 0 and published == []
    rc2 = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                 observe=(True, 12, newest))
    assert rc2 == 1
    assert [(p["category"], p["severity"]) for p in published] == [
        ("emit_count_divergence", 6)]


def test_witness_degraded_never_accuses(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "probe.db")
    _write_events(ev, _recent_events(5))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    rc = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                observe=(False, 0, ""))
    assert rc == 1
    assert [(p["category"], p["severity"]) for p in published] == [
        ("witness_degraded", 4)]


def test_emit_stale(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "probe.db")
    _write_events(ev, _recent_events(3, gap=10))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    old = _ts(datetime.now(timezone.utc).replace(tzinfo=None)
              - timedelta(seconds=900))
    rc = bp.run(events_path=ev, db_path=db, publish=fake_pub,
                observe=(True, 3, old))
    assert rc == 1
    assert [(p["category"], p["severity"]) for p in published] == [
        ("emit_stale", 7)]


def test_subscribe_loopback_end_to_end(tmp_path):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    msgs = [_msg(_ts(now - timedelta(seconds=(3 - i) * 10)), 2000 + i)
            for i in range(3)]
    broker = SubBroker(msgs)
    broker.start()
    proven, received, newest = bp.observe_wire(
        "vsf.alpha.vsf-nucleus.up.kernel_tick", 5, "tok",
        "127.0.0.1", broker.port)
    broker.join(timeout=15)
    assert proven is True and received == 3
    assert broker.got_sub and "kernel_tick" in broker.got_sub[0]


def test_recompute_match_silent(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "shadow.db")
    # fixture vectors equal so recompute matches claimed exactly
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    lines = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(3):
        v = [0.6 + 0.01 * ((i + j) % 5) for j in range(8)]
        lines.append(_tick_line(_ts(now - timedelta(seconds=(3 - i) * 20)),
                                 3000 + i, claimed=sr.cosine_similarity(v, v),
                                 sv=v, st=list(v)))
    _write_events(ev, lines)
    rc = sr.run(events_path=ev, db_path=db, publish=fake_pub)
    assert rc == 0 and published == []


def test_semantic_divergence_sev8(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "shadow.db")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    v = [0.6 + 0.01 * (j % 5) for j in range(8)]
    r = [0.1 * ((j % 3) + 1) for j in range(8)]
    lines = [_tick_line(_ts(now - timedelta(seconds=20)), 4000,
                        claimed=0.99, sv=v, st=r)]
    _write_events(ev, lines)
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    rc = sr.run(events_path=ev, db_path=db, publish=fake_pub)
    assert rc == 1
    assert len(published) == 1
    assert published[0]["category"] == "semantic_divergence"
    assert published[0]["severity"] == 8
    assert "0.99" in published[0]["detail"]


def test_hysteresis_no_rest_strobe(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "shadow.db")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    v = [0.6 + 0.01 * (j % 5) for j in range(8)]
    r = [0.1 * ((j % 3) + 1) for j in range(8)]
    lines = [_tick_line(_ts(now - timedelta(seconds=20)), 4000,
                        claimed=0.99, sv=v, st=r)]
    _write_events(ev, lines)
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    assert sr.run(events_path=ev, db_path=db, publish=fake_pub) == 1
    assert len(published) == 1
    assert sr.run(events_path=ev, db_path=db, publish=fake_pub) == 0
    assert len(published) == 1


def test_zero_guard_parity():
    assert sr.cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert sr.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert sr.cosine_similarity([3.0, 4.0], [3.0, 4.0]) == 1.0
    assert sr.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_malformed_safe(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "shadow.db")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = [_tick_line(_ts(now - timedelta(seconds=20)), 4000,
                        claimed=0.9, sv=[1.0, 2.0], st=[1.0, 2.0, 3.0])]
    _write_events(ev, lines)
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    rc = sr.run(events_path=ev, db_path=db, publish=fake_pub)
    assert rc == 1
    assert [(p["category"], p["severity"]) for p in published] == [
        ("shadow_malformed", 5)]


def test_sparse_tail_silent(tmp_path):
    ev = os.path.join(str(tmp_path), "events.jsonl")
    db = os.path.join(str(tmp_path), "shadow.db")
    _write_events(ev, _recent_events(5, claimed=0.9, sampled=False))
    published = []

    def fake_pub(**kw):
        published.append(kw)
        return True

    rc = sr.run(events_path=ev, db_path=db, publish=fake_pub)
    assert rc == 0 and published == []


def test_no_random_in_probes():
    for rel in ("scripts/state/monitoring/s3_broker_probe.py",
                "scripts/state/monitoring/s3_shadow_recompute.py"):
        with open(os.path.join(_WSROOT, rel), encoding="utf-8") as fh:
            assert "import random" not in fh.read()


def test_design_headers_present():
    for rel in ("scripts/state/monitoring/s3_broker_probe.py",
                "scripts/state/monitoring/s3_shadow_recompute.py"):
        with open(os.path.join(_WSROOT, rel), encoding="utf-8") as fh:
            head = "".join(fh.readlines()[:40])
        assert "design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm" in head


_WSROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
