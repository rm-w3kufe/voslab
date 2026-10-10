"""graph_study — loaders + deterministic layouts + matplotlib renderers for
NB05 "grafos de nodos por capas" (micro -> meso -> macro).

Deterministic-first (R10): no randomness, no time-dependent layout, sorted
iteration everywhere. Portable: pure matplotlib (works on LXC 114's env
which has no networkx). The predicate-layer loader is a local mirror of
`trace_graph.per_trace` (packages/framework/trace_graph/graph.py) so the
notebook runs standalone on 114; identity rules follow trace_graph F3
(node key = VSL text, never per-trace local id).

Denominator rule: every loader returns (objects, stats) where stats carries
counts + skips — never a bare list.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, deque
from pathlib import Path

# ── paleta espejo de trace_graph.export: TRUE verde, FALSE rojo, UNKNOWN gris
TRUTH_FILL = {"TRUE": "#d4edda", "FALSE": "#f8d7da", "UNKNOWN": "#f0f0f0"}
KIND_FILL = {
    "document": "#cfe2ff", "claim": "#fff3cd", "predicate": "#e2e3e5",
    "certificate": "#f8d7da", "answer": "#d1e7dd", "experiment": "#ffd8a8",
    "decision": "#d0bfff", "gap": "#ffc9c9", "rule": "#b6e5ff",
}


# ── loaders ───────────────────────────────────────────────────────────────────

def load_trace_sample(path: Path | str, k: int = 3):
    """Last k traces from a big JSONL (streaming; 230MB source never loaded
    whole). Returns (traces, stats) with total/skipped denominators."""
    p = Path(path)
    buf: deque[dict] = deque(maxlen=k)
    total = skipped = dropped = 0
    if p.exists():
        with p.open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if isinstance(rec, dict) and rec.get("nodes"):
                    buf.append(rec)
                else:
                    dropped += 1
    return list(buf), {"total": total, "kept": len(buf), "skipped": skipped,
                       "dropped_no_nodes": dropped}


def per_trace_graph(trace: dict) -> dict:
    """One trace -> predicate graph (mirror of trace_graph.per_trace core)."""
    nodes, edges = [], []
    for nd in trace.get("nodes", []):
        nodes.append({
            "id": str(nd.get("node_id")),
            "name": nd.get("name") or "",
            "type": nd.get("type") or "",
            "truth": str(nd.get("truth", "Truth.UNKNOWN")).replace("Truth.", ""),
            "certified": bool(nd.get("certified")),
            "text": (nd.get("text") or "")[:60],
        })
        for ch in nd.get("children") or []:
            edges.append((str(nd.get("node_id")), str(ch)))
    return {"nodes": nodes, "edges": edges,
            "meta": {"trace_id": trace.get("trace_id"),
                     "ts": trace.get("ts"),
                     "final_truth": str(trace.get("final_truth")).replace("Truth.", ""),
                     "shape": trace.get("tree_shape")}}


_ASSIGN_RE = re.compile(r"^(\w+) = ", re.MULTILINE)


def parse_vsm_assignments(text: str) -> dict:
    """Top-level `key = value` assignments of our own generated sidecars
    (claims/depth). Value = balanced JSON (raw_decode — nested ]/} safe).
    Tolerant: unparsable / non-JSON values are skipped, not fatal."""
    out: dict = {}
    dec = json.JSONDecoder()
    for m in _ASSIGN_RE.finditer(text):
        try:
            val, _end = dec.raw_decode(text, m.end())
        except (json.JSONDecodeError, ValueError):
            continue
        out[m.group(1)] = val
    return out


def load_sidecars(sidecars_dir: Path | str):
    """All .claims.vsm + .depth.vsm in a dir -> documents view.
    Keys casefolded: ADDENDUM.claims and addendum.depth are the SAME doc.
    Returns (docs, stats): docs[name] = {claims, depth, ...}."""
    d = Path(sidecars_dir)
    docs: dict[str, dict] = {}
    claims_parsed = claims_failed = 0
    n_claims_files = n_depth_files = 0
    for f in sorted(d.glob("*.claims.vsm")):
        n_claims_files += 1
        a = parse_vsm_assignments(f.read_text(errors="replace"))
        cl = a.get("claims")
        name = f.stem.replace(".claims", "").casefold()
        if isinstance(cl, list):
            claims_parsed += len(cl)
            docs.setdefault(name, {})["claims"] = cl
            docs[name]["claims_src"] = f.name
        else:
            claims_failed += 1
    for f in sorted(d.glob("*.depth.vsm")):
        n_depth_files += 1
        a = parse_vsm_assignments(f.read_text(errors="replace"))
        name = f.stem.replace(".depth", "").casefold()
        docs.setdefault(name, {})["depth"] = {k: a.get(k) for k in
                                               ("levels", "tools", "verdict",
                                                "related_sources")}
        docs[name]["depth_src"] = f.name
    return docs, {"docs": len(docs), "claims_parsed": claims_parsed,
                  "claims_files_failed": claims_failed,
                  "claims_files": n_claims_files,
                  "depth_files": n_depth_files,
                  "paired": sum(1 for v in docs.values()
                                if "claims" in v and "depth" in v)}


def load_gaps(gaps_dir: Path | str):
    gaps = []
    for f in sorted(Path(gaps_dir).glob("*.gap.json")):
        try:
            g = json.loads(f.read_text(errors="replace"))
        except json.JSONDecodeError:
            continue
        gaps.append({"id": g.get("id") or f.stem, "trigger": g.get("trigger", ""),
                     "source": f.name})
    return gaps, {"count": len(gaps), "dir": str(gaps_dir)}


def load_rules(rules_md: Path | str):
    rows = []
    pat = re.compile(r"^\|\s*(R[\d.]+|doc_sync)\s*\|\s*([^|]+)\|", re.MULTILINE)
    for m in pat.finditer(Path(rules_md).read_text(errors="replace")):
        rows.append({"id": m.group(1), "name": m.group(2).strip()})
    return rows, {"count": len(rows)}


def load_experiments(paper_data: Path | str):
    txt = Path(paper_data).read_text(errors="replace")
    ids = sorted(set(re.findall(r"\bEXP-[A-Za-z0-9-]+", txt)))
    return [{"id": i} for i in ids], {"count": len(ids)}


def load_decisions(focus_json: Path | str):
    entries = json.loads(Path(focus_json).read_text(errors="replace"))
    rows = [{"ref": e.get("ref"), "status": e.get("status", "?")}
            for e in entries if isinstance(e, dict)]
    return rows, {"count": len(rows),
                  "active": sum(1 for r in rows if r["status"] == "active")}


def macro_census(sources: list[tuple[str, list, dict]]) -> dict:
    """kind -> {count, source, ...stats}. Deterministic, with denominators."""
    out = {}
    for kind, objs, stats in sources:
        out[kind] = {"count": len(objs), "stats": stats}
    return out


# ── layouts (deterministic) ───────────────────────────────────────────────────

def tree_layout(root: str, children: dict[str, list[str]]) -> dict[str, tuple]:
    """Tidy-tree: leaves get consecutive x, depth gets y. No randomness."""
    pos: dict[str, tuple] = {}
    counter = [0.0]

    def walk(node: str, depth: int) -> None:
        kids = sorted(children.get(node, []))
        if not kids:
            pos[node] = (counter[0], -float(depth))
            counter[0] += 1.0
            return
        for k in kids:
            walk(k, depth + 1)
        xs = [pos[k][0] for k in kids]
        pos[node] = (sum(xs) / len(xs), -float(depth))

    walk(root, 0)
    return pos


def radial_layout(items: list[str], center: tuple = (0.0, 0.0),
                  radius: float = 1.0) -> dict[str, tuple]:
    """Fixed-angle ring: item i at angle 2*pi*i/n starting at top (sorted
    input order preserved — caller sorts)."""
    n = max(len(items), 1)
    pos = {}
    for i, it in enumerate(sorted(items)):
        ang = math.pi / 2 - 2 * math.pi * i / n
        pos[it] = (center[0] + radius * math.cos(ang),
                   center[1] + radius * math.sin(ang))
    return pos


def layered_layout(layers: dict[str, list[str]]) -> dict[str, tuple]:
    """kind -> column x (stable order of dict keys), items stacked in y."""
    pos: dict[str, tuple] = {}
    for col, kind in enumerate(sorted(layers)):
        items = layers[kind]
        n = max(len(items), 1)
        for row, name in enumerate(items):
            pos[name] = (float(col), -float(row) / max(n - 1, 1) * 10)
    return pos


# ── renderers (matplotlib, portable) ─────────────────────────────────────────

def truth_color(truth: str) -> str:
    return TRUTH_FILL.get(str(truth).upper(), TRUTH_FILL["UNKNOWN"])


def draw_tree(ax, g: dict, title: str = "") -> None:
    children: dict[str, list[str]] = {}
    ids = [n["id"] for n in g["nodes"]]
    for a, b in g["edges"]:
        children.setdefault(a, []).append(b)
    roots = [i for i in ids if i not in {b for _, b in g["edges"]}]
    pos = {}
    for r in sorted(roots):
        sub = tree_layout(r, children)
        offset = max((x for x, _ in pos.values()), default=-1.0) + 2.0
        for k, (x, y) in sub.items():
            pos[k] = (x + (offset if pos else 0.0), y)
    by_id = {n["id"]: n for n in g["nodes"]}
    for a, b in g["edges"]:
        if a in pos and b in pos:
            ax.plot([pos[a][0], pos[b][0]], [pos[a][1], pos[b][1]],
                    color="#999999", lw=0.8, zorder=1)
    for nid, (x, y) in pos.items():
        n = by_id.get(nid, {})
        ax.scatter([x], [y], s=260, c=truth_color(n.get("truth", "UNKNOWN")),
                   edgecolors="#444444", linewidths=0.7, zorder=2)
        label = (n.get("name") or nid)[:16]
        ax.annotate(label, (x, y), fontsize=6.5, ha="center", va="center",
                    zorder=3)
    ax.set_title(title, fontsize=10)
    ax.axis("off")


def draw_radial(ax, center_id: str, spokes: dict[str, list[str]],
                title: str = "") -> None:
    """center -> type hubs -> count labels (2-level meso view)."""
    hubs = radial_layout(list(spokes), radius=1.0)
    ax.scatter([0], [0], s=900, c=KIND_FILL["document"],
               edgecolors="#222222", linewidths=1.0, zorder=3)
    ax.annotate(center_id, (0, 0), fontsize=8, ha="center", va="center",
                weight="bold", zorder=4)
    for hub, members in sorted(spokes.items()):
        x, y = hubs[hub]
        ax.plot([0, x], [0, y], color="#888888", lw=1.0, zorder=1)
        ax.scatter([x], [y], s=420, c=KIND_FILL["claim"],
                   edgecolors="#444444", linewidths=0.8, zorder=3)
        ax.annotate(f"{hub}\n×{len(members)}", (x, y), fontsize=7,
                    ha="center", va="center", zorder=4)
        # hojas compactas alrededor del hub (hasta 8, orden fijo)
        members_sorted = sorted(members)
        for j, _m in enumerate(members_sorted[:8]):
            ang = (j / max(len(members_sorted), 1)) * 2 * math.pi
            lx = x + 0.22 * math.cos(ang)
            ly = y + 0.22 * math.sin(ang)
            ax.scatter([lx], [ly], s=40, c="#f8f9fa",
                       edgecolors="#999999", linewidths=0.4, zorder=2)
        if len(members) > 8:
            ax.annotate(f"+{len(members) - 8}", (x + 0.24, y - 0.18),
                        fontsize=6, color="#666666")
    ax.set_title(title, fontsize=10)
    ax.axis("off")


def draw_layers(ax, layers: dict[str, list[str]], edges: list[tuple[str, str]],
                title: str = "", cap: int = 26) -> None:
    """Macro: one column per node kind, capped dots + '+N' tail marker,
    sparse edges. Positions built directly (name collisions impossible)."""
    pos: dict[str, tuple] = {}
    kind_of: dict[str, str] = {}
    for col, kind in enumerate(sorted(layers)):
        items = sorted(layers[kind])
        shown = items[:cap]
        for row, name in enumerate(shown):
            pos[name] = (float(col), -0.45 * row)
            kind_of[name] = kind
        if len(items) > cap:
            tail = f"+{len(items) - cap} {kind}"
            pos[tail] = (float(col), -0.45 * len(shown) - 0.7)
            kind_of[tail] = kind
    for col, kind in enumerate(sorted(layers)):
        x = float(col)
        ax.text(x, 0.9, kind, ha="center", va="bottom", fontsize=9,
                weight="bold", color="#333333")
        ax.text(x, 0.45, f"n={len(layers[kind])}", ha="center", va="bottom",
                fontsize=7, color="#666666")
    for a, b in edges:
        if a in pos and b in pos:
            ax.plot([pos[a][0], pos[b][0]], [pos[a][1], pos[b][1]],
                    color="#bbbbbb", lw=0.6, zorder=1)
    for name, (x, y) in sorted(pos.items()):
        kind = kind_of.get(name, "claim")
        if name.startswith("+"):  # cola de cap
            ax.annotate(name, (x, y), fontsize=6.5, ha="center", va="center",
                        color="#333333",
                        bbox=dict(boxstyle="round,pad=0.15", fc="#f1f3f5",
                                  ec="#adb5bd", lw=0.5))
            continue
        ax.scatter([x], [y], s=70, c=KIND_FILL.get(kind, "#eeeeee"),
                   edgecolors="#555555", linewidths=0.5, zorder=2)
    ax.set_title(title, fontsize=10)
    ax.axis("off")
