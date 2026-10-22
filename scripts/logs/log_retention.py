#!/usr/bin/env python3
"""log_retention.py — archive old rotated log spans (P-EV-R10 / F11).

Ratified cutoff 30d (S5 rmw3, 2026-10-22): rotated agent_plugin gz spans
older than CUTOFF_DAYS move to logs/archive/ (MOVE, never rm — R17-safe:
the operation is reversible). Deterministic (R10): same disk state → same
decision set.

Why: query_sessions fingerprints ALL gz spans in logs/; the cold scan
(cost ~8s/250 spans) grows with span count. Archiving old spans bounds it
by the retention window. Semantics note: query_sessions only sees spans
in logs/ — archived spans leave the session index by design (30d window).

Usage:
  python3 scripts/logs/log_retention.py            # dry-run (list)
  python3 scripts/logs/log_retention.py --apply    # move old spans
  python3 scripts/logs/log_retention.py --selftest # harness in tmp env

Exit codes: 0 ok (no-op counts as ok), 1 simulated/real failure.
"""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

VOSLAB = Path(os.environ.get("VOSLAB_PATH", Path(__file__).resolve().parents[3]))
CUTOFF_DAYS = 30.0


def _voslab() -> Path:
    """Resolve per call (module-level VOSLAB stayed frozen at import —
    the selftest env switch had no effect; fixed 2026-10-22)."""
    return Path(os.environ.get("VOSLAB_PATH", str(VOSLAB)))


def candidates() -> list[Path]:
    """Deterministic: gz spans in logs/ older than cutoff, sorted."""
    log_dir = _voslab() / "logs"
    if not log_dir.exists():
        return []
    cutoff = time.time() - CUTOFF_DAYS * 86400
    out = []
    for f in sorted(log_dir.iterdir()):
        if not (f.name.startswith("agent_plugin") and f.name.endswith(".gz")):
            continue
        if f.stat().st_mtime < cutoff:
            out.append(f)
    return out


def apply() -> list[str]:
    archive_dir = _voslab() / "logs" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for src in candidates():
        dst = archive_dir / src.name
        if dst.exists():  # already archived (re-run) → skip, never overwrite
            continue
        shutil.move(str(src), str(dst))  # move, never rm (R17-safe)
        moved.append(dst.name)
    return moved


def state_write(moved: list[str]) -> None:
    state_file = _voslab() / "state" / "logs_retention.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cutoff_days": CUTOFF_DAYS,
        "moved": moved,
    }, indent=2))


def selftest() -> int:
    """Harness in a tmp VOSLAB env — never touches the real logs/ state."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        env = {"VOSLAB_PATH": td}
        old_env = os.environ.get("VOSLAB_PATH")
        os.environ.update(env)
        try:
            logd = Path(td) / "logs"
            logd.mkdir()
            now = time.time()
            old = now - (CUTOFF_DAYS + 1) * 86400
            new = now - 3600
            p_old, p_new = logd / "agent_plugin.jsonl.a.jsonl.gz", logd / "agent_plugin.jsonl.b.jsonl.gz"
            p_old.write_bytes(b"old"); os.utime(p_old, (old, old))
            p_new.write_bytes(b"new"); os.utime(p_new, (new, new))
            p_unknown = logd / "other.span.jsonl.gz"  # not agent_plugin → no touch
            p_unknown.write_bytes(b"x"); os.utime(p_unknown, (old, old))
            sys = __import__("sys")
            mod = sys.modules[__name__]
            moved = mod.apply()
            assert moved == ["agent_plugin.jsonl.a.jsonl.gz"], moved
            assert not p_old.exists()
            assert (logd / "archive" / "agent_plugin.jsonl.a.jsonl.gz").exists()
            assert p_new.exists(), "new span must NOT move"
            assert p_unknown.exists(), "non-agent_plugin spans must NOT move"
            # re-run idempotency: no candidates left
            assert mod.apply() == []
        finally:
            if old_env is None:
                os.environ.pop("VOSLAB_PATH", None)
            else:
                os.environ["VOSLAB_PATH"] = old_env
    print("selftest PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    cand = candidates()
    if not args.apply:
        print(f"Dry-run: {len(cand)} spans >{CUTOFF_DAYS:.0f}d:")
        for f in cand:
            print(f"  WOULD MOVE: {f.name}")
        print(f"archive dir: {_voslab() / 'logs' / 'archive'}")
        return 0
    moved = apply()
    state_write(moved)
    print(f"APPLIED: moved {len(moved)} spans → logs/archive/")
    for f in moved:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
