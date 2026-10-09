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
