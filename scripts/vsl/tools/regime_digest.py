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


def digest() -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "quarantine": _quarantine(),
        "manifest": _manifest(),
        "log": _log_health(),
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
    print(f"  focus active: {d['focus']['active'] or 'none'}")
    print(f"  note: {d['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
