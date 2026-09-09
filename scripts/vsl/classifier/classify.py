#!/usr/bin/env python3
# design: docs/spec_revision/plan/classification-policy-plan-v1/classification_policy_plan.vsm
# (CLASSIFICATION-POLICY-PLAN-v1, PART IV-B tree_rules)
#        + docs/spec_revision/*/classification.local.vsm (políticas locales)
# classify.py — PARAMETRIC RECURSIVE classifier for the Socratic document tree.
#
# THE POLICY IS THE CODE'S SOURCE OF TRUTH: this script READS the
# machine-readable rule tables and applies them to any document under
# docs/spec_revision/. A tree change re-classifies without editing this file
# (R16 parametric pattern, same as version-change-plan: canonical read,
# parametric checks).
#
# RECURSIVE CHAIN (EXP-RECURSIVE-ENGINE v6, validated 2026-08-17): classification
# descends level by level, exactly like TreeOfContents.php — the SAME contract
# at every node:
#   level 0 = ROOT policy = tree_rules (classification_policy_plan.vsm PART IV-B)
#   level N = local policy of the level directory = classification.local.vsm
#             (each directory declares ITS OWN question group in its directory)
#   resolve: apply the current level's rules to the doc's TYPE → home
#            home="."  → the doc lives HERE (leaf reached)
#            home="sub" → descend into sub/ and apply ITS local policy
#            "?"       → the level's test did not resolve (coverage gap)
# The returned canonical home is the FULL chain ("plan/vsf-vsl-revision/phase-spec"),
# NOT the first level ("plan") — that was the 1-level defect this replaces.
#
# A directory with NO local policy is a GAP: its docs cannot be classified
# locally (visible, not invented) — the engine reports it; the level declares
# its policy when it grows.
#
# Usage:
#   python3 scripts/vsl/classify.py classify <abs-path>
#       → prints the canonical home chain (relative to spec_revision/)
#         for ONE file, or "?" when the tree does not resolve deterministically.
#   python3 scripts/vsl/classify.py tree
#       → prints the loaded rule tables (self-check: the instrument sees the policy).
#   python3 scripts/vsl/classify.py --self
#       → selftest: rule table loads, a known doc classifies correctly.
#
# Exit: 0 on success, 1 on failure (missing policy, unparseable table).
import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "docs/spec_revision/plan/classification-policy-plan-v1/classification_policy_plan.vsm"
SR = ROOT / "docs/spec_revision"
LOCAL_NAME = "classification.local.vsm"


class Rule:
    """One declarative leaf of the Socratic tree (PART IV-B or a local policy)."""

    def __init__(self, name: str, raw: str):
        self.name = name
        self.type = self._field(raw, "type", default="*")
        self.status = self._field(raw, "status", default="")
        self.home = self._field(raw, "home", default="")
        # plan_parent="true" → the rule only applies when the doc is
        # DECLARED as a spec/phase of an active plan (NODO 3: "¿tiene PLAN
        # padre activo? SÍ → plan/<plan>/<fase>/"). classify() resolves it by
        # consulting the plan tree — parametric, never hard-coded.
        self.plan_parent = self._field(raw, "plan_parent", default="") == "true"

    @staticmethod
    def _field(raw: str, key: str, default: str = "") -> str:
        m = re.search(rf"{key}=\"([^\"]*)\"", raw)
        return m.group(1) if m else default

    def matches(self, doc_type: str, doc_status: str) -> bool:
        """A rule matches when the doc's TYPE matches the pattern AND (if the
        rule constrains status) the @status matches. `type="*"` matches any
        type — a catch-all, used by the PROPUESTA rule (proposed → sandbox/)."""
        if not any(pat.strip() and fnmatch.fnmatch(doc_type, pat.strip())
                   for pat in self.type.split("|")):
            return False
        if self.status:
            # status is a prefix match: "design" matches "@status design"
            if not doc_status.startswith(self.status):
                return False
        return True

    def __repr__(self) -> str:
        return (f"rule({self.name}, type={self.type!r}, "
                f"status={self.status!r}, home={self.home!r})")


def parse_rules(text: str, source: str) -> list[Rule]:
    blocks = re.findall(r'rule\("([^"]+)"\s*,(.*?)\)', text, re.S)
    if not blocks:
        print(f"FAIL: rule table not found in {source}", file=sys.stderr)
        sys.exit(1)
    return [Rule(name, raw) for name, raw in blocks]


def load_root_rules() -> list[Rule]:
    """The ROOT policy: tree_rules (PART IV-B of classification_policy_plan.vsm).
    Fails LOUD when absent — a policy without rules is a defect, not a no-op."""
    if not POLICY.exists():
        print(f"FAIL: policy not found: {POLICY}", file=sys.stderr)
        sys.exit(1)
    return parse_rules(POLICY.read_text(encoding="utf-8"), str(POLICY))


def load_local_rules(level_dir: Path) -> list[Rule] | None:
    """The LOCAL policy of a level directory: classification.local.vsm.
    None when the level does not declare its own question group → GAP
    (the engine reports it; never invents an answer)."""
    pf = level_dir / LOCAL_NAME
    if not pf.exists():
        return None
    return parse_rules(pf.read_text(encoding="utf-8"), str(pf))


def read_doc_nature(path: Path) -> tuple[str, str]:
    """Read the TYPE (2nd header slot) and @status of a doc. Returns
    (type, status) — both possibly empty for untyped/gateway files."""
    try:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    except Exception:
        return "", ""
    m = re.match(r"⟦\s*([^|]+)\|\s*([^|]+)\s*\|", first)
    doc_type = m.group(2).strip() if m else ""
    # @status in first 10 lines
    head = ""
    try:
        head = "\n".join(path.read_text(encoding="utf-8").split("\n")[:10])
    except Exception:
        pass
    m2 = re.search(r"@status(?:\(V\))?\s+([a-z_]+)", head)
    doc_status = m2.group(1) if m2 else ""
    return doc_type, doc_status


def has_plan_parent(doc_basename: str) -> bool:
    """NODO 3: ¿tiene PLAN padre activo? — a spec belongs to a plan when it is
    DECLARED inside the plan tree: plan/<plan>/root.vsm references it as a
    phase/spec, or the trunk (plans_active.vsm) lists it. Consult the tree
    (parametric): a spec hooked to a plan is re-classified automatically when
    the plan declares it; never hard-coded here."""
    plan_dir = SR / "plan"
    if not plan_dir.exists():
        return False
    # trunk + every plan root — any declaration of the basename counts
    candidates = [plan_dir / "plans_active.vsm"]
    candidates += sorted(plan_dir.glob("*/root.vsm"))
    for p in candidates:
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if doc_basename in text:
            return True
    return False


def apply_chain(doc_type: str, doc_status: str, doc_name: str) -> str:
    """The RECURSIVE chain: apply the ROOT policy, then descend through each
    level's LOCAL policy until the leaf ("." is reached) or a level does not
    resolve. Returns the canonical home CHAIN ("plan/vsf-vsl-revision/phase-spec")
    or "?" when any level's test does not resolve (coverage gap)."""
    chain: list[str] = []
    rules = load_root_rules()
    level_dir = SR
    depth = 0
    while True:
        home = None
        for rule in rules:
            if not rule.matches(doc_type, doc_status):
                continue
            if rule.plan_parent and not has_plan_parent(doc_name):
                continue          # fall through (SIN-PLAN → sandbox)
            home = rule.home
            break
        if home is None or home == "?":
            return "?"            # the current level's test did not resolve
        if home == ".":
            break                 # leaf: the doc lives HERE
        chain.append(home)
        level_dir = level_dir / home
        # a level directory that does not exist physically = the tree does
        # not contain that branch → the doc cannot live there
        if not level_dir.exists():
            return "?"
        rules = load_local_rules(level_dir)
        if rules is None:
            break                 # no local policy → the doc lives HERE (GAP visible)
        depth += 1
        if depth > 12:
            return "?"            # defensive: no unbounded recursion
    return "/".join(chain) if chain else "."


def classify(path: Path) -> str:
    """Classify ONE file by the recursive chain. Gateway files (README/INDEX/
    classification.local.vsm) are the level's doors, not docs — return '.'."""
    name = path.name
    if name in ("README.vsm", "INDEX.vsm", LOCAL_NAME):
        return "."
    doc_type, doc_status = read_doc_nature(path)
    return apply_chain(doc_type, doc_status, name)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0
    if args[0] == "tree":
        for r in load_root_rules():
            print(r)
        return 0
    if args[0] == "--self":
        rules = load_root_rules()
        if len(rules) < 8:
            print(f"FAIL (selftest): expected ≥8 rules, got {len(rules)}",
                  file=sys.stderr)
            return 1
        # a known policy doc must resolve to its leaf chain (boot/)
        probe = SR / "system/boot/hard_rules.vsm"
        home = classify(probe)
        if home != "system/boot":
            print(f"FAIL (selftest): hard_rules.vsm → {home!r}, expected system/boot",
                  file=sys.stderr)
            return 1
        # a phase spec must resolve to its full leaf chain
        # (phase-spec/exp-token-grounding — la subcarpeta-categoría que la
        # materialización de colapsos creó; NUNCA volver a phase-spec/)
        probe2 = SR / "plan/vsf-vsl-revision/phase-spec/exp-token-grounding/EXP-TOKEN-GROUNDING.spec.vsm"
        home2 = classify(probe2)
        if home2 != "plan/vsf-vsl-revision/phase-spec/exp-token-grounding":
            print(f"FAIL (selftest): EXP-TOKEN-GROUNDING → {home2!r}, "
                  f"expected plan/vsf-vsl-revision/phase-spec/exp-token-grounding",
                  file=sys.stderr)
            return 1
        print(f"PASS (selftest): {len(rules)} rules; "
              f"hard_rules.vsm → {home}; EXP-TOKEN-GROUNDING → {home2}")
        return 0
    if args[0] == "classify":
        if len(args) < 2:
            print("usage: classify.py classify <abs-path>", file=sys.stderr)
            return 2
        p = Path(args[1]).resolve()
        if not p.exists():
            print("?", file=sys.stderr)
            return 0
        print(classify(p))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())