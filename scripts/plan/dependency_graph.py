#!/usr/bin/env python3
# design: docs/plans/version-change-plan-v1/version_change_plan.vsm
# (R16_impl_with_design — VERSION-CHANGE-PLAN-v1 PART II/IV; the dependency
#  graph + plan emitter for the VSM12-VERSION-CHANGE-PLAN-HOOK)
"""dependency_graph.py — the version-change dependency graph (VSM12-VERSION-CHANGE-PLAN-HOOK).

S5 vision (rmw3, 2026-08-16): every doc depends on the canonical language
primer (and the covenant / core boot primer — co-dependents). When one of
these roots bumps its protocol version, dependents must re-commit to the
new version. This script:

  1. BUILDS the explicit graph:  depende_de(doc, padre, tipo)
       tipo ∈ {co-firma, aplicacion, lectura}
       - co-firma : the doc is @status ratified AND references the root
                    (it re-signs against the new policy — mechanical
                    evidence the review happened)
       - aplicacion: the doc lives in the corpus (has @vsm header) and
                    references the root — it must migrate its version
       - lectura  : the doc merely references the root (informational;
                    no migration action)
  2. EMITS the migration plan as task() blocks (TASKS.vsm syntax) with a
     manual gate — it NEVER edits docs (R16: instrument emits, human
     executes; no auto-edit).

Usage:
  python3 scripts/plan/dependency_graph.py graph            # print the graph
  python3 scripts/plan/dependency_graph.py plan --root <path> [--to <version>]
      # emit task() migration plan for all dependents of <root>
  python3 scripts/plan/dependency_graph.py check [--root <path>]
      # exit 0 if no migration needed for the root (or a consistent state);
      # exit 1 if a dependents' @vsm lags the root's @vsm (migration needed)

Design: docs/plans/version-change-plan-v1/version_change_plan.vsm (VERSION-CHANGE-PLAN-v1,
PART II cycle, PART IV next-bump playbook).
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "docs", "spec_revision")

# The canonical roots — co-dependent by S5 policy (covenant ≻ core_boot_primer
# ≻ vsl_language_primer, boot_manifest.vsm). A bump in ANY of them ripples.
CANON_ROOTS = {
    "covenant": "system/boot/covenant.vsm",
    "core_boot_primer": "system/boot/core_boot_primer.vsm",
    "vsl_language_primer": "system/boot/vsl_language_primer.vsm",
}

_VSM_RE = re.compile(r"vsm-([0-9.]+)")
_RATIFIED_RE = re.compile(r"^@status ratified", re.M)


def doc_version(path):
    """Read the @vsm protocol version from a doc's header (first non-blank line)."""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.readline()
        m = _VSM_RE.search(head)
        return m.group(1) if m else None
    except OSError:
        return None


def is_ratified(path):
    try:
        with open(path, encoding="utf-8") as f:
            return bool(_RATIFIED_RE.search(f.read()))
    except OSError:
        return False


_ACTIVE_RE = re.compile(r"^@status active", re.M)


def is_active(path):
    """True if the doc declares @status active (canon-operating)."""
    try:
        with open(path, encoding="utf-8") as f:
            return bool(_ACTIVE_RE.search(f.read()))
    except OSError:
        return False


def has_footer_version(path):
    """True if the doc carries the two-line versioned footer (⟦ /name | … ⟧)
    — i.e. it is a versioned corpus doc, not a catalog/worklist/note file."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False
    # footer: last non-blank lines contain a closing ⟦ /name … ⟧ block
    tail = content.strip().splitlines()
    return any("⟦ /" in line and "vsm-" in line for line in tail[-6:])


def build_graph():
    """Scan the corpus; returns {root_relpath: [(doc_relpath, tipo), ...]}.

    VSM12-CORPUS-CENSUS-NOT-REFERENCE-2026-08-17 (decision a): the graph
    censuses EVERY versioned corpus doc (⟦ /name | … | vsm-X ⟧ footer) by
    its STATUS — not only docs that textually reference the root. Textual
    reference was a proxy; the versioned header/footer IS the declaration
    of dependence on the canonical language. Status classification:
      - @status ratified     → tipo=co-firma  (re-signs against the policy)
      - @status active       → tipo=aplicacion (active doc must declare the
                               canonical version)
      - other/no status      → tipo=lectura   (proposed/conjecture/template/
                               historical_record/… are not yet canon —
                               informational, no migration)
    """
    graph = {}
    # doc_relpath -> content references
    docs = {}
    for dirpath, _dirnames, filenames in os.walk(CORPUS):
        if "/archive" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(".vsm"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            try:
                with open(full, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue
            docs[rel] = content

    for root_rel, root_path in CANON_ROOTS.items():
        deps = []
        root_basename = os.path.basename(root_path)
        for rel, content in docs.items():
            if rel == root_path:
                continue
            # versioned corpus doc? (⟦ /name | … | vsm-X ⟧ footer)
            if not has_footer_version(os.path.join(ROOT, rel)):
                continue  # catalog/worklist/note — not a versioned corpus doc
            if is_ratified(os.path.join(ROOT, rel)):
                tipo = "co-firma"   # re-signs against the new policy
            elif is_active(os.path.join(ROOT, rel)):
                # canon-operating doc (active) must declare the canonical version;
                # proposed/conjecture/template/… are NOT canon — informational
                tipo = "aplicacion"
            else:
                tipo = "lectura"
            deps.append((rel, tipo))
        # sort: co-firma first (they re-sign), then aplicacion, then lectura
        deps.sort(key=lambda t: (0 if t[1] == "co-firma" else 1 if t[1] == "aplicacion" else 2, t[0]))
        graph[root_rel] = deps
    return graph


def needs_migration(root_path, deps):
    """True if any co-firma/aplicacion dependent has @vsm ≠ root's @vsm."""
    root_v = doc_version(os.path.join(ROOT, root_path))
    if not root_v:
        return False, []
    stale = []
    for rel, tipo in deps:
        if tipo == "lectura":
            continue
        dv = doc_version(os.path.join(ROOT, rel))
        if dv != root_v:
            stale.append((rel, tipo, dv))
    return bool(stale), stale


def emit_task(dep_rel, tipo, root_v, to_v):
    """Emit a task() block (TASKS.vsm syntax) with a manual gate."""
    name = f"VERSION-MIGRATE-{os.path.basename(dep_rel).replace('.', '-')}"
    action = {
        "co-firma": "re-sign: header/footer + @vsm line to new version — the mechanical evidence of review (covenant co-signature rule)",
        "aplicacion": "migrate: header/footer + @vsm line to new version, timestamp → UTC ISO 8601",
        "lectura": "verify-only: informational reference — no version migration required",
    }[tipo]
    return (
        f'task("{name}", priority=P1, agent=[S], gate="manual — {tipo} migration") = {{\n'
        f'  what: "VERSION-CHANGE-PLAN-HOOK: {dep_rel} is a {tipo} dependent of the\n'
        f'      canonical root (vsm-{root_v} → vsm-{to_v}). {action}.\n'
        f'      Hook emits the PLAN only — it does NOT modify docs.",\n'
        f'  status: open,\n'
        f'  recursion: "system → kernel (instrumentos)",\n'
        f'  organ: "S2 (coordinación) — grafo; S3 (control) — emite el plan; human executes",\n'
        f'  gate: "manual — review the migration before applying",\n'
        f'  done_when: "{dep_rel} declares @vsm {to_v} and passes the full battery",\n'
        f'  verified_by: "version-change-plan, ratified-version-current",\n'
        f'}}\n'
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["graph", "plan", "check"])
    ap.add_argument("--root", choices=list(CANON_ROOTS), default="vsl_language_primer")
    ap.add_argument("--file", default=None, help="check only this dependent (staged-file mode)")
    ap.add_argument("--to", default=None, help="target version (default: root's current @vsm)")
    args = ap.parse_args()

    graph = build_graph()

    if args.mode == "graph":
        for root_rel, deps in graph.items():
            print(f"# {root_rel} ({CANON_ROOTS[root_rel]})")
            for rel, tipo in deps:
                print(f"  depende_de({rel}, {root_rel}, tipo={tipo})")
        return 0

    root_path = CANON_ROOTS[args.root]
    root_v = doc_version(os.path.join(ROOT, root_path))
    if not root_v:
        print(f"FAIL: cannot read version from {root_path}", file=sys.stderr)
        return 1
    to_v = args.to or root_v

    stale, stale_list = needs_migration(root_path, graph[args.root])
    if args.mode == "check":
        if args.file:
            # staged-file mode: only this dependent matters
            hit = None
            for rel, tipo, dv in stale_list:
                if rel == args.file:
                    hit = (rel, tipo, dv)
                    break
            if hit:
                print(f"FAIL: {hit[0]} — {hit[1]} at vsm-{hit[2]} (root vsm-{root_v})")
                return 1
            print(f"PASS: {args.file} in sync (root vsm-{root_v})")
            return 0
        if stale:
            print(f"FAIL: {args.root} is at vsm-{root_v} but {len(stale_list)} dependents lag:")
            for rel, tipo, dv in stale_list:
                print(f"  {rel} — {tipo} at vsm-{dv} (root vsm-{root_v})")
            return 1
        print(f"PASS: {args.root} at vsm-{root_v} — all dependents in sync (no migration needed)")
        return 0

    # plan mode — emit task() blocks
    if stale:
        print(f"# VERSION-CHANGE-PLAN-HOOK — {args.root} bumped to vsm-{root_v}; "
              f"{len(stale_list)} dependents need migration:")
        for rel, tipo, dv in stale_list:
            print(emit_task(rel, tipo, root_v, to_v))
    else:
        print(f"# No migration needed: {args.root} at vsm-{root_v}, all dependents in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())