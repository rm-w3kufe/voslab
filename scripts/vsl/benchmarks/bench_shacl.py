#!/usr/bin/env python3
"""bench_shacl.py — the corpus as an RDF graph, three constraints as SHACL.

NOT shipped. Same discipline as bench_pydantic: run it, do not assert it.

rmw3 2026-08-09: "si sirve, lo podemos implementar, y si no, ya sabemos que
podemos construir (y ofrecer)."

THE EXPERIMENT
  1. export the identifier index to RDF triples — does the corpus HAVE a graph
     shape, or are we forcing one?
  2. state three constraints we already enforce in Python as SHACL shapes
  3. run both, compare findings

The three were chosen because they are the ones whose Python is ugliest —
each is a JOIN across documents, which is what a graph is for:

  C1  every CITED identifier is DEFINED somewhere      (dangling)
  C2  a canon identifier is defined in ONE document    (dupes)
  C3  every @var referenced has a binding              (paths)

WHAT THIS CANNOT SETTLE
Whether a graph is the right substrate for the CORPUS. It tests three
constraints, not thirty, and the encoding/glyph gates have ∄ graph form at all
— they are character-level. A win here would mean "the relational constraints
belong in a graph", ¬"the corpus is a graph".
"""
from __future__ import annotations
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("VOS_ROOT", os.getcwd()))
SCRATCH = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "st", ROOT / "scripts/vsl/parser/symbol_table.py")
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

NS = "https://vsf.u2738.org/ns#"
BASE = "https://vsf.u2738.org/corpus/"



def load_index():
    """Build the index the way the gate's own main() does — same reader."""
    idx = st.Index()
    for f in sorted(st.CORPUS.rglob("*.vsm")):
        if any(x in f.parts for x in st.SKIP_DIRS):
            continue
        idx.add_file(f)
    return idx

def q(s: str) -> str:
    return s.replace(" ", "_").replace("/", "_").replace(".", "_")


def build_triples() -> tuple[str, dict]:
    """Emit N-Triples from the same index the Python gates read.

    Deliberately NOT a new extraction: if the graph is fed by a different
    reader than the gates, a disagreement tells us about the readers, ¬about
    the substrate.
    """
    idx = load_index()
    t, counts = [], {"defines": 0, "cites": 0, "binds": 0, "refs": 0}

    for ident, docs in idx.defined.items():
        for d in docs:
            t.append(f'<{BASE}doc/{q(d)}> <{NS}defines> <{BASE}id/{q(ident)}> .')
            counts["defines"] += 1
    for ident, docs in idx.cited.items():
        for d in docs:
            t.append(f'<{BASE}doc/{q(d)}> <{NS}cites> <{BASE}id/{q(ident)}> .')
            counts["cites"] += 1
    for ident in set(idx.defined) | set(idx.cited):
        t.append(f'<{BASE}id/{q(ident)}> <{NS}kind> "{st.kind_of(ident)}" .')
        t.append(f'<{BASE}id/{q(ident)}> '
                 f'<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> '
                 f'<{NS}Identifier> .')
    return "\n".join(t) + "\n", counts


SHAPES = f"""
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix vsf:  <{NS}> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

# C1 — every cited identifier is defined somewhere.
# In Python this is a set difference across two dicts built in one pass.
# Here it is a property shape with a minCount, and the join is the engine's.
vsf:CitedIsDefinedShape
    a sh:NodeShape ;
    sh:targetClass vsf:Identifier ;
    sh:property [
        sh:path [ sh:inversePath vsf:defines ] ;
        sh:minCount 1 ;
        sh:message "cited but defined in ∄ document" ;
    ] .

# C2 — an identifier is defined in exactly one document.
vsf:DefinedOnceShape
    a sh:NodeShape ;
    sh:targetClass vsf:Identifier ;
    sh:property [
        sh:path [ sh:inversePath vsf:defines ] ;
        sh:maxCount 1 ;
        sh:message "defined in more than one document" ;
    ] .
"""


def run_shacl(triples: str) -> tuple[int, list[str], float]:
    (SCRATCH / "corpus.nt").write_text(triples, encoding="utf-8")
    (SCRATCH / "shapes.ttl").write_text(SHAPES, encoding="utf-8")
    t0 = time.perf_counter()
    r = subprocess.run(
        [str(SCRATCH / "rdfvenv/bin/pyshacl"),
         "-s", str(SCRATCH / "shapes.ttl"), "-f", "human",
         str(SCRATCH / "corpus.nt")],
        capture_output=True, text=True)
    dt = time.perf_counter() - t0
    out = r.stdout + r.stderr
    viols = [l.strip() for l in out.splitlines() if "Focus Node" in l]
    return out.count("Constraint Violation"), viols, dt


def run_python() -> tuple[list[str], list[str], float]:
    """The same two questions, as the gates ask them today."""
    t0 = time.perf_counter()
    idx = load_index()
    dangling = sorted(i for i in idx.cited if i not in idx.defined)
    dupes = sorted(i for i, d in idx.defined.items() if len(d) > 1)
    return dangling, dupes, time.perf_counter() - t0


def main() -> int:
    triples, counts = build_triples()
    print(f"  graph: {len(triples.splitlines())} triples "
          f"({counts['defines']} defines · {counts['cites']} cites)\n")

    dangling, dupes, t_py = run_python()
    n_viol, viols, t_sh = run_shacl(triples)

    print(f"  python  dangling {len(dangling):>2} · multi-defined {len(dupes):>2}"
          f"   {t_py*1000:7.1f} ms")
    print(f"  shacl   violations {n_viol:>2}"
          f"                     {t_sh*1000:7.1f} ms\n")

    expected = len(dangling) + len(dupes)
    print(f"  python total {expected}  ▪  shacl total {n_viol}  "
          f"→ {'AGREE' if expected == n_viol else '◄ DIVERGE'}\n")
    if dupes:
        print("  multi-defined (python):")
        for d in dupes:
            print(f"    {d:<22} {sorted(idx_docs(d))}")
    if viols[:6]:
        print("\n  shacl focus nodes (first 6):")
        for v in viols[:6]:
            print(f"    {v}")
    return 0


def idx_docs(ident):
    return load_index().defined.get(ident, set())


if __name__ == "__main__":
    sys.exit(main())
