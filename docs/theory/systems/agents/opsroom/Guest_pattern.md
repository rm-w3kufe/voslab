# Guest Agent Pattern

## Purpose

Invite ad-hoc, single-task specialists when the resident opsroom seats
don't cover the work. Examples already done:
- **SCADA dashboard** (D.4) — full-stack UI implementation (since
  decommissioned and replaced by the formaid studio; the *pattern* and its
  spec remain the canonical reference shape)
- **`/simplify` x4** — parallel code-review agents

## When to invite vs convene a resident

| Use case | Pattern |
|---|---|
| "design + implement a bounded feature (~500-2000 LOC)" | Guest, isolation: worktree |
| "audit / review existing code along one angle" | Guest (parallel if angles independent) |
| "ongoing role tied to one VSM subsystem" | Resident specialist (S1..S5/Research) |
| "fix this typo / patch one line" | Orchestrator alone, no spawn |

## Mandatory before spawning a guest

1. **Spec doc.** No guest is spawned without a spec at
   `docs/spec/<NAME>.md`. The spec defines scope, deliverables,
   security gates, out-of-scope. The SCADA spec
   (`docs/spec/D4_scada_dashboard_spec.md`) is the reference shape.
2. **Optional peer review.** For larger guests, route the spec
   through Qwen (or the relevant resident specialist) before spawn.
   Found drift early in D.4.
3. **Worktree isolation** when LOC > 50, so commits don't pollute
   main until the operator reviews.
4. **Production safety clauses** baked into the spec: explicit
   "may read prod via SSH" / "may NOT alter prod systemd, push
   binaries, restart services". Spec §"PRODUCTION SAFETY".
5. **Final deliverables list** (a-e in the SCADA spec): commits,
   README, status report, TASKS.md update, screenshot/verification
   recipe.

## Spawn convention

```
Agent({
  description: "<task name>",
  subagent_type: "general-purpose",
  isolation: "worktree",
  prompt: """
    You are implementing <X> per docs/spec/<X>.md.
    [...standard preamble...]
    CONSTRAINTS:
      - Tier-α scope only
      - Worktree commits only; operator merges
      - WSL boundary: no cargo build / no apt; build on n02 via SSH
      - read state.db FIRST for status queries (canon order)
    DELIVERABLES (a-e):
      a. git commits in worktree
      b. README or docs update
      c. 1-paragraph status report at end
      d. TASKS.md updated
      e. verification recipe
  """
})
```

Capture the `agentId` returned. Resume via `SendMessage` if the
guest pauses or needs redirection.

## Mid-task redirection

If the operator changes their mind (e.g., D.4 → swap vanilla SVG for
Cytoscape mid-flight), the orchestrator uses `SendMessage` to the
agentId with a clear instruction:

```
"ARCHITECTURAL UPDATE (operator decision, supersedes spec §X):
 [...what changed...]. If you've already invested heavily in
 the prior path, finish that step then refactor at next boundary —
 don't throw away working code mid-step."
```

This preserves the agent's full transcript context, much cheaper
than re-spawning.

## On completion

1. Guest reports back; orchestrator reviews the commits.
2. Cross-check against the spec deliverables list.
3. Run `/code-review` skill on the diff if appetite for thoroughness.
4. Present to operator with: branch name, summary of changes, the
   verification recipe, any surfaced follow-up tasks.
5. **Operator (S5-human) signs the merge.** Always.
6. After merge, deploy via `deploy_bundle.sh` on n02 if applicable.
   `vsf-state-populate` + G-D.4 will catch any sha drift within 5 min.

## Anti-patterns

- Spawning without a spec → guest invents requirements as it goes.
- Spawning to do something a resident specialist handles → wastes
  cold-start context; the resident already knows the per-S spec.
- No worktree on >50 LOC work → main contaminated before review.
- "Just merge it" → A5 violation; operator signature is mandatory.
- Inviting two guests on overlapping scope concurrently without
  designated arbiter → race condition on commits + design drift.

## When to convert a guest into a resident

If the same ad-hoc role keeps being invited (e.g., "security audit"
spawned three sessions in a row), promote it to a resident specialist
file in this directory. Threshold of three invocations = signal.
