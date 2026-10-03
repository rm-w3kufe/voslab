# CLAUDE.md — VSF (Viable System Framework)

Framework for designing and operating viable systems. Beer's VSM (1972) + Cybersyn (1971).

**This file is an INDEX. It holds no status, no live state, and no rule text.**
Status lives in `TASKS.vsm`. Live state lives in `state.db`. Rules are defined in
`docs/spec_revision/system/boot/hard_rules.vsm` and mapped in `RULES.md` (pointer file).
Anything here that starts to look like a source of truth is a bug — it will go stale
and then it will lie. (2026-08-10 boot audit: three such tables were removed, not updated.)

## Session start

Order is normative: `≡ hard_rules.R5_canon_over_recall`. Do not improvise it.

**CLEAN session**
1. `system/boot/boot_manifest.vsm` — the boot index:
   every artifact the boot loads, by layer, with role and hash. Follow
   it; do not improvise the order (R5). Dependency base: notation and
   axioms every other document is written in. Read once per session.
2. `RULES.md` — pointer file: rule → canonical block map, rationale pointers.
3. `bash scripts/state/onboard.sh` — open tasks, rule divergence, service census
   freshness, chain heads, last HANDOFF block, algedonic digest, instruments. ~130 lines.
   `--full` for the unaggregated tables.

**AFTER A COMPACT** — before acting on the summary, before any other tool call:
1. `state_query('focus')` via **state-canon**, or read `current_focus.json`. Cross-check
   every active/paused ref against `TASKS.vsm` — focus entries go stale (confirmed
   2026-07-27: an entry stayed "active" after the task was done and superseded).
2. If focus is empty, missing, or contradicts TASKS.vsm → full `onboard.sh`.

The summary is RECALL, not canon: every claim in it is a lead to verify, never a source.
Enforced structurally by the `SessionStart` hook `.claude/hooks/vsf-onboard-reminder`.
*(Known gap, 2026-08-10: that hook doesn't fire on a clean `startup`.)*

Tie-breaking between sources: `≡ hard_rules.R7_state_db_wins`.
R7's former inversion for `rules` was RESOLVED 2026-08-11 (rmw3, S5): rules are DECLARED,
never polled; the `rules` table was dropped 2026-08-12. See `RULES.md` — R7 row.

## Boot manifest — everything that loads context, and what each is for

Audited 2026-08-10. If you add an artifact to the boot, add it here in the same commit.

**Decoupled 2026-08-12 (rmw3):** this file is NOT part of opencode's boot —
`OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1` is exported in `~/.bashrc`, so opencode
skips both this project file and `~/.claude/CLAUDE.md` (binary-derived
kill-switch; project `.env` is NOT autoloaded by opencode). This file remains
the Claude Code reference and the human-readable index.

**Canon — read these, in this order** (dependency order is declared once,
in `system/boot/boot_manifest.vsm`, per `hard_rules.R5`
— covenant ≻ core_boot_primer ≻ vsl_language_primer ≻ regulation_layer ≻
hard_rules ≻ communication_protocol; follow the manifest, not this re-list)
| artifact | role |
|---|---|
| `docs/spec_revision/system/boot/covenant.vsm` | the covenant itself — the S5 contract nothing overrides |
| `docs/spec_revision/system/boot/core_boot_primer.vsm` | axioms A0/A0.1/A1-A11, notation, channels, handshake. Portable: this alone is what you hand an external agent |
| `docs/spec_revision/system/boot/vsl_language_primer.vsm` | the VSL grammar writing core — the notation rules every other document is written in (promoted 2026-08-13; replaces single-file vsl_language.vsm, deleted) |
| `docs/spec_revision/system/s5-policy/vsl-language/` | the 14-item reference set of vsl_language (validators, kernel/runtime, provenance); manifest `index.vsm` — read on demand, not at boot |
| `docs/spec_revision/system/boot/regulation_layer.vsm` | boundary axioms, caution mode, traceability |
| `docs/spec_revision/system/boot/hard_rules.vsm` | **normative definition** of R1-R15 (`PROTOCOL_VERSION: 3`) |
| `docs/spec_revision/system/boot/communication_protocol.vsm` | the message shape every agent-to-agent exchange uses |
| `docs/spec_revision/system/boot/.primer_sources_manifest.json` | hashes that make `verify_boot_primer.py` block when a source drifts |
| `RULES.md` | pointer file — rule → canonical block map; rationale → incidents; cites the definition only |
| `state.db` on n02 | live state: services, chains, lxcs, topology. **Not** rules |
| `HANDOFF.vsm.md` | session continuity, last block first |
| `TASKS.vsm` | the backlog, and the only home for work-item status |
| `current_focus.json` | what was in flight, cross-check against TASKS.vsm |
| `docs/sessions/` | **the session history — always has been.** Cross-agent exchanges (Gemini, Qwen, Kimi), `briefs/` dispatched to DS, dialogue logs, archives: `handoff/`, `ds/`, `tasks_closed/`. Registered in `docs/INDEX.md`; consult that index before concluding a record does not exist |

**Instruments — prefer these over raw ssh**
| server | serves | do not ask it for |
|---|---|---|
| `state-canon` | tasks · focus · journal | services, rules |
| `state-canon-infra` | services · lxcs · components · chains · topology (n02 `state.db`) | tasks, focus — and `rules` QUIERY RAISES (domain retracted, R7 resolved) |

Rules canon is `docs/spec_revision/system/boot/hard_rules.vsm`, full stop — not
this server, mirrored or not. `state_query("rules", …)` / `state://rules` now fail
loud, pointing at the canonical file (see TASKS.vsm `R7-RULES-TABLE-CLEANUP-2026-08-11`).

An empty result from one of these is **not** evidence of absence — check you asked the
right server. Both are declared in `.mcp.json` (Claude Code) and natively in
`opencode.json` (opencode does NOT read `.mcp.json`; `opencode.json` is the ONE config,
don't recreate `.opencode/opencode.json`). Their schemas load on demand.

`codebase-memory-mcp` is **out of scope** for this repo, with one carve-out
(decision 2026-08-10, rmw3 — `docs/spec/self_audit/codebase_memory_scope_decision.vsm`):
don't index `/home/rmw3/vsf`, don't follow its hook here. Carve-out:
`projects/vsf-nucleus/src` (the Rust kernel) — index on demand if a real call-graph
question ever needs it.

**Hooks that will interrupt you**
| hook | when | effect |
|---|---|---|
| `.claude/hooks/vsf-onboard-reminder` | SessionStart: compact, resume, startup, clear | injects the R5 reminder |
| `.claude/hooks/vsl-measure-before-write` | PreToolUse: Write, Edit | reads file state *before* the edit |
| `.claude/hooks/vsl-check-on-write` | PostToolUse: Write, Edit | VSL grammar check |
| `scripts/docs/git_pre_commit.sh` | pre-commit | **blocks**: `--strict` parse of staged `docs/spec_revision/*.vsm`, `verify_boot_primer`, `symbol_table --gates/--status/--undeclared`, `debt_register --check`, secret guard |

`scripts/vsl/verify_boot_primer.py` blocks a commit when a canonical source changed
without the primer being re-verified. Re-baseline with `--update` **after** re-reading
the source — updating without checking defeats the point (R4).

## Session end

Full protocol: `docs/theory/vos_dev_cycle.vsm §session_end_protocol`.

1. `git commit` all changes
2. `HANDOFF.vsm.md` ← a `session("date")` block: results + key numbers
3. `memory/*.md` ← non-derivable findings only
4. experiments pending → `docs/experiments/queue.vsm`
5. paper in progress → `main.tex` compiles + `paper_data.vsm` complete
6. new terms → `docs/glossary.vsm`

**Test**: could a fresh agent read the last HANDOFF block tomorrow and know exactly what
to do, without any session context? If no, the session is not ready to close.

## Key concepts

```
S1 Operations    the units that do the work
S2 Coordination  prevents units from stepping on each other
S3 Control       allocates resources, monitors performance
S3* Audit        sporadic direct channel — sees what S3 misses
S4 Intelligence  watches the environment, plans ahead
S5 Policy        sets the rules that nobody can override
```

Cybersyn → host: `Cybernet→S2 | Cyberfilter→S3 | Cyberstride→S3* | CHECO→S4 | Opsroom→S5`

Standing decisions, defined elsewhere, listed here so you know they exist:
**D6** no LLM at L0/L1 (`vsl_language`, widened 2026-08-10 to band(reflex)/band(deliberative_tactical)) ·
**D7** all committed files in English ·
**D4** single-loop automatable / double-loop requires human ·
**A4** no direct sibling coupling · **A5** autonomy ceiling — L3 always needs human approval.
A4/A5 are axioms: `core_boot_primer.axioms_universal`.

## Where things are

Orientation only — not an authority, and not exhaustive.

```
docs/spec_revision/system/boot/   ★ the canon base — 6 boot docs, indexed by
                                  docs/spec_revision/system/boot/
                                  boot_manifest.vsm (the boot index: layers,
                                  roles, hashes); + s5-policy/vsl-language/
                                  reference set (14 items, on demand)
docs/spec/agent_protocol/         retired v1 copies (2026-08-11) — files
                                  remain on disk, unmaintained, not referenced
docs/spec_revision/               ★ the active restructure: system/ fuses, ledger, debt register
docs/spec/                  notation spec, migration protocols, incident specs
docs/theory/                composition proofs, vos_dev_cycle, recursive VSM theory
docs/experiments/           registry + queue.vsm
docs/papers/                attractor_convergence, symbolic_substrates, …
docs/governance/            covenant.vsm, covenant_ops.vsm, strategy, disclosure
docs/incidents/             dated incident reconstructions
projects/vsf-nucleus/       the Rust kernel — builds on LXC 108, NEVER in WSL (R1)
opsroom/view_host/          formaid diagram studio, deployed LXC 109
scripts/state/              onboard.sh, rotate_nats_token.sh, populate
scripts/vsl/                parser, symbol_table, debt_register, verify_boot_primer
core/connection_schema.json φ↑ φ↓ channel contract
viability.yaml · validator.py   the public template + compliance checker
```

## Operating

```bash
vsf-tunnels                     # n02 tunnel set
# http://localhost:8088         # / = formaid studio · /live = module dashboard
```

Build, deploy and state locality are R1 — read it before touching a target. The short
version: builds happen on the target LXC or its declared build host, never in WSL; never
write to `/root` on the n02 host.

## References

- Beer, S. (1972). *Brain of the Firm*. Allen Lane.
- Beer, S. (1979). *The Heart of Enterprise*. Wiley.
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press. (Cybersyn)
- Ashby's Law of Requisite Variety — foundation of Cyberfilter
