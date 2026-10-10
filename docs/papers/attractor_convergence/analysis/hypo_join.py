"""hypo_join — L4: hipótesis → EXP-* → valores en results.vsm (COVERAGE-DENOMINATOR).

Deterministic (R10): fixed regexes, sorted file scan, no randomness, no
clock. Sources: docs/papers/attractor_convergence/main.tex (§Hypotheses,
tab:realgov table, Findings subsections) joined against
docs/experiments/*/results.vsm. Plan: NB03 cell L4 ("hipotesis -> EXP-*
-> valores en results.vsm (COVERAGE-DENOMINATOR)").

Resolution classes (honest denominator — nothing is silently "matched"):
  exact          — EXP id from section window/span found in a results.vsm
  protocol       — \\texttt{protocol} token == experiments/<stem>/results.vsm
  token          — hyp id occurs in exactly ONE results.vsm (no EXP hint)
  exp_no_results — EXP id known in the section, no results.vsm carries it
  ambiguous      — hyp id occurs in >1 results.vsm, no EXP hint
  none           — no candidate at all
"""
from __future__ import annotations

import re
from pathlib import Path

KINDS = ("named", "table", "finding")
RESOLUTIONS = ("exact", "protocol", "token", "exp_no_results",
               "ambiguous", "none")

_P_NAMED = re.compile(r"\\item\[\$H_\\text\{(\w+)\}\$\]")
_P_TABLE = re.compile(r"^(H\d)\b[^\n]*?&\s*\\textbf\{([^}]*)\}")
_P_FIND = re.compile(r"^\\textbf\{(H\d)\b([^}]*)\}")
_P_LABEL = re.compile(r"\\label\{(sec:[^}]+)\}")
_P_SECTION = re.compile(r"\\section\*?\{")
_P_SECNAME = re.compile(r"\\section\*?\{([^}]+)\}")
_P_EXP = re.compile(r"EXP-[A-Z0-9]+(?:-[A-Z0-9]+)*")
_P_NUM_ASSIGN = re.compile(r"[\w.]+\s*[=:]\s*(-?\d[\d.]*)")
_P_TEXTTT = re.compile(r"\\texttt\{([^}]{3,40})\}")
_P_RESULTS_ID = re.compile(r"results\(([\w-]+)")


# ── rutas (R1: relativas al fuente; fallback data/ = sync_to_114) ────────────

def _root() -> Path | None:
    here = Path(__file__).resolve().parent
    for r in (here, *here.parents):
        if (r / "docs" / "experiments").is_dir() and \
                (r / "docs" / "papers").is_dir():
            return r
    return None


def main_tex_path() -> Path:
    root = _root()
    if root is not None:
        return root / "docs" / "papers" / "attractor_convergence" / "main.tex"
    fb = Path(__file__).resolve().parent / "data" / "main.tex"
    if fb.is_file():
        return fb
    raise FileNotFoundError("main.tex no encontrado (repo ni data/)")


def experiments_dir() -> Path:
    root = _root()
    if root is not None:
        return root / "docs" / "experiments"
    fb = Path(__file__).resolve().parent / "data" / "experiments"
    if fb.is_dir():
        return fb
    raise FileNotFoundError("experiments/ no encontrado (repo ni data/)")


# ── 1. extracción de hipótesis ───────────────────────────────────────────────

def find_hypotheses(tex: str) -> list[dict]:
    """19 hipótesis (orden de aparición): 3 named (§Hypotheses),
    4 table (tab:realgov), 12 finding (Findings de cycling/maxwell)."""
    lines = tex.splitlines()
    labels = [(i, m.group(1)) for i, l in enumerate(lines)
              for m in [_P_LABEL.search(l)] if m]
    sec_starts = [i for i, l in enumerate(lines) if _P_SECTION.search(l)]

    def section_for(line_idx: int) -> str:
        lab = None
        for i, name in labels:
            if i <= line_idx:
                lab = name
            else:
                break
        return lab or "?"

    out: list[dict] = []
    for i, line in enumerate(lines):
        m = _P_NAMED.search(line)
        if m:
            out.append({"id": f"H_{m.group(1)}", "kind": "named",
                        "line": i + 1, "section": section_for(i),
                        "verdict": None, "note": line.strip()[:80]})
            continue
        m = _P_TABLE.match(line)
        if m:
            out.append({"id": m.group(1), "kind": "table",
                        "line": i + 1, "section": section_for(i),
                        "verdict": m.group(2), "note": line.strip()[:80]})
            continue
        m = _P_FIND.match(line)
        if m:
            out.append({"id": m.group(1), "kind": "finding",
                        "line": i + 1, "section": section_for(i),
                        "verdict": None,
                        "note": (m.group(1) + m.group(2)).strip()[:80]})
    return out


def _section_span(lines: list[str], hyp_line0: int) -> tuple[int, int]:
    """[inicio, fin) de la \\section que contiene hyp_line0 (0-based)."""
    starts = [i for i, l in enumerate(lines) if _P_SECTION.search(l)]
    start = 0
    for s in starts:
        if s <= hyp_line0:
            start = s
        else:
            break
    end = next((s for s in starts if s > hyp_line0), len(lines))
    return start, end


# ── 2. mapeo hipótesis → results.vsm ─────────────────────────────────────────

def _results_index(exp_dir: Path) -> list[dict]:
    files = []
    for p in sorted(exp_dir.glob("*/results.vsm")):
        content = p.read_text(errors="replace")
        ids = set(_P_RESULTS_ID.findall(content))
        ids |= set(_P_EXP.findall(content))
        files.append({"path": p, "stem": p.parent.name,
                      "content": content, "exp_ids": ids})
    return files


def map_to_results(hyps: list[dict], tex: str,
                   exp_dir: Path | None = None) -> list[dict]:
    """Resuelve cada hipótesis a un results.vsm (clase + valores)."""
    exp_dir = exp_dir or experiments_dir()
    lines = tex.splitlines()
    index = _results_index(exp_dir)

    rows: list[dict] = []
    for h in hyps:
        h0 = h["line"] - 1
        start, end = _section_span(lines, h0)
        window = "\n".join(lines[max(0, h0 - 30):h0 + 31])
        span = "\n".join(lines[start:end])

        exp_candidates = list(dict.fromkeys(
            _P_EXP.findall(window) or _P_EXP.findall(span)))

        res: dict = {**h, "exp": None, "results": None,
                     "resolution": "none", "verdict_text": None,
                     "n_values": 0, "candidates": []}

        # a) EXP id (ventana cercana, luego span) → results que lo declara
        chosen = None
        for e in exp_candidates:
            res["exp"] = res["exp"] or e
            hit = next((f for f in index if e in f["exp_ids"]), None)
            if hit:
                chosen = hit
                res["resolution"] = "exact"
                break
        # b) protocolo \texttt{...} == stem del directorio (más cercano
        #    a la hipótesis gana — el orden alfabético elegía mal)
        if chosen is None:
            protos = list(dict.fromkeys(
                t.replace("\\_", "_") for t in _P_TEXTTT.findall(span)))
            stems = {f["stem"]: f for f in index}
            best = None
            for t in protos:
                if t not in stems:
                    continue
                pos = span.find(t)
                line_no = span[:pos].count("\n") if pos >= 0 else 1 << 30
                dist = abs((start + line_no) - h0)
                if best is None or dist < best[0]:
                    best = (dist, stems[t])
            if best is not None:
                chosen = best[1]
                res["resolution"] = "protocol"
        # c) token del id en results (1 → token, >1 → ambiguous)
        if chosen is None:
            if exp_candidates and not any(
                    e in f["exp_ids"] for e in exp_candidates for f in index):
                res["resolution"] = "exp_no_results"
            else:
                hits = [f for f in index
                        if re.search(rf"\b{re.escape(h['id'])}\b",
                                     f["content"])]
                res["candidates"] = sorted(f["stem"] for f in hits)
                if len(hits) == 1:
                    chosen = hits[0]
                    res["resolution"] = "token"
                elif len(hits) > 1:
                    res["resolution"] = "ambiguous"

        if chosen is not None:
            res["results"] = str(chosen["path"])
            res["n_values"] = len(
                _P_NUM_ASSIGN.findall(chosen["content"]))
            vm = re.search(
                rf"^\s*{re.escape(h['id'])}\s*[:=]\s*\"([^\n]{{0,80}})",
                chosen["content"], re.M)
            if vm:
                res["verdict_text"] = vm.group(1).strip()
        rows.append(res)
    return rows


# ── 3. COVERAGE-DENOMINATOR ──────────────────────────────────────────────────

def coverage(rows: list[dict]) -> dict:
    total = len(rows)
    n_res = sum(1 for r in rows if r["results"] is not None)
    n_ver = sum(1 for r in rows if r["verdict_text"])
    n_val = sum(1 for r in rows if r["n_values"] > 0)
    by_res = {k: sum(1 for r in rows if r["resolution"] == k)
              for k in RESOLUTIONS}
    gaps = [f"{r['section']}:{r['id']}" for r in rows
            if r["results"] is None]
    return {
        "total_hypotheses": total,
        "with_results_file": n_res,
        "with_verdict": n_ver,
        "with_values": n_val,
        "ratio_results": round(n_res / total, 4) if total else 0.0,
        "ratio_verdict": round(n_ver / total, 4) if total else 0.0,
        "ratio_values": round(n_val / total, 4) if total else 0.0,
        "by_resolution": by_res,
        "gaps": gaps,
    }


def run(tex_path: Path | None = None) -> tuple[list[dict], dict]:
    tex = (tex_path or main_tex_path()).read_text(errors="replace")
    hyps = find_hypotheses(tex)
    rows = map_to_results(hyps, tex)
    return rows, coverage(rows)
