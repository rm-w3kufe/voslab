# EXP-PHI-01 — Findings

**Date**: 2026-05-09
**Status**: DONE (closure achieved, fidelity gap observed)
**Total runs**: 5 (4 remote failures + 1 local partial closure)
**Paper placement**: Paper 2 seed §1 (substrate viability) + §3 (sovereignty + fidelity)

---

## Setup

- **S3 (coordinator)**: Claude (this session, kali host)
- **S1 (executor)**: variable across runs — see table
- **Substrate**: VSL brief (`brief_format.vsm` schema v1.0)
- **Channel intended**: BBS (lxc106:8600) — bypassed in Run 005 due to wrapper using direct API
- **Brief target**: extract 5 structural metrics from `docs/guides/concepts.md`
- **Ground truth**: pre-computed by Claude, stored in `ground_truth.json`

---

## Run-by-run summary

| Run | S1 substrate | Status | Failure / Result | Wall time |
|---|---|---|---|---|
| 001 | OR `openrouter/free` (key=API_KEY) | API_FAIL | HTTP 401 — Anthropic key on OR endpoint | ~1s |
| 002 | OR `openrouter/free` (key=AUTH_TOKEN) | API_FAIL | HTTP 400 — reasoning mandatory upstream | ~1s |
| 003 | OR `meta-llama/llama-3.3-70b:free` | API_FAIL | HTTP 429 — rate-limited Venice (after D9 retry) | ~10s |
| 004 | Ollama qwen2.5-coder:7b LXC 101 | RESOURCE_FAIL | OOM — n02 host had 3.1 GiB free at request time | <1s |
| 005 | Ollama qwen2.5-coder:7b (post-reboot) | **DONE (partial)** | Loop closed, 3/5 output keys correct | 271s |

Cumulative closure: **0/4 remote**, **1/1 local** (with caveats).

---

## Key findings

### F1 — H1 substrate_viability: CONFIRMED

The VSL substrate works as a coordination protocol. Run 005 produced a syntactically
valid JSON response with all 5 expected output keys. The brief was parseable, the
constraints respected (read-only, English, no shell), and the closure detectable.

**Evidence**: `closure_status: DONE`, `model_response.status: DONE`, all output_format keys present.

### F2 — H5 substrate_sovereignty: CONFIRMED, multi-dimensional

Pre-experiment H5 hypothesized sovereignty cost as a function of N external credentials.
The 4 remote failures decompose this into three orthogonal sovereignty axes:

1. **Credential semantics** (Run 001): two env vars (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`)
   with overlapping names but distinct endpoint mappings. Operator cannot disambiguate
   without out-of-band knowledge.
2. **Routing non-determinism** (Run 002): `openrouter/free` resolves to arbitrary upstream;
   capability requirements (e.g. mandatory reasoning) clash with client-side payload schema
   (e.g. `thinking: disabled`). Operator has no signal until 400 is returned.
3. **Upstream availability** (Run 003): rate-limit at provider level (Venice/Llama free tier);
   shared global pool exhausted by other users; D9 retry useless for upstream-side errors.
4. **Dynamic resources** (Run 004): nominal allocation (8 GiB) ≠ available memory at request
   time; sovereignty extends *inside* self-hosted infra to shared-resource fragility.

H5 is therefore not a single-axis variable. **Sovereignty cost = Σ(creds, routing, upstream, resources)**.

### F3 — H2 algedonic_floor: QUANTIFIED at 270s for this configuration

Run 005 took 271s wall clock. Decomposition:
- `load_duration`: 251 ms (model already in RAM, no disk hit)
- `prompt_eval_count`: 2965 tokens at 100% CPU
- `eval_count`: 168 tokens generated

Throughput: ~11 tokens/s prompt eval + ~0.6 tokens/s output gen (rough). For 4-core CPU LXC.
**This sustrate cannot achieve sub-minute closure without either GPU or smaller model.**

L_floor decomposition for this run: T_eval (~270s) >> T_post (<1s) >> T_poll (would be 5s if BBS were in loop).
The CPU-bound execution dominates by 2 orders of magnitude.

### F4 — H6 operational_fidelity: NEW HYPOTHESIS, EMERGENT

Run 005 closed the loop with 3/5 output keys correct:

| Key | Expected | Got | Match |
|---|---|---|---|
| `file_line_count` | 153 | 153 | ✅ |
| `cybersyn_terms` | 5 elements | 5 elements | ✅ |
| `blank_line_count` | 30 | 30 | ✅ |
| `s_levels_present` | 6 (incl. S3*) | 5 (omitted S3*) | ❌ |
| `s_level_mentions` | sum 122 | sum 30 (~25%) | ❌ |

**Diagnosis**: Qwen-7B exhibits well-known LLM counting bias. It correctly identified
*existence* of patterns but undercounted *frequency* by ~5×. The model knows S1-S5 are
in the file, but cannot reliably count occurrences of each.

**Implication**: closure (loop completes) and correctness (output is right) are
**separable properties**. A VSM coordinated through VSL **must** include automated
ground-truth scoring; closure detection alone is insufficient as a viability signal.

This was not in the original hypothesis set — it emerged from the data. It's the
single most important conceptual contribution of EXP-PHI-01 to Paper 2.

### F5 — Methodological discovery: brief.vsm had a capability bug

The original `brief.vsm` instructed the executor to *"read docs/guides/concepts.md"*.
Neither Claude (via OR Anthropic-compat) nor Qwen (via Ollama /api/chat) have native
filesystem access. The brief was syntactically valid but semantically inexecutable.

This was caught only after Runs 001-004 failed for unrelated reasons. Had any of them
succeeded auth-wise, they would have either failed with "no tool" or hallucinated content.

`brief_inline.vsm` (Run 005) corrected this by making the brief self-contained:
the wrapper inlines the file content into the brief, eliminating the capability assumption.

**Lesson for VSL grammar v2.0**: a brief should declare required executor capabilities
(filesystem, network, shell) and the wrapper/runtime should validate before dispatch.

---

## Implications for Paper 2

This experiment, even with N=1 local closure, generates rich material:

- **§1 Substrate viability proof**: Run 005 demonstrates the protocol works end-to-end.
- **§2 Sovereignty taxonomy**: 4-dimensional decomposition (creds/routing/upstream/resources).
- **§3 Fidelity vs viability**: H6 — the most novel observation, requires N≥3 to consolidate.
- **§4 Capability-awareness**: F5 — VSL v2.0 needs capability declaration in brief schema.

**Decision**: do NOT commit Paper 2 yet. Need:
- EXP-PHI-02: H6 reproducibility (N=3+ with same brief, same substrate) → fidelity stability
- EXP-PHI-03: NL baseline comparison for H3 (compression ratio is meaningful only relative)
- EXP-PHI-04: BBS-mediated full loop (Run 005 bypassed BBS — need end-to-end with real algedonic)

If EXP-PHI-02/03/04 confirm and refine, write `docs/papers/symbolic_substrates/seed.vsm`
and start a paper draft. If H6 fails to reproduce or compression is null, paper goes back
to seed status.

---

## Artifacts

- `spec.vsm` — formal specification with all run data
- `brief.vsm` — original brief (kept as reference, demonstrates capability bug)
- `brief_inline.vsm` — corrected self-contained brief used in Run 005
- `ground_truth.json` — pre-computed expected output (deterministic Python)
- `findings.md` — this document
- `../../scripts/llm/run_phi01_ollama.py` — wrapper used for Run 005

## Refs

- `projects/claude-qwen-s1/brief_format.vsm` — VSL grammar v1.0 used as schema
- `docs/theory/qwen_synthesis.vsm` §1 — semantic substrate definition
- HANDOFF.vsm.md `session(2026-05-09)` — session in which experiment ran (to be written next)
