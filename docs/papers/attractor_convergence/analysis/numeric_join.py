"""numeric_join — L5: join numérico paper ↔ addendum ↔ paper_data
+ layer2a abstract ↔ body.

Deterministic (R10): fixed regexes, fixed normalization, no randomness,
no clock. Registry-driven: paper_data.vsm `numbers="..."` fields are the
COVERAGE-DENOMINATOR; each number is checked for literal presence in
main.tex and addendum.tex (unicode minus normalized; decimals also try a
trailing-zeros variant, documented rule — no fuzzy matching).

layer2a: abstract span vs body of main.tex via claim_ingest extract
patterns (loaded by file path — no package init, no vos_kernel needed):
numeric candidates join on value, theorem candidates join on exact
sentence (whitespace-collapsed). Misses stay visible (denominator rule).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_P_CALL = re.compile(r"^\s*(exp|trilogy|real_gov)\(([^,\n]+)", re.M)
_P_NUMBERS = re.compile(r'numbers\s*=\s*"([^"]+)"')
_P_DEC = re.compile(r"[-−]?\d+\.\d+")
_P_INT3 = re.compile(r"(?<![\d.])\d{3,}(?![\d.])")
_P_YEAR = re.compile(r"^[12]\d{3}$")
_P_WORD_BEFORE = re.compile(r"([\wθλβδΔ_\s=→]{1,40})$")


# ── rutas (R1: relativas al fuente; fallback data/ = sync_to_114) ────────────

def _root() -> Path | None:
    here = Path(__file__).resolve().parent
    for r in (here, *here.parents):
        if (r / "docs" / "papers").is_dir():
            return r
    return None


def _pick(*rel: str) -> Path:
    root = _root()
    if root is not None:
        p = root.joinpath(*rel)
        if p.exists():
            return p
    fb = Path(__file__).resolve().parent / "data" / rel[-1]
    if fb.exists():
        return fb
    raise FileNotFoundError(f"{'/'.join(rel)} no encontrado (repo ni data/)")


def paper_data_path() -> Path:
    return _pick("docs", "papers", "attractor_convergence", "paper_data.vsm")


def main_tex_path() -> Path:
    return _pick("docs", "papers", "attractor_convergence", "main.tex")


def addendum_tex_path() -> Path:
    return _pick("docs", "correspondence", "fierro", "addendum_omega",
                 "addendum.tex")


def _patterns_module():
    root = _root()
    cands = []
    if root is not None:
        cands.append(root / "packages" / "framework" / "claim_ingest" /
                     "extract" / "patterns.py")
    cands.append(Path(__file__).resolve().parent / "data" / "patterns.py")
    for c in cands:
        if c.is_file():
            spec = importlib.util.spec_from_file_location("_ci_patterns", c)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("claim_ingest patterns.py no encontrado")


def _norm(s: str) -> str:
    """Unicode minus → ascii; whitespace colapsado para joins de texto."""
    return re.sub(r"\s+", " ", s.replace("\u2212", "-"))


# ── 1. registro paper_data: entries + numbers ───────────────────────────────

def registry_entries(pd_text: str) -> list[dict]:
    """Entradas exp/trilogy/real_gov con su campo numbers (o su ausencia)."""
    lines = pd_text.splitlines()
    calls = [(i, m.group(1), m.group(2).strip().strip('"'))
             for i, l in enumerate(lines)
             for m in [_P_CALL.match(l)] if m]
    out = []
    for idx, (i, form, eid) in enumerate(calls):
        end = calls[idx + 1][0] if idx + 1 < len(calls) else len(lines)
        span = "\n".join(lines[i:end])
        nm = _P_NUMBERS.search(span)
        out.append({"id": eid, "form": form, "line": i + 1,
                    "has_numbers": nm is not None,
                    "numbers": nm.group(1) if nm else None})
    return out


def numbers_tokens(numbers: str) -> list[dict]:
    """Decimales + enteros ≥3 dígitos (años 19xx/20xx excluidos)."""
    toks: list[dict] = []
    for m in _P_DEC.finditer(numbers):
        raw = m.group(0).lstrip("−")
        if _P_YEAR.match(raw.lstrip("-")):
            continue
        before = _P_WORD_BEFORE.search(numbers[:m.start()])
        toks.append({"value": raw.replace("−", ""),
                     "label": (before.group(1).strip() if before else "")})
    for m in _P_INT3.finditer(numbers):
        raw = m.group(0)
        if _P_YEAR.match(raw):
            continue
        before = _P_WORD_BEFORE.search(numbers[:m.start()])
        toks.append({"value": raw,
                     "label": (before.group(1).strip() if before else "")})
    # dedup por valor, orden estable
    seen: set = set()
    return [t for t in toks if not (t["value"] in seen or
                                    seen.add(t["value"]))]


def _variants(value: str) -> list[str]:
    """Valor literal + única variante documentada: zeros finales cortados
    (siempre ≥1 dígito tras el punto: 4.00 → 4.0, no → 4)."""
    out = [value]
    if "." in value:
        ip, _, fp = value.partition(".")
        fp2 = fp.rstrip("0") or "0"
        trimmed = f"{ip}.{fp2}"
        if trimmed != value:
            out.append(trimmed)
    return out


def _present(value: str, text: str) -> bool:
    return any(v in text for v in _variants(value))


# ── 2. join matrix paper ↔ addendum ↔ paper_data ─────────────────────────────

def join_rows(entries: list[dict], paper: str,
              addendum: str) -> tuple[list[dict], dict]:
    paper_n, add_n = _norm(paper), _norm(addendum)
    rows: list[dict] = []
    for e in entries:
        if not e["has_numbers"]:
            rows.append({**{k: e[k] for k in ("id", "form", "line")},
                         "value": None, "label": None,
                         "in_paper": None, "in_addendum": None})
            continue
        for t in numbers_tokens(e["numbers"]):
            rows.append({**{k: e[k] for k in ("id", "form", "line")},
                         "value": t["value"], "label": t["label"],
                         "in_paper": _present(t["value"], paper_n),
                         "in_addendum": _present(t["value"], add_n)})
    checked = [r for r in rows if r["value"] is not None]
    n = len(checked)
    n_paper = sum(1 for r in checked if r["in_paper"])
    n_add = sum(1 for r in checked if r["in_addendum"])
    n_both = sum(1 for r in checked if r["in_paper"] and r["in_addendum"])
    n_none = sum(1 for r in checked
                 if not r["in_paper"] and not r["in_addendum"])
    summary = {
        "entries_total": len(entries),
        "entries_with_numbers": sum(1 for e in entries
                                    if e["has_numbers"]),
        "entries_without_numbers": [e["id"] for e in entries
                                    if not e["has_numbers"]],
        "tokens_checked": n,
        "in_paper": n_paper,
        "in_addendum": n_add,
        "in_both": n_both,
        "in_neither": n_none,
        "ratio_paper": round(n_paper / n, 4) if n else 0.0,
        "ratio_addendum": round(n_add / n, 4) if n else 0.0,
        "ratio_both": round(n_both / n, 4) if n else 0.0,
    }
    return rows, summary


# ── 3. cruce directo addendum ↔ paper (cantidades compartidas, literal tex) ──

def addendum_paper_cross(paper: str, addendum: str) -> list[dict]:
    """3 anclas fijas (FIERRO-NS-RANGE): N=3000 ticks, límite de ruido σ,
    y la CONVENCIÓN σ_in vs 4×‖x‖ — los literales tex se comparan crudos
    (solo el unicode minus se normaliza vía _norm para los needles suaves)."""
    p, a = _norm(paper), _norm(addendum)
    rows = []

    n_add = bool(re.search(r"N\s*=\s*3000", a))
    n_pap = "N=3000" in p
    rows.append({"id": "ns_ticks_N", "in_addendum": n_add,
                 "in_paper": n_pap, "verdict": "match"
                 if (n_add and n_pap) else "miss",
                 "note": "N=3000 ticks por nivel de ruido (EXP-NS-01)"})

    sig_add = "4.0\\,\\|x\\|" in addendum
    sig_pap_phrase = "four times the state norm" in p
    sig_pap_latex = bool(re.search(r"\\sigma[^.\n]{0,40}4\.0", p))
    rows.append({"id": "sigma_noise_bound",
                 "in_addendum": sig_add,
                 "in_paper": sig_pap_latex or sig_pap_phrase,
                 "verdict": "match_latex" if (sig_add and sig_pap_latex)
                 else ("match_phrase" if (sig_add and sig_pap_phrase)
                       else "miss"),
                 "note": "addendum escribe 4.0‖x‖ (convención noise=4×norm); "
                         "el paper lo dice en frase 'four times the state "
                         "norm' — literales distintos, misma cantidad"})

    sin_add = "σ_in∈[0,2.0]" in addendum or "sweep σ_in" in addendum
    sin_pap = bool(re.search(r"\\sigma\$ up to \$2\.0", p))
    rows.append({"id": "sigma_in_convention",
                 "in_addendum": sin_add, "in_paper": sin_pap,
                 "verdict": "match" if (sin_add and sin_pap) else "miss",
                 "note": "σ_in ∈ [0,2.0] (param del sweep) — coexiste con "
                         "noise=4×norm; NO es contradicción si se leen las "
                         "dos convenciones"})
    return rows


# ── 4. layer2a: abstract ↔ body ──────────────────────────────────────────────

def abstract_body(tex: str) -> dict:
    m0 = re.search(r"\\begin\{abstract\}", tex)
    m1 = re.search(r"\\end\{abstract\}", tex)
    if not (m0 and m1):
        raise ValueError("abstract no encontrado en main.tex")
    abstract = tex[m0.end():m1.start()]
    body = tex[:m0.start()] + tex[m1.end():]
    body_n = _norm(body)

    pat = _patterns_module()
    cands = pat.extract_deterministic(abstract,
                                      sections={"abstract": abstract})
    num = [c for c in cands if c.get("type") == "number"
           and c.get("value") is not None]
    thm = [c for c in cands if c.get("type") == "theorem"]

    def num_eligible(v: str) -> bool:
        return "." in v or len(v.lstrip("-")) >= 3

    num_rows = []
    for c in num:
        v = str(c["value"])
        if not num_eligible(v):
            num_rows.append({"value": v, "eligible": False,
                             "matched": None})
            continue
        num_rows.append({"value": v, "eligible": True,
                         "matched": _present(v, body_n)})

    thm_rows = []
    for c in thm:
        sent = _norm(c["text"])
        thm_rows.append({"matched": sent in body_n,
                         "text": sent[:70]})

    n_chk = [r for r in num_rows if r["eligible"]]
    n_thm = len(thm_rows)
    return {
        "abstract_candidates": len(cands),
        "numeric_total": len(num_rows),
        "numeric_checked": len(n_chk),
        "numeric_matched": sum(1 for r in n_chk if r["matched"]),
        "numeric_miss": [r["value"] for r in n_chk if not r["matched"]],
        "theorem_total": n_thm,
        "theorem_matched": sum(1 for r in thm_rows if r["matched"]),
        "theorem_miss": [r["text"] for r in thm_rows if not r["matched"]],
        "ratio_numeric": (round(sum(1 for r in n_chk if r["matched"]) /
                                len(n_chk), 4) if n_chk else 0.0),
        "ratio_theorem": (round(sum(1 for r in thm_rows if r["matched"]) /
                                n_thm, 4) if n_thm else 0.0),
    }


# ── runner ───────────────────────────────────────────────────────────────────

def run() -> dict:
    pd_text = paper_data_path().read_text(errors="replace")
    paper = main_tex_path().read_text(errors="replace")
    add = addendum_tex_path().read_text(errors="replace")
    entries = registry_entries(pd_text)
    rows, summary = join_rows(entries, paper, add)
    return {"join_summary": summary, "join_rows": rows,
            "cross": addendum_paper_cross(paper, add),
            "layer2a": abstract_body(paper)}
