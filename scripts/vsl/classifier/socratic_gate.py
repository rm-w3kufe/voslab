#!/usr/bin/env python3
"""socratic_gate.py — write-time socratic gate (PLUGIN-CLASS-TAXONOMY-v1, fase c).

design: docs/spec_revision/design-sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
(PLUGIN-CLASS-TAXONOMY-v1 — write-time universal: el questionnaire IS el gate).

WHY (2026-08-18, fase c — rmw3 S5 "todos son de mi interés"): the registry
write_gates.vsm declares gates as external cmds. This gate makes the
SOCRATIC QUESTIONNAIRE itself a write-time gate: the CLASSIFY tree
(classify.tree.vsm) is evaluated against the TYPE of the file being
written, and the answer (home) is compared with the file's REAL directory.
A mismatch blocks the write (policy breach: the doc is being created in the
wrong place per its own declared nature).

R10: the engine decides with structural evidence (certified=True). If the
engine reports UNKNOWN (no TYPE readable, or the tree cannot decide), the
gate does NOT block — it reports '?' visibly (R9: no silent concession) as
an advisory, never as a false block.

Contract:
  exit 0 — home matches real dir, or UNKNOWN (advisory)
  exit 1 — home ≠ real dir (misclassification = policy breach)
  stderr — [SOCRATIC-CLASSIFY] report: the tree's answer vs reality
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "scripts/vsl/classifier/vsf_socratic_engine.py"
TREE = ROOT / ".opencode/plugins/support/trees/classify.tree.vsm"
# Policy-local artifacts are NOT classifiable docs: they are the per-directory
# classification doors themselves (classify.py LOCAL_NAME; socratic_proposal.py
# SKIP tuple). The CLASSIFY tree routes DIR-CLASSIFICATION-LOCAL to system via
# the generic DIR- rule, but these files live in EVERY directory — no single
# home. Consistent with classify.py/socratic_proposal.py: skip them, they are
# not docs to place. (TAXONOMY-V2-HOME-MISMATCH, 2026-08-19.)
# STATE-ARTIFACTS-2026-09-06: TASKS/HANDOFF/focus are dynamic state, not docs.
SKIP_NAMES = {
    "classification.local.vsm", "README.vsm", "INDEX.vsm",
    "TASKS.vsm", "HANDOFF.vsm", "current_focus.json",
    # Living system registries with ratified operational homes outside
    # system/ (S5 calibration 2026-09-10): the tree routes REGISTRY types
    # to home='system', but docs/index.vsm ratifies docs/reference/ as
    # their home. Skipped like classification.local.vsm — not misplaced.
    "technical_debt_registry.vsm",
}
# known homes: where the tree may route a doc under docs/spec_revision/system/
HOMES = {
    "vsl-language": "system/s5-policy/vsl-language",
    "s3-control": "system/s3-control",
    "s4-intelligence": "system/s4-intelligence",
    "boot": "system/boot",
    "s5-policy": "system/s5-policy",
    "system": "system",  # else
    # v2 (2026-08-19, HOOK-ARGS-CONTRACT-REPAIR): homes for the extended tree —
    # routes docs OUTSIDE system/ too (learning_records/, plan/, sandbox/...).
    # The gate compares the real dir under docs/spec_revision/ (the replace
    # below strips the prefix), so these are relative to that root.
    "learning": "learning_records",
    "experiment": "plan",
    "papers": "papers",
    "plan": "plan",
    "archive": "archive",
    "design": "design-sources",
    "plugin": ".opencode/plugins",
    "ledger": "ledger",
    "incidents": "incidents",
    "kernel": "kernel",
    "sandbox": "sandbox",
    "instance": "instance",
    "s1-operations": "system/s1-operations",
    "s2-coordination": "system/s2-coordination",
    "s3star-audit": "system/s3star-audit",
    # internal (2026-08-20, CLASSIFY-PATH-NULL-NOISE 2a faceta): informes
    # de estudio/auditoría del agente en docs/internal/ — FUERA de
    # docs/spec_revision/ (el replace de spec_revision no aplica, por eso
    # el mapping es la ruta relativa completa al repo root).
    "internal": "docs/internal",
}


def read_doc_type(path: Path) -> str:
    """Extrae el TYPE (slot 2 del header ⟦ name | TYPE | vsm ⟧).

    Distingue el formato viejo (⟦ name | vsm-1.0 | 2026-06-04 ⟧ — sin TYPE
    separado; slot 3 = fecha) del moderno (⟦ name | TYPE | vsm-1.2 ⟧ —
    slot 3 = versión vsm). Si slot 3 es una fecha, NO hay TYPE → "" (el
    doc no es clasificable → '?' R9, nunca un falso 'fuera de lugar').
    CLASSIFY-PATH-NULL-NOISE 2a faceta (2026-08-20): los signoffs/auditorías
    viejas en docs/internal/ leían 'vsm-1.0' como TYPE → else_home=system
    → falsos positivos."""
    try:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    except Exception:
        return ""
    m = re.match(r"⟦\s*[^|]+\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|", first)
    if not m:
        return ""
    slot2, slot3 = m.group(1).strip(), m.group(2).strip()
    # formato viejo: slot 3 = fecha (YYYY-MM-DD) → slot 2 es la versión, no TYPE
    if re.match(r"\d{4}-\d{2}-\d{2}", slot3):
        return ""
    return slot2


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: socratic_gate.py <file.vsm>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).resolve()
    if not path.exists():
        print("[SOCRATIC-CLASSIFY] file not found:", path, file=sys.stderr)
        return 1

    if path.name in SKIP_NAMES:
        # policy-local door / README / INDEX — not a classifiable doc
        # (TAXONOMY-V2-HOME-MISMATCH, 2026-08-19)
        print(f"[SOCRATIC-CLASSIFY] {path.name}: artefacto de política local — "
              f"no clasificable (skip)", file=sys.stderr)
        return 0

    doc_type = read_doc_type(path)
    # evaluate the CLASSIFY tree with the engine (the questionnaire)
    try:
        p = subprocess.run(
            ["python3", str(ENGINE), "eval-tree", str(TREE),
             "--doc-type", doc_type],
            capture_output=True, text=True, timeout=30, cwd=ROOT)
        if p.returncode != 0:
            print(f"[SOCRATIC-CLASSIFY] engine error: {p.stderr.strip()}",
                  file=sys.stderr)
            return 1
        decision = json.loads(p.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        print(f"[SOCRATIC-CLASSIFY] engine unavailable: {e}", file=sys.stderr)
        return 1

    home = decision.get("home")
    truth = decision.get("truth")
    certified = decision.get("certified", False)

    if truth == "UNKNOWN" or home is None:
        # R9: no inventar, no conceder silenciosamente — report '?', do NOT block
        print("[SOCRATIC-CLASSIFY] UNKNOWN (no TYPE o árbol indecidible) — "
              "'?' visible, no bloquea (R9)", file=sys.stderr)
        return 0

    expected_rel = HOMES.get(home)
    if expected_rel is None:
        print(f"[SOCRATIC-CLASSIFY] home '{home}' sin mapping en HOMES — "
              f"reportado, no bloquea", file=sys.stderr)
        return 0

    # compare with the file's REAL directory (relative to repo root)
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path  # fuera del repo — no podemos comparar
    real_dir = str(rel.parent)
    real_dir = real_dir.replace("docs/spec_revision/", "", 1)

    # Recalibration 2026-09-10 (S5 triage): working docs live OUTSIDE
    # docs/spec_revision/ (docs/plans/, docs/archive/, ...). The HOMES
    # table is relative to the spec_revision root, so those files
    # mismatched systematically. Workspace aliases complete the mapping;
    # anything still unmatched keeps reporting MISMATCH (advisory-safe).
    _WORKSPACE_HOMES = {
        "plan": "docs/plans",
        "archive": "docs/archive",
    }
    candidates = [expected_rel]
    if home in _WORKSPACE_HOMES:
        candidates.append(_WORKSPACE_HOMES[home])

    def _matches(exp: str) -> bool:
        return (real_dir == exp or real_dir.endswith(exp)
                or exp.endswith(real_dir)
                or (exp + "/") in (real_dir + "/"))

    if any(_matches(exp) for exp in candidates):
        print(f"[SOCRATIC-CLASSIFY] {path.name}: home='{home}' ✓ coincide "
              f"(real: {real_dir})", file=sys.stderr)
        return 0

    print(f"[SOCRATIC-CLASSIFY] {path.name}: MISMATCH — el árbol dice "
          f"home='{home}' (esperado {expected_rel}) pero el archivo vive en "
          f"{real_dir} — clasificación violada (certified={certified})",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())