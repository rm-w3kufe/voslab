#!/usr/bin/env python3
"""regime_digest.py — Session health snapshot for the observability regime.

Reads ONLY local state (never mutates): tests are NOT run here (BOOT runs
gates); this digests recorded evidence so S5 sees the regime at a glance.

Usage:
  regime_digest.py            # human-readable digest to stdout
  regime_digest.py --json     # machine-readable JSON to stdout

Sections: gates (last harness state), queue (L4 depth), quarantine,
manifest drift, log error rate (24h), focus (active items).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]


def _quarantine() -> dict:
    qdir = VOSLAB / "state" / "rsi"
    q = VOSLAB / "state" / "quarantine"
    files = sorted(p.name for p in q.glob("*.vsm")) if q.exists() else []
    return {"quarantined_files": files, "count": len(files)}


def _queue() -> dict:
    try:
        sys.path.insert(0, str(VOSLAB / ".opencode" / "plugins" / "operational"))
        return {"note": "query via bridge: rsi-queue"}
    finally:
        pass


def _manifest() -> dict:
    man = VOSLAB / "state" / "doc_manifest.jsonl"
    if not man.exists():
        return {"tracked": 0, "status": "no manifest (run doc_manifest.py scan)"}
    n = sum(1 for _ in open(man))
    return {"tracked": n, "manifest": "state/doc_manifest.jsonl"}


def _log_health() -> dict:
    log = VOSLAB / "logs" / "agent_plugin.jsonl"
    if not log.exists():
        return {"total": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    total = err = block = 0
    for line in open(log, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        total += 1
        if e.get("ts", "") < cutoff:
            continue
        if e.get("result") in ("error", "fail"):
            err += 1
        a = str(e.get("action", ""))
        if "BLOCKED" in a or "quarantine" in a:
            block += 1
    return {"entries_total": total, "errors_24h": err,
            "blocks_quarantines_24h": block}


def _focus() -> dict:
    fp = VOSLAB / "current_focus.json"
    try:
        data = json.loads(fp.read_text())
    except Exception:
        return {"active": []}
    return {"active": [e.get("ref") for e in data
                       if e.get("status") == "active"]}


def _anomalies() -> dict:
    """Review surface s3 (volume/trend/distribution): deterministic rules.

    Compares last 24h vs previous 24h. Flags (never acts):
      error_spike: errors_24h >= 3x previous window (min 10 baseline)
      block_spike: blocks >= 3x previous window (min 3 baseline)
      new_source: source unseen in previous 7 days
    Thresholds documented here (S5-tunable, change with reason).
    """
    log = VOSLAB / "logs" / "agent_plugin.jsonl"
    now = datetime.now(timezone.utc)
    w1 = now - timedelta(hours=24)
    w0 = now - timedelta(hours=48)
    e1 = e0 = b1 = b0 = 0
    seen_old, seen_new = set(), set()
    if log.exists():
        for line in open(log, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            try:
                ts = datetime.fromisoformat(str(e.get("ts", "")))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            bad = e.get("result") in ("error", "fail")
            blk = "BLOCKED" in str(e.get("action", "")) or \
                "quarantine" in str(e.get("action", ""))
            src = str(e.get("source", "?"))
            if ts >= w1:
                e1 += bad
                b1 += blk
                seen_new.add(src)
            elif ts >= w0:
                e0 += bad
                b0 += blk
                seen_old.add(src)
            elif now - ts < timedelta(days=7):
                seen_old.add(src)
    flags = []
    if e1 >= max(3 * e0, 10) and e1 > e0:
        flags.append(f"error_spike:{e0}-> {e1}")
    if b1 >= max(3 * b0, 3) and b1 > b0:
        flags.append(f"block_spike:{b0}-> {b1}")
    for s in sorted(seen_new - seen_old):
        flags.append(f"new_source:{s}")
    return {"error_24h": e1, "error_prev_24h": e0,
            "blocks_24h": b1, "blocks_prev_24h": b0,
            "flags": flags}


def _autonomy() -> dict:
    """Autonomy score: machine-resolved evaluations vs human governance.

    auto = rsi-cycle evaluations (no human in the loop);
    intervened = governance decision entries + enforced blocks.
    Ratio only — direction of quality comes from Omega, not here.
    """
    log = VOSLAB / "logs" / "agent_plugin.jsonl"
    auto = human = 0
    if log.exists():
        for line in open(log, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            src = str(e.get("source", ""))
            act = str(e.get("action", ""))
            lvl = str(e.get("level", ""))
            if src == "rsi-cycle" and "evaluate" in str(e.get("event_type", "")):
                auto += 1
            elif lvl == "decision" or "BLOCKED" in act or "quarantine" in act:
                human += 1
    total = auto + human
    return {"auto": auto, "intervened": human,
            "autonomy_ratio": round(auto / total, 4) if total else 1.0}


def digest() -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "quarantine": _quarantine(),
        "manifest": _manifest(),
        "log": _log_health(),
        "anomalies": _anomalies(),
        "autonomy": _autonomy(),
        "focus": _focus(),
        "note": "run rsi-queue + gates for full depth (see BOOT)",
    }


def main(argv: list[str]) -> int:
    d = digest()
    if "--json" in argv:
        print(json.dumps(d, indent=2))
        return 0
    print(f"regime digest @ {d['ts']}")
    print(f"  quarantine: {d['quarantine']['count']} files "
          f"{d['quarantine']['quarantined_files']}")
    print(f"  manifest: {d['manifest']}")
    print(f"  log: {d['log']}")
    print(f"  anomalies: {d['anomalies']['flags'] or 'none'}")
    print(f"  autonomy: {d['autonomy']}")
    print(f"  focus active: {d['focus']['active'] or 'none'}")
    print(f"  note: {d['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
