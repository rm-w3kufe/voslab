#!/usr/bin/env python3
"""verify_docs.py — F5 Fase 3 ligera del doc_tracking_plan (§3.3 + §3.4).

Verify de consistencia del manifest + changelog de cambios observados:

  checksum     source re-hash vs manifest (drift upstream) + dest
               re-hash observado entre corridas
  huerfanos    .vsm en directorios con dests trackeados SIN entrada en
               el manifest (copia nueva no registrada)
  faltantes    entries con dest declarado que ya no esta en disco
  cola         status=modified -> cola de revision S5
               (state/doc_tracking/review_queue.jsonl)
  changelog    cambios observados vs estado previo -> doc_changelog.jsonl
               {ts, doc_id, action, source, dest, checksum_before,
                checksum_after}  (plan §3.4)

rc: 0 = verify completo (drift/cola = report, NO gate — el gate de
       integridad con rc1 es `doc_manifest.py verify`, Fase 1);
    2 = error (manifest faltante/ilegible).

Uso:
  verify_docs.py            # escribe changelog + estado + cola
  verify_docs.py --dry-run  # solo reporta, sin escrituras

Paths (nota de alcance — divergencia documentada del §4): el manifest ya
vive en state/ desde Fase 1; changelog/estado/cola viven en
state/doc_tracking/ por la misma razon: datos en state/, codigo en
scripts/. Honra los overrides DOC_MANIFEST_VOSLAB / DOC_MANIFEST_VSF /
DOC_MANIFEST de doc_manifest.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()


def _load_doc_manifest():
    root = _HERE.parents[2]
    p = root / "scripts" / "vsl" / "tools" / "doc_manifest.py"
    spec = importlib.util.spec_from_file_location("doc_manifest", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dm = _load_doc_manifest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _buckets(rows: list[dict]) -> tuple:
    """Observacion por entry: obs id -> {source_sha, dest_sha} + buckets."""
    obs: dict[str, dict] = {}
    source_drifted: list[str] = []
    source_unreadable: list[str] = []
    faltantes: list[str] = []
    cola: list[dict] = []
    dest_set: set[str] = set()
    for e in rows:
        eid = e["id"]
        dest = e.get("dest")
        src = Path(e.get("source") or "")
        s_sha = dm._sha(src) if src.is_file() else None
        if s_sha is None:
            source_unreadable.append(eid)
        elif s_sha != e.get("checksum"):
            source_drifted.append(eid)
        d_sha = None
        if dest:
            dest_set.add(dest)
            dp = dm.VOSLAB / dest
            if dp.is_file():
                d_sha = dm._sha(dp)
            else:
                faltantes.append(eid)
        else:
            faltantes.append(eid)
        obs[eid] = {"source_sha": s_sha, "dest_sha": d_sha}
        if e.get("status") == "modified":
            cola.append({"id": eid, "dest": dest,
                         "priority": e.get("priority")})
    # huerfanos: .vsm en los directorios que tienen dests trackeados
    # (scope acotado: un dir nuevo de sync, no el repo entero). Dos tiers:
    #   canon   — docs/canon_mirror/: scope de sync, ACCIONABLE (copia
    #             stale con dest canonico ya registrado en otra ruta, o
    #             sin entrada alguna)
    #   native  — resto: docs nativos de vOSlab, informativo (el manifest
    #             es vsf-driven desde Fase 1)
    tracked_dirs = sorted({str(Path(d).parent) for d in dest_set})
    huerfanos: list[str] = []
    huerfanos_canon: list[dict] = []
    huerfanos_native: list[dict] = []
    for rd in tracked_dirs:
        base = dm.VOSLAB / rd
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.vsm")):
            rel = str(p.relative_to(dm.VOSLAB))
            if rel in dest_set:
                continue
            huerfanos.append(rel)
            tier = ("canon" if rel.startswith("docs/canon_mirror/")
                    else "native")
            rec = {"path": rel, "tier": tier}
            (huerfanos_canon if tier == "canon"
             else huerfanos_native).append(rec)
    return (obs, source_drifted, source_unreadable, faltantes, cola,
            huerfanos, huerfanos_canon, huerfanos_native)


def _diff(prev: dict, obs: dict, rows: list[dict]) -> list[dict]:
    """Cambios observados vs estado previo (§3.4). Sin estado = baseline."""
    if not prev:
        return []
    by_id = {e["id"]: e for e in rows}
    out: list[dict] = []
    ts = _utc_now()
    for eid in sorted(obs):
        cur = obs[eid]
        p = prev.get(eid)
        meta = by_id.get(eid, {})
        if p is None:
            if cur["dest_sha"]:
                out.append({"ts": ts, "doc_id": eid, "action": "create",
                            "source": meta.get("source"),
                            "dest": meta.get("dest"),
                            "checksum_before": None,
                            "checksum_after": cur["dest_sha"]})
            continue
        if p.get("dest_sha") != cur["dest_sha"]:
            if p.get("dest_sha") and cur["dest_sha"]:
                act = "modify"
            elif p.get("dest_sha"):
                act = "delete"
            else:
                act = "create"
            out.append({"ts": ts, "doc_id": eid, "action": act,
                        "source": meta.get("source"),
                        "dest": meta.get("dest"),
                        "checksum_before": p.get("dest_sha"),
                        "checksum_after": cur["dest_sha"]})
        if (p.get("source_sha") and cur["source_sha"]
                and p.get("source_sha") != cur["source_sha"]):
            out.append({"ts": ts, "doc_id": eid, "action": "source-modify",
                        "source": meta.get("source"),
                        "dest": meta.get("dest"),
                        "checksum_before": p["source_sha"],
                        "checksum_after": cur["source_sha"]})
    return out


def run(dry: bool = False) -> int:
    if not dm.MANIFEST.exists():
        print(json.dumps({"ok": False, "rc": 2,
                          "error": f"manifest missing: {dm.MANIFEST}"}))
        return 2
    try:
        rows = sorted(dm._load(), key=lambda e: e["id"])
    except Exception as exc:  # ilegible
        print(json.dumps({"ok": False, "rc": 2,
                          "error": f"manifest unreadable: {exc}"}))
        return 2

    (obs, s_drift, s_unread, faltantes, cola, huerfanos, h_canon,
     h_native) = _buckets(rows)

    state_dir = dm.VOSLAB / "state" / "doc_tracking"
    state_path = state_dir / "verify_state.json"
    changelog_path = state_dir / "doc_changelog.jsonl"
    queue_path = state_dir / "review_queue.jsonl"
    orphans_path = state_dir / "orphans.jsonl"
    prev: dict = {}
    if state_path.exists():
        try:
            prev = json.loads(state_path.read_text())
        except Exception:
            prev = {}
    baseline = not prev
    changes = _diff(prev, obs, rows)

    if not dry:
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obs, indent=1, sort_keys=True) + "\n")
        tmp.replace(state_path)
        if changes:
            with open(changelog_path, "a") as f:
                for c in changes:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
        with open(queue_path, "w") as f:
            for c in cola:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        with open(orphans_path, "w") as f:
            for o in h_canon + h_native:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(json.dumps({
        "ok": True, "rc": 0, "entries": len(rows),
        "source_drifted": len(s_drift), "source_unreadable": len(s_unread),
        "faltantes": len(faltantes), "huerfanos": len(huerfanos),
        "huerfanos_canon": len(h_canon), "huerfanos_native": len(h_native),
        "cola_modified": len(cola), "baseline": baseline,
        "changelog_appended": len(changes) if not dry else 0,
        "would_append": len(changes) if dry else None,
        "queue": str(queue_path.relative_to(dm.VOSLAB)) if not dry else None,
        "huerfanos_canon_list": [o["path"] for o in h_canon],
        "dry_run": dry,
    }))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="solo reporta, sin escrituras")
    args = ap.parse_args(argv)
    return run(dry=args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
