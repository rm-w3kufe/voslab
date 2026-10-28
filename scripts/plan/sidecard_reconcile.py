#!/usr/bin/env python3
# design: docs/spec_revision/sandbox/matter-ontology-v1/matter_ontology.vsm
"""sidecard_reconcile.py — reconcile paper sidecards with their claims ledger.

The cycle already has:
  sidecard --(analytic-on-read)--> .claims.vsm --(epistemic_graph)--> graph
  MATTERS.vsm --evidence--> sidecard path

What is missing is the join/coverage check between those pieces. This
instrument is read-only by default. It reuses the existing truth stores:
  * claim_ingest.ids.source_id_for  -> freshness identity
  * vos_kernel.epistemic.load_sidecar -> canonical ledger parser
  * analytic_engine.analyze(persist=True) -> backfill (same path as the
    analytic-on-read hook)
  * matter_path.parse_abox -> MATTERS.vsm evidence refs

Modes:
  report    inventory + coverage + freshness + duplicates + refs (default)
  backfill  create/refresh missing or stale ledgers for real sidecards
  check     exit 1 on missing/stale/empty real sidecard, or broken evidence
            refs; --strict also fails on duplicate-case/version drift.
  ingest    create/refresh the ledger for one sidecard (on-write hook)

No new ontology. No new truth store. Sidecards remain SIDE-v1/AUDIT-v1;
claims remain CLAIMS-v1 in state/epistemic/sidecars/.

Usage:
  python3 scripts/plan/sidecard_reconcile.py report [--json]
  python3 scripts/plan/sidecard_reconcile.py backfill [--dry-run]
  python3 scripts/plan/sidecard_reconcile.py check [--strict]
  python3 scripts/plan/sidecard_reconcile.py ingest <sidecard.vsm>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIDECARDS = (
    ROOT / "docs" / "papers" / "attractor_convergence" / "sidecards"
)
DEFAULT_CLAIMS = ROOT / "state" / "epistemic" / "sidecars"
DEFAULT_MATTERS = ROOT / "MATTERS.vsm"
DEFAULT_FIXTURES = frozenset({"test_write.vsm"})

# ── imports from the existing instrument set ────────────────────────────────
# Keep these lazy-ish: report only needs the pure identity/parser helpers;
# backfill imports analytic_engine (which imports claim_ingest).
for _p in (ROOT / "packages" / "framework", ROOT / "packages" / "public"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from claim_ingest.ids import source_id_for  # noqa: E402
from vos_kernel.epistemic import load_sidecar  # noqa: E402


HEADER_RE = re.compile(
    r"^\s*⟦\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*vsm-([^|]+?)\s*\|\s*([^⟧]+?)\s*⟧"
)
STATUS_RE = re.compile(r"^\s*@status\s+([a-z_]+)", re.M)
SUPERSEDES_RE = re.compile(
    r"^\s*supersedes\s*[:=]\s*[\"']([^\"']+)[\"']", re.M
)
VERSION_RE = re.compile(r"^(.*)_v(\d+)$", re.I)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _header(text: str) -> tuple[str | None, str | None]:
    first = text.splitlines()[0] if text else ""
    m = HEADER_RE.match(first)
    if not m:
        return None, None
    return m.group(2).strip(), m.group(1).strip()


def _status(text: str) -> str | None:
    m = STATUS_RE.search(text)
    return m.group(1) if m else None


def _is_sidecard_type(typ: str | None) -> bool:
    return bool(typ) and (typ.startswith("SIDE-") or typ.startswith("AUDIT-"))


def _claims_path(claims_dir: Path, stem: str) -> Path:
    """Exact-case first; fall back to a case-insensitive match if unique."""
    exact = claims_dir / f"{stem}.claims.vsm"
    if exact.exists():
        return exact
    want = f"{stem}.claims.vsm".casefold()
    hits = sorted(
        p for p in claims_dir.glob("*.claims.vsm")
        if p.name.casefold() == want
    )
    return hits[0] if len(hits) == 1 else exact


def _load_ledger(path: Path) -> tuple[list[dict], str | None]:
    if not path.exists():
        return [], None
    try:
        claims = load_sidecar(path)
    except Exception as exc:  # tolerant: report, never crash the audit
        return [], f"{type(exc).__name__}: {exc}"
    if not isinstance(claims, list):
        return [], "ledger claims is not a list"
    return claims, None


def _matters_refs(path: Path) -> tuple[dict[str, list[str]], list[str], str | None]:
    """Return ({relpath: [matter ids]}, all sidecard refs, error)."""
    if not path.exists():
        return {}, [], f"MATTERS not found: {_rel(path)}"
    try:
        import matter_path as mp
        matters = mp.parse_abox(str(path))
    except Exception as exc:
        return {}, [], f"MATTERS parse failed: {type(exc).__name__}: {exc}"

    by_path: dict[str, list[str]] = {}
    all_refs: list[str] = []
    for mid, rec in sorted(matters.items()):
        for ev in rec.get("evidence") or []:
            if not isinstance(ev, str) or "/sidecards/" not in ev:
                continue
            all_refs.append(ev)
            by_path.setdefault(ev, []).append(mid)
    return by_path, sorted(set(all_refs)), None


def _inventory(
    sidecards_dir: Path,
    claims_dir: Path,
    matters_path: Path,
    fixtures: frozenset[str],
) -> tuple[list[dict], dict]:
    refs_by_path, matters_refs, matters_err = _matters_refs(matters_path)
    files = sorted(
        (p for p in sidecards_dir.glob("*.vsm") if p.is_file()),
        key=lambda p: p.name.casefold(),
    )
    items: list[dict] = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        typ, header_name = _header(text)
        status = _status(text)
        rel = _rel(p)
        fixture = p.name in fixtures
        if not _is_sidecard_type(typ):
            items.append({
                "name": p.name, "path": rel, "type": typ,
                "header_name": header_name, "status": status,
                "fixture": fixture, "coverage": "ignored",
                "ledger": None, "claims": 0, "fresh": None,
                "source_id": None, "ledger_source_id": None,
                "referenced_by": [], "flags": ["NOT_SIDECARD_TYPE"],
            })
            continue

        ledger = _claims_path(claims_dir, p.stem)
        claims, ledger_err = _load_ledger(ledger)
        current_sid = source_id_for(rel, text)
        ledger_sid = claims[0].get("source_id") if claims else None
        mixed_sid = any(
            c.get("source_id") != ledger_sid for c in claims
        ) if claims else False
        subjects = {
            str(c.get("subject")) for c in claims if c.get("subject")
        }
        subject_ok = (
            not subjects
            or any(s == rel or s.endswith("/" + rel) or s.endswith(rel) for s in subjects)
        )

        if ledger_err:
            coverage = "invalid"
        elif not ledger.exists():
            coverage = "missing"
        elif not claims:
            coverage = "empty"
        elif ledger_sid != current_sid or mixed_sid or not subject_ok:
            coverage = "stale"
        else:
            coverage = "covered"
        fresh = coverage == "covered"

        referenced_by: list[str] = []
        for ref, mids in refs_by_path.items():
            if ref == rel or ref.endswith("/" + rel) or ref == p.name:
                referenced_by.extend(mids)
        referenced_by = sorted(set(referenced_by))

        flags: list[str] = []
        if fixture:
            flags.append("FIXTURE")
        if status == "archived":
            flags.append("ARCHIVED")
        if ledger_err:
            flags.append("LEDGER_INVALID")
        if coverage == "stale":
            if ledger_sid != current_sid:
                flags.append("SOURCE_ID_MISMATCH")
            if mixed_sid:
                flags.append("MIXED_SOURCE_IDS")
            if not subject_ok:
                flags.append("SUBJECT_MISMATCH")
        if not referenced_by and not fixture and status != "archived":
            flags.append("ORPHAN")
        items.append({
            "name": p.name, "path": rel, "type": typ,
            "header_name": header_name, "status": status,
            "fixture": fixture, "coverage": coverage,
            "ledger": _rel(ledger) if ledger.exists() else None,
            "claims": len(claims), "fresh": fresh,
            "source_id": current_sid, "ledger_source_id": ledger_sid,
            "referenced_by": referenced_by,
            "supersedes": (
                SUPERSEDES_RE.search(text).group(1)
                if SUPERSEDES_RE.search(text) else None
            ),
            "flags": flags,
        })

    # Archived sidecards are historical: they still get coverage/freshness
    # accounting, but they do not create duplicate/version/orphan drift.
    active_items = [
        it for it in items
        if it["coverage"] != "ignored" and it["status"] != "archived"
    ]

    # case-insensitive duplicate groups (active only)
    groups: dict[str, list[str]] = {}
    for it in active_items:
        groups.setdefault(Path(it["name"]).stem.casefold(), []).append(it["name"])
    duplicate_groups = {
        k: sorted(v) for k, v in groups.items() if len(v) > 1
    }
    duplicate_names = {
        n for names in duplicate_groups.values() for n in names
    }

    # _vN version pairs (case-insensitive). A bare base name is v1 when
    # a sibling _vN exists (phase_a_llm_evaluation_progress + _v2).
    vgroups: dict[str, list[tuple[int, str]]] = {}
    by_stem = {
        Path(it["name"]).stem.casefold(): it
        for it in active_items
    }
    for it in active_items:
        stem = Path(it["name"]).stem
        m = VERSION_RE.match(stem)
        if m:
            vgroups.setdefault(m.group(1).casefold(), []).append(
                (int(m.group(2)), it["name"])
            )
    for base_cf, pairs in list(vgroups.items()):
        if any(v == 1 for v, _ in pairs):
            continue
        base_it = by_stem.get(base_cf)
        if base_it and not VERSION_RE.match(Path(base_it["name"]).stem):
            pairs.append((1, base_it["name"]))
    version_pairs = {
        k: sorted(v) for k, v in vgroups.items() if len(v) > 1
    }
    version_names = {
        n for pairs in version_pairs.values() for _, n in pairs
    }
    unlinked_versions: list[str] = []
    for pairs in version_pairs.values():
        # newest by numeric suffix; require it to declare supersedes
        newest = max(pairs, key=lambda x: x[0])[1]
        it = next(x for x in active_items if x["name"] == newest)
        if not it.get("supersedes"):
            unlinked_versions.append(newest)

    for it in items:
        if it["name"] in duplicate_names:
            it["flags"].append("DUPLICATE_CASE")
        if it["name"] in version_names:
            it["flags"].append("VERSION_PAIR")
        if it["name"] in unlinked_versions:
            it["flags"].append("VERSION_WITHOUT_SUPERSEDES")
        it["flags"] = sorted(set(it["flags"]))

    real = [it for it in items if not it["fixture"] and it["coverage"] != "ignored"]
    active_real = [it for it in real if it["status"] != "archived"]
    fixtures_items = [it for it in items if it["fixture"] and it["coverage"] != "ignored"]
    refs_missing = []
    for ref in matters_refs:
        if not (ROOT / ref).exists():
            refs_missing.append(ref)
    refs_covered = 0
    for ref in matters_refs:
        rel = ref[2:] if ref.startswith("./") else ref
        item = next((x for x in real if x["path"] == rel or x["name"] == Path(rel).name), None)
        if item and item["coverage"] == "covered":
            refs_covered += 1

    summary = {
        "sidecards_total": len(items),
        "sidecards_real": len(real),
        "fixtures": len(fixtures_items),
        "covered": sum(1 for x in real if x["coverage"] == "covered"),
        "stale": sum(1 for x in real if x["coverage"] == "stale"),
        "missing": sum(1 for x in real if x["coverage"] == "missing"),
        "empty": sum(1 for x in real if x["coverage"] == "empty"),
        "invalid": sum(1 for x in real if x["coverage"] == "invalid"),
        "ignored": sum(1 for x in items if x["coverage"] == "ignored"),
        "referenced_real": sum(1 for x in active_real if x["referenced_by"]),
        "orphans_real": sum(1 for x in active_real if not x["referenced_by"]),
        "archived_real": sum(1 for x in real if x["status"] == "archived"),
        "matters_sidecard_refs": len(matters_refs),
        "matters_sidecard_refs_covered": refs_covered,
        "matters_sidecard_refs_missing": len(refs_missing),
        "duplicates_case": len(duplicate_groups),
        "version_pairs": len(version_pairs),
        "unlinked_versions": len(unlinked_versions),
        "claims_total": sum(x["claims"] for x in real),
    }
    report = {
        "schema": "sidecard-reconcile-v1",
        "root": ".",
        "sidecards_dir": _rel(sidecards_dir),
        "claims_dir": _rel(claims_dir),
        "matters": _rel(matters_path),
        "summary": summary,
        "items": items,
        "duplicate_groups": duplicate_groups,
        "version_pairs": {
            k: [{"version": v, "name": n} for v, n in pairs]
            for k, pairs in version_pairs.items()
        },
        "unlinked_versions": unlinked_versions,
        "matters_refs": matters_refs,
        "matters_refs_missing": refs_missing,
        "matters_error": matters_err,
    }
    return items, report


def _print_human(report: dict) -> None:
    s = report["summary"]
    print("sidecard-reconcile report")
    print(f"root: {report['root']}")
    print(
        "sidecards: {sidecards_total} total | {sidecards_real} real | "
        "{fixtures} fixture(s)".format(**s)
    )
    print(
        "coverage: {covered} covered | {stale} stale | {missing} missing | "
        "{empty} empty | {invalid} invalid | {ignored} ignored | "
        "archived {archived_real}".format(**s)
    )
    print(
        "MATTERS sidecard refs: {matters_sidecard_refs} | covered "
        "{matters_sidecard_refs_covered} | missing file "
        "{matters_sidecard_refs_missing}".format(**s)
    )
    print(
        "real orphans: {orphans_real} | duplicate-case groups: "
        "{duplicates_case} | version pairs: {version_pairs} "
        "(unlinked: {unlinked_versions})".format(**s)
    )
    if report["matters_error"]:
        print(f"MATTERS: {report['matters_error']}")
    print()
    print(
        f"{'SIDECARD':44} {'TYPE':9} {'STATUS':8} {'CLAIMS':>6} "
        f"{'COVERAGE':9} {'FRESH':5} {'REFS':4} FLAGS"
    )
    for it in report["items"]:
        if it["coverage"] == "ignored":
            continue
        flags = ",".join(it["flags"]) or "-"
        print(
            f"{it['name'][:44]:44} {str(it['type'])[:9]:9} "
            f"{str(it['status'])[:8]:8} {it['claims']:6d} "
            f"{it['coverage']:9} {str(bool(it['fresh'])):5} "
            f"{len(it['referenced_by']):4} {flags}"
        )
    if report["duplicate_groups"]:
        print("\nduplicate-case groups:")
        for k, names in sorted(report["duplicate_groups"].items()):
            print(f"  {k}: {', '.join(names)}")
    if report["version_pairs"]:
        print("\nversion pairs:")
        for k, pairs in sorted(report["version_pairs"].items()):
            vals = ", ".join(f"v{p['version']}={p['name']}" for p in pairs)
            print(f"  {k}: {vals}")
    if report["matters_refs_missing"]:
        print("\nmissing MATTERS evidence files:")
        for ref in report["matters_refs_missing"]:
            print(f"  {ref}")


def _summary_line(report: dict) -> str:
    s = report["summary"]
    return (
        "sidecards={sidecards_real} covered={covered} stale={stale} "
        "missing={missing} empty={empty} orphans={orphans_real} "
        "archived={archived_real} refs={matters_sidecard_refs} "
        "refs_covered={matters_sidecard_refs_covered}".format(**s)
    )


def _backfill(report: dict, dry_run: bool) -> int:
    targets = [
        it for it in report["items"]
        if not it["fixture"] and it["coverage"] in ("missing", "stale", "empty")
    ]
    if not targets:
        print("sidecard-reconcile backfill: nothing to do")
        return 0
    if dry_run:
        print(f"sidecard-reconcile backfill: DRY-RUN ({len(targets)} target(s))")
        for it in targets:
            print(f"  would ingest {it['path']} ({it['coverage']})")
        return 0

    from analytic_engine import analyze

    failures = 0
    print(f"sidecard-reconcile backfill: {len(targets)} target(s)")
    for it in targets:
        try:
            result = analyze(
                str(ROOT / it["path"]),
                name=it["path"],
                subject=it["path"],
                level="L1",
                route=True,
                persist=True,
                register=False,
            )
            status = result.get("ledger_status") or "?"
            nclaims = len(result.get("claims") or [])
            print(
                f"  {it['name']}: {status} | claims={nclaims} | "
                f"source_id={result.get('source_id', '')}"
            )
            if status not in ("written", "unchanged"):
                failures += 1
        except Exception as exc:
            failures += 1
            print(f"  {it['name']}: ERROR {type(exc).__name__}: {exc}")
    return 1 if failures else 0


def _check(report: dict, strict: bool) -> int:
    errors: list[str] = []
    s = report["summary"]
    for it in report["items"]:
        if it["fixture"] or it["coverage"] == "ignored":
            continue
        if it["coverage"] in ("missing", "stale", "empty", "invalid"):
            errors.append(f"{it['path']}: {it['coverage']}")
    if report["matters_error"]:
        errors.append(report["matters_error"])
    for ref in report["matters_refs_missing"]:
        errors.append(f"MATTERS evidence missing: {ref}")
    if strict:
        for names in report["duplicate_groups"].values():
            errors.append(f"duplicate-case group: {', '.join(names)}")
        for newest in report["unlinked_versions"]:
            errors.append(f"version without supersedes: {newest}")
    if errors:
        print("sidecard-reconcile check: FAIL")
        for e in errors:
            print(f"  {e}")
        print(_summary_line(report))
        return 1
    print("sidecard-reconcile check: PASS")
    print(_summary_line(report))
    if s["orphans_real"]:
        print(
            f"  advisory: {s['orphans_real']} real sidecard(s) are not "
            "referenced by MATTERS"
        )
    if s["duplicates_case"] or s["unlinked_versions"]:
        print(
            "  advisory: duplicate-case/unlinked-version drift exists; "
            "use --strict to make it fatal"
        )
    return 0


def _ingest(path: Path) -> int:
    """Create/refresh one sidecard ledger, or skip a non-sidecard .vsm."""
    path = path.resolve()
    if not path.is_file():
        print(f"sidecard-reconcile ingest: not a file: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    typ, _ = _header(text)
    rel = _rel(path)
    if not _is_sidecard_type(typ):
        print(json.dumps({"path": rel, "skipped": True,
                          "reason": "not a SIDE/AUDIT sidecard"}))
        return 0
    try:
        from analytic_engine import analyze
        result = analyze(
            str(path),
            name=rel,
            subject=rel,
            level="L1",
            route=True,
            persist=True,
            register=False,
        )
    except Exception as exc:
        print(json.dumps({"path": rel, "error":
                          f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({
        "path": rel,
        "skipped": False,
        "ledger_status": result.get("ledger_status") or "",
        "claims": len(result.get("claims") or []),
        "source_id": result.get("source_id", ""),
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sidecard_reconcile.py")
    ap.add_argument("mode", choices=("report", "backfill", "check", "ingest"),
                    nargs="?", default="report")
    ap.add_argument("path", nargs="?",
                    help="ingest: sidecard path")
    ap.add_argument("--sidecards-dir", default=str(DEFAULT_SIDECARDS))
    ap.add_argument("--claims-dir", default=str(DEFAULT_CLAIMS))
    ap.add_argument("--matters", default=str(DEFAULT_MATTERS))
    ap.add_argument("--fixture", action="append", default=None,
                    help="fixture filename to exclude (repeatable; "
                         "default: test_write.vsm)")
    ap.add_argument("--json", action="store_true",
                    help="report/backfill: emit JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="backfill: show targets, write nothing")
    ap.add_argument("--strict", action="store_true",
                    help="check: duplicate-case/version drift are fatal")
    args = ap.parse_args(argv)

    sidecards_dir = Path(args.sidecards_dir).resolve()
    claims_dir = Path(args.claims_dir).resolve()
    matters_path = Path(args.matters).resolve()
    fixtures = frozenset(args.fixture) if args.fixture else DEFAULT_FIXTURES

    if not sidecards_dir.is_dir():
        print(f"sidecard-reconcile: sidecards dir not found: {sidecards_dir}",
              file=sys.stderr)
        return 2
    if not claims_dir.is_dir():
        print(f"sidecard-reconcile: claims dir not found: {claims_dir}",
              file=sys.stderr)
        return 2

    if args.mode == "ingest":
        if not args.path:
            print("sidecard-reconcile ingest: missing path", file=sys.stderr)
            return 2
        return _ingest(Path(args.path))

    _, report = _inventory(sidecards_dir, claims_dir, matters_path, fixtures)

    if args.mode == "report":
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True,
                             ensure_ascii=False))
        else:
            _print_human(report)
        return 0

    if args.mode == "backfill":
        rc = _backfill(report, args.dry_run)
        _, report = _inventory(sidecards_dir, claims_dir, matters_path,
                               fixtures)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True,
                             ensure_ascii=False))
        else:
            _print_human(report)
        return rc

    return _check(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
