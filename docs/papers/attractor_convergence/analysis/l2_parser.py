"""l2_parser — L2 theorem/structure extraction over LaTeX sources.

Deterministic-first (R10): regex over canonical .tex sources, no randomness,
no network, no time-dependent behaviour. Designed for the F2/L2 analysis of
the Attractor Convergence × Fierro × addendum set (docs/plans: claim_ingest
layer 2 — theorem hypothesis→conclusion records).

Sources (paper_data.vsm is canonical):
  - paper:  docs/papers/attractor_convergence/main.tex
  - reply:  docs/correspondence/fierro/addendum_omega/addendum.tex
  - review: analysis/data/fierro_review.txt (PDF→text; no LaTeX source)

Usage:
  python3 l2_parser.py <file.tex> [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ENV_KINDS = ("theorem", "lemma", "corollary", "proposition", "definition", "remark")

_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(ENV_KINDS) + r")\}(?:\[([^\]]*)\])?(.*?)\\end\{\1\}",
    re.DOTALL,
)
_ENUM_RE = re.compile(r"\\begin\{enumerate\}(.*?)\\end\{enumerate\}", re.DOTALL)
_ITEM_RE = re.compile(r"\\item\b")
_BOLD_RE = re.compile(r"\\textbf\{(.*?)\}", re.DOTALL)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref)\{([^}]+)\}")
_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
_SECTION_RE = re.compile(r"\\section\*\{([^}]+)\}")

# deterministic hypothesis connectors (statement-level, word-boundary match)
_HYP_MARKERS = ("with", "Under", "if", "Given", "Suppose", "Let", "Then")

# load-bearing figures: (id, token) — curated vs paper_data.vsm census
FIGURE_TOKENS = (
    ("lambda_max", "-0.01005"),   # EXP-LY-01
    ("thermal_ceiling", "0.9377"), # exp(7)
    ("ns_ticks", "3000"),          # EXP-NS-01 (FIERRO-NS-RANGE)
    ("psi_threshold", "0.79"),     # exp(8)
    ("soplo_freq", "162.8"),       # EXP-SOPLO-01
    ("basin_floor", "0.945"),      # EXP-MC-01
)


def _norm(text: str) -> str:
    """Collapse whitespace; drop LaTeX comments on their own lines."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("%"):
            continue
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _split_refs(blob: str) -> list[str]:
    return [c.strip() for piece in blob.split(",") if (c := piece.strip())]


def parse_envs(tex: str) -> list[dict]:
    """Extract theorem-like environments as structured records."""
    records = []
    for m in _ENV_RE.finditer(tex):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        line = tex.count("\n", 0, m.start()) + 1

        enum = _ENUM_RE.search(body)
        conclusions: list[dict] = []
        statement = body
        if enum:
            statement = body[: enum.start()] + body[enum.end():]
            for item in _ITEM_RE.split(enum.group(1)):
                item = item.strip()
                if not item:
                    continue
                head_m = _BOLD_RE.search(item)
                conclusions.append({
                    "head": _norm(head_m.group(1)) if head_m else _norm(item[:80]),
                    "text": _norm(item),
                })

        labels = _LABEL_RE.findall(body)
        refs: list[str] = []
        for r in _REF_RE.findall(body):
            refs.extend(_split_refs(r))
        cites: list[str] = []
        for c in _CITE_RE.findall(body):
            cites.extend(_split_refs(c))

        st = _norm(_LABEL_RE.sub("", statement))  # labels son metadata, no statement
        hyp_markers = [mk for mk in _HYP_MARKERS
                       if re.search(r"\b" + re.escape(mk) + r"\b", st)]
        records.append({
            "kind": kind,
            "name": name,
            "label": labels[0] if labels else None,
            "labels": labels,
            "line": line,
            "statement": st,
            "conclusions": conclusions,
            "hyp_markers": hyp_markers,
            "refs": sorted(set(refs)),
            "cites": sorted(set(cites)),
        })
    return records


def labels_and_refs(tex: str) -> tuple[set[str], set[str]]:
    labels = set(_LABEL_RE.findall(tex))
    refs: set[str] = set()
    for r in _REF_RE.findall(tex):
        refs.update(_split_refs(r))
    return labels, refs


def dangling_refs(tex: str) -> list[str]:
    labels, refs = labels_and_refs(tex)
    return sorted(refs - labels)


def figure_tokens(tex: str) -> dict[str, bool]:
    return {fid: (token in tex) for fid, token in FIGURE_TOKENS}


def addendum_sections(tex: str) -> list[str]:
    return [_norm(s) for s in _SECTION_RE.findall(tex)]


def analyse(tex_path: Path) -> dict:
    tex = tex_path.read_text(errors="replace")
    return {
        "source": str(tex_path),
        "records": parse_envs(tex),
        "dangling_refs": dangling_refs(tex),
        "figure_tokens": figure_tokens(tex),
        "env_count": len(parse_envs(tex)),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    as_json = "--json" in argv
    result = analyse(path)
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"source: {result['source']}")
    print(f"records: {result['env_count']}")
    for r in result["records"]:
        print(f"  L{r['line']:5d}  {r['kind']:<11} {r['name'] or '':<55} "
              f"conclusions={len(r['conclusions'])} label={r['label']}")
    print(f"dangling refs: {result['dangling_refs'] or 'none'}")
    missing = [k for k, v in result["figure_tokens"].items() if not v]
    print(f"figure tokens missing: {missing or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


# ── B2: A0/A0.1 inventory (agent-layer interface classification) ──────────────

_A0_RE = re.compile(r"A0\.1|\bA0\b|coercion")


def section_map(tex: str) -> list[tuple[int, str]]:
    """(line, section-title) for every \\section{...} in document order."""
    out = [(1, "(preamble)")]
    for i, ln in enumerate(tex.splitlines(), 1):
        m = re.match(r"\\(?:sub)*section\*?\{([^}]*)\}", ln.strip())
        if m:
            out.append((i, _norm(m.group(1))))
    return out


def _section_for(secs: list[tuple[int, str]], line: int) -> str:
    cur = "(preamble)"
    for ln, name in secs:
        if ln <= line:
            cur = name
        else:
            break
    return cur


def a0_inventory(tex: str) -> list[dict]:
    """All A0/A0.1/coercion mentions with line + nearest section."""
    secs = section_map(tex)
    rows = []
    for i, ln in enumerate(tex.splitlines(), 1):
        s = ln.strip()
        if s.startswith("%"):
            continue
        if _A0_RE.search(s):
            rows.append({"line": i, "section": _section_for(secs, i), "snippet": _norm(s)[:100]})
    return rows


# ── C: Fierro ↔ addendum ↔ paper correlation (layer2b seed) ───────────────────

def fierro_bullets(txt: str) -> list[str]:
    """Objection bullets (•). Drops any preamble before the first bullet."""
    first = txt.find("•")
    body = txt[first:] if first >= 0 else txt
    parts = [p for p in re.split(r"[•▪]", body) if p.strip()]
    return [_norm(p) for p in parts]


def addendum_q_sections(tex: str) -> dict[int, str]:
    """Content of \\section*{N. ...} blocks (N = 1..3) until the next section."""
    heads = list(_SECTION_RE.finditer(tex))
    out: dict[int, str] = {}
    for i, m in enumerate(heads):
        title = m.group(1)
        num = re.match(r"([123])\.", _norm(title))
        if not num:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(tex)
        out[int(num.group(1))] = _norm(tex[m.end():end])
    return out


# deterministic evidence signatures: (doc, required substrings)
_Q_SIGNATURES = {
    1: {
        "fierro": ("convexe", "Brower"),
        "addendum": {1: ("convexity", "Krylov", "Banach")},
        "paper_any": ("Brouwer is not needed",),                      # remark L767
        "paper_env": ("thm:hybrid_invariance", ("requires the convexity",)),
    },
    2: {
        "fierro": ("invariant", "f0 (ω)"),
        "addendum": {2: ("Invariance", "L_f", "Lipschitz")},
        "paper_any": ("not merely postulated",),                      # remark L767 title
        "paper_env": ("thm:hybrid_invariance", ("do not claim per-step non-expansiveness",
                                                "Lipschitz bound")),
    },
    3: {
        "fierro": ("noise", "σ · η(t)"),
        "addendum": {3: ("stochastic viability", "Aubin", "4.0", "Meyn")},
        "paper_any": (),                                              # no global snippet
        "paper_env": ("thm:hybrid_invariance", ("sustained noise up to",)),
    },
}


def correlate(tex_main: str, tex_addendum: str, txt_fierro: str) -> list[dict]:
    """Build the discharge matrix Q1..Q3 with machine-checked evidence."""
    bullets = fierro_bullets(txt_fierro)
    qsecs = addendum_q_sections(tex_addendum)
    recs = {r["label"]: r for r in parse_envs(tex_main) if r["label"]}
    glob_norm = _norm(tex_main)  # line-wrapped snippets only match normalized text
    rows = []
    for qi in (1, 2, 3):
        sig = _Q_SIGNATURES[qi]
        b_ok = all(any(term in b for b in bullets) for term in sig["fierro"]) if len(bullets) >= qi else False
        q_text = qsecs.get(qi, "")
        a_ok = all(t in q_text for t in sig["addendum"].get(qi, ()))
        env_label, terms = sig["paper_env"]
        env = recs.get(env_label, {})
        env_blob = env.get("statement", "") + " " + " ".join(c["text"] for c in env.get("conclusions", []))
        e_ok = all(t in env_blob for t in terms)
        g_ok = all(t in glob_norm for t in sig["paper_any"])
        rows.append({
            "qi": qi,
            "objection": bullets[qi - 1][:90] if len(bullets) >= qi else "??",
            "fierro_ok": b_ok,
            "addendum_ok": a_ok,
            "paper_ok": e_ok and g_ok,
            "status": "DISCHARGED" if (b_ok and a_ok and e_ok and g_ok) else "OPEN",
        })
    return rows


# ── NB04: L2-full — inventario de ecuaciones, grafo de dependencias, ──────────
#    proof-vs-asserted (audit de demostraciones) — ordenado por main.depth.vsm

_EQ_ENV_RE = re.compile(r"\\begin\{equation\}(.*?)\\end\{equation\}", re.DOTALL)
_PROOF_ENV = "\\begin{proof}"
_DISCHARGE_RE = re.compile(r"discharged by measurement|discharged by", re.I)
_ASSERT_RE = re.compile(
    r"\bfollows from\b|\bimmediate(?:ly)?\b|\bstandard (?:argument|result|fact|approach)\b"
    r"|\bby construction\b|\btrivial(?:ly)?\b|\bstraightforward\b", re.I)


def equation_inventory(tex: str) -> list[dict]:
    """Every numbered equation in document order: \\begin{equation} blocks
    PLUS loose \\label{eq:*} outside blocks. Each row: idx, label, block,
    line, section, snippet, refs (deterministic, R10)."""
    secs = section_map(tex)
    rows: list[dict] = []
    spans: list[tuple[int, int]] = []
    for m in _EQ_ENV_RE.finditer(tex):
        body = m.group(1)
        spans.append(m.span())
        labels = _LABEL_RE.findall(body)
        refs: list[str] = []
        for r in _REF_RE.findall(body):
            refs.extend(_split_refs(r))
        rows.append({
            "label": labels[0] if labels else None,
            "block": True,
            "line": tex.count("\n", 0, m.start()) + 1,
            "snippet": _norm(_LABEL_RE.sub("", body))[:90],
            "refs": sorted(set(refs)),
        })
    for m in _LABEL_RE.finditer(tex):
        lab = m.group(1)
        if not lab.startswith("eq:"):
            continue
        if any(s <= m.start() < e for s, e in spans):
            continue  # ya capturado con su bloque
        rows.append({
            "label": lab,
            "block": False,
            "line": tex.count("\n", 0, m.start()) + 1,
            "snippet": "",
            "refs": [],
        })
    rows.sort(key=lambda r: r["line"])
    for i, r in enumerate(rows, 1):
        r["idx"] = i
        r["section"] = _section_for(secs, r["line"])
    return rows


def dependency_graph(tex: str) -> dict:
    """Nodes = labeled envs + labeled equations; edges = ref -> resolved label
    (unresolved refs reported as dangling, never emitted as edges)."""
    labels, _ = labels_and_refs(tex)
    nodes: list[dict] = []
    edges: set[tuple[str, str]] = set()
    dangling: set[str] = set()
    for r in parse_envs(tex):
        nid = r["label"] or f"{r['kind']}@L{r['line']}"
        nodes.append({"id": nid, "kind": r["kind"], "line": r["line"]})
        for t in r["refs"]:
            if t in labels:
                edges.add((nid, t))
            else:
                dangling.add(t)
    for eq in equation_inventory(tex):
        if not eq["label"]:
            continue
        nodes.append({"id": eq["label"], "kind": "equation", "line": eq["line"]})
        for t in eq["refs"]:
            if t in labels:
                edges.add((eq["label"], t))
            else:
                dangling.add(t)
    return {
        "nodes": sorted(nodes, key=lambda n: (n["line"], n["id"])),
        "edges": sorted(edges),
        "dangling": sorted(dangling),
        "denominator": {"nodes": len(nodes), "edges": len(edges),
                        "dangling": len(dangling)},
    }


def proof_audit(tex: str) -> list[dict]:
    """proof-vs-asserted per theorem-class env: classification is
    formal-proof (proof env in body OR within 400 chars after the env)
    | discharged-by-measurement | asserted (standard markers) | statement-only.
    Denominator: every env in ENV_KINDS, no skips."""
    secs = section_map(tex)
    rows = []
    for m in _ENV_RE.finditer(tex):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        labels = _LABEL_RE.findall(body)
        window = body + " " + tex[m.end(): m.end() + 400]
        basis = None
        if _PROOF_ENV in body:
            basis = "in_body"
        elif _PROOF_ENV in window:
            basis = "adjacent"
        if basis:
            cls = "formal-proof"
            markers = [basis]
        elif _DISCHARGE_RE.search(_norm(body)):
            cls = "discharged-by-measurement"
            markers = sorted(set(_DISCHARGE_RE.findall(_norm(body))))
        else:
            found = sorted(set(_ASSERT_RE.findall(_norm(body))))
            cls = "asserted" if found else "statement-only"
            markers = found
        rows.append({
            "kind": kind,
            "name": _norm(name) if name else "",
            "label": labels[0] if labels else None,
            "line": tex.count("\n", 0, m.start()) + 1,
            "section": _section_for(secs, tex.count("\n", 0, m.start()) + 1),
            "classification": cls,
            "markers": markers,
        })
    return rows
