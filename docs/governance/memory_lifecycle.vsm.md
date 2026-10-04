# `memory_lifecycle.vsm`

```
⟦ memory-lifecycle | rmw3 | vsm-0.4 | 2026-04-18 ⟧

@vsm 1.0
// domain_context: {target=vsf-memory, env=VSF-session, layer=S3}
// Constraint: MEMORY.md truncates at 200 lines — keep index under limit
// @ref ~/.claude/projects/-home-rmw3-vsf/memory/

memory_types {
  user:      "rmw3 profile — role, expertise, collaboration preferences"
  feedback:  "agent behavior corrections + confirmed non-obvious approaches"
  project:   "non-derivable state/decisions — do NOT duplicate HANDOFF.vsm.md"
  reference: "pointers to external resources"
}

memory_create(type, name, description, content) {
  1. verify no equivalent entry in MEMORY.md
  2. write ~/.../memory/<name>.md — frontmatter + content
  3. add to MEMORY.md: "- [Title](file.md) — hook (≤150 chars)"
  4. verify MEMORY.md < 200 lines
  invariant: no duplicates — update existing entry if already present
}

memory_update(file): read → update content → update MEMORY.md hook if changed
memory_deprecate(file): verify info exists elsewhere → remove MEMORY.md line → archive or delete
memory_merge(a, b, merged): read both → write non-redundant → update MEMORY.md

review_protocol {
  triggers: [MEMORY.md > 15 entries, project entry > 60 days stale, redundancy detected, rmw3 request]
  checklist: [
    project entry duplicates HANDOFF.vsm.md? → deprecate
    feedback no longer applies? → deprecate
    two project entries on same topic? → merge
    reference pointing to dead resource? → deprecate
    MEMORY.md < 150 active lines? → if not, review
  ]
  owner: claude @S4_collab proposes | rmw3 @S5 approves
}

exclusions {
  // Better homes — do NOT duplicate in memory:
  D1-D12 architecture decisions → HANDOFF.vsm.md
  experiment results           → HANDOFF.vsm.md sessions + paper_data.vsm
  open tasks                   → TASKS.vsm
  code/notation conventions    → vsm_notation_spec.md
  git history / blame          → git log / git blame
  bug fix recipes              → code + commit message
  current session state        → ephemeral
}

current_state {
  date:    2026-04-18
  entries: 16           // see MEMORY.md — approaching review threshold
  next_review: "when >18 entries or redundancy detected"
}

⟦ /memory-lifecycle | rmw3 | vsm-0.4 | 2026-04-18 ⟧
```
