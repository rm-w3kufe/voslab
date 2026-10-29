#!/usr/bin/env python3
"""socratic_gate.py — write-time DOC-HOME gate (policy-driven).

design: docs/plans/classification-policy-plan-v1/classification_policy_plan.vsm
(PART IV-B tree_rules + PART IV-C home_policy; F4 DOC-HOME-POLICY, S5 2026-10-29)
        + docs/design/sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
(PLUGIN-CLASS-TAXONOMY-v1 — write-time universal: el questionnaire IS el gate).

WHY (2026-08-18, fase c; reinforced 2026-10-29): the write-time gate must know
the canonical home of a document at creation time, not after a corpus scan.
The old implementation duplicated the CLASSIFY tree and a HOMES table in this
script. That duplicated policy drifted from the classifier. The gate now
delegates to the kernel resolver (`vos_kernel.utils.doc_home`), which reads
the SAME policy as checks/classification-v2-valid.

Contract:
  exit 0 — canonical home, approved new-doc area, or tracked legacy advisory
  exit 1 — policy mismatch, or a NEW doc outside the approved homes
  stderr — [DOC-HOME] report: the policy answer vs reality

R10: the answer is the declared policy (classifier.apply_chain), not an LLM.
R9: UNKNOWN is visible; a new doc outside the approved homes is blocked with
the list of approved homes, never silently accepted.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "packages" / "framework") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "framework"))

from vos_kernel.utils.doc_home import check_path  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: socratic_gate.py <file.vsm>", file=sys.stderr)
        return 2
    decision = check_path(argv[0])
    print(decision.message, file=sys.stderr)
    if decision.advisory:
        print("[DOC-HOME] advisory only (legacy area; no new docs)",
              file=sys.stderr)
    return 0 if decision.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
