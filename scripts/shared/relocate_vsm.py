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
# INCIDENT-CHILD-TAIL-CORRUPTION-2026-08-18 (R13): relocate_vsm.py es el
# ÚNICO órgano del root que toca child/ por diseño. Todo toque a child/
# (fuera de child/docs/archive/) DEBE generar un dispatch φ↓ al child —
# nunca un touch silencioso (la corrupción tail→TASKS.vsm de ds-30 llegó
# al child sin aviso; el child la detectó en su propio boot días después).
# checks/child-refs-notify-valid verifica este mecanismo (drift guard) +
# que los dispatches del parent son conformes (footer — R18).
CHILD_DEPLOY = "child/docs/deploy/"
DISPATCH_HEADER = "PARENT-DISPATCH-REFS-NOTIFY-v1"


def _dispatch_touched_child(paths):
    """True si algún path remapeado vive bajo child/ (fuera de archives)."""
    return any(p.startswith("child/") and "docs/archive/" not in p for p in paths)


def write_child_notify(paths, old, new, dry_run):
    """Genera un dispatch φ↓ en child/docs/deploy/ listando los archivos
    child/ tocados por el remap. Formato canónico de envelope CON footer
    (lección R18 del incidente: el dispatch sin footer no parseaba y
    bloqueó el gate del child). Devuelve el nombre del dispatch."""
    if dry_run:
        print(f"◯ child/ tocado ({len(paths)} archivos) — dispatch φ↓ se generará al ejecutar")
        return None
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fname = f"{ts[:10]}_{ts[11:]}_parent_dispatch_refs_notify.vsm"
    fname = f"{ts[:10]}_parent_dispatch_refs_notify_{ts[11:17]}.vsm"
    path = os.path.join(ROOT, CHILD_DEPLOY, fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        f"⟦ parent_dispatch_refs_notify | {DISPATCH_HEADER} | vsm-1.2.1 | {ts} ⟧",
        "",
        "@vsm 1.2.1",
        "// ══════════════════════════════════════════════════════════════",
        "// PARENT DISPATCH — REFS NOTIFY (INCIDENT-CHILD-TAIL-CORRUPTION)",
        "// from: vsf-s3-planner (S3, root)  ·  to: vsf-s1-executor (S1, child)",
        f"// date: {ts}  ·  tool: relocate_vsm.py  ·  remap: {old} → {new}",
        "// ══════════════════════════════════════════════════════════════",
        "",
        "// ─── AVISO ─────────────────────────────────────────────────────",
        "// El root ejecutó un remap de refs que tocó archivos de TU árbol",
        "// (child/). Lista de archivos tocados:",
    ]
    for p in sorted(paths):
        lines.append(f"//   - {p}")
    lines += [
        "",
        "// ─── ACCIONES ──────────────────────────────────────────────────",
        "// 1. Revisa los archivos listados: el remap actualizó refs de paths",
        "//    (re-architecture) — contenido semántico intacto.",
        "// 2. Commitea en tu rama (feat/s1-child) o revierte si el cambio",
        "//    no aplica a tu árbol.",
        "// 3. Si detectas corrupción (ej: find-replace ciego de substring),",
        "//    repórtala al parent ANTES de reparar (R13 bidireccional).",
        "",
        f"⟦ /parent_dispatch_refs_notify ⟧",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✓ dispatch φ↓ al child: {CHILD_DEPLOY}{fname} ({len(paths)} archivos child/ tocados)")
    return fname


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
    already_moved = new_exists  # pattern B: git mv ya lo movió (plugin after)

    # 0. snapshot refs rotas pre-move (baseline)
    pre_broken = set(broken_refs())

    # 1. git mv — SOLO si el mv no ocurrió aún (pattern A)
    if not dry_run and not already_moved:
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        r = subprocess.run(["git", "mv", old, new], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            # fallback: plain mv (file may be untracked)
            os.rename(old_abs, new_abs)
            print(f"  (git mv falló: {r.stderr.strip()[:80]} — usé os.rename)")
    elif not dry_run and already_moved:
        print(f"◯ mv ya hecho (old no existe, new sí) — solo remapeo refs")

    # 2. header interno del doc movido: // <old> → // <new>
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

    # 3. remap corpus: <old> → <new> en todos los archivos que lo citan
    hits = 0
    child_touched = []
    for path in corpus_files():
        rel = path.replace(ROOT + "/", "")
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
            # INCIDENT-CHILD-TAIL-CORRUPTION: registra todo touch a child/
            if rel.startswith("child/"):
                child_touched.append(rel)
    print(f"✓ {hits} archivos del corpus remapeados: {old} → {new}")

    # 3b. R13 notify (INCIDENT-CHILD-TAIL-CORRUPTION-2026-08-18): el remap
    #     tocó child/ → dispatch φ↓ obligatorio al child. Nunca silencioso.
    if child_touched:
        write_child_notify(child_touched, old, new, dry_run)

    # 4. re-baseline hash en boot_manifest.vsm si el doc está declarado
    manifest = os.path.join(ROOT, "docs/spec_revision/system/boot/boot_manifest.vsm")
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

    # 5. censo post-move
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