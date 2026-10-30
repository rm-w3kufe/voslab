#!/usr/bin/env python3
"""canon_census.py — stage 1 of the canon audit pipeline.

Builds ONE machine-readable index over the documents AND the code that are
supposed to agree with each other, so that "do these two say the same thing?"
becomes a query instead of a reading session.

Motivation, entirely from real 2026-08-03/04 failures that manual review
missed repeatedly even while actively looking:
  - the same axiom ID defined in 2+ docs with different meanings (A0, A2, A4,
    A12, D7)
  - the same glyph declared with 2+ meanings (⟹ "escalation" vs implication;
    ⊥ "infeasible" vs false; ⊕ never defined as an operation at all)
  - a doc constant contradicting the deployed one (λ(L0)=0.02 vs the live
    clamp floor LAMBDA_MIN=0.05 — unreachable by construction, unnoticed for
    ~2 months)
  - an axiom with no implementation anywhere (A6)
  - two documents with the same purpose, 4 months apart, neither aware of the
    other (docs/archive/spec_2026-10-30/vsl_primer.md vs the 08-03 boot primer)
  - a DRAFT spec with explicit promotion criteria, unassessed for 3 months,
    whose contents were already implemented and tested (A12-A15/D14-D21)

Scanning docs and code into the SAME tables is the whole point: drift is only
visible when both sides are in one index.

This is a LEAD GENERATOR, not a verdict. Extraction is heuristic (regex over
prose + VSL + Rust/Python). Every row it emits is a claim to be verified by
reading, in the same spirit as R4 — it tells you where to look, it does not
tell you who is right.

Usage:
  python3 scripts/docs/canon_census.py              # build index, print summary
  python3 scripts/docs/canon_census.py --report     # build + run conflict queries
  python3 scripts/docs/canon_census.py --report --id A6    # focus one identifier

Output: docs/.canon_census.db (sqlite, gitignored — regenerate, never edit)

Deterministic, stdlib-only. No LLM in this path (R10).
"""
from __future__ import annotations
import argparse
import hashlib
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "docs/.canon_census.db"

# ── what counts as canon-bearing ────────────────────────────────────────────
DOC_GLOBS = [
    "docs/reference/**/*.md", "docs/reference/**/*.vsm",
    "docs/papers/**/*.md", "docs/papers/**/*.vsm",
    "docs/design/sources/**/*.vsm", "docs/design/sandbox/**/*.vsm",
    "docs/governance/**/*.md", "docs/governance/**/*.vsm",
    "system/s5-policy/governance/**/*.md", "system/s5-policy/governance/**/*.vsm",
    "system/s3-control/soc-xdr-01/security/**/*.md", "system/s3-control/soc-xdr-01/security/**/*.vsm",
    "system/s2-coordination/nats-auth-01/**/*.vsm",
    "system/s3-control/cyberfilter-01/**/*.vsm",
    "system/s4-intelligence/ethics-vigilance-01/**/*.vsm",
    "system/s5-policy/s5-algedonic-01/**/*.vsm",
    "system/s5-policy/vsl-language/**/*.vsm",
]
ROOT_DOCS = ["RULES.md", "CLAUDE.md", "README.md"]
CODE_GLOBS = [
    "projects/vsf-nucleus/src/*.rs",
    "core/*.py",
    "scripts/**/*.py",
    "scripts/**/*.sh",
]
# Dated/historical material: excluded by default. Session logs and the corpus
# legitimately contain superseded statements -- including them would drown the
# collision queries in history that is SUPPOSED to disagree with the present.
EXCLUDE_PARTS = {".claude", "site", "sessions", "corpus", "historical",
                 "Revisiones", "node_modules", "target"}


def in_scope(p: Path) -> bool:
    return not (EXCLUDE_PARTS & set(p.relative_to(ROOT).parts))


# ── extraction patterns ─────────────────────────────────────────────────────
# An identifier DEFINITION: at line start (after markdown #'s / whitespace /
# list markers), followed by a separator or a formula. A citation mid-sentence
# does not match -- that asymmetry is what makes "defined in 2 places" mean
# something.
RE_DEF = re.compile(
    r"^[\s#>*-]*"
    r"(?P<id>A\d{1,2}(?:\.\d)?|D\d{1,2}[a-z]?|R\d{1,2}|"
    r"Ax_[A-Za-z_]\w*|Def_[A-Za-z_]\w*|Thm_[A-Za-z_]\w*)"
    r"(?P<sep>\s*[—:=–-]\s+|\s{2,})"
    r"(?P<stmt>\S.*)$"
)
RE_CITE = re.compile(
    r"\b(A\d{1,2}(?:\.\d)?|D\d{1,2}[a-z]?|Ax_[A-Za-z_]\w*|Def_[A-Za-z_]\w*)\b"
)
# UPPER_SNAKE = numeric literal. Catches LAMBDA_MIN, VIABLE_THRESHOLD,
# CAUTION_DURATION_S ... in BOTH Rust consts and doc prose.
RE_CONST = re.compile(
    r"\b(?P<name>[A-Z][A-Z0-9_]{2,})\b\s*(?::\s*\w+\s*)?=\s*"
    r"(?P<val>-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)"
)
RE_STATUS = re.compile(
    r"\b(DRAFT|STABLE|RESOLVED|SUPERSEDED|DEPRECATED|CLOSED|OPEN|"
    r"CANONICAL|RETIRED|PARKED)\b"
)
RE_CODEREF = re.compile(r"\b((?:[\w.-]+/)*[\w.-]+\.(?:rs|py|sh|json|toml))\b")
RE_DOCREF = re.compile(r"\b((?:docs|projects|scripts|core)/[\w./-]+\.(?:md|vsm))\b")
RE_VERSION = re.compile(r"@(?:vsm|vsl_core)[\s.]*v?([\d.]+)")

DECORATIVE = set("═─│┌┐└┘├┤┬┴┼" "—–…“”‘’")


def is_glyph(ch: str) -> bool:
    if ch.isascii() or ch.isspace() or ch in DECORATIVE:
        return False
    cat = unicodedata.category(ch)
    if cat.startswith("L") and "GREEK" not in unicodedata.name(ch, ""):
        return False
    return True


SCHEMA = """
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS ids;
DROP TABLE IF EXISTS constants;
DROP TABLE IF EXISTS glyphs;
DROP TABLE IF EXISTS refs;
DROP TABLE IF EXISTS statuses;
DROP TABLE IF EXISTS aliases;
CREATE TABLE aliases (numeric_id TEXT, semantic_id TEXT, path TEXT, line INT);
CREATE INDEX i_alias_n ON aliases(numeric_id);
CREATE INDEX i_alias_s ON aliases(semantic_id);
CREATE TABLE documents (path TEXT PRIMARY KEY, kind TEXT, title TEXT,
                        version TEXT, sha256 TEXT, lines INT);
CREATE TABLE ids     (path TEXT, kind TEXT, id TEXT, line INT,
                      statement TEXT, is_def INT);
CREATE TABLE constants(path TEXT, kind TEXT, name TEXT, value TEXT, line INT);
CREATE TABLE glyphs  (path TEXT, glyph TEXT, count INT);
CREATE TABLE refs    (path TEXT, target TEXT, ref_kind TEXT, line INT);
CREATE TABLE statuses(path TEXT, status TEXT, line INT, context TEXT);
CREATE INDEX i_ids ON ids(id);
CREATE INDEX i_const ON constants(name);
"""


def title_of(text: str, path: Path) -> str:
    for line in text.splitlines()[:15]:
        s = line.strip()
        m = re.match(r"^#\s+(.*)", s) or re.match(r"^//\s*(.{6,})", s)
        if m and not m.group(1).lower().startswith(("docs/", "scripts/", "projects/")):
            return m.group(1).strip()
    return path.name


def code_context(lines: list[str]) -> list[bool]:
    """Per-line mask: True = the line is 'live declaration context'.

    False for: comment-only lines, lines inside #[cfg(test)] / mod tests
    blocks, and lines whose declaration is conditional-compilation gated
    (#[cfg(feature=...)] within the 3 preceding lines).

    Every exclusion here came from a verified stage-1 false positive:
    D_KY (test-comment fixture), COVENANT_DEGRADED_THRESHOLD /
    HALT_AFTER_DEGRADED / ESCALATION_GRACE_TICKS (all correct
    production/experiment cfg pairs). Filtering them is not blunting the
    audit -- they were never defects.
    """
    mask = [True] * len(lines)
    in_test = False
    test_depth = 0
    for i, raw in enumerate(lines):
        s = raw.strip()
        if re.match(r"#\[cfg\(test\)\]", s) or re.match(r"mod tests\b", s):
            in_test, test_depth = True, 0
        if in_test:
            test_depth += raw.count("{") - raw.count("}")
            mask[i] = False
            if test_depth <= 0 and "{" in "".join(lines[max(0, i - 1):i + 1]):
                in_test = False
            continue
        if s.startswith(("//", "#", "///", "*")) and "=" in s:
            mask[i] = False            # commented-out or prose-with-a-number
        for back in range(1, 4):       # cfg-gated declaration
            if i - back >= 0 and re.match(r"#\[cfg\(", lines[i - back].strip()):
                mask[i] = False
                break
    return mask


def harvest_aliases(conn, rel: str, lines: list[str]) -> None:
    """Link a numeric axiom ID to its semantic name (A13 ≡ Ax_RecurrentSet).

    Stage-1 review found this was the census's worst blind spot: it reported
    A13 as having no code trace while lyapunov.rs cites `Ax_RecurrentSet`
    for exactly that axiom. Two names, one axiom, treated as strangers.

    Two signals, both conservative:
      (a) a header `### A13 — Recurrent Set` whose CamelCased title matches
          an Ax_/Def_ name appearing within the next 8 lines;
      (b) a header title that CamelCases directly onto a known Ax_/Def_ name.
    """
    for i, raw in enumerate(lines):
        m = re.match(r"^[\s#>*-]*(?P<id>A\d{1,2}(?:\.\d)?|D\d{1,2}[a-z]?)"
                     r"\s*[—–-]\s*(?P<title>[A-Za-z][\w ()'-]{2,60})\s*$", raw)
        if not m:
            continue
        camel = re.sub(r"[^A-Za-z0-9]", "", m.group("title").title())
        window = "\n".join(lines[i:i + 9])
        # Type agreement: A<n> pairs with Ax_/Thm_, D<n> with Def_. Without
        # this, "D18 — Reframe Staged Execution" matched Ax_ReframeScope (a
        # DIFFERENT covenant_ops axiom) on the shared "Reframe" prefix, while
        # its real alias Def_Reframe_Staged sat two lines below. Verified
        # false positive, 2026-08-04.
        want = ("Ax_", "Thm_") if m.group("id").startswith("A") else ("Def_",)
        for sem in set(re.findall(r"\b((?:Ax|Def|Thm)_[A-Za-z_]\w*)\b", window)):
            if not sem.startswith(want):
                continue
            tail = sem.split("_", 1)[1]
            norm = tail.lower().replace("_", "")
            if norm == camel.lower() or \
               camel.lower().startswith(norm[:8]) or \
               norm.startswith(camel.lower()[:8]):
                conn.execute("INSERT INTO aliases VALUES (?,?,?,?)",
                             (m.group("id"), sem, rel, i + 1))


def collect(patterns: list[str]) -> list[Path]:
    out: set[Path] = set()
    for g in patterns:
        for p in ROOT.glob(g):
            if p.is_file() and in_scope(p):
                out.add(p)
    return sorted(out)


def build(conn: sqlite3.Connection) -> tuple[int, int]:
    conn.executescript(SCHEMA)
    docs = collect(DOC_GLOBS) + [ROOT / d for d in ROOT_DOCS if (ROOT / d).exists()]
    code = collect(CODE_GLOBS)
    n_doc = n_code = 0

    for path, kind in [(p, "doc") for p in docs] + [(p, "code") for p in code]:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(ROOT))
        lines = text.splitlines()
        vm = RE_VERSION.search(text)
        conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)",
            (rel, kind, title_of(text, path), vm.group(1) if vm else None,
             hashlib.sha256(text.encode()).hexdigest(), len(lines)))
        if kind == "doc":
            n_doc += 1
        else:
            n_code += 1

        gc: dict[str, int] = {}
        for ch in text:
            if is_glyph(ch):
                gc[ch] = gc.get(ch, 0) + 1
        conn.executemany("INSERT INTO glyphs VALUES (?,?,?)",
                         [(rel, g, c) for g, c in gc.items()])

        harvest_aliases(conn, rel, lines)
        live = code_context(lines)

        for i, line in enumerate(lines, 1):
            m = RE_DEF.match(line)
            if m:
                conn.execute("INSERT INTO ids VALUES (?,?,?,?,?,1)",
                             (rel, kind, m.group("id"), i,
                              m.group("stmt").strip()[:400]))
            else:
                for cid in set(RE_CITE.findall(line)):
                    conn.execute("INSERT INTO ids VALUES (?,?,?,?,?,0)",
                                 (rel, kind, cid, i, line.strip()[:400]))
            for cm in RE_CONST.finditer(line):
                conn.execute("INSERT INTO constants VALUES (?,?,?,?,?)",
                             (rel, kind, cm.group("name"), cm.group("val"), i))
            for sm in RE_STATUS.finditer(line):
                conn.execute("INSERT INTO statuses VALUES (?,?,?,?)",
                             (rel, sm.group(1), i, line.strip()[:200]))
            for t in set(RE_CODEREF.findall(line)):
                conn.execute("INSERT INTO refs VALUES (?,?,?,?)",
                             (rel, t, "code", i))
            for t in set(RE_DOCREF.findall(line)):
                conn.execute("INSERT INTO refs VALUES (?,?,?,?)",
                             (rel, t, "doc", i))
    conn.commit()
    return n_doc, n_code


# ── conflict queries (stage-2 seeds, run here to size the problem) ──────────
def q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def report(conn, focus: str | None) -> None:
    print("\n" + "=" * 72)
    print("CONFLICT QUERIES — leads to verify, not verdicts")
    print("=" * 72)

    print("\n[1] Same ID defined in >=2 DOCS (candidate collisions)")
    rows = q(conn, """
        SELECT id, COUNT(DISTINCT path) n, GROUP_CONCAT(DISTINCT path)
        FROM ids WHERE is_def=1 AND kind='doc'
        GROUP BY id HAVING n>=2 ORDER BY n DESC, id LIMIT 25""")
    for i, n, paths in rows:
        print(f"    {i:<22} {n} docs")
        for p in sorted(set(paths.split(",")))[:4]:
            print(f"        {p}")
    print(f"    → {len(rows)} identifiers defined in more than one document")

    print("\n[2] Constant with >=2 DISTINCT values across files (drift)")
    rows = q(conn, """
        SELECT name, COUNT(DISTINCT value) nv, GROUP_CONCAT(DISTINCT value)
        FROM constants GROUP BY name HAVING nv>=2 ORDER BY nv DESC LIMIT 20""")
    for name, nv, vals in rows:
        where = q(conn, "SELECT DISTINCT kind, path, value FROM constants "
                        "WHERE name=? ORDER BY kind", (name,))
        print(f"    {name:<28} values: {vals}")
        for k, p, v in where[:4]:
            print(f"        [{k}] {v:<10} {p}")
    print(f"    → {len(rows)} constants disagree with themselves somewhere")

    print("\n[3] Axiom/definition IDs with NO mention anywhere in code")
    rows = q(conn, """
        SELECT DISTINCT id FROM ids
        WHERE is_def=1 AND kind='doc'
          AND (id LIKE 'A%' OR id LIKE 'Ax\\_%' ESCAPE '\\')
          AND id NOT IN (SELECT DISTINCT id FROM ids WHERE kind='code')
        ORDER BY id""")
    ids = [r[0] for r in rows]
    print(f"    {', '.join(ids) if ids else '(none)'}")
    print(f"    → {len(ids)} axioms with no code trace (unenforced, or "
          f"enforced under another name)")

    print("\n[4] DRAFT / OPEN documents (promotion criteria unassessed?)")
    rows = q(conn, """
        SELECT DISTINCT s.path, d.title FROM statuses s JOIN documents d
        ON d.path=s.path WHERE s.status='DRAFT' AND d.kind='doc' LIMIT 15""")
    for p, t in rows:
        print(f"    {p}\n        {t}")
    print(f"    → {len(rows)} documents carrying a DRAFT marker")

    print("\n[5] Glyphs used in >=2 docs that DEFINE them differently")
    rows = q(conn, """
        SELECT g.glyph, COUNT(DISTINCT g.path) n FROM glyphs g
        GROUP BY g.glyph HAVING n>=3 ORDER BY n DESC LIMIT 12""")
    print("    (glyph, #docs using it — each is a shared-vocabulary surface)")
    print("    " + "  ".join(f"{g}:{n}" for g, n in rows))

    if focus:
        print(f"\n[focus] every appearance of {focus}")
        for path, kind, line, stmt, isdef in q(
                conn, "SELECT path,kind,line,statement,is_def FROM ids "
                      "WHERE id=? ORDER BY is_def DESC, kind, path", (focus,)):
            tag = "DEF " if isdef else "cite"
            print(f"    {tag} [{kind}] {path}:{line}")
            print(f"         {stmt[:100]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--id", default=None)
    a = ap.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    n_doc, n_code = build(conn)

    tot = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  ✓ census built: {DB_PATH.relative_to(ROOT)}")
    print(f"    {n_doc} docs + {n_code} code files")
    print(f"    {tot('ids')} identifier occurrences "
          f"({conn.execute('SELECT COUNT(*) FROM ids WHERE is_def=1').fetchone()[0]} definitions)")
    print(f"    {tot('constants')} constants · {tot('refs')} refs · "
          f"{tot('statuses')} status markers")

    if a.report or a.id:
        report(conn, a.id)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
