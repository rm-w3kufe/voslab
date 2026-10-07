#!/usr/bin/env python3
"""log_distill.py — O-6 trajectory→learning distill (R-3, PROPOSE-ONLY).

Design: docs/plans/refs_optimization_proposal.vsm §6.2. R-3 APROBADO por
S5 2026-10-07 con la condición de revisión de calidad del log cumplida
(§11.7 — 5 hallazgos, P0+P1 ejecutados).

Reads logs/agent_plugin.jsonl + rotated .gz archives, DUAL SCHEMA:
  esquema B (vivo, desde 2026-09-09): {source, event_type, event_id, ...}
  esquema A (.gz pre-2026-09):       {instrument, hook, ...}  → normalized
Groups fan-out by event_id (same logical event, multiple emitters —
UNIT-LOCAL: computed per archive / live file, so an id appearing once on
each side of a rotation boundary is not grouped; a report-only stat,
candidates never depend on it),
extracts deterministic tool-use patterns + session summaries and appends
CANDIDATES to state/distill/candidates.jsonl.

SEMI-AUTOMATIC BY DESIGN (§6.2): this script only PROPOSES. Applying a
candidate requires S5 ratification. HARD LIMIT (K5): no code path writes
toward skills/ or predicate stores — the only permitted write targets are
the candidates file and the archive feature cache (enforced by
_safe_write; test_log_distill asserts the write set).

DETERMINISM (R10): pure function of the log bytes — no randomness, no
TTL, stable ordering. Archives are memoized by signature
(basename+size+mtime, the check_agent_log census pattern): same bytes →
same features, rotation/prune → recompute. The live log is parsed fresh
every run. class=="test" records (pytest fixtures, D-15) and
socratic evaluate-FALSE verdicts are excluded from failure signals
(K4: FALSE is a normal outcome, not breakage) — both counted in the
report.

Usage:
    python3 scripts/state/monitoring/log_distill.py            # run + report
    python3 scripts/state/monitoring/log_distill.py --json     # machine report
    python3 scripts/state/monitoring/log_distill.py --dry-run  # no candidate writes
    python3 scripts/state/monitoring/log_distill.py --top 20   # report width
Exit: 0 always (report tool), 2 on usage error.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_VOS_ROOT = Path(__file__).resolve().parents[3]
LOG_NAME = "agent_plugin.jsonl"
#: candidate thresholds (deterministic constants, tunable by edit)
MIN_ERROR_SIG = 10     # normalized error signature occurrences
MIN_CMD_HEAD = 30      # repeated bash command head
MIN_SESSION_ERRORS = 5  # per-day/session health
MIN_SESSION_ERR_RATE = 0.30
#: the ONLY files this script may write (K5 hard limit, test-enforced)
WRITE_ALLOWED = {"candidates.jsonl", f"{LOG_NAME}.distill_cache"}
#: cache format version — bump invalidates stale archives caches (v1 fanout=int)
CACHE_VERSION = 2


def _root() -> Path:
    return Path(os.environ.get("VOSLAB_PATH", str(_VOS_ROOT)))


def _safe_write(path: Path, data: str) -> None:
    """K5 hard limit: refuse any write target outside WRITE_ALLOWED."""
    if path.name not in WRITE_ALLOWED:
        raise PermissionError(
            f"K5: distill may not write {path} (allowed: {sorted(WRITE_ALLOWED)})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _safe_append(path: Path, lines: list[str]) -> None:
    """Append-only candidate writes, same K5 guard as _safe_write."""
    if path.name not in WRITE_ALLOWED:
        raise PermissionError(
            f"K5: distill may not write {path} (allowed: {sorted(WRITE_ALLOWED)})")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


# ── schema normalization (dual A/B) ─────────────────────────────────────────

def normalize(rec: dict) -> dict:
    """Map schema-A keys to B (identity for B records)."""
    return {
        "ts": rec.get("ts") or "",
        "source": rec.get("source") or rec.get("instrument") or "?",
        "event_type": rec.get("event_type") or rec.get("hook") or "?",
        "event_id": rec.get("event_id") or "",
        "session_id": rec.get("session_id") or None,
        "action": rec.get("action") or "",
        "result": rec.get("result") or "",
        "detail": rec.get("detail") or "",
        "class": rec.get("class") or "operational",
        "duration_ms": rec.get("duration_ms")
        if isinstance(rec.get("duration_ms"), (int, float))
        else ((rec.get("metrics") or {}).get("duration_ms")),
    }


def _norm_text(text: str) -> str:
    """Collapse volatile tokens so equal failures group together."""
    s = str(text)
    s = re.sub(r"0x[0-9a-fA-F]+", "<hex>", s)
    s = re.sub(r"\b[0-9a-f]{8,40}\b", "<hex>", s)
    s = re.sub(r"[/~][\w.\-/]+", "<path>", s)
    s = re.sub(r"\d{3,}", "<n>", s)
    return re.sub(r"\s+", " ", s).strip()[:80]


def _tool_of(action: str) -> str | None:
    m = re.match(r"(?:tool|vsm):\s+(\S+)", action)
    return m.group(1) if m else None


def _cmd_head(action: str) -> str | None:
    """`tool: bash git status --porcelain` → `git status` (3 sig tokens)."""
    parts = action.split()
    if len(parts) < 3 or parts[0] not in ("tool:", "vsm:") or parts[1] != "bash":
        return None
    toks = [t for t in parts[2:] if not t.startswith("-")][:3]
    if not toks:
        return None
    return " ".join(re.sub(r"\d+", "#", t)[:40] for t in toks)


def _is_failure(rec: dict) -> bool:
    """result==error BUT socratic evaluate-FALSE/ERROR is not a system
    failure (normal outcome, K4) — exclude from error signals so
    candidates surface actionable breakage, not learning verdicts.
    Evidence-style JSON details (detail starts '{') are likewise not
    error messages and are excluded from signatures."""
    if rec["result"] != "error":
        return False
    return not rec["event_type"].startswith("evaluate")


def _error_sig(source: str, rec: dict) -> str | None:
    if str(rec["detail"]).lstrip().startswith("{"):
        return None  # evidence payload, not an error message
    return f"{source}|{_norm_text(rec['detail'] or rec['action'])}"


# ── extraction (pure) ───────────────────────────────────────────────────────

def _empty_features() -> dict:
    return {"records": 0, "test_excluded": 0, "errors": 0,
            "tool_freq": {}, "cmd_heads": {},
            "error_sigs": {}, "days": {}, "fanout": {}}


def extract(records: list[dict]) -> dict:
    """Aggregate features from normalized records (mergeable, R10-pure)."""
    f = _empty_features()
    # event_id → {"n": count, "sources": [..]} — distinguishes true fan-out
    # (N sources, same logical event) from same-second collisions (1 source;
    # rsi_cycle ids use int(time.time())).
    event_counts: dict[str, dict] = {}
    for raw in records:
        rec = normalize(raw)
        if rec["class"] == "test":
            f["test_excluded"] += 1
            continue
        f["records"] += 1
        if rec["event_id"]:
            slot = event_counts.setdefault(
                rec["event_id"], {"n": 0, "sources": []})
            slot["n"] += 1
            if rec["source"] not in slot["sources"]:
                slot["sources"].append(rec["source"])
        day = (rec["ts"][:10] if len(rec["ts"]) >= 10 else "unknown")
        day_slot = f["days"].setdefault(
            day, {"n": 0, "err": 0, "dur_sum": 0, "dur_n": 0, "sources": {}})
        day_slot["n"] += 1
        day_slot["sources"][rec["source"]] = day_slot["sources"].get(rec["source"], 0) + 1
        if isinstance(rec["duration_ms"], (int, float)):
            day_slot["dur_sum"] += rec["duration_ms"]
            day_slot["dur_n"] += 1
        if _is_failure(rec):
            f["errors"] += 1
            day_slot["err"] += 1
            sig = _error_sig(rec["source"], rec)
            if sig is not None:
                slot = f["error_sigs"].setdefault(
                    sig, {"n": 0, "examples": [], "sources": {}})
                slot["n"] += 1
                slot["sources"][rec["source"]] = (
                    slot["sources"].get(rec["source"], 0) + 1)
                if len(slot["examples"]) < 3 and rec["event_id"]:
                    slot["examples"].append(rec["event_id"])
        tool = _tool_of(rec["action"])
        if tool:
            f["tool_freq"][tool] = f["tool_freq"].get(tool, 0) + 1
        head = _cmd_head(rec["action"])
        if head:
            f["cmd_heads"][head] = f["cmd_heads"].get(head, 0) + 1
    for eid, slot in event_counts.items():
        if slot["n"] > 1:
            f["fanout"][eid] = {"n": slot["n"], "sources": slot["sources"]}
    return f


def merge(a: dict, b: dict) -> dict:
    """Sum two feature dicts (associative/commutative — archive + live)."""
    out = _empty_features()
    for key in ("records", "test_excluded", "errors"):
        out[key] = a.get(key, 0) + b.get(key, 0)
    for map_key in ("tool_freq", "cmd_heads"):
        for k, v in (a.get(map_key) or {}).items():
            out[map_key][k] = out[map_key].get(k, 0) + v
        for k, v in (b.get(map_key) or {}).items():
            out[map_key][k] = out[map_key].get(k, 0) + v
    # fanout entries are {n, sources} objects: sum counts, union sources
    for side in (a, b):
        for k, v in (side.get("fanout") or {}).items():
            if isinstance(v, int):  # v1 cache legacy: bare count
                v = {"n": v, "sources": []}
            slot = out["fanout"].setdefault(k, {"n": 0, "sources": []})
            slot["n"] += v.get("n", 0)
            for src in v.get("sources", []):
                if src not in slot["sources"]:
                    slot["sources"].append(src)
    for k, v in (a.get("error_sigs") or {}).items():
        out["error_sigs"][k] = {"n": v.get("n", 0),
                                "examples": list(v.get("examples", [])),
                                "sources": dict(v.get("sources", {}))}
    for k, v in (b.get("error_sigs") or {}).items():
        slot = out["error_sigs"].setdefault(
            k, {"n": 0, "examples": [], "sources": {}})
        slot["n"] += v.get("n", 0)
        for ex in v.get("examples", []):
            if ex not in slot["examples"] and len(slot["examples"]) < 3:
                slot["examples"].append(ex)
        for s, n in (v.get("sources") or {}).items():
            slot["sources"][s] = slot["sources"].get(s, 0) + n
    for k, v in (a.get("days") or {}).items():
        out["days"][k] = {"n": v.get("n", 0), "err": v.get("err", 0),
                          "dur_sum": v.get("dur_sum", 0), "dur_n": v.get("dur_n", 0),
                          "sources": dict(v.get("sources", {}))}
    for k, v in (b.get("days") or {}).items():
        slot = out["days"].setdefault(
            k, {"n": 0, "err": 0, "dur_sum": 0, "dur_n": 0, "sources": {}})
        slot["n"] += v.get("n", 0)
        slot["err"] += v.get("err", 0)
        slot["dur_sum"] += v.get("dur_sum", 0)
        slot["dur_n"] += v.get("dur_n", 0)
        for s, n in (v.get("sources") or {}).items():
            slot["sources"][s] = slot["sources"].get(s, 0) + n
    return out


# ── loading (live fresh, archives cached by signature) ─────────────────────

def _archives(log_dir: Path) -> list[Path]:
    files = glob.glob(str(log_dir / f"{LOG_NAME}.*.jsonl*"))
    def epoch(p: str) -> int:
        m = re.search(r"\.(\d{13})\.jsonl", p)
        return int(m.group(1)) if m else 0
    return [Path(p) for p in sorted(files, key=epoch) if p.endswith((".gz", ".jsonl"))]


def _signature(files: list[Path]) -> list:
    return [[f.name, f.stat().st_size, int(f.stat().st_mtime)] for f in files]


def _read_records(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    out = []
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:  # type: ignore[operator]
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # corrupt line: skip, count happens via records
    except OSError:
        return []
    return out


def load_archives(log_dir: Path) -> tuple[dict, str]:
    """Archive features, memoized by set signature (census pattern)."""
    files = _archives(log_dir)
    if not files:
        return _empty_features(), "none"
    sig = _signature(files)
    cache_path = log_dir / f"{LOG_NAME}.distill_cache"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (cached.get("signature") == sig
                    and cached.get("v") == CACHE_VERSION):
                return cached.get("features", _empty_features()), "hit"
        except (json.JSONDecodeError, OSError):
            pass  # stale/corrupt cache → recompute
    features = _empty_features()
    for f in files:
        features = merge(features, extract(_read_records(f)))
    try:
        _safe_write(cache_path, json.dumps(
            {"v": CACHE_VERSION, "signature": sig, "features": features},
            ensure_ascii=False))
    except PermissionError:
        pass  # cache is a nicety; never fail the run over it
    return features, "miss"


def load_live(log_dir: Path) -> dict:
    return extract(_read_records(log_dir / LOG_NAME))


# ── candidates (propose-only) ───────────────────────────────────────────────

def _candidates_path(root: Path) -> Path:
    return root / "state" / "distill" / "candidates.jsonl"


def load_candidates(path: Path) -> dict:
    """id → record. Rejected/accepted ids are never re-proposed (S5 veto)."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("id"):
            out[rec["id"]] = rec
    return out


def propose(features: dict) -> list[dict]:
    """Deterministic candidate extraction from merged features."""
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []

    def _cid(kind: str, key: str) -> str:
        return hashlib.sha1(f"{kind}|{key}".encode("utf-8")).hexdigest()[:16]

    for sig in sorted(features["error_sigs"]):
        slot = features["error_sigs"][sig]
        if slot["n"] >= MIN_ERROR_SIG:
            out.append({
                "id": _cid("error_pattern", sig), "kind": "error_pattern",
                "key": sig, "count": slot["n"],
                "evidence": {"sources": slot["sources"],
                             "event_ids": slot["examples"][:3]},
                "suggested": "revisar causa raíz (fix doc/gate) — aplica solo con S5",
                "status": "proposed", "ts": now,
            })
    for head in sorted(features["cmd_heads"]):
        n = features["cmd_heads"][head]
        if n >= MIN_CMD_HEAD:
            out.append({
                "id": _cid("tool_pattern", head), "kind": "tool_pattern",
                "key": head, "count": n, "evidence": {},
                "suggested": "comando altamente repetido: considerar batch/alias/cache",
                "status": "proposed", "ts": now,
            })
    for day in sorted(features["days"]):
        slot = features["days"][day]
        rate = slot["err"] / slot["n"] if slot["n"] else 0.0
        if slot["err"] >= MIN_SESSION_ERRORS and rate >= MIN_SESSION_ERR_RATE:
            out.append({
                "id": _cid("session_health", day), "kind": "session_health",
                "key": day, "count": slot["err"],
                "evidence": {"records": slot["n"], "error_rate": round(rate, 3),
                             "sources": slot["sources"]},
                "suggested": "día/sesión con tasa de error alta: revisar",
                "status": "proposed", "ts": now,
            })
    return out


def append_new(candidates: list[dict], existing: dict, path: Path,
               dry_run: bool) -> list[dict]:
    fresh = [c for c in candidates if c["id"] not in existing]
    if fresh and not dry_run:
        _safe_append(path, [json.dumps(c, ensure_ascii=False) for c in fresh])
    return fresh


# ── report / CLI ────────────────────────────────────────────────────────────

def _events_report(fanout: dict) -> dict:
    """Split event_id groups: multi-source = fan-out (feature, §11.7);
    single-source n>1 = same-second id collision (rsi ids at 1s grain)."""
    multi = {k: v for k, v in fanout.items() if len(v.get("sources", [])) > 1}
    single = {k: v for k, v in fanout.items() if len(v.get("sources", [])) <= 1}
    def _top_f(d: dict, n: int) -> list:
        return [[k, v["n"], v["sources"][:4]] for k, v in
                sorted(d.items(), key=lambda kv: (-kv[1]["n"], kv[0]))[:n]]
    return {
        "fanout_groups": len(multi),
        "fanout_records": sum(v["n"] for v in multi.values()),
        "fanout_top": _top_f(multi, 5),
        "collision_groups": len(single),
        "collision_records": sum(v["n"] for v in single.values()),
        "collision_top": _top_f(single, 5),
    }


def run(dry_run: bool = False, top: int = 10) -> dict:
    root = _root()
    log_dir = root / "logs"
    arch_features, cache_state = load_archives(log_dir)
    live_records = _read_records(log_dir / LOG_NAME)
    live_features = extract(live_records)
    features = merge(arch_features, live_features)

    cand_path = _candidates_path(root)
    existing = load_candidates(cand_path)
    proposed = propose(features)
    fresh = append_new(proposed, existing, cand_path, dry_run)
    # re-load after append (or synthesize for dry-run) so `open` counts
    # each candidate exactly once
    if dry_run:
        existing_after = dict(existing)
        for c in fresh:
            existing_after[c["id"]] = c
    else:
        existing_after = load_candidates(cand_path)

    def _top(d: dict, n: int) -> list:
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    day_slots = sorted(
        ((d, v) for d, v in features["days"].items() if d != "unknown"),
        key=lambda kv: (kv[0]), reverse=True)[:top]
    sessions = {}
    # session_id attribution (P0): live records may carry it — summarize
    for rec in live_records:
        nrec = normalize(rec)
        if nrec["class"] == "test" or not nrec["session_id"]:
            continue
        slot = sessions.setdefault(nrec["session_id"], {"n": 0, "err": 0})
        slot["n"] += 1
        if _is_failure(nrec):
            slot["err"] += 1

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "dry_run": dry_run,
        "input": {
            "archives": len(_archives(log_dir)),
            "archive_records": arch_features["records"],
            "live_records": live_features["records"],
            "test_excluded": features["test_excluded"],
            "cache": cache_state,
        },
        "events": _events_report(features["fanout"]),
        "patterns": {
            "errors": features["errors"],
            "top_tools": _top(features["tool_freq"], top),
            "top_cmd_heads": _top(features["cmd_heads"], top),
            "error_sigs": len(features["error_sigs"]),
            "top_error_sigs": [[k, v["n"]] for k, v in
                               sorted(features["error_sigs"].items(),
                                      key=lambda kv: (-kv[1]["n"], kv[0]))[:top]],
        },
        "sessions": {
            "with_session_id": len(sessions),
            "live_by_session": dict(sorted(sessions.items(),
                                           key=lambda kv: (-kv[1]["n"], kv[0]))[:top]),
            "recent_days": [[d, v["n"], v["err"]] for d, v in day_slots],
        },
        "candidates": {
            "existing": len(existing),
            "new": [c["id"] for c in fresh],
            "new_detail": fresh,
            "open": sum(1 for c in existing_after.values()
                        if c.get("status") == "proposed"),
        },
        "propose_only": True,
        "k5_write_allowed": sorted(WRITE_ALLOWED),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="O-6 trajectory distill (propose-only)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--dry-run", action="store_true", help="no candidate writes")
    ap.add_argument("--top", type=int, default=10, help="report width")
    args = ap.parse_args()
    if args.top < 1 or args.top > 100:
        print("usage: --top between 1 and 100", file=sys.stderr)
        return 2
    report = run(dry_run=args.dry_run, top=args.top)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        i, p, c = report["input"], report["patterns"], report["candidates"]
        print(f"log distill ({report['ts']}) root={report['root']}"
              f"{' [DRY-RUN]' if report['dry_run'] else ''}")
        print(f"  input: {i['archives']} archives ({i['archive_records']} recs, "
              f"cache={i['cache']}) + {i['live_records']} live, "
              f"test excluded {i['test_excluded']}")
        ev = report["events"]
        print(f"  events: fanout={ev['fanout_groups']} groups "
              f"({ev['fanout_records']} recs), id-collisions="
              f"{ev['collision_groups']} ({ev['collision_records']} recs)")
        print(f"  errors: {p['errors']} across {p['error_sigs']} signatures")
        print(f"  top tools: {p['top_tools'][:5]}")
        print(f"  candidates: {c['existing']} existing, "
              f"{len(c['new'])} new, open={c['open']}")
        if c["new_detail"]:
            print("  new candidates:")
            for cand in c["new_detail"][:10]:
                print(f"    [{cand['kind']}] {cand['key'][:70]} (n={cand['count']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
