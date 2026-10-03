"""evolution_report.py — CC-8.0 evolution presentation (A-3, ratificado S5).

Answers, from ONE regenerated artifact, S5's entry question:
"what changed since X, when, why, with evidence".

Deltas across (plan deliverable): ledgers, commits, snapshots, focus,
drift. Sources are read-only; output is deterministic given the same
inputs (R10) — only `generated_at` moves with the clock.

Usage (workspace root):
    python3 -m vos_kernel.evolution_report                 # since last report (or 24h)
    python3 -m vos_kernel.evolution_report --since 2026-09-30T00:00:00Z
    python3 -m vos_kernel.evolution_report --stdout        # do not write files

Writes (state/epistemic/reports/, same pattern as real_state_battery_*):
    evolution_<YYYY-MM-DD>.json   per-day artifact (regenerated in place)
    evolution_latest.json         baseline for the next run's delta
    EVOLUTION.md                  single S5-facing view

CC-8.0 exit criteria tracked in the plan — this module provides the
generator; the "3 consecutive days" criterion is observed over time.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[3]  # <vOSlab>/packages/framework/vos_kernel/ -> <vOSlab>
REPORTS_DIR = WORKSPACE / "state" / "epistemic" / "reports"
EPISTEMIC_DIR = WORKSPACE / "state" / "epistemic"
SNAPSHOTS_DIR = WORKSPACE / "state" / "rsi" / "snapshots"
FOCUS_PATH = WORKSPACE / "current_focus.json"

#: ledger name -> timestamp field used for --since filtering
LEDGERS: dict[str, str] = {
    "decisions": "ts",
    "findings": "ts",
    "guards": "ts",
    "claims": "declared_at",
    "certs": "observed_at",
}


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (Z or offset) -> aware UTC, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _since_cutoff(since: str | None) -> datetime:
    if since:
        dt = _parse_ts(since)
        if dt is None:
            raise ValueError(f"--since no es ISO-8601: {since!r}")
        return dt
    # default: previous report's generated_at, else 24h ago
    latest = REPORTS_DIR / "evolution_latest.json"
    if latest.exists():
        try:
            prev = json.loads(latest.read_text(encoding="utf-8"))
            dt = _parse_ts(prev.get("generated_at"))
            if dt is not None:
                return dt
        except (OSError, ValueError):
            pass
    return datetime.now(timezone.utc) - timedelta(hours=24)


def collect_git(workspace: Path, cutoff: datetime) -> dict[str, Any]:
    """Commits since cutoff: {commits: [{sha, subject, date}], error?}."""
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(workspace), "log",
                f"--since={cutoff.strftime('%Y-%m-%dT%H:%M:%S')}",
                "--pretty=%h|%ad|%s", "--date=iso-strict", "-n", "200",
            ],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commits": [], "error": f"git log failed: {exc}"}
    if proc.returncode != 0:
        return {"commits": [], "error": (proc.stderr or "git log rc!=0").strip()}
    commits = []
    for line in proc.stdout.splitlines():
        if "|" not in line:
            continue
        sha, date, subject = line.split("|", 2)
        commits.append({"sha": sha, "date": date, "subject": subject})
    return {"commits": commits}


def collect_ledger(name: str, ts_field: str, cutoff: datetime) -> dict[str, Any]:
    """Ledger delta: totals + entries with ts >= cutoff + no_ts count."""
    path = EPISTEMIC_DIR / f"{name}.jsonl"
    if not path.exists():
        return {"total": 0, "new_count": 0, "new": [], "no_ts": 0,
                "error": "missing ledger"}
    total = no_ts = 0
    new: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            no_ts += 1
            continue
        total += 1
        ts = _parse_ts(entry.get(ts_field))
        if ts is None:
            no_ts += 1
        elif ts >= cutoff:
            new.append(entry)
    return {
        "total": total,
        "new_count": len(new),
        "new": new,
        "no_ts": no_ts,
        "ts_field": ts_field,
    }


def collect_focus(cutoff: datetime) -> dict[str, Any]:
    if not FOCUS_PATH.exists():
        return {"entries": 0, "active": [], "changed_since": [], "error": "missing"}
    try:
        data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"entries": 0, "active": [], "changed_since": [], "error": str(exc)}
    active, changed = [], []
    for entry in data if isinstance(data, list) else []:
        ref = entry.get("ref", "?")
        if entry.get("status") == "active":
            active.append(ref)
        ts = _parse_ts(entry.get("updated_at"))
        if ts is not None and ts >= cutoff:
            changed.append({"ref": ref, "status": entry.get("status"),
                            "updated_at": entry.get("updated_at")})
    return {"entries": len(data) if isinstance(data, list) else 0,
            "active": sorted(active), "changed_since": changed}


def collect_snapshots(cutoff: datetime) -> dict[str, Any]:
    """Daily runtime snapshots: index rows + dated dirs since cutoff."""
    out: dict[str, Any] = {"index_new": [], "days": [], "error": None}
    if not SNAPSHOTS_DIR.exists():
        out["error"] = "missing snapshots dir"
        return out
    index = SNAPSHOTS_DIR / "index.jsonl"
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            ts = _parse_ts(row.get("ts"))
            if ts is not None and ts >= cutoff:
                out["index_new"].append(row)
    for child in sorted(SNAPSHOTS_DIR.iterdir()):
        if child.is_dir() and child.name >= cutoff.strftime("%Y-%m-%d"):
            out["days"].append(child.name)
    return out


def collect_battery() -> dict[str, Any]:
    """Latest anti-pantomima battery verdict (real_state_battery_*.json)."""
    reports = sorted(EPISTEMIC_DIR.glob("reports/real_state_battery_*.json"))
    if not reports:
        return {"error": "no battery reports"}
    try:
        latest = json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}
    return {
        "file": reports[-1].name,
        "id": latest.get("id"),
        "verdict": latest.get("verdict"),
        "checks": len(latest.get("checks", [])),
        "not_verified": latest.get("not_verified", []),
    }


def collect_journal() -> dict[str, Any]:
    """state_journal rows + latest drift count (drift lens)."""
    db = WORKSPACE / "state_journal.db"
    if not db.exists():
        return {"rows": 0, "error": "missing state_journal.db"}
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "select count(*), coalesce(max(drift_count),0) from state_journal"
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — report honest failure, don't crash
        return {"rows": 0, "error": str(exc)}
    return {"rows": rows[0], "latest_drift_count": rows[1]}


def _fingerprint(report: dict[str, Any]) -> str:
    """Stable content hash (generated_at excluded) — R10."""
    import hashlib
    stable = {k: v for k, v in report.items() if k not in ("generated_at", "delta_vs_previous")}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def delta_vs_previous(report: dict[str, Any]) -> dict[str, Any] | None:
    """Compare against the previous evolution_latest.json, if any."""
    latest = REPORTS_DIR / "evolution_latest.json"
    if not latest.exists():
        return None
    try:
        prev = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    prev_refs = set(prev.get("focus", {}).get("active", []))
    cur_refs = set(report.get("focus", {}).get("active", []))
    return {
        "previous_generated_at": prev.get("generated_at"),
        "previous_fingerprint": prev.get("fingerprint"),
        "focus_refs_added": sorted(cur_refs - prev_refs),
        "focus_refs_removed": sorted(prev_refs - cur_refs),
        "ledger_total_delta": {
            name: report.get("ledgers", {}).get(name, {}).get("total", 0)
            - prev.get("ledgers", {}).get(name, {}).get("total", 0)
            for name in LEDGERS
        },
        "git_commits_since_previous": len(report.get("git", {}).get("commits", [])),
    }


def collect_shadow(cutoff: datetime) -> dict[str, Any]:
    """CC-8.1 counterfactual shadow: would-be actions + divergence review."""
    try:
        try:
            from . import shadow  # package mode (vos_kernel.evolution_report)
        except ImportError:
            import shadow  # noqa: N813 — sibling module (script/sys.path mode)
        return shadow.analyze(cutoff, repo_root=WORKSPACE)
    except Exception as exc:  # noqa: BLE001 — report honest failure, don't crash
        return {"total": 0, "new_count": 0, "new": [], "blocked_count": 0,
                "blocked_ids": [], "divergences": [], "aligned_count": 0,
                "untracked_targets": 0, "error": str(exc)}


def collect(since: str | None = None, workspace: Path | None = None) -> dict[str, Any]:
    """Gather every section. Deterministic for a fixed `since` + inputs (R10)."""
    ws = Path(workspace) if workspace else WORKSPACE
    cutoff = _since_cutoff(since)
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "id": f"EVOLUTION-{now.strftime('%Y-%m-%d')}",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": collect_git(ws, cutoff),
        "ledgers": {
            name: collect_ledger(name, field, cutoff)
            for name, field in LEDGERS.items()
        },
        "focus": collect_focus(cutoff),
        "snapshots": collect_snapshots(cutoff),
        "battery": collect_battery(),
        "journal": collect_journal(),
        "shadow": collect_shadow(cutoff),
    }
    report["fingerprint"] = _fingerprint(report)
    report["delta_vs_previous"] = delta_vs_previous(report)
    return report


def render_md(report: dict[str, Any]) -> str:
    """Single S5-facing view of one report."""
    lines = [
        f"# Evolution report — {report['id']}",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- since: `{report['since']}`",
        f"- fingerprint: `{report['fingerprint']}`",
        "",
        "## Commits since",
    ]
    commits = report["git"].get("commits", [])
    if report["git"].get("error"):
        lines.append(f"- ERROR: {report['git']['error']}")
    elif not commits:
        lines.append("- (none)")
    for c in commits:
        lines.append(f"- `{c['sha']}` {c['date']} — {c['subject']}")

    lines += ["", "## Ledgers"]
    for name, led in report["ledgers"].items():
        if led.get("error"):
            lines.append(f"- **{name}**: ERROR {led['error']}")
            continue
        lines.append(
            f"- **{name}**: total={led['total']} new={led['new_count']} "
            f"no_ts={led['no_ts']} (ts={led.get('ts_field')})"
        )
        for entry in led["new"][:10]:
            label = entry.get("id") or entry.get("question") or entry.get("claim_id") or "?"
            lines.append(f"  - new: `{label}`")

    focus = report["focus"]
    lines += ["", "## Focus", f"- entries: {focus.get('entries')}"]
    lines.append(f"- active: {', '.join(focus.get('active', [])) or '(none)'}")
    for ch in focus.get("changed_since", []):
        lines.append(f"- changed: `{ch['ref']}` -> {ch['status']} @ {ch['updated_at']}")

    snap = report["snapshots"]
    lines += ["", "## Snapshots"]
    if snap.get("error"):
        lines.append(f"- ERROR: {snap['error']}")
    lines.append(f"- days: {', '.join(snap.get('days', [])) or '(none)'}")
    lines.append(f"- index rows since: {len(snap.get('index_new', []))}")

    bat = report["battery"]
    lines += ["", "## Battery (anti-pantomima)"]
    if bat.get("error"):
        lines.append(f"- ERROR: {bat['error']}")
    else:
        lines.append(f"- latest: `{bat['file']}` — {bat['verdict']}")
        for gap in bat.get("not_verified", []):
            lines.append(f"- declared gap: {gap}")

    j = report["journal"]
    lines += ["", "## Drift",
              f"- journal rows: {j.get('rows')}"
              + (f", latest_drift_count={j['latest_drift_count']}"
                 if "latest_drift_count" in j else ""),
              ]
    if j.get("error"):
        lines.append(f"- ERROR: {j['error']}")

    sh = report.get("shadow", {})
    lines += ["", "## Shadow (CC-8.1) — would-be, never executed"]
    if sh.get("error"):
        lines.append(f"- ERROR: {sh['error']}")
    else:
        lines.append(f"- entries: total={sh.get('total', 0)} "
                     f"new={sh.get('new_count', 0)} "
                     f"blocked-by-bounds={sh.get('blocked_count', 0)} "
                     f"aligned={sh.get('aligned_count', 0)}")
        for entry in sh.get("new", [])[:10]:
            state = "BLOCKED" if not entry.get("bounds", {}).get("pass", True) \
                else "would-run"
            lines.append(f"- new: `{entry.get('id')}` [{state}] "
                         f"src={entry.get('source')} "
                         f"action={str(entry.get('action'))[:80]}")
        divs = sh.get("divergences", [])
        if divs:
            for div in divs:
                lines.append(f"- DIVERGENCE: `{div['id']}` {div['kind']} "
                             f"target={div['target']}")
        else:
            lines.append("- divergences: (none in window)")
        if sh.get("blocked_ids"):
            lines.append(f"- guard-would-have-blocked: "
                         f"{', '.join(sh['blocked_ids'])}")

    delta = report.get("delta_vs_previous")
    lines += ["", "## Delta vs previous report"]
    if delta is None:
        lines.append("- (no previous report — first run)")
    else:
        lines.append(f"- previous: `{delta['previous_generated_at']}` "
                     f"(fp {delta['previous_fingerprint']})")
        lines.append(f"- focus refs added: {delta['focus_refs_added'] or '(none)'}")
        lines.append(f"- focus refs removed: {delta['focus_refs_removed'] or '(none)'}")
        lines.append(f"- ledger totals delta: {delta['ledger_total_delta']}")
        lines.append(f"- commits since previous: {delta['git_commits_since_previous']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CC-8.0 evolution report generator")
    parser.add_argument("--since", default=None,
                        help="ISO-8601 cutoff (default: previous report or 24h)")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--out-dir", default=None,
                        help="default: state/epistemic/reports")
    parser.add_argument("--stdout", action="store_true",
                        help="print markdown, write nothing")
    args = parser.parse_args(argv)

    ws = Path(args.workspace) if args.workspace else WORKSPACE
    try:
        report = collect(since=args.since, workspace=ws)
    except ValueError as exc:
        print(f"evolution-report: {exc}", file=sys.stderr)
        return 2
    md = render_md(report)
    if args.stdout:
        print(md)
        return 0

    out_dir = Path(args.out_dir) if args.out_dir else ws / "state" / "epistemic" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (out_dir / f"evolution_{day}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "evolution_latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "EVOLUTION.md").write_text(md, encoding="utf-8")
    print(f"evolution-report: wrote {out_dir}/evolution_{day}.json, "
          f"evolution_latest.json, EVOLUTION.md "
          f"(commits={len(report['git'].get('commits', []))}, "
          f"fingerprint={report['fingerprint']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
