#!/usr/bin/env python3
# design: docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm
# (CLASSIFICATION-POLICY-PLAN-v1, PART IV-B tree_rules)
#        + <root>/*/classification.local.vsm (local policies)
# classify.py — PARAMETRIC RECURSIVE classifier for the Socratic document tree.
#
# THE POLICY IS THE CODE'S SOURCE OF TRUTH: this script READS the
# machine-readable rule tables and applies them to any document under the
# post-decomposition roots (system/, docs/design/sources/, docs/plans/, ...).
# A tree change re-classifies without editing this file (R16 parametric
# pattern, same as version-change-plan: canonical read, parametric checks).
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
# The returned canonical home is the FULL LOGICAL chain
# ("plan/vsf-vsl-revision/phase-spec"), NOT the first level ("plan") — the
# first level is translated to its physical root by HOME_ROOTS; deeper levels
# are physical subdirectories of that root.
#
# A directory with NO local policy is a GAP: its docs cannot be classified
# locally (visible, not invented) — the engine reports it; the level declares
# its policy when it grows.
#
# Usage:
#   python3 scripts/vsl/classify.py classify <abs-path>
#       → prints the canonical logical home chain for ONE file, or "?" when
#         the tree does not resolve deterministically.
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
POLICY = ROOT / "docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm"
PLAN_DIR = ROOT / "docs/plans"
LOCAL_NAME = "classification.local.vsm"

# 2026-10-28 decomposition: the root policy still names LOGICAL homes
# (system, plan, design-sources, sandbox, learning_records, ledger, incidents,
# archive). The physical roots moved; this table is the only place that knows
# the mapping. Deeper levels are always <physical_root>/<local_home>.
#
# 2026-10-29 F4 DOC-HOME-POLICY: the table is now DECLARED in the policy doc
# (`home_policy:` block) and loaded below. These defaults keep the classifier
# usable if an older policy doc is checked out; the declared block wins.
_DEFAULT_HOME_ROOTS = {
    "system": ROOT / "system",
    "plan": ROOT / "docs/plans",
    "design-sources": ROOT / "docs/design/sources",
    "design": ROOT / "docs/design/sources",
    "sandbox": ROOT / "docs/design/sandbox",
    "learning_records": ROOT / "state/learning_records",
    "learning": ROOT / "state/learning_records",
    "ledger": ROOT / "docs/ledger",
    "incidents": ROOT / "docs/incidents",
    "archive": ROOT / "docs/archive/spec_revision_2026-10-28/archive",
    "sessions": ROOT / "docs/sessions",
    "audit": ROOT / "docs/audit",
    "findings": ROOT / "docs/findings",
    "evaluation": ROOT / "docs/evaluation",
    "rubric": ROOT / "docs/rubric",
    "deploy": ROOT / "docs/deploy",
    "historical": ROOT / "docs/historical",
    "papers": ROOT / "docs/papers",
    "publishing": ROOT / "docs/publishing",
    "outreach": ROOT / "docs/outreach",
    "charts": ROOT / "docs/charts",
    "corpus": ROOT / "docs/corpus",
    "guides": ROOT / "docs/guides",
    "reference": ROOT / "docs/reference",
    "vault": ROOT / "docs/vault",
    "notebooks": ROOT / "docs/notebooks",
    "metaphors": ROOT / "docs/metaphors",
    "memory": ROOT / "docs/memory",
    "correspondence": ROOT / "docs/correspondence",
}

# Logical homes where NEW docs may be born. `archive` is a record home but
# frozen (no direct writes); `internal`, `experiments`, `spec`, `specs`,
# `governance`, `theory`, ... are legacy areas with no new-doc admission.
_DEFAULT_APPROVED_HOMES = {
    "system", "plan", "design-sources", "design", "sandbox",
    "learning_records", "learning", "ledger", "incidents",
    "sessions", "audit", "findings", "evaluation", "rubric",
    "deploy", "historical", "papers", "publishing", "outreach",
    "charts", "corpus", "guides", "reference", "vault", "notebooks",
    "metaphors", "memory", "correspondence",
}

# Legacy physical areas: editable while they exist (tracked docs), but no NEW
# doc may be created here. The F4 cleanup archives/promotes them in waves.
_DEFAULT_LEGACY_AREAS = (
    "docs/experiments",
    "docs/governance",
    "docs/internal",
    "docs/architecture",
    "docs/canon_mirror",
    "docs/archive",
)

HOME_ROOTS = dict(_DEFAULT_HOME_ROOTS)
APPROVED_HOMES = set(_DEFAULT_APPROVED_HOMES)
LEGACY_AREAS = tuple(_DEFAULT_LEGACY_AREAS)


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


def parse_home_policy(text: str) -> tuple[dict[str, Path], set[str], tuple[str, ...]]:
    """Read the `home_policy:` block — the machine-readable homes declaration.

    `home("logical", path="physical", new_docs="true|false")` maps a logical
    chain root to its physical directory. `area("physical", new_docs="false")`
    declares a legacy area that may still be edited but must not receive new
    docs. The block is the policy source; the defaults above only keep older
    checkouts working (R16: policy declares, instrument interprets).
    """
    m = re.search(r"home_policy:\s*\[(.*?)\n\]", text, re.S)
    if not m:
        return dict(_DEFAULT_HOME_ROOTS), set(_DEFAULT_APPROVED_HOMES), _DEFAULT_LEGACY_AREAS

    section = m.group(1)
    roots: dict[str, Path] = {}
    approved: set[str] = set()
    legacy: list[str] = []

    for name, path, attrs in re.findall(
            r'home\("([^"]+)"\s*,\s*path="([^"]+)"([^)]*)\)', section, re.S):
        roots[name] = (ROOT / path).resolve()
        if re.search(r'new_docs="true"', attrs):
            approved.add(name)

    for path, attrs in re.findall(
            r'area\("([^"]+)"\s*,([^)]*)\)', section, re.S):
        if re.search(r'new_docs="false"', attrs):
            legacy.append(path)
        elif re.search(r'new_docs="true"', attrs):
            approved.add(path)

    if not roots:
        return dict(_DEFAULT_HOME_ROOTS), set(_DEFAULT_APPROVED_HOMES), _DEFAULT_LEGACY_AREAS
    return roots, approved, tuple(legacy)


HOME_ROOTS, APPROVED_HOMES, LEGACY_AREAS = parse_home_policy(
    POLICY.read_text(encoding="utf-8") if POLICY.exists() else "")


def physical_home(chain: str) -> Path | None:
    """Translate a canonical logical chain to its physical directory."""
    if not chain or chain in (".", "?"):
        return None
    parts = chain.split("/")
    root = HOME_ROOTS.get(parts[0])
    if root is None:
        return None
    return root.joinpath(*parts[1:]) if len(parts) > 1 else root


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
    plan_dir = PLAN_DIR
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
    level_dir = ROOT
    at_root = True
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
        if at_root:
            level_dir = HOME_ROOTS.get(home)
            at_root = False
            if level_dir is None:
                return "?"     # logical home has no physical root (coverage gap)
        else:
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
        probes = [
            (ROOT / "system/boot/hard_rules.vsm", "system/boot"),
            (ROOT / "system/s5-policy/learning-cycle-policy-01/learning_cycle.vsm",
             "system/s5-policy/learning-cycle-policy-01"),
            (ROOT / "docs/design/sources/plugin-audit-design-v1/plugin_audit_design.vsm",
             "design-sources/plugin-audit-design-v1"),
            (ROOT / "docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm",
             "plan/classification-policy-plan-v1"),
        ]
        for probe, expected in probes:
            home = classify(probe)
            if home != expected:
                print(f"FAIL (selftest): {probe.name} → {home!r}, "
                      f"expected {expected}", file=sys.stderr)
                return 1
        print(f"PASS (selftest): {len(rules)} rules; "
              f"{len(probes)} probes classify to their new roots")
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