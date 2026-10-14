#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/relocate-vsm-v1/relocate_vsm_spec.vsm
"""
relocate_vsm.py — RELOCATE-VSM motor determinista (propuesta sandbox 2026-08-14).

Mueve un documento @vsm 1.0 y remapea TODAS las refs pineadas del corpus al
nuevo path: headers internos del doc movido, refs en canon activo, re-baseline
de hashes en boot_manifest.vsm. La tarea 'mover docs' deja de ser manual
(incidente DIR-SCHEMA-RECURSIVE: 29 renames, ~90% del esfuerzo en refs).

Usage:
  python3 scripts/docs/relocate_vsm.py --from <old> --to <new> [--dry-run]

Exit: 0 = movido + remapeado + 0 refs rotas nuevas · 1 = error.

Corpus: docs/spec_revision/ + docs/experiments/ + docs/plan/ + TASKS.vsm +
        child/sandbox/ + scripts/. Excluye registros (docs/archive/,
        docs/sessions/, child/docs/archive/) y no-code (node_modules, .git).
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

import os
ROOT = os.environ.get("VOS_ROOT", os.getcwd())
CORPUS = [
    "docs/spec_revision/",
    "docs/experiments/",
    "docs/plan/",
    "TASKS.vsm",
    "child/sandbox/",
    "scripts/",
]
EXCLUDE_DIRS = {"docs/archive/", "docs/sessions/", "child/docs/archive/",
                "node_modules/", ".git/"}
VSM_REF = re.compile(r"(?:docs|child)/[a-zA-Z0-9_./-]+\.vsm")
# CHILD-ARCHIVE-LEGACY (2026-10-14, rmw3 S5, L4): the φ↓ child dispatch
# mechanism (INCIDENT-CHILD-TAIL-CORRUPTION-2026-08-18) is RETIRED. child/
# is archived at docs/archive/child/ — there is no live child to notify, and
# no child/docs/deploy/ to write into. The drift guard that verified it
# (checks/child-refs-notify-valid) was retired in the same commit. The
# incident lesson (never touch a subtree silently) now applies via the
# canonical R17/consent gate, not a bespoke dispatch organ.


def corpus_files():
    """Yields (abspath) of all corpus files that can carry refs."""
    for base in CORPUS:
        full = os.path.join(ROOT, base)
        if os.path.isfile(full):
            yield full
        elif os.path.isdir(full):
            for dirpath, dirnames, filenames in os.walk(full):
                dirnames[:] = [d for d in dirnames
                               if os.path.join(dirpath, d).replace(ROOT + "/", "")
                               not in EXCLUDE_DIRS
                               and d != "node_modules"]
                if any(ex in dirpath.replace(ROOT + "/", "") for ex in EXCLUDE_DIRS):
                    continue
                for fn in filenames:
                    if fn.endswith((".vsm", ".md", ".sh", ".py", ".json")):
                        yield os.path.join(dirpath, fn)


def broken_refs():
    """Census of .vsm refs under docs/ that do not resolve (canon-scope)."""
    broken = []
    for path in corpus_files():
        if not path.endswith((".vsm", ".md")):
            continue
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for m in VSM_REF.finditer(txt):
            ref = m.group(0)
            if ref.startswith(("docs/spec_revision/", "docs/experiments/", "docs/plan/")):
                if not os.path.exists(os.path.join(ROOT, ref)):
                    broken.append((path.replace(ROOT + "/", ""), ref))
    return sorted(set(broken))


def relocate(old, new, dry_run):
    """Move doc + remap refs corpus-wide.

    Two call patterns are supported (the plugin fires AFTER the agent's
    `git mv` — tool.execute.after — so the move may already be done):
      A) old exists,  new missing  → this script does the git mv + remap
      B) old missing, new exists   → move already happened → remap only
    Anything else (both exist / both missing) is a real error.
    """
    old_abs = os.path.join(ROOT, old)
    new_abs = os.path.join(ROOT, new)
    old_exists = os.path.exists(old_abs)
    new_exists = os.path.exists(new_abs)

    if old_exists and new_exists:
        sys.exit(f"✗ --from Y --to existen ambos: {old} y {new} — "
                 "¿el mv ya se hizo y --to es incorrecto? Aborta.")
    if not old_exists and not new_exists:
        sys.exit(f"✗ ni --from ni --to existen: {old} → {new}")
    already_moved = new_exists  # pattern B: git mv already moved it (plugin after)

    # 0. snapshot of broken refs pre-move (baseline)
    pre_broken = set(broken_refs())

    # 1. git mv — ONLY if the mv has not happened yet (pattern A)
    if not dry_run and not already_moved:
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        r = subprocess.run(["git", "mv", old, new], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            # fallback: plain mv (file may be untracked)
            os.rename(old_abs, new_abs)
            print(f"  (git mv falló: {r.stderr.strip()[:80]} — usé os.rename)")
    elif not dry_run and already_moved:
        print(f"◯ mv ya hecho (old no existe, new sí) — solo remapeo refs")

    # 2. internal header of the moved doc: // <old> → // <new>
    if not dry_run:
        try:
            txt = open(new_abs, encoding="utf-8").read()
            if old in txt:
                txt = txt.replace(old, new)
                open(new_abs, "w", encoding="utf-8").write(txt)
                print(f"✓ header interno remapeado: {new}")
            else:
                print(f"◯ header interno: '{old}' no aparecía en el doc (OK si el doc no se auto-cita)")
        except Exception as e:
            print(f"⚠ header interno no procesado: {e}")

    # 3. remap corpus: <old> → <new> in every file that cites it
    hits = 0
    for path in corpus_files():
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            continue
        if old not in txt:
            continue
        hits += 1
        new_txt = txt.replace(old, new)
        if not dry_run:
            open(path, "w", encoding="utf-8").write(new_txt)
    print(f"✓ {hits} archivos del corpus remapeados: {old} → {new}")

    # 4. re-baseline hash in boot_manifest.vsm if the doc is declared
    manifest = os.path.join(ROOT, "system/boot/boot_manifest.vsm")  # post-migration (FND-BOOTOOLS-PATH-DRIFT-01)
    if os.path.exists(manifest):
        m = open(manifest, encoding="utf-8").read()
        if old in m and not dry_run:
            import hashlib
            h = hashlib.sha256(open(new_abs, "rb").read()).hexdigest()[:16]
            # replace the artifact() entry's hash after its path
            pattern = re.compile(
                r'(artifact\("[^"]*' + re.escape(old) + r'"[^"]*hash=")[^"]*(")')
            m2 = pattern.sub(lambda mm: mm.group(1) + h + mm.group(2), m)
            if m2 != m:
                open(manifest, "w", encoding="utf-8").write(m2)
                print(f"✓ manifest hash re-baselineado: {h}")
        elif old in m:
            print("◯ manifest hash se re-baselineará al ejecutar (no dry-run)")

    # 5. post-move census
    if not dry_run:
        post = set(broken_refs())
        new_broken = post - pre_broken
        if new_broken:
            print("✗ REFS ROTAS NUEVAS:")
            for p, ref in sorted(new_broken):
                print(f"   {p} → {ref}")
            return 1
        print("✓ 0 refs rotas nuevas (censo post-move)")
    else:
        print("◯ dry-run — sin cambios escritos")

    return 0


def main():
    ap = argparse.ArgumentParser(description="RELOCATE-VSM: mover @vsm 1.0 + remap refs")
    ap.add_argument("--from", dest="old", required=True)
    ap.add_argument("--to", dest="new", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rc = relocate(args.old, args.new, args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()