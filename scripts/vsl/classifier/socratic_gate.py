#!/usr/bin/env python3
"""socratic_gate.py — write-time socratic gate (PLUGIN-CLASS-TAXONOMY-v1, fase c).

design: docs/design/sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
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
    # MATTERS.vsm (2026-10-28, MATTER-ONTOLOGY-v1 P1): root-level living
    # registry next to TASKS.vsm. The CLASSIFY tree has no MATTERS- prefix;
    # its else_home='system' would force a false mismatch on a root file.
    # Same state-artifact doctrine as TASKS/HANDOFF/focus — not a doc to place.
    "MATTERS.vsm",
    # Living system registries with ratified operational homes outside
    # system/ (S5 calibration 2026-09-10): the tree routes REGISTRY types
    # to home='system', but docs/index.vsm ratifies docs/reference/ as
    # their home. Skipped like classification.local.vsm — not misplaced.
    "technical_debt_registry.vsm",
    # Root-level living roadmap (S5 migration 2026-10-04): referenced by
    # TASKS.vsm / boot protocol / instance.vsm from the repo root — same
    # root-living doctrine as TASKS/HANDOFF (no single docs/ home).
    "ROADMAP.vsm",
}
# Mirrors and dead archives are not classifiable working docs (2026-09-10):
# mirrors are verified copies (MIRROR.json), archive is not edited.
SKIP_DIRS = {
    "docs/canon_mirror",
    "docs/archive",
    # Decision trees are policy artifacts of the plugin layer (same
    # doctrine as SKIP_NAMES policy-local doors): they live under
    # .opencode/plugins/support/trees/ by construction and are not docs
    # to place — the CLASSIFY questionnaire has no home for them
    # (health_check.tree.vsm migrated 2026-10-04, S5 containment).
    ".opencode/plugins/support/trees",
    # The epistemic store (findings/guards/sidecars) is state, not the
    # working-docs corpus — same doctrine as STATE-ARTIFACTS-2026-09-06
    # (TASKS/HANDOFF/focus are dynamic state). *.claims.vsm sidecars live
    # WITH their findings as store evidence; their home is the store, not
    # a docs/ area (exposed when state/ tracking landed, 2026-09-30).
    "state",
    # CHILD-ARCHIVE-LEGACY (2026-10-14, rmw3 S5): the executor's tree moved
    # child/ → docs/archive/child/. "docs/archive" (above) already excludes
    # it from this corpus; the former "child/sandbox" + "child" SKIP_DIRS
    # entries were retired as vestigial (child/ no longer exists at root).
    # packages/ = vendored distributions + their upstream docs (S5
    # containment 2026-10-04): verified copies with their own house style,
    # same doctrine as canon_mirror — not this repo's working corpus.
    "packages",
}
# known homes: physical root for every logical home the CLASSIFY tree emits.
# 2026-10-28 decomposition: the old tree rooted everything under
# docs/spec_revision/; working docs now live under docs/design/, docs/plans/,
# docs/learning_records/, docs/ledger/, docs/incidents/ and the archive.
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
    "learning": "docs/learning_records",
    "experiment": "docs/plans",
    "papers": "docs/papers",
    "plan": "docs/plans",
    "archive": "docs/archive/spec_revision_2026-10-28/archive",
    "design": "docs/design/sources",
    "design-sources": "docs/design/sources",
    "plugin": ".opencode/plugins",
    "ledger": "docs/ledger",
    "incidents": "docs/incidents",
    "kernel": "system/kernel",
    "sandbox": "docs/design/sandbox",
    "instance": "system/instance",
    "s1-operations": "system/s1-operations",
    "s2-coordination": "system/s2-coordination",
    "s3star-audit": "system/s3star-audit",
    # internal (2026-08-20, CLASSIFY-PATH-NULL-NOISE facet 2a): agent
    # study/audit reports in docs/internal/ — OUTSIDE of
    # docs/spec_revision/ (the spec_revision replace does not apply, hence
    # the mapping is the full path relative to the repo root).
    "internal": "docs/internal",
}


def read_doc_type(path: Path) -> str:
    """Extracts the TYPE (slot 2 of the header ⟦ name | TYPE | vsm ⟧).

    Distinguishes the old format (⟦ name | vsm-1.0 | 2026-06-04 ⟧ — no
    separate TYPE; slot 3 = date) from the modern one (⟦ name | TYPE |
    vsm-1.2 ⟧ — slot 3 = vsm version). If slot 3 is a date there is NO
    TYPE → "" (the doc is not classifiable → '?' R9, never a false 'out
    of place'). CLASSIFY-PATH-NULL-NOISE facet 2a (2026-08-20): old
    signoffs/audits in docs/internal/ read 'vsm-1.0' as TYPE →
    else_home=system → false positives."""
    try:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    except Exception:
        return ""
    m = re.match(r"⟦\s*[^|]+\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|", first)
    if not m:
        return ""
    slot2, slot3 = m.group(1).strip(), m.group(2).strip()
    # old format: slot 3 = date (YYYY-MM-DD) → slot 2 is the version, not TYPE
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

    try:
        _rel = str(path.relative_to(ROOT))
    except ValueError:
        _rel = str(path)
    if path.name in SKIP_NAMES or any(
            _rel == d or _rel.startswith(d + "/") for d in SKIP_DIRS):
        # policy-local door / README / INDEX / mirrors / dead archives —
        # not classifiable working docs (TAXONOMY-V2-HOME-MISMATCH)
        print(f"[SOCRATIC-CLASSIFY] {path.name}: artefacto no clasificable "
              f"— skip", file=sys.stderr)
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

    # HOMES now carries the full post-decomposition path, so workspace
    # aliases are no longer needed for migrated roots. Kept empty as the
    # extension point for future ratified aliases (do not re-add legacy
    # spec_revision prefixes here).
    _WORKSPACE_HOMES: dict[str, str] = {}
    # Working-docs zone (S5 triage 2026-09-10, corpus matrix: 22/31 docs
    # route to home='system' while legitimately living here). A doc whose
    # TYPE routes to 'system' but lives under a working dir is working
    # material, not misplaced — the gate still fires outside the tree.
    _WORKSPACE_SYSTEM_DIRS = {
        "docs/plans", "docs/architecture", "docs/reference", "docs/guides",
        "docs/specs", "docs",
    }
    candidates = [expected_rel]
    if home in _WORKSPACE_HOMES:
        candidates.append(_WORKSPACE_HOMES[home])
    if home == "system":
        candidates.extend(sorted(_WORKSPACE_SYSTEM_DIRS))
    # S5 calibration 2026-10-04: records whose ratified home moved with
    # the migration (one alias per relocated home, documented).
    _HOME_WORKSPACE_ALIASES = {
        "vsl-language": ["docs/sessions"],   # session briefs record the spec
        "incident": ["packages/public/vsf-rsi/docs/ir"],  # superseded by packages skip
        "boot": ["docs/spec"],               # boot primer under docs/spec/agent_protocol
        "sandbox": ["docs/internal"],        # kernel scaffolding register
        "plan": ["docs/roadmap",  # roadmap records (docs/roadmap/)
                 # Project-workspace plans (calibration 2026-10-19): the
                 # arc-prize plans (viarc*_master_plan/next_run_plan,
                 # PLAN-v1) are project docs under their project — same
                 # doctrine as R_param_resolution (substrate artifacts stay
                 # with the substrate). Keeps all other homes checked.
                 "projects/arc-prize/knowledge"],
        "s5-policy": ["docs/design/sandbox"],  # sandbox reports (spec_revision)
    }
    candidates.extend(_HOME_WORKSPACE_ALIASES.get(home, []))

    _orig_dir = str(rel.parent)  # pre-strip path (spec_revision docs)

    def _matches(exp: str) -> bool:
        for d in (real_dir, _orig_dir):
            if (d == exp or d.endswith(exp) or exp.endswith(d)
                    or (exp + "/") in (d + "/")):
                return True
        return False

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