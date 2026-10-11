"""Tolerant loading of the 7 epistemic sources (read-only projection).

Sources (MVP, docs/plans/graph_epistemic_proposal.vsm @status ratified):
  1. state/rsi/tree_traces.jsonl              -> predicate/answer nodes (reuses trace_graph.load)
  2. state/epistemic/sidecars/*.claims.vsm    -> claim + certificate nodes (claims, routes)
  3. state/epistemic/sidecars/*.depth.vsm     -> document nodes (levels/tools/verdict/span)
  4. .opencode/plugins/operational/gap-definitions/*.gap.json -> gap nodes
  5. docs/spec_revision/system/boot/hard_rules.vsm           -> rule nodes
  6. docs/papers/attractor_convergence/paper_data.vsm        -> experiment nodes
  7. current_focus.json + docs/plans/plan_registry.vsm        -> decision nodes

Every loader is tolerant (old/partial shapes never raise) and reports
skips — never silent (denominator rule). Nothing here writes.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

_EXP_RE = re.compile(
    r"(?<![\w-])EXP-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
    r"(?![A-Za-z0-9\-])(?!\{)")
_RULE_RE = re.compile(r"^(\s+)(R\d+[A-Za-z0-9_.]*)\s*:\s*\"", re.M)
_HEADER_TS_RE = re.compile(r"^⟦\s*[^|]+?\s*\|\s*[^|]+?\s*\|\s*vsm-[0-9.]+\s*\|\s*([^\s⟧]+)\s*⟧")
_STATUS_RE = re.compile(r"^@status\s+(\w+)", re.M)
_PLAN_ID_RE = re.compile(r"^\s*plan_id:\s*\"([^\"]+)\"", re.M)


def roots() -> Path:
    """Workspace root; VOSLAB_PATH re-read at runtime (trace_graph convention)."""
    root = os.environ.get("VOSLAB_PATH")
    if root:
        return Path(root)
    from vos_kernel.epistemic import repo_root
    return repo_root()


# ---------------------------------------------------------------- paths

def traces_path() -> Path:
    return roots() / "state" / "rsi" / "tree_traces.jsonl"


def sidecars_dir() -> Path:
    return roots() / "state" / "epistemic" / "sidecars"


def gaps_dir() -> Path:
    return roots() / ".opencode" / "plugins" / "operational" / "gap-definitions"


def hard_rules_path() -> Path:
    return roots() / "docs" / "spec_revision" / "system" / "boot" / "hard_rules.vsm"


def paper_data_path() -> Path:
    return roots() / "docs" / "papers" / "attractor_convergence" / "paper_data.vsm"


def focus_path() -> Path:
    return roots() / "current_focus.json"


def registry_path() -> Path:
    return roots() / "docs" / "plans" / "plan_registry.vsm"


def source_files() -> list[Path]:
    """Every file the projection reads (fingerprint input; artifacts resolved
    later are added on top of this by graph.fingerprint_inputs)."""
    files: list[Path] = [traces_path(), hard_rules_path(), paper_data_path(),
                         focus_path(), registry_path()]
    if sidecars_dir().is_dir():
        files += sorted(sidecars_dir().glob("*.claims.vsm"))
        files += sorted(sidecars_dir().glob("*.depth.vsm"))
    if gaps_dir().is_dir():
        files += sorted(gaps_dir().glob("*.gap.json"))
    return files


# ---------------------------------------------------------------- primitives

def _balanced(text: str, start: int, open_c: str, close_c: str) -> tuple[str, int] | None:
    """String-aware balanced slice text[start..end] starting AT open_c.
    When open_c is a quote, scans a single quoted scalar (escaped quotes
    allowed) instead of running the depth counter (which would treat the
    opening delimiter as a string start and never balance)."""
    if start >= len(text) or text[start] != open_c:
        return None
    if open_c in "\"'":
        esc = False
        for i in range(start + 1, len(text)):
            ch = text[i]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == open_c:
                return text[start:i + 1], i + 1
        return None
    depth = 0
    in_str: str | None = None
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
        elif ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None


def _assignment(text: str, name: str, open_c: str, close_c: str) -> tuple[str, int] | None:
    """Slice of `name = <balanced open_c...close_c>` (first match)."""
    m = re.search(rf"(?m)^{re.escape(name)}\s*=\s*", text)
    if not m:
        return None
    return _balanced(text, m.end(), open_c, close_c)


def _loads(blob: str):
    """json first, ast.literal_eval fallback (tolerates python-ish literals)."""
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        try:
            return ast.literal_eval(blob)
        except (ValueError, SyntaxError, TypeError) as e:
            raise ValueError(f"not a literal: {e}") from e


def _header_fields(text: str) -> tuple[str | None, str | None]:
    """(ts, status) from `⟦ name | TYPE | vsm-x | ts ⟧` + `@status` line."""
    ts = None
    status = None
    first = text.splitlines()[0] if text else ""
    m = _HEADER_TS_RE.match(first)
    if m:
        ts = m.group(1)
    m = _STATUS_RE.search(text)
    if m:
        status = m.group(1)
    return ts, status


# ---------------------------------------------------------------- loaders

def load_traces(path: Path | str | None = None):
    """(traces, skipped) — delegates to trace_graph (reuse, no duplication)."""
    from trace_graph.load import load_traces as _lt
    return _lt(path if path is not None else traces_path())


def load_claims() -> dict:
    """All *.claims.vsm -> {claims, routes, skipped, files, ts_by_stem}.

    claims: flat list, each enriched with _file (sidecar rel path).
    routes: claim_id -> {route, status, verdict} (kept as claim dims source).
    """
    claims: list[dict] = []
    routes: dict[str, dict] = {}
    ts_by_stem: dict[str, str] = {}
    skipped = 0
    files = 0
    d = sidecars_dir()
    for p in sorted(d.glob("*.claims.vsm")) if d.is_dir() else []:
        files += 1
        text = p.read_text(errors="replace")
        ts, _ = _header_fields(text)
        stem = p.name[:-len(".claims.vsm")]
        if ts:
            ts_by_stem[stem.lower()] = ts
        blob = _assignment(text, "claims", "[", "]")
        if blob:
            try:
                arr = _loads(blob[0])
                if isinstance(arr, list):
                    for c in arr:
                        if isinstance(c, dict) and c.get("id"):
                            c["_file"] = str(p.relative_to(roots())) \
                                if p.is_relative_to(roots()) else str(p)
                            claims.append(c)
                        else:
                            skipped += 1
                else:
                    skipped += 1
            except (ValueError, SyntaxError):
                skipped += 1
        else:
            if "claims" in text:
                skipped += 1
        rblob = _assignment(text, "routes", "{", "}")
        if rblob:
            try:
                obj = _loads(rblob[0])
                if isinstance(obj, dict):
                    routes.update({str(k): v for k, v in obj.items()
                                   if isinstance(v, dict)})
            except (ValueError, SyntaxError):
                skipped += 1
    return {"claims": claims, "routes": routes, "skipped": skipped,
            "files": files, "ts_by_stem": ts_by_stem}


def load_depth() -> dict:
    """All *.depth.vsm -> {docs: stem->{fields}, skipped, files}.

    fields: levels, tools, evidence, verdict, span, related_sources + ts/status.
    """
    docs: dict[str, dict] = {}
    skipped = 0
    files = 0
    d = sidecars_dir()
    for p in sorted(d.glob("*.depth.vsm")) if d.is_dir() else []:
        files += 1
        text = p.read_text(errors="replace")
        ts, status = _header_fields(text)
        stem = p.name[:-len(".depth.vsm")]
        rec: dict = {"stem": stem, "_file": str(p.relative_to(roots()))
                     if p.is_relative_to(roots()) else str(p),
                     "ts": ts, "status": status}
        for field in ("levels", "tools", "evidence", "verdict", "span",
                      "related_sources"):
            blob = _assignment(text, field, "[", "]") or \
                _assignment(text, field, "{", "}") or \
                _assignment(text, field, '"', '"') or \
                _assignment(text, field, "'", "'")
            if blob is None:
                # bare scalar (ints/idents): rest of the line
                m2 = re.search(rf"(?m)^{re.escape(field)}\s*=\s*(.+)$", text)
                if not m2:
                    continue
                try:
                    rec[field] = _loads(m2.group(1).strip())
                except (ValueError, SyntaxError, TypeError):
                    skipped += 1
                continue
            try:
                rec[field] = _loads(blob[0])
            except (ValueError, SyntaxError, TypeError):
                skipped += 1
        docs[stem.lower()] = rec
    return {"docs": docs, "skipped": skipped, "files": files}


def load_gaps() -> dict:
    """Registry gap definitions -> {gaps: [...], skipped, files}."""
    gaps: list[dict] = []
    skipped = 0
    files = 0
    d = gaps_dir()
    for p in sorted(d.glob("*.gap.json")) if d.is_dir() else []:
        files += 1
        try:
            obj = json.loads(p.read_text(errors="replace"))
        except (ValueError, json.JSONDecodeError):
            skipped += 1
            continue
        if isinstance(obj, dict) and obj.get("id"):
            obj["_file"] = str(p.relative_to(roots())) \
                if p.is_relative_to(roots()) else str(p)
            gaps.append(obj)
        else:
            skipped += 1
    return {"gaps": gaps, "skipped": skipped, "files": files}


def load_rules() -> dict:
    """hard_rules.vsm -> {rules: [{key, body?}], status, ts, skipped}."""
    p = hard_rules_path()
    if not p.exists():
        return {"rules": [], "status": None, "ts": None, "skipped": 0,
                "exists": False}
    text = p.read_text(errors="replace")
    ts, status = _header_fields(text)
    rules = []
    skipped = 0
    for m in _RULE_RE.finditer(text):
        key = m.group(2)
        if not any(r["key"] == key for r in rules):  # first occurrence wins
            rules.append({"key": key})
    if not rules:
        skipped = 1
    return {"rules": rules, "status": status, "ts": ts, "skipped": skipped,
            "exists": True}


def load_experiments() -> dict:
    """paper_data.vsm -> {ids: [...], skipped} (EXP-* tokens, content-keyed)."""
    p = paper_data_path()
    if not p.exists():
        return {"ids": [], "skipped": 0, "exists": False}
    text = p.read_text(errors="replace")
    seen: set[str] = set()
    for m in _EXP_RE.finditer(text):
        tok = m.group(0)
        # strip trailing '-' fragment from greedy-but-broken boundaries
        seen.add(tok)
    return {"ids": sorted(seen), "skipped": 0, "exists": True}


def load_decisions() -> dict:
    """focus refs + plan_registry plan_ids -> {decisions, skipped}."""
    out: list[dict] = []
    skipped = 0
    fp = focus_path()
    if fp.exists():
        try:
            arr = json.loads(fp.read_text(errors="replace"))
            if isinstance(arr, list):
                for e in arr:
                    if isinstance(e, dict) and e.get("ref"):
                        out.append({
                            "id": f"decision:{e['ref']}", "ref": e["ref"],
                            "status": e.get("status"),
                            "ts": e.get("updated_at") or e.get("started_at"),
                            "source": "current_focus.json",
                            "label": e.get("note") or e["ref"],
                        })
                    else:
                        skipped += 1
            else:
                skipped += 1
        except (ValueError, json.JSONDecodeError):
            skipped += 1
    rp = registry_path()
    if rp.exists():
        text = rp.read_text(errors="replace")
        matches = list(_PLAN_ID_RE.finditer(text))
        for i, m in enumerate(matches):
            plan_id = m.group(1)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            seg = text[m.end():end]
            sm = re.search(r"^\s*status:\s*\"([^\"]+)\"", seg, re.M)
            cm = re.search(r"^\s*created_at:\s*\"([^\"]+)\"", seg, re.M)
            out.append({
                "id": f"decision:{plan_id}", "ref": plan_id,
                "status": sm.group(1) if sm else None,
                "ts": cm.group(1) if cm else None,
                "source": "docs/plans/plan_registry.vsm",
                "label": plan_id,
            })
    return {"decisions": out, "skipped": skipped}


# ---------------------------------------------------------------- fingerprint

def fingerprint(paths: list[Path]) -> str:
    """Content fingerprint of every input file (sha256 over sorted bytes).

    Content-based, not mtime-based: touching a file without changing bytes
    does not invalidate the cache; any byte change does.
    """
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: str(x)):
        if not p.is_file():
            h.update(f"absent:{p}".encode())
            continue
        h.update(str(p).encode())
        h.update(p.read_bytes())
    return h.hexdigest()
