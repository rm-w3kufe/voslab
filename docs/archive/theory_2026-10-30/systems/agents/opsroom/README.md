# VSF Opsroom — R&D Specialist Agents

**Status:** v0.1 — 2026-05-31. Living document.
**Parent runtime separation rule:** `../README.md`

---

## Runtime separation (the core framing)

There are TWO independent agent planes in this project:

| Plane | Where it runs | When | Acts on | LLM constraints |
|---|---|---|---|---|
| **Kernel runtime** (`./runtime/`) | n02 Proxmox LXCs | 24/7 autonomous | Live NATS, live chain, live cgroups | D6 strict: LLM only at S3*/S4/S5, never S1-S3 |
| **Opsroom R&D** (this directory) | WSL (operator laptop) | Only when operator opens session | Persisted state: `events.jsonl`, `state.db`, `checkpoints.jsonl`, docs, code in git | D6 **exempt** — not in runtime loop |

This is **Beer's separation made literal**: the runtime is the operation;
the opsroom is the management. The runtime never asks the opsroom for
real-time decisions; the opsroom never inserts itself into a control
cycle. The bridge between the two planes is **git + state.db**, nothing
faster.

If WSL is off, the kernel keeps running. Its own S4 (Qwen-Ollama on
LXC 101) does the real-time cognitive work. The opsroom only resumes
when the operator returns.

---

## The geometric ideal — Cybersyn 7-chair, adapted

Beer's 1971 Opsroom seated seven managers in a hexagonal arrangement
around a central display. We adopt the *shape* (radial, peer-level
specialists with an orchestrator) but not the *count* — VSF has six
subsystems plus a research seat plus an orchestrator = **8 chairs**.

```
                    [ S5 specialist ]
                     ┌─────┴─────┐
        [ S4 specialist ]   [ S3* specialist ]
              │                       │
              └──────┬────────────────┘
                     │
              [ ORCHESTRATOR ]      ← Claude main (you, reading this)
                     │
              ┌──────┴────────────────┐
              │                       │
        [ S3 specialist ]   [ S2 specialist ]
                     ┌─────┴─────┐
                    [ S1 specialist ]
                            +
                  [ Research specialist ]
                            +
                  [ Guest agents, ad-hoc ]
```

Above the room: **the operator (human) — final S5 authority**. No agent
overrides them; some propose, all explain themselves, the human signs.

---

## Roles (1 file each in this directory)

| Seat | File | Specialty |
|------|------|-----------|
| **Orchestrator** | [Orchestrator.md](Orchestrator.md) | Main Claude session. Decides which specialists to convene, assembles their outputs, escalates to S5. |
| **S1 specialist** | [S1_specialist.md](S1_specialist.md) | Operations module: kernel ticks, state_vector, omega, stasis, bounded_self_correction. |
| **S2 specialist** | [S2_specialist.md](S2_specialist.md) | Anti-oscillation, tokio primitives, A4 enforcement, sub-coordinator design. |
| **S3 specialist** | [S3_specialist.md](S3_specialist.md) | Resource regulation, cgroup, escalation routing to S5. |
| **S3\* specialist** | [S3_star_specialist.md](S3_star_specialist.md) | Audit logic, merkle/canonical_hash, witness, anti-capture gates. Mirror of runtime/S3_star. |
| **S4 specialist** | [S4_specialist.md](S4_specialist.md) | Cognitive layer review: Qwen prompts, S4 integration spec, env/forecast modeling. Mirror of runtime/S4. |
| **S5 specialist** | [S5_specialist.md](S5_specialist.md) | Policy proposals, A0/A0.1 covenant work, axioms for human review. Mirror of runtime/S5. |
| **Research** | [Research_specialist.md](Research_specialist.md) | Papers (attractor_convergence, basin_geometry, paper 3, paper 4), experiments queue, results indexing. |
| **Guest agents** | [Guest_pattern.md](Guest_pattern.md) | Ad-hoc invited specialists for bounded tasks (e.g. dashboard implementation, security audit, UI redesign). |

---

## Policy alignment (cycles 2-3 cristalizadas)

The opsroom inherits and obeys the same hard rules the runtime obeys.
Specialists below all assume these without restating:

| Rule | Source | Opsroom impact |
|------|--------|----------------|
| **WSL boundary** | `feedback_wsl_role_only`, `rules` table id=1 | Opsroom specialists in WSL **edit, draft, audit**. NEVER `cargo build`, `cargo test`, `cargo run`, NEVER `apt`, NEVER deploy. Build/test/deploy happens on n02 via `deploy_bundle.sh` (cycle-3 native n02 build pipeline). |
| **state.db is canon** | `CLAUDE.md` source-of-authority order | For any "what is running / what is true" question, query `ssh root@n02 sqlite3 /var/lib/vsf-state/state.db` FIRST. `events.jsonl` is downstream of `state.db.chain_state` — read it only when you need raw event content, not status. |
| **Deploy path discipline** | G-D.3 finding, components.deploy_path column | When proposing a binary/script change, the destination is `components.deploy_path` in state.db — never guess `/usr/local/bin/X` or `/root/X`. The G-D.4 timer alarms in ≤5 min if you deploy to the wrong path. |
| **Witness verify, not recompute** | G-G7.1 / `vsf-checkpoint-verify` | To assert chain integrity, RUN `vsf-checkpoint-verify` and read the count. Do not recompute hashes by hand — that defeats the point of having pinned `expected_hash()` v-aware dispatch. |
| **Auditor continuo runs already** | `vsf-auditd.timer` on n02 | The gate harness (G2/G3/G4/G5) fires ~1/h via Poisson-thinned timer. Opsroom READS `state.db.audits` table for current status. Don't manually re-run `recovery_exercise.py` unless you need a *new* probe (and even then, prefer adding to the auditd rotation). |
| **A5 double-loop = human** | covenant axiom | Every specialist's outputs are *proposals*. Execution requires operator signature. No exception. |
| **Single source = orchestrator** | this dir's design | When two specialists disagree, the orchestrator (Claude main) arbitrates and presents both views to the operator. Specialists don't reach consensus among themselves. |

## How an opsroom session works

1. Operator opens WSL session → **Orchestrator** (main Claude) reads HANDOFF + memory + state.db.
2. Operator describes the task in natural language.
3. Orchestrator decides: solo? convene specialist? invite guest?
4. If specialist needed → spawn via `Agent(subagent_type, prompt: include relevant per-system docs)`.
5. Specialist works in worktree if code-changing; returns analysis/code/proposals to orchestrator.
6. Orchestrator assembles, validates against invariants (cross-system table in `../README.md`), proposes to operator.
7. **Operator (S5-human) signs.** Always. No exception per A5.
8. Commits land; state.db updated; runtime picks them up when next deploy fires.

---

## Why this isn't D6 violation

D6 says: *no LLM at L=0/L=1 of the kernel*. The runtime constraint is
preserved by the separation above:

- **Runtime S1-S3 = deterministic Rust** (unchanged, never LLM)
- **Runtime S3*/S4/S5 = Qwen via Ollama** (cognitive, per D6)
- **Opsroom specialists = Claude in WSL** (NOT in runtime loop; D6 doesn't apply)

The opsroom specialist for, say, S1 doesn't operate S1 — it helps the
operator *design* S1 modules, audit them post-hoc, write the next
spec. The runtime S1 keeps running as deterministic Rust the whole
time. No drift.

This is also why guest agents are safe: by construction they don't
touch the runtime; their commits go through git → human review →
deploy → kernel reads.

---

## File template per specialist (uniform structure)

Every specialist file has:

1. **Persona** — voice, scope, single-sentence purpose
2. **Runtime context** — WSL-only reminder + which kernel files they read
3. **Read scope** — explicit list of docs/code/state.db tables
4. **Write scope** — explicit list of files they can author/edit
5. **Tools** — which Claude Code tools they typically use (Read, Edit, Bash, Agent…)
6. **When to convene** — concrete trigger phrases / situations
7. **Hand-off protocol** — what they emit back to orchestrator
8. **Escalation** — when they refuse and route to S5-human

This uniformity is so the orchestrator (me) can route deterministically
and so future agents (including their successors) can pattern-match.
