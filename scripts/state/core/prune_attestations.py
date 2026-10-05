#!/usr/bin/env python3
"""prune_attestations.py — D-14 retention for state/rsi/attestations (R17-safe).

Backlog D-14: the attestation store grows ~1000 files/day (94M block-bound
on 23k small files) with NO declared prune/rotate/retention. Consumers:
  alerting.py      reads the newest 20 files only
  feedback_loop    reads ALL files (23k JSON loads + sig verifies per report)
  audit_pipeline   WRITES new attestations (signer, never deletes)

Design (decision S5 pending on the window; the mechanism is window-agnostic):
  * deterministic selection (R10): filename epoch `trace-<ms>-<pid>.…`
    cross-checked against the file's own `ts` field — disagreement beyond
    tolerance SKIPS the file (never delete on bad data)
  * default = DRY-RUN: prints the candidate set, touches NOTHING
    (--apply required to delete)
  * --keep-days N: files strictly older than N days are candidates
  * --keep-newest K (default 100): the newest K files are NEVER candidates
    (floor > alerting window of 20; protects against clock weirdness)
  * deletes ONLY regular `*.attest.json` files directly in the target dir —
    no symlinks, no subdirs, no other names, no recursion
  * every run emits a JSON report on stdout (count/bytes/kept/skipped)

Self-test (`--self-test`): fixture dir with old/new/mismatch files proves
dry-run removes nothing, --apply removes exactly the old ones, the newest-K
floor holds, and a ts-mismatch file is skipped.

Exit codes: 0 success (dry-run or apply), 1 structural/self-test failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ATTEST_DIR = ROOT / "state" / "rsi" / "attestations"
NAME_RE = re.compile(r"^trace-(\d{13})-\d+\.attest\.json$")
TS_TOLERANCE_S = 86400  # filename epoch vs ts field: >24h apart = suspect


def _candidate(path: Path, now_ms: int, keep_days: int, floor_names: set[str]
               ) -> tuple[bool, str]:
    """(is_candidate, reason). Deterministic; skips anything suspect."""
    if path.name in floor_names:
        return False, "floor-newest"
    if not path.is_file() or path.is_symlink():
        return False, "not-regular-file"
    m = NAME_RE.match(path.name)
    if not m:
        return False, "name-not-parseable"
    epoch_ms = int(m.group(1))
    age_s = (now_ms - epoch_ms) / 1000.0
    if age_s <= keep_days * 86400:
        return False, "within-window"
    # cross-check the attestation's own ts against the filename epoch
    try:
        data = json.loads(path.read_text())
        ts = datetime.fromisoformat(str(data.get("ts", "")).replace("Z", "+00:00"))
        ts_delta = abs(ts.timestamp() - epoch_ms / 1000.0)
        if ts_delta > TS_TOLERANCE_S:
            return False, f"ts-mismatch({int(ts_delta)}s)"
    except (OSError, ValueError, json.JSONDecodeError):
        return False, "unreadable"          # corrupt != deletable
    return True, "older-than-window"


def run(dir_path: Path, keep_days: int, keep_newest: int, apply: bool,
        now_ms: int | None = None) -> dict:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if not dir_path.is_dir():
        return {"ok": True, "dir": str(dir_path), "exists": False,
                "candidates": 0, "deleted": 0, "note": "dir absent — nothing to do"}
    files = sorted(dir_path.glob("*.attest.json"))
    # newest-K floor by filename epoch (deterministic)
    def epoch_of(p: Path) -> int:
        m = NAME_RE.match(p.name)
        return int(m.group(1)) if m else -1
    floor_names = {p.name for p in sorted(files, key=epoch_of, reverse=True)
                   [:keep_newest]}
    cands, kept, skipped = [], 0, {}
    for p in files:
        yes, why = _candidate(p, now_ms, keep_days, floor_names)
        if yes:
            cands.append(p)
        else:
            kept += 1
            skipped[why] = skipped.get(why, 0) + 1
    bytes_ = 0
    deleted = 0
    errors = []
    for p in cands:
        try:
            bytes_ += p.stat().st_size
            if apply:
                p.unlink()
                deleted += 1
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    return {
        "ok": not errors,
        "dir": str(dir_path),
        "exists": True,
        "mode": "apply" if apply else "dry-run",
        "keep_days": keep_days,
        "keep_newest": keep_newest,
        "total_files": len(files),
        "candidates": len(cands),
        "deleted": deleted,
        "candidate_bytes": bytes_,
        "kept": kept,
        "kept_reasons": skipped,
        "errors": errors,
        "now": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def self_test() -> int:
    """Fixture discrimination: dry-run touches nothing, apply == exact set."""
    import tempfile
    old_ms = int(time.time() * 1000) - 10 * 86400000   # 10 days old
    new_ms = int(time.time() * 1000) - 3600000          # 1 hour old
    fail = 0

    def mk(d: Path, name: str, ts: str) -> None:
        (d / name).write_text(json.dumps({"trace_id": name, "ts": ts}))

    def iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) \
                       .strftime("%Y-%m-%dT%H:%M:%SZ")

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        mk(d, f"trace-{old_ms}-1.attest.json", iso(old_ms))          # old  -> DEL
        mk(d, f"trace-{new_ms}-2.attest.json", iso(new_ms))          # new  -> KEEP
        mk(d, f"trace-{old_ms}-3.attest.json", iso(new_ms))          # ts-mismatch -> SKIP
        mk(d, "not-an-attestation.json", iso(old_ms))                # wrong name (not globbed)
        # 6 more old files (epochs old_ms+i) -> all candidates
        for i in range(4, 10):
            mk(d, f"trace-{old_ms + i}-9.attest.json", iso(old_ms + i))
        # globbed = 9 (A,B,C + 6 loop); candidates = A + 6 loop = 7

        r = run(d, keep_days=7, keep_newest=0, apply=False)
        if r["mode"] != "dry-run" or r["deleted"] != 0:
            print(f"SELFTEST FAIL: dry-run must not delete ({r})"); fail = 1
        if r["candidates"] != 7:
            print(f"SELFTEST FAIL: candidates={r['candidates']} want 7 ({r})"); fail = 1
        if len(list(d.glob("*.attest.json"))) != 9:
            print("SELFTEST FAIL: dry-run removed files"); fail = 1

        # floor: newest 2 by epoch (new file + highest old) never candidates
        r = run(d, keep_days=7, keep_newest=2, apply=False)
        if r["candidates"] != 6 or r["kept_reasons"].get("floor-newest", 0) != 2:
            print(f"SELFTEST FAIL: floor wrong ({r})"); fail = 1

        # determinism (R10): identical inputs -> identical output
        fixed_now = old_ms + 8 * 86400000          # old files are 8d old
        r1 = run(d, keep_days=7, keep_newest=0, apply=False, now_ms=fixed_now)
        r2 = run(d, keep_days=7, keep_newest=0, apply=False, now_ms=fixed_now)
        if r1 != r2 or r1["candidates"] != 7:
            print(f"SELFTEST FAIL: non-deterministic or wrong count ({r1})"); fail = 1

        # apply: exactly the 7 old files go, everything else stays
        r = run(d, keep_days=7, keep_newest=0, apply=True)
        if r["deleted"] != 7:
            print(f"SELFTEST FAIL: deleted={r['deleted']} want 7 ({r})"); fail = 1
        remaining = sorted(p.name for p in d.glob("*.attest.json"))
        want = {f"trace-{new_ms}-2.attest.json",
                f"trace-{old_ms}-3.attest.json"}
        if set(remaining) != want:
            print(f"SELFTEST FAIL: remaining={remaining} want {want}"); fail = 1
        if not (d / "not-an-attestation.json").exists():
            print("SELFTEST FAIL: non-matching filename was deleted"); fail = 1

    print("SELFTEST: PASS" if fail == 0 else "SELFTEST: FAIL")
    return fail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-days", type=int, default=None,
                    help="files older than N days are prune candidates")
    ap.add_argument("--keep-newest", type=int, default=100,
                    help="newest K files are never candidates (floor)")
    ap.add_argument("--dir", default=str(ATTEST_DIR))
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry-run report)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.keep_days is None or args.keep_days <= 0:
        print("error: --keep-days N (N>0) is required — refusing to guess "
              "the retention window (D-14 is an S5 decision)", file=sys.stderr)
        return 1

    report = run(Path(args.dir), args.keep_days, args.keep_newest, args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
