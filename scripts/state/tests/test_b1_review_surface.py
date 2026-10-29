#!/usr/bin/env python3
# design: docs/design/sources/driver-topology-v1/driver_topology.vsm
"""test_b1_review_surface.py — B1/A rescue: review surface over durable log.
design: docs/design/sources/driver-topology-v1/driver_topology.vsm

Covers the §12 review contract (volume/trend/distribution/anomalies):
  - volume counts + resource moved; malformed lines tolerated, counted
  - trend rising/falling/stable from day halves
  - chronic prop: >=N grants 0 restores flags; restores clear it
  - standing escalations surface; test-escalation rows labeled, not counted
  - empty log: silent nominal, exit 0
Deterministic (R10): fixed timestamps relative to now, no random.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_MON = os.path.normpath(os.path.join(_HERE, "..", "monitoring"))
if _MON not in sys.path:
    sys.path.insert(0, _MON)

import s3_review_surface as rs


def _ts(days_ago=0, hours_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(days=days_ago, hours=hours_ago)).isoformat()


def _grant(vmid="112", **kw):
    e = {"event_type": "s3_resource_grant", "audit_source": "s3_resource_alloc",
         "audit_chain": "s3star", "action": "EXECUTE", "role": "s1-clima",
         "escalated": False, "vmid": vmid, "grant_cores": 1,
         "grant_mem_mb": 128, "ts": _ts()}
    e.update(kw)
    return e


def _write(path, events, raw_lines=()):
    with open(path, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        for ln in raw_lines:
            fh.write(ln + "\n")


def test_volume_and_malformed(tmp_path):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    _write(p, [_grant(), _grant(vmid="113"),
               {"event_type": "s3_pool_red_algedonic",
                "audit_source": "x", "role": "s1-clima", "action": "HOLD",
                "escalated": False, "ts": _ts()}],
            raw_lines=["not json {{", ""])
    events, malformed = rs.load_events(p)
    assert malformed == 1
    rep = rs.analyze(events, malformed, 7, 5)
    assert rep["volume"]["by_type"]["s3_resource_grant"] == 2
    assert rep["volume"]["cores_granted"] == 2
    assert rep["volume"]["mem_mb_granted"] == 256


def test_trend_rising_and_falling(tmp_path):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    rising = [_grant(ts=_ts(days_ago=d)) for d in (6, 5, 1, 0, 0, 0)]
    _write(p, rising)
    events, mal = rs.load_events(p)
    assert rs.analyze(events, mal, 7, 99)["trend"]["direction"] == "rising"
    p2 = os.path.join(str(tmp_path), "audit2.jsonl")
    falling = [_grant(ts=_ts(days_ago=d)) for d in (6, 6, 6, 6, 1, 0)]
    _write(p2, falling)
    events2, mal2 = rs.load_events(p2)
    assert rs.analyze(events2, mal2, 7, 99)["trend"]["direction"] == "falling"


def test_chronic_needs_grants_without_restore(tmp_path):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    evs = [_grant(vmid="112") for _ in range(5)]
    evs.append({"event_type": "s3_resource_restore", "audit_source": "x",
                "role": "s1-clima", "action": "RESTORE", "escalated": False,
                "vmid": "113", "ts": _ts()})
    evs.extend([_grant(vmid="113") for _ in range(6)])
    _write(p, evs)
    events, mal = rs.load_events(p)
    rep = rs.analyze(events, mal, 7, 5)
    targets = {r["target"]: r for r in rep["anomalies"]["chronically_propped"]}
    assert set(targets) == {"112"}
    assert targets["112"]["grants"] == 5


def test_escalations_surface_and_test_rows_labeled(tmp_path):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    _write(p, [
        {"event_type": "s3_pool_red_algedonic", "audit_source": "x",
         "role": "s1-clima", "action": "HOLD", "escalated": True,
         "reason": "RED zone", "vmid": "112", "ts": _ts()},
        {"event_type": "supervision_decision", "escalation_id": "test-x",
         "action": "DECISION_APPROVE", "ts": _ts()},
    ])
    events, mal = rs.load_events(p)
    rep = rs.analyze(events, mal, 7, 99)
    assert len(rep["anomalies"]["standing_escalations"]) == 1
    assert rep["test_rows_labeled"] == 1
    assert "supervision_decision" not in rep["volume"]["by_type"]


def test_empty_log_nominal(tmp_path):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    _write(p, [])
    events, mal = rs.load_events(p)
    rep = rs.analyze(events, mal, 7, 5)
    assert rep["events_in_window"] == 0
    assert rep["anomalies"] == {"chronically_propped": [],
                                "standing_escalations": []}
    assert rs.render(rep).startswith("S3* supervision review")


def test_main_exit_codes_and_json(tmp_path, capsys):
    p = os.path.join(str(tmp_path), "audit.jsonl")
    _write(p, [_grant()])
    assert rs.main(["--file", p, "--days", "7"]) == 0
    _write(p, [_grant() for _ in range(6)])
    assert rs.main(["--file", p, "--days", "7"]) == 1
    capsys.readouterr()
    assert rs.main(["--file", p, "--days", "7", "--json"]) == 1
    out = capsys.readouterr().out
    assert json.loads(out)["anomalies"]["chronically_propped"][0]["target"] == "112"


def test_design_header_present():
    with open(os.path.join(_MON, "s3_review_surface.py"),
              encoding="utf-8") as fh:
        head = "".join(fh.readlines()[:40])
    assert "design: docs/design/sources/driver-topology-v1/driver_topology.vsm" in head
