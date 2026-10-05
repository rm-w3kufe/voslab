"""shadow_cycle — CC-8.1 runner: candidates -> shadow ledger.

First candidate source: epistemic audit findings (every finding carries a
`fix` + its guard). The cycle does NOT apply anything — it appends the
would-be action + bounds-check (guard liveness) to shadow.jsonl.

Usage (workspace root):
    python3 scripts/epistemic/shadow_cycle.py            # record new candidates
    python3 scripts/epistemic/shadow_cycle.py --check    # analyze only

Dedup: one shadow entry per finding id (SHD-<finding-id>) — re-runs are
idempotent. Divergence review happens in the evolution report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/framework/vos_kernel"))

import shadow  # noqa: E402

FINDINGS = ROOT / "state/epistemic/findings.jsonl"


def _candidates() -> list[dict]:
    if not FINDINGS.exists():
        return []
    out = []
    for line in FINDINGS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("fix"):
            out.append(entry)
    return out


def run() -> int:
    existing = {e.get("id") for e in shadow.load()}
    recorded = skipped = 0
    for finding in _candidates():
        entry_id = f"SHD-{finding.get('id', '?')}"
        if entry_id in existing:
            skipped += 1
            continue
        guard = finding.get("guard", "?")
        status = finding.get("guard_status", "unknown")
        live = status == "live"
        shadow.record(
            source="audit-findings",
            action={"fix": finding["fix"],
                    "finding": finding.get("id"),
                    "src": finding.get("src")},
            bounds={"pass": live,
                    "reasons": [f"guard={guard}", f"guard_status={status}"]},
            blocked_by=[] if live else [guard],
            target=None,  # src is a reference (FIXES.md#F01), not a repo path
            entry_id=entry_id,
        )
        recorded += 1
    print(f"shadow-cycle: recorded={recorded} skipped={skipped} "
          f"candidates={recorded + skipped}")
    return 0


def check() -> int:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    report = shadow.analyze(cutoff, repo_root=ROOT)
    print(f"shadow-check: total={report['total']} new(7d)={report['new_count']} "
          f"blocked={report['blocked_count']} "
          f"divergences={len(report['divergences'])} "
          f"explained={report.get('divergences_explained', 0)} "
          f"unexplained={report.get('divergences_unexplained', 0)}")
    for div in report["divergences"]:
        print(f"  divergence: {div['id']} {div['kind']} target={div['target']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="analyze the ledger instead of recording")
    args = parser.parse_args()
    return check() if args.check else run()


if __name__ == "__main__":
    sys.exit(main())
