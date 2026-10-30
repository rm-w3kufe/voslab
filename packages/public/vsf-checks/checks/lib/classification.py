#!/usr/bin/env python3
# design: docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm
# (CLASSIFICATION-POLICY-PLAN-v1, S5 rmw3 2026-08-17)
# (R16_impl_with_design — DESIGN-SOURCES-POLICY; PART II questionnaire)
# CLAIM: classification-v2-valid holds — every .vsm under the three
# post-decomposition roots whose nature the tree resolves lives in the
# directory its NATURE prescribes. Classification = applying the questionnaire
# (binary, Socratic, non-leading) recursively — the SAME contract at every
# level — until the leaf directory.
#
# 2026-10-29 (Fase 3c): replaces classification-valid for the post-retirement
# layout. Scope is the system tree + design sources/sandbox; plan/learning/
# ledger/incidents have their own structural checks. Docs the tree does not
# resolve are counted as legacy coverage gaps (visible, not misclassified);
# check-file stays strict for new writes.
#
# MODES:
#   pass       -> scan the active roots; a resolved doc must be canonical.
#   check-file -> (single-arg path) strict O(1) classification for one file.
#   fail       -> deliberately-false variant (R4.1: ALWAYS exits non-zero).
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve()
while not (ROOT / ".git").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
CLASSIFY = ROOT / "scripts" / "vsl" / "classifier" / "classify.py"
GATEWAYS = {"README.vsm", "INDEX.vsm", "classification.local.vsm"}
ROOTS = [
    ("system", ROOT / "system"),
    ("design-sources", ROOT / "docs" / "design" / "sources"),
    ("sandbox", ROOT / "docs" / "design" / "sandbox"),
]


def load_classifier():
    if not CLASSIFY.is_file():
        return None
    spec = importlib.util.spec_from_file_location("classify", CLASSIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def actual_for(path: Path):
    """Return the logical directory chain for path, or None if outside roots."""
    path = path.resolve()
    for prefix, base in ROOTS:
        try:
            rel = path.relative_to(base.resolve())
        except ValueError:
            continue
        parent = rel.parent
        return prefix if str(parent) == "." else f"{prefix}/{parent.as_posix()}"
    return None


def check_one(f: Path, C, strict: bool = False):
    """Return (violation|None, unclassified_flag)."""
    if f.name in GATEWAYS or f.suffix != ".vsm":
        return None, False
    actual = actual_for(f)
    if actual is None:
        return None, False
    home = C.classify(f)
    if home == "":
        return None, False
    rel = f.resolve().relative_to(ROOT)
    if home == "?":
        msg = f"  {rel} — el árbol NO lo clasifica (gap de cobertura en la cadena)"
        return (msg if strict else None), True
    if actual != home and not actual.startswith(home + "/"):
        return f"  {rel} — el árbol clasifica {home}/, encontrado en {actual}/", False
    return None, False


def main(argv):
    mode = "pass"
    if len(argv) > 1 and argv[1]:
        mode = argv[1]
    C = load_classifier()
    if C is None:
        print("SKIP: scripts/vsl/classifier/classify.py ausente")
        return 0

    if mode == "fail":
        FIXDIR = ROOT / "docs" / "design" / "sandbox"
        FIXDIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=".vsm", dir=str(FIXDIR))
        Path(name).write_text(
            '⟦ fix | AXIS2-FIRST-LOOP | vsm-1.2 | 2026-08-17 ⟧\n'
            "@status active\n"
            'fact("fix") = { body: "fixture" }\n'
        )
        home = C.classify(Path(name))
        Path(name).unlink(missing_ok=True)
        if home == "ledger":
            print("FAIL(fail-mode): fixture classified ledger — check cannot discriminate", file=sys.stderr)
            return 1
        print("FAIL (negative): fixture did not pass — the false claim does not hold", file=sys.stderr)
        return 1

    if mode == "check-file":
        if len(argv) < 3:
            print("usage: classification-v2-valid check-file <path>", file=sys.stderr)
            return 2
        f = Path(argv[2]).resolve()
        if actual_for(f) is None:
            print(f"OK: {f.name} — fuera de las raíces activas (claim no aplica)")
            return 0
        violation, _ = check_one(f, C, strict=True)
        if violation:
            print(violation)
            return 1
        print(f"OK: {f.name} — directorio canónico según el árbol")
        return 0

    if mode != "pass":
        print("usage: classification-v2-valid pass|fail|check-file <path>", file=sys.stderr)
        return 2

    violations = []
    unclassified = 0
    count = 0
    for _prefix, base in ROOTS:
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.vsm")):
            violation, gap = check_one(f, C, strict=False)
            if violation:
                violations.append(violation)
            else:
                count += 1
                unclassified += 1 if gap else 0

    if violations:
        print("FAIL: classification-v2-valid — hoja del árbol ≠ directorio real:")
        for v in violations:
            print(v)
        print("  Reclasificar según PART II/IV-B (plan/classification_policy_plan.vsm)")
        return 1
    print(f"PASS: classification-v2-valid — {count} documentos en directorio canónico "
          f"({unclassified} sin clasificar, legado)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
