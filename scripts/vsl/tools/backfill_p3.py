#!/usr/bin/env python3
"""P3 backfill (D-SA1=A; P3 ratified scripts_r16_policy_proposal 2026-10-16).

Inserts `# design: <path.vsm> (SUT: <rel>)` on line 1 (line 2 after shebang)
ONLY for airtight tiers:
  already : topline `# design:` present -> skip
  moved   : resolvable decl deeper in first 40 (often docstring prose) ->
            normalize `# design: <path>` on line 1, KEEP original line
  inherit : SUT declares its own resolvable design -> copy path
  mention : SUT has no decl, but its UNIQUE-basename file is named in
            exactly ONE doc of design-sources/ OR plans/ (P3: "design/plan
            del SUT") -> pointer with (SUT:) annotation
Everything else = design debt (R9: no fake pointers; listed for P1 task).
Deterministic (R10): no clock, no randomness; single repo walk + docs load.
"""
import re
import sys
from pathlib import Path

REPO = Path("/home/rmw3/vOSlab")
JUNK = (".venv", ".git", "node_modules", "__pycache__", ".pnp")
DES_RE = re.compile(r"design:\s*(\S+\.vsm)")
IMP_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.M)
DRY = "--write" not in sys.argv

# ── one-time indexes ──────────────────────────────────────────────────
PY_INDEX: dict[str, list[Path]] = {}
for _dir, _dirs, _files in __import__("os").walk(REPO):
    _dirs[:] = [d for d in _dirs if d not in JUNK]
    for _f in _files:
        if _f.endswith(".py"):
            PY_INDEX.setdefault(_f, []).append(Path(_dir) / _f)

def _keep_doc(d: Path) -> bool:
    return not any(x in d.parts for x in ("archive", "sessions"))


DES_DOCS = sorted(
    [d for d in REPO.glob("docs/design/sources/**/*.vsm") if _keep_doc(d)]
    + [d for d in REPO.glob("docs/plans/**/*.vsm") if _keep_doc(d)]
    + [d for d in REPO.glob("docs/specs/**/*.vsm") if _keep_doc(d)]
    + [d for d in REPO.glob("system/**/*.vsm") if _keep_doc(d)]
)
DOC_TEXTS: dict[Path, str] = {}
for _d in DES_DOCS:
    try:
        DOC_TEXTS[_d] = _d.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass


def top_rel(rel: str) -> bool:
    return rel.startswith(("packages/", "system/", "scripts/"))


def _resolves(decl: str) -> bool:
    t = REPO / decl
    # archive/ = stale design (R5: canon live) — never a valid pointer target
    return t.is_file() and "archive" not in t.parts


def topline_path(p: Path):
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[:2]
    except OSError:
        return None
    if lines and lines[0].startswith("#!"):
        lines = lines[1:2]
    if not lines or not lines[0].lstrip().startswith("#"):
        return None
    m = DES_RE.search(lines[0])
    if m and _resolves(m.group(1)):
        return m.group(1)
    return None


def head_path(p: Path, n=40):
    try:
        head = p.read_text(encoding="utf-8", errors="replace").splitlines()[:n]
    except OSError:
        return None
    for line in head:
        m = DES_RE.search(line)
        if m and _resolves(m.group(1)):
            return m.group(1)
    return None


def _is_test_sut(c: Path) -> bool:
    return c.is_file() and "tests" not in c.parts and "test_" not in c.name and c.suffix == ".py"


def sut_by_name(p: Path):
    d, stem = p.parent.parent, p.stem
    if not stem.startswith("test_"):
        return None
    parts = stem[5:].split("_")
    for i in range(len(parts), 0, -1):
        base = "_".join(parts[:i])
        for c in (d / (base + ".py"), d / base / "__init__.py"):
            if c.is_file():
                return c
    for i in range(len(parts), 0, -1):
        hits = [x for x in PY_INDEX.get("_".join(parts[:i]) + ".py", [])
                if not any(j in x.parts for j in JUNK) and x != p]
        if len(hits) == 1:
            return hits[0]
    return None


def sut_by_imports(p: Path):
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pkg = p.parent.parent
    for m in IMP_RE.finditer(text):
        segs = m.group(1).split(".")
        for i in range(len(segs), 0, -1):
            rel = "/".join(segs[:i])
            for c in (pkg / (rel + ".py"), pkg / rel / "__init__.py",
                      pkg.parent / (rel + ".py"), pkg.parent / rel / "__init__.py",
                      REPO / (rel + ".py"),
                      REPO / "packages/framework" / (rel + ".py"),
                      REPO / "packages/public" / (rel + ".py"),
                      REPO / "scripts" / (rel + ".py"),
                      REPO / "system/kernel" / (rel + ".py")):
                if _is_test_sut(c) and c != p:
                    return c
        hits = [x for x in PY_INDEX.get(segs[-1] + ".py", [])
                if not any(j in x.parts for j in JUNK) and x != p]
        if len(hits) == 1:
            return hits[0]
    return None


def mention_single_doc(sut: Path):
    """(a) exact-stem doc: a doc named <stem>.vsm (docs/ minus archive/
    sessions) IS the doc for that artifact -> unique hit wins.
    (b) unique-basename SUT mentioned in exactly ONE doc of the design set
    (P3: 'el design/plan del SUT'). Ambiguity -> None (R9)."""
    name = sut.name
    if len(PY_INDEX.get(name, [])) != 1:
        return None
    stem = sut.stem + ".vsm"
    stem_hits = [d for d in DOC_TEXTS if d.name == stem]
    if len(stem_hits) == 1:
        return stem_hits[0]
    if len(stem_hits) > 1:
        return None
    hits = [d for d, t in DOC_TEXTS.items() if name in t]
    if len(hits) == 1:
        return hits[0]
    return None


def insert_top(p: Path, line: str) -> None:
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    idx = 1 if (lines and lines[0].startswith("#!")) else 0
    lines.insert(idx, line)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    tests = sorted(
        list(REPO.glob("packages/**/tests/test_*.py"))
        + list(REPO.glob("system/**/tests/test_*.py"))
        + list(REPO.glob("scripts/**/tests/test_*.py"))
    )
    report = {"already": [], "moved": [], "inherit": [], "mention": [], "debt": []}
    for p in tests:
        rel = str(p.relative_to(REPO))
        tp = topline_path(p)
        if tp:
            report["already"].append(rel)
            continue
        hp = head_path(p)
        if hp:
            line = f"# design: {hp}"
            if not DRY:
                insert_top(p, line)
            report["moved"].append((rel, line))
            continue
        sut = sut_by_name(p) or sut_by_imports(p)
        decl = kind = None
        if sut is not None:
            sp = head_path(sut)
            if sp:
                decl, kind = f"# design: {sp} (SUT: {sut.relative_to(REPO)})", "inherit"
            else:
                doc = mention_single_doc(sut)
                if doc:
                    decl = (f"# design: {doc.relative_to(REPO)} "
                            f"(SUT: {sut.relative_to(REPO)})")
                    kind = "mention"
        if decl is None:
            report["debt"].append((rel, str(sut.relative_to(REPO)) if sut else "no-sut"))
            continue
        if not DRY:
            insert_top(p, decl)
        report[kind].append((rel, decl))

    for k, v in report.items():
        print(f"{k}: {len(v)}")
    for k in ("moved", "inherit", "mention"):
        if report[k]:
            print(f"\n-- {k}:")
            for rel, d in report[k]:
                print(f"  {rel}\n      {d[:110]}")
    print("\n-- debt (R9: sin pointer; task P1):")
    for rel, s in report["debt"]:
        print(f"  {rel} | {s}")
    print(f"\n{'DRY-RUN (no files written)' if DRY else 'WRITTEN'}")


if __name__ == "__main__":
    main()
