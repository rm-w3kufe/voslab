#!/usr/bin/env python3
"""docs_reconcile — model≡reality for the documentation tree (an AX-STATE-01 dogfood).

The manual docs/INDEX.md drifts the same way state.db drifted from running processes (FIND-NUC-ORPHANS).
This makes the doc index TAMPER/DRIFT-EVIDENT: a canonical catalog (docs/INDEX.md, committed) is the
declared MODEL; the live filesystem is REALITY; the reconciler flags divergence.

Anomaly classes:
  ORPHAN        — a doc on disk not in the index (added without indexing).
  MISSING       — an index entry with no file (deleted/moved without updating the index).
  CRUFT         — Zone.Identifier / LaTeX build artifacts present (should be gitignored/removed).
  DUPLICATE     — two files with identical content (same sha256).
  UNCATEGORIZED — a doc in a directory outside the canonical taxonomy.
  STALE (info)  — content sha changed vs the index (expected for working docs; flagged for canonical ones).

Modes:
  (default) --check : report drift, exit 1 if any HARD anomaly (ORPHAN/MISSING/CRUFT/UNCATEGORIZED/DUPLICATE).
  --update          : regenerate docs/INDEX.md (committed human catalog)
                      + docs/.index.db (local sqlite cache). ALL LOCAL — no network.

Pure stdlib. Run from the repo root: python3 scripts/shared/docs_reconcile.py [--update]
The index lives LOCAL (WSL), next to the docs — a deliberate exception to "operational state lives on n02":
docs are local content; the doc index must NOT cross into the runtime state.db. The queryable CANONICAL
index is docs/.index.db (local sqlite, git-ignored, the declared model the reconciler checks against);
docs/INDEX.md is the COMMITTED git-visible human catalog (generated, the text model). A pre-commit hook runs --update so
both stay current with zero network on every commit.
"""
import os, sys, hashlib, json, sqlite3, datetime, collections

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(REPO, "docs")
INDEX_MD = os.path.join(DOCS, "INDEX.md")
# Local queryable index — docs are LOCAL content, so the DB lives NEXT TO the docs (WSL), NOT n02.
# A deliberate exception to "operational state lives on n02": the doc index must not cross into the
# runtime state.db. The DB is a regenerable cache (git-ignored); docs/INDEX.vsm is the canonical text model.
LOCAL_DB = os.path.join(DOCS, ".index.db")

# ── The canonical taxonomy (the "harder control": an explicit, enforced category list) ──
CATEGORIES = {
    "theory":      ("canonical",  "formal theory, design specs, proofs (.vsm)"),
    "spec":        ("canonical",  "protocol/component specifications"),
    "governance":  ("canonical",  "strategy, vault policy, comms, disclosure"),
    "security":    ("canonical",  "security design + hardening"),
    "roadmap":     ("canonical",  "canonical roadmap"),
    "vault":       ("canonical",  "integrity-tracked record (committed by design)"),
    "metaphors":   ("canonical",  "public metaphors translating system capabilities (each states where it breaks)"),
    "guides":      ("working",    "how-to / human guides"),
    "operations":  ("working",    "ops runbooks, telemetry, plans"),
    "infra":       ("working",    "infrastructure profiles + state"),
    "evaluation":  ("working",    "evaluations + scorecards"),
    "experiments": ("working",    "experiment specs + results"),
    "internal":    ("working",    "working docs, findings, VSL exchanges"),
    "outreach":    ("working",    "community / outreach"),
    "papers":      ("working",    "paper sources + figures"),
    "historical":  ("archive",    "dated snapshots, superseded docs"),
    "sessions":    ("reference",  "raw chat exports (mostly git-ignored)"),
    "corpus":      ("reference",  "book source material (raw exports git-ignored)"),
    "charts":      ("reference",  "visualization artifacts (html/pdf)"),
    "notebooks":   ("reference",  "jupyter notebooks"),
    "vsf-bbh":     ("reference",  "BBH references"),
    "spec_revision": ("working", "active spec revision — boot canon, system fuses, sandbox, learning_records, incidents"),
    # The taxonomy must list EVERY directory that exists under docs/ — category_of()
    # returns any existing dir, so an unlisted dir used to silently fall through:
    # write_index() emitted no section (files dropped from INDEX.md) and the
    # UNCATEGORIZED check tested only `category is None` (dir existence) instead
    # of membership, so nothing ever flagged it. Fixed 2026-10-13 (orphan triage).
    "architecture": ("reference", "system architecture descriptions (pre-spec-revision era)"),
    "archive":      ("archive",   "retrievable superseded material (not canon)"),
    "audit":        ("reference", "audit records"),
    "canon_mirror": ("reference", "byte mirrors of canon docs (synced copies)"),
    "correspondence": ("reference", "external correspondence"),
    "deploy":       ("working",   "deployment reports + sync logs"),
    "design":       ("working",   "design docs"),
    "findings":     ("working",   "findings + analyses"),
    "incidents":    ("reference", "incident reports + rationale"),
    "ledger":       ("working",   "ledgers, censuses, worklists"),
    "learning_records": ("working", "learning records (IR) + cycle proposals"),
    "memory":       ("reference", "memory docs"),
    "plan":         ("working",   "plan docs"),
    "plans":        ("working",   "execution plans + backlogs"),
    "publishing":   ("working",   "publishing docs"),
    "reference":    ("reference", "reference material"),
    "rubric":       ("reference", "rubrics + scoring criteria"),
    "specs":        ("working",   "registries + specs (working set)"),
}
# Root-level canonical files that belong to the index too.
ROOT_DOCS = {"CLAUDE.md", "README.md", "HANDOFF.vsm.md", "RULES.md", "ROADMAP.vsm",
             "TASKS.vsm", "viability.yaml", "mkdocs.yml"}
# Meta/canonical files that legitimately live directly in docs/ (not in a category subdir).
DOCS_ROOT_META = {"DOCS.md", "glossary.vsm", "index.md",
                  "system_analysis_tracking.vsm"}  # INDEX.vsm/INDEX.md handled separately

def intentional_dup(paths):
    """Some duplicates are BY DESIGN: vault/triage keeps a 'sent' record; the paper bundles copy
    material to be self-contained (incl. snapshots of root canon like RULES.md); canon_mirror IS a
    mirror category; archive/ by definition holds frozen copies of (possibly live) material.
    These are not drift — report as info, not a hard anomaly.
    Residual gap (documented, not enforced): divergence between intentional mirrors is not
    yet a first-class anomaly (a SYNC class) — only equality-while-duplicated is observed."""
    return any("vault/triage" in p for p in paths) or \
        all(("/figures/" in p or "fig_" in p) for p in paths) or \
        any(p.startswith("docs/canon_mirror/") for p in paths) or \
        any(p.startswith("docs/papers/") for p in paths) or \
        any(p.startswith("docs/archive/") for p in paths)

CRUFT_SUFFIXES = ("Zone.Identifier", ".aux", ".bbl", ".blg", ".log", ".out", ".toc",
                  ".fls", ".fdb_latexmk", ".synctex.gz")

def sha256(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:
        return None

def is_cruft(name):
    return name.endswith(CRUFT_SUFFIXES)

def category_of(relpath):
    parts = relpath.split(os.sep)
    if parts[0] == "docs" and len(parts) == 2 and parts[1] in DOCS_ROOT_META:
        return "(docs-root)"
    if parts[0] == "docs" and len(parts) >= 2:
        return parts[1] if os.path.isdir(os.path.join(REPO, "docs", parts[1])) else None
    if len(parts) == 1 and parts[0] in ROOT_DOCS:
        return "(root)"
    return None

def scan():
    """Reality: every doc on disk (repo docs/ + root canonical files). Returns {relpath: meta}."""
    out = {}
    cruft = []
    # root docs
    for f in ROOT_DOCS:
        p = os.path.join(REPO, f)
        if os.path.isfile(p):
            out[f] = dict(category="(root)", kind=f.split(".")[-1], sha=sha256(p),
                          size=os.path.getsize(p), status="canonical")
    # docs tree (runtime interpreter caches are not knowledge: __pycache__/
    # *.pyc bytecode would otherwise be catalogued as docs on every regen —
    # doctrine matches the header (caches checked by PATH presence only))
    _JUNK_DIRS = {"__pycache__", ".ipynb_checkpoints"}
    _JUNK_SUFFIXES = (".pyc", ".pyo")
    for dp, dns, fs in os.walk(DOCS):
        dns[:] = [d for d in dns if d not in _JUNK_DIRS]
        for f in fs:
            ap = os.path.join(dp, f)
            rel = os.path.relpath(ap, REPO)
            if is_cruft(f):
                cruft.append(rel); continue
            if f.endswith(_JUNK_SUFFIXES):
                continue
            if f in ("INDEX.vsm", "INDEX.md", ".index.db"):
                continue  # the index + its cache are not indexed
            cat = category_of(rel)
            if cat in CATEGORIES:
                status = CATEGORIES[cat][0]
            elif cat in ("(docs-root)", "(root)"):
                status = "canonical"
            else:
                status = None
            out[rel] = dict(category=cat, kind=f.rsplit(".", 1)[-1] if "." in f else "",
                            sha=sha256(ap), size=os.path.getsize(ap), status=status)
    return out, cruft

def load_index():
    """The declared MODEL = the local .index.db (persistent, regenerated on --update). Empty on first run."""
    idx = {}
    if not os.path.exists(LOCAL_DB):
        return idx
    try:
        con = sqlite3.connect(LOCAL_DB)
        for path, sha in con.execute("SELECT path, sha256 FROM documents"):
            idx[path] = {"path": path, "sha": sha}
        con.close()
    except Exception:
        pass
    return idx

def reconcile():
    reality, cruft = scan()
    model = load_index()
    hard, info = [], []

    for rel in cruft:
        hard.append(("CRUFT", rel))
    # duplicates by sha
    byhash = collections.defaultdict(list)
    for rel, m in reality.items():
        if m["sha"]:
            byhash[m["sha"]].append(rel)
    for h, paths in byhash.items():
        if len(paths) > 1:
            (info if intentional_dup(paths) else hard).append(("DUPLICATE", " | ".join(sorted(paths))))
    # uncategorized — membership in the explicit taxonomy, not mere dir existence
    for rel, m in reality.items():
        if m["category"] not in CATEGORIES and m["category"] not in ("(docs-root)", "(root)"):
            hard.append(("UNCATEGORIZED", rel))
    # vs model
    for rel in reality:
        if model and rel not in model:
            hard.append(("ORPHAN", rel))
    for rel in model:
        if rel not in reality:
            hard.append(("MISSING", rel))
    for rel, m in reality.items():
        dm = model.get(rel)
        if dm and dm.get("sha") and m["sha"] and dm["sha"] != m["sha"]:
            tag = "STALE-canonical" if m["status"] == "canonical" else "stale"
            (hard if m["status"] == "canonical" else info).append((tag, rel))
    return reality, hard, info

def write_index(reality):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # docs/INDEX.md — the COMMITTED, git-visible human catalog (the only text index).
    # The queryable canonical index is docs/.index.db (local, git-ignored, regenerated here).
    by_cat = collections.defaultdict(list)
    for rel, m in reality.items():
        by_cat[m["category"]].append(rel)
    with open(INDEX_MD, "w", encoding="utf-8") as f:
        f.write("# Documentation Index\n\n")
        # NB: NO timestamp here — INDEX.md must be DETERMINISTIC so it changes only when docs change
        # (the canonical_serialize lesson: exclude volatile fields → no spurious diffs every commit).
        f.write(f"> GENERATED from the filesystem by `scripts/shared/docs_reconcile.py --update` "
                f"({len(reality)} files). Queryable canonical index: `docs/.index.db` (local). "
                f"Do not hand-edit.\n\n")
        f.write("## Taxonomy\n\n| category | status | n | purpose |\n|---|---|---|---|\n")
        for c, (st, desc) in CATEGORIES.items():
            n = sum(1 for m in reality.values() if m["category"] == c)
            f.write(f"| {c} | {st} | {n} | {desc} |\n")
        f.write("\n")
        for c in list(CATEGORIES) + ["(docs-root)", "(root)"]:
            files = sorted(by_cat.get(c, []))
            if not files:
                continue
            st = CATEGORIES.get(c, ("", ""))[0] if c in CATEGORIES else "root"
            f.write(f"## {c}  _({st}, {len(files)})_\n\n")
            for rel in files:
                f.write(f"- `{rel}`\n")
            f.write("\n")

def write_db(reality):
    """Write the catalog into the LOCAL sqlite cache (docs/.index.db) — no network, queryable in WSL."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(LOCAL_DB)
    con.execute("CREATE TABLE IF NOT EXISTS documents (path TEXT PRIMARY KEY, category TEXT, kind TEXT,"
                " status TEXT, size INTEGER, sha256 TEXT, refreshed_at TEXT)")
    con.execute("DELETE FROM documents")
    con.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
                    [(rel, m["category"], m["kind"], m["status"], m["size"], m["sha"], now)
                     for rel, m in sorted(reality.items())])
    con.commit()
    con.close()
    return len(reality)

def _in_worktree():
    """Return True if the repo root's .git is a file (worktree) not a directory."""
    git_path = os.path.join(REPO, ".git")
    return os.path.isfile(git_path)

def main():
    update = "--update" in sys.argv
    if update and _in_worktree():
        print("  ✗ ABORT: --update from a git worktree is not supported "
              "(would corrupt INDEX.md in the worktree context)")
        sys.exit(1)
    reality, hard, info = reconcile()
    cats = collections.Counter((m["category"] or "(UNCATEGORIZED)") for m in reality.values())
    print(f"# docs_reconcile — {len(reality)} docs across {len(cats)} categories")
    print("  taxonomy: " + ", ".join(f"{k}:{v}" for k, v in sorted(cats.items())))
    for tag, msg in info:
        print(f"  [info/{tag}] {msg}")
    if update:
        write_index(reality)
        n = write_db(reality)
        print(f"  ✓ wrote docs/INDEX.md + docs/.index.db ({n} entries, local — no network)")
        return 0
    if not hard:
        print("\n## RESULT: ✓ RECONCILED — docs ≡ index, no cruft/dups/uncategorized.")
        return 0
    print(f"\n## RESULT: ✗ {len(hard)} drift(s)")
    for tag, msg in hard:
        print(f"  [{tag}] {msg}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
