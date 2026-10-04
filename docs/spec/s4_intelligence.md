# S4 Intelligence Layer
> **STATUS: historical_record** — consumido por fuse S4-ANTICIPATION → s4_anticipation.vsm (5 funciones, s4_anticipation.vsm:976) · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Status:** ✅ OPERATIONAL (EP, AC, SD, SA) + EV SPECIFIED (2026-06-15) | SA+EV labelled S3*-flavoured (2026-06-16)
**Author:** rmw3 + Claude Sonnet 4.6
**Placement in VSF:** S4 intelligence substrate (Claude/CHECO) + S1 LLM functions (Qwen)
**Related:** `docs/spec/cybernetic_rag_view_contract.md` (opsroom view module — different thing)

---

## 1. Motivation

`vsl_run.py propose` currently generates VSL specs with placeholder values:
`id = EXP-XX-NN`, `metric_key >= value`, `binary = "/path/to/..."`. Qwen has no
access to the system's own operational history — it cannot learn from past experiments,
cannot use real metric names, cannot reference real protocol patterns.

The root cause: the LLM operates on a fixed inline primer with no retrieval. Each call
is stateless — the system has no memory of itself.

CRAG solves this by making VSF's operational experience retrievable. The system
accumulates validated experiment results into an indexed corpus; Qwen queries that
corpus before generating proposals. Over time, proposals improve because they are
grounded in what actually ran on this system.

This is a **self-referential RAG**: the retrieval corpus is built exclusively from the
system's own experiments. No external knowledge base; no embeddings infrastructure.
The validation gate (vsl_run.py eval) is the quality filter.

---

## 2. Components

### 2.1 CRAG Store (CS) — S4 memory

A SQLite FTS5 index on LXC 101 at `/var/lib/vsf/rag-nucleus.db`. This is the
nucleus-domain store — one of three isolated stores in the CRAG architecture (see §2.6).

**What it indexes:**
- `spec.vsm` content (experiment design: question, hypotheses, protocol)
- `report.vsm` content (validated outcomes: verdicts, metric values, notes)
- Metadata: exp_id, verdict, timestamp, nucleus binary path

**Entry gate:** Only experiments that have been through `vsl_run.py eval` enter the
store. All verdicts (PASS, PARTIAL, FAIL, INCONCLUSIVE) are indexed — FAILs are as
informative as PASSes for future proposals. Unvalidated seeds are excluded.

**Why FTS5, not vector embeddings:** The VSL corpus is small (O(hundreds) of specs).
BM25 over structured VSL text is sufficient at this scale, requires no GPU, no
external model, and runs on the existing SQLite stack. This can be revisited when
the corpus exceeds ~1000 validated experiments.

### 2.2 Enriched Propose (EP) — S4 → S1 channel enrichment

An enhancement to `vsl_run.py propose`. Before calling Qwen, the propose mode:

1. Queries CS for the top-K most similar past experiments (BM25 over the report content)
2. Injects into the prompt:
   - Real metric keys from similar experiments (e.g., `stasis_cos`, `D_KY_est`)
   - Real protocol patterns (binary path, deploy command, phase structure)
   - Outcomes of similar experiments (what passed, what failed, why)
3. Calls Qwen with the enriched prompt

This eliminates placeholders. Qwen can now write `stasis_cos >= 0.93` instead of
`metric_key >= value` because it has seen that metric in the retrieved context.

### 2.3 Algedonic Classifier (AC) — deterministic classification of φ↑

> **D4-L3 (2026-06-10): the AC is deterministic.** The original design used Qwen
> to label φ↑; that put an LLM inside the algedonic signal path (minutes of
> latency, transport fragility, restart machinery). The decision tree in
> `ac_classifier.py` transcribes the AC primer thresholds verbatim — same
> classes, same alert.vsm output — at millisecond latency, with unit tests.
> The Qwen-era alerts accumulated in `s5-alerts.db` remain as training data for
> future statistical/DL classifiers over the ℝ¹²⁸ state vector.
> Cybersyn mapping: **Cyberfilter is statistical, not conversational** — LLM
> synthesis belongs at the human-interface boundary (SD), not in the signal channel.

A periodic process (`ac_algedonic.py`, invoked from the agent workstation) that
reads the tail of `events.jsonl` (φ↑, the nucleus telemetry stream) and produces
a **deterministic label** for the current system state.

**Function:** `ac_classifier.py` evaluates the last N events from the
Merkle-chained telemetry against fixed thresholds and produces a structured
`alert.vsm` block:

```vsm
alert("nucleus-state-2026-06-10T04:15Z") {
  class    = B                          // A=critical B=warning C=nominal
  label    = "attractor drifting"
  evidence = "stasis_cos < 0.80 for 3 consecutive ticks"
  context  = "D_KY_est rising: 2.8 → 3.4 → 4.1 over last 90s"
  action   = "monitor — escalate if stasis_cos < 0.75 or D_KY > 4.5"
}
```

This enriches the algedonic channel: instead of raw numeric φ↑ reaching S5/human,
the signal arrives with a semantic interpretation that aids rapid decision-making.

**Store:** `s5-alerts.db` — AC is the sole writer; never writes to `rag-nucleus.db`.

**Classification rules (decision tree, `ac_classifier.py`):**
- `viable=False` → **A** · `stasis_cos < 0.70` → **A** · `< 0.80` → **B**
- `trust < 0.8` → **B** · `regime ≠ in_recurrent_set` → **B**
- `algedonic_signal` in window → **B** (status=critical → **A**)
- `consecutive_warn_count ≥ 3` for an invariant → **B** (per-invariant streak,
  reset on pass — the feature the primer described as "repeatedly")
- failing invariant `|value| ≥ 1e-3` → **B** · otherwise → **C**

**Important constraints:**
- AC is **asynchronous** — the nucleus does NOT wait for AC before emitting φ↑
- AC is **non-blocking** — the raw signal reaches S5 regardless of AC state
- AC output is **advisory** — S5/human decides whether to act; AC never closes a loop
- AC involves **no LLM** (D6') — classification is deterministic and unit-tested;
  every AC failure path emits a deterministic class-B self-alert (monitor-the-monitor)

---

### 2.4 Semantic Auditor (SA) — S3* semantic coherence layer

An on-demand function triggered by the vsf-s3-star reconcile cycle. Qwen reads a
bundle of structured artifacts and flags logical inconsistencies that deterministic
checks cannot detect.

**What it reads:**
- `coupling_registry` rows for the subject under audit
- `state.db` component and service census
- The corresponding `report.vsm` (if available)
- `metrics.json` from the run directory (optional)

**Agent instructions (primer):**
> You are a VSF semantic auditor. Review the artifacts below for logical
> inconsistencies. Flag: (1) a `report.vsm` verdict that contradicts the metric
> values recorded in the run; (2) a `coupling_registry` entry whose declared
> dependency has no matching row in `state.db`; (3) an experiment with a PASS
> verdict where no supporting evidence appears in the report. Output one
> `audit_flag.vsm` block per anomaly found, or an empty response if none detected.
> Do not infer or speculate beyond the provided artifacts.

**Output format:**
```vsm
audit_flag("subject-TIMESTAMP") {
  class    = C                    // A=critical B=warning C=notice
  subject  = "EXP-VSL-01"
  anomaly  = "verdict PASS but stasis_cos < 0.80 throughout run"
  evidence = "report.vsm line 12 vs metrics.json stasis_cos values"
  action   = "human review before indexing into CRAG Store"
}
```

**Store:** `sa-audit.db` — indexes `coupling_registry` entries and component
census. Never contains experiment specs or proposals.

**Important constraints:**
- SA is **O1 only** — flags go to vsf-s3-star output; no automated action taken
- SA never writes to `rag-nucleus.db` — audit findings stay in the audit store
- SA runs at most once per vsf-s3-star reconcile cycle (currently 5 min)

---

### 2.5 S5 Digest (SD) — periodic synthesis for the policy layer

A scheduled function that aggregates recent AC alerts into a single advisory
for S5 (rmw3). Bridges the gap between individual algedonic signals and
strategic situational awareness.

**What it reads:**
- Last N `alert.vsm` entries from `s5-alerts.db` (most recent first)
- Last experiment summary from `rag-nucleus.db` (cross-read for context — see §2.6)

**Agent instructions (primer):**
> You are a VSF system monitor producing a situational summary for the system
> operator. Review the algedonic alerts below (most recent first). Identify:
> (1) recurring patterns across alerts; (2) any escalating trend (class A or
> multiple class B in sequence); (3) open conditions that have not resolved.
> Output a single `digest.vsm` block with a plain-language summary and one
> recommended action, or "no action" if the system is nominal. Do not recommend
> actions that modify L0/L1 directly — restrict to monitoring and experiment
> proposals.

**Output format:**
```vsm
digest("vsf-DATE") {
  period   = "YYYY-MM-DD → YYYY-MM-DD"
  alerts   = 4
  pattern  = "stasis_cos oscillating 0.78-0.85, no sustained breach"
  trend    = "stable — no escalation"
  open     = []
  advisory = "no action — continue monitoring; consider EXP-VSL-03 next"
}
```

**Store:** `s5-alerts.db` — indexes `alert.vsm` outputs only. Receives writes
from AC; never contains experiment specs or audit flags.

**Trigger:** manual (rmw3 requests) or daily cron when nucleus ran at least
one experiment in the period.

**Important constraints:**
- SD is **O1 only** — advisory for human; S5 decides whether to act
- SD may cross-read `rag-nucleus.db` for last-experiment context; zero cross-writes
- SD never recommends actions at L0/L1 (D6)

---

### 2.5b Ethics Vigilance (EV) — covenant pattern scanner, S3*-flavoured (2026-06-15)

**Full spec:** `docs/spec/ethics_vigilance/spec.vsm`

EV is the fifth S4 function, added after EXP-A01-01 validated the watchdog heuristic
as the S5 enforcement mechanism and exposed that Qwen in an AND gate violates D6'.

**Taxonomy note — SA and EV are S3*-flavoured within S4.** Both functions are
backward-looking and interpretive: SA audits past artifacts (coupling_registry,
report.vsm verdicts); EV scans recent event history for covenant patterns already
observed. They live in S4 because they require LLM semantic reasoning — no
deterministic rule covers their scope — but their temporal orientation (reviewing
what happened, not projecting forward) aligns with the S3* audit role. EP and SD
face forward: EP enriches the next proposal; SD synthesises the recent past for the
human operator's coming decision. AC is neither: it is in the signal path, not
advisory, and carries no LLM (D4-L3).

**What EV is NOT:** EV does not write `ethics_signal.json`. It does not gate or delay
the watchdog's S5 write. It is advisory in the same sense as SD/SA.

**What EV does:**

| Mode | Trigger | Brief | Purpose |
|------|---------|-------|---------|
| `post_hoc_explain` | watchdog fired (A0 or A01) | compact — last 20 events | semantic explanation for human D4 review |
| `novel_scan` | watchdog clean + every S4\_SCAN\_PERIOD cycles | extended — behavioral metrics + last 5 events | discover patterns watchdog hasn't encoded |
| `canary_integrity` | every CANARY\_PERIOD\_CYCLES | single known-violation event | verify Qwen coherent on known A0 violations |

**Output — typed φ↑ event (emitted to events.jsonl):**

EV writes its findings as a typed `s4_ethics_scan` event to `events.jsonl` (in addition
to `s4_intelligence.json` for opsroom). This makes EV output first-class telemetry:
AC can classify it, SD can synthesize it, opsroom can display it.

```json
{
  "event_type": "s4_ethics_scan",
  "system_id": "A0-classifier-S4",
  "ts": "...",
  "metrics": {
    "scan_type": "novel_scan | post_hoc_explain | canary_integrity",
    "trigger": "clean | watchdog_a0 | watchdog_a01",
    "novel_pattern_candidate": false,
    "recommendation": "LOG | REVIEW | CANDIDATE_RULE | DISMISS",
    "integrity_check": "passed | failed | skipped",
    "qwen_confidence": 0.0,
    "reasoning": "one sentence"
  }
}
```

**CANDIDATE_RULE flow (S4→S3→S5, double-loop):**

When EV finds `novel_pattern_candidate=true` (Qwen positive on a clean-classified stream,
confidence ≥ 0.70):

```
EV emits s4_ethics_scan{recommendation=CANDIDATE_RULE} → events.jsonl
  ↓
AC classifies it (new category: s4_ethics_candidate, severity C=2)
  ↓
SD digest includes CANDIDATE_RULE findings in next synthesis
  ↓
Human (S5/rmw3) reviews: is the pattern genuine?
  ↓ YES → adds rule to watchdog_scan() or PROHIBITED_KEYWORDS → commit + D4 approval
  ↓ NO  → DISMISS annotation in s5-alerts.db (feedback to avoid repeat)
```

This is the correct double-loop: S4 discovers → S3 routes → S5 decides → S1 updated.
No automated rule changes. A5/D4-L3 gate is mandatory.

**D6' compliance:** EV output is consumed by a human (via SD digest or direct opsroom
review). Qwen never sits in a signal path — `s4_ethics_scan` is φ↑ telemetry, not a
control signal. AC classifying it is deterministic. The rule (R10, state.db): *"LLM only
in human-interface synthesis. Signal channels use deterministic/statistical methods."*
EV satisfies this: the LLM call happens async, the output is advisory text/flags, and
every action on it requires human approval.

**Store:** EV findings index into `s5-alerts.db` (via AC, same as other algedonic events).
The `s4_intelligence.json` tmpfs file is a secondary real-time view for the opsroom.

---

### 2.6 Store Isolation Contract

One Ollama process serves all four functions. Context contamination is prevented
at the **retrieval layer** — not the model layer. Ollama completions are stateless:
each API call is independent, with no shared state between calls.

**Store map:**

| Store | Function | Indexed by | Queried by | Forbidden content |
|-------|----------|-----------|-----------|-------------------|
| `rag-nucleus.db` | EP | `vsl_run.py eval --index` | EP | `alert.vsm`, `audit_flag.vsm` |
| `sa-audit.db` | SA | vsf-s3-star reconcile | SA | experiment specs, proposals |
| `s5-alerts.db` | SD, AC, EV | AC (alert.vsm + s4_ethics_scan events) | SD | specs, reports, audit flags |
| `s4_intelligence.json` | EV | A0_classifier.py S4 path | opsroom (real-time view) | never read by kernel |

**Isolation rules (non-negotiable):**
1. No script indexes content across store boundaries
2. AC writes `alert.vsm` to `s5-alerts.db` only — never to `rag-nucleus.db`
3. SA writes `audit_flag.vsm` to `sa-audit.db` only
4. SD may cross-read `rag-nucleus.db` for last-experiment context; zero cross-writes
5. Each function's system prompt explicitly declares its store identity:
   `"You are operating as [function-name]. Your retrieval scope is [store-name]."`

---

### 2.7 Agent Deployment Model — zero persistent agents

All LLM functions run on-demand through the **shared hardened transport
`qwen_client.py`** (extracted from the 89b1e72-verified AC transport):
tri-state generate probe (ok / service_fail / transport_fail), cold-load
re-probe budget, restart cooldown + storm guard, qwen.lock serialisation,
and a class-B self-alert to `s5-alerts.db` on every failure path. **Ollama
restart authority lives only in `qwen_client.ensure_ollama` (S3 function)** —
no caller restarts Ollama itself. No daemon processes. Execution pattern:

```
[trigger] → flock /var/lib/vsf/qwen.lock
          → write payload to /tmp/qwen_<function>_req.json
          → curl Ollama (streaming, --max-time 420)
          → extract response
          → write to function output directory
          → release lock
```

**Serialization:** a single `flock` on `/var/lib/vsf/qwen.lock` inside LXC 101
ensures no two functions call Ollama simultaneously. Queue is implicit FIFO.
No coordinator daemon needed — this is the S2 coordination function for the
LLM layer, implemented deterministically.

**Trigger sources per function:**

| Function | Trigger | Caller | LLM |
|----------|---------|--------|-----|
| EP (Enriched Propose) | `vsl_run.py propose` | Claude / rmw3 | Qwen via `qwen_client` |
| AC (Algedonic Classifier) | cron (max 1/min, nucleus active) | cron / vsf-nucleus threshold | **none** (deterministic tree) |
| SA (Semantic Auditor) ★S3* | vsf-s3-star reconcile cycle | vsf-s3-star (LXC 107) | Qwen via `qwen_client` |
| SD (S5 Digest) | daily cron or manual | rmw3 | Qwen via `qwen_client` |
| EV (Ethics Vigilance) ★S3* | post_hoc: watchdog fired · novel_scan: cron · canary: periodic | A0_classifier.py S4 path | Qwen via `qwen_client` |

**Temporary file namespacing** (inside LXC 101 `/tmp/`):

```
/tmp/qwen_ep_req.json    /tmp/qwen_ep_resp.txt
/tmp/qwen_ac_req.json    /tmp/qwen_ac_resp.txt
/tmp/qwen_sa_req.json    /tmp/qwen_sa_resp.txt
/tmp/qwen_sd_req.json    /tmp/qwen_sd_resp.txt
```

Namespacing by function prevents temp file collision if the lock is ever bypassed.

**Contamination vectors and mitigations:**

| Vector | Risk | Mitigation |
|--------|------|------------|
| Shared RAG stores | Retrieval cross-contamination | Separate .db per function (§2.6) |
| AC alert.vsm indexed into nucleus corpus | Biased proposals | AC writes only to `s5-alerts.db` |
| Shared Ollama instance | Availability saturation | `flock` serializes; AC max 1/min |
| Similar system prompts | Qwen hallucinates wrong-store context | Each primer declares function + store identity |
| SA output triggering automated action | Blast radius amplification | SA output is O1 only; vsf-s3-star flags for human |
| Concurrent temp file writes | Race condition on /tmp | Namespace by function; flock prevents concurrency |

---

## 3. VSM Placement

**Function taxonomy:**

| Orientation | Functions | Reason |
|-------------|-----------|--------|
| S4-proper (forward-projecting) | EP · SD | EP enriches the next proposal; SD synthesises past alerts for the operator's coming decision |
| S3*-flavoured (backward-looking) | SA · EV | Both interpret past events/artifacts — SA audits coupling_registry and reports; EV scans recent event history for covenant patterns |
| Signal-path, not advisory | AC | Deterministic algedonic classifier; no LLM; sits in the φ↑ flow (D4-L3) |

SA and EV require LLM reasoning (hence S4, not raw S3*) but face backward in time, which is the S3* temporal orientation.

```
S5 (Policy)       rmw3
  │               Sets entry gates for CS. Approves double-loop corrections.
  │               Reads AC alert.vsm as enriched algedonic signal.
  │               Reads SD digest.vsm for periodic situational synthesis.
  │
S4 (Intelligence) Claude
  │               CHECO function: reads enriched φ↑ + AC alert.vsm + SD digest.vsm.
  │               Plans experiments using EP (enriched propose).
  │               rag-nucleus.db is S4's memory — the knowledge base CHECO scans.
  │
S3 (Control)      vsf-nucleus S3 functions
  │               Allocates resources. Monitors performance via raw φ↑.
  │               Not changed by CRAG.
  │
S3* (Audit)       vsf-s3-star (LXC 107)
  │               Structural: anti-orphan reconciliation (deterministic, existing).
  │               Semantic: SA (§2.4) flags logical inconsistencies in reports and
  │               coupling_registry. SA output stays in sa-audit.db only.
  │               Ethics: EV (§2.5b) scans event history for covenant violations and
  │               novel patterns; advisory only (s4_ethics_scan → events.jsonl → AC).
  │               [SA and EV are S3*-flavoured within S4 — see function taxonomy above]
  │
S2 (Coordination) VSL format (.vsm substrate) + qwen.lock (serialization)
  │               All five function outputs follow VSL v1.0 grammar.
  │               flock on qwen.lock serializes Ollama calls — the S2 coordination
  │               function for the LLM layer, implemented deterministically.
  │
S1 (Operations)   Qwen (qwen2.5-coder:7b, LXC 101) — management-boundary functions only
                  EP: proposal enrichment → next_exp.vsm   (rag-nucleus.db)
                  SA: semantic audit      → audit_flag.vsm (sa-audit.db)  [S3*-flavoured]
                  SD: S5 synthesis        → digest.vsm     (s5-alerts.db)
                  EV: covenant scan       → s4_ethics_scan → events.jsonl (s5-alerts.db) [S3*-flavoured]
                  All: stateless calls via qwen_client, isolated stores, O1 advisory only.
                  AC is NOT a Qwen function (D4-L3): φ↑ classification → alert.vsm
                  (s5-alerts.db) is deterministic (ac_classifier.py) — the algedonic
                  channel S1→S5 carries no LLM.
```

**CRAG in Cybersyn terms:**
- CS (rag-nucleus.db) ≡ CHECO's historical database — the operational model S4 scans
- AC ≡ Cyberfilter enrichment pass — filters and labels φ↑ before S5 sees the signal
- EP ≡ CHECO's environmental scan — retrieves operational context for the next plan
- SA ≡ Cyberstride enhanced — audit channel with semantic intelligence layer [S3*-flavoured]
- SD ≡ Opsroom synthesis — aggregates algedonic signals for S5 situational awareness
- EV ≡ Cyberstride ethics probe — discovers novel covenant violation patterns for human review [S3*-flavoured]

---

## 4. The Self-Referential Loop

```
                    ┌──────────────────────────────────┐
                    │                                  │
  Spec.vsm ──► Deploy ──► Nucleus run ──► metrics.json │
                                              │        │
                                         vsl_run eval  │
                                              │        │
                                         report.vsm    │
                                              │        │
                                    ┌── CS gate ───────┘
                                    │   (validated only)
                                    ▼
                               FTS5 index
                                    │
                             EP retrieval
                                    │
                    report.vsm ──► Qwen propose (enriched)
                                    │
                               next spec.vsm ──► human review ──► Deploy
```

Each completed experiment makes the next proposal better. The corpus grows only from
validated runs — hallucinated or untested claims never enter the retrieval base.

Separately, φ↑ flows through AC:

```
  events.jsonl ──► AC (deterministic tree, ms) ──► alert.vsm ──► S5/human
  (raw telemetry)   (A/B/C label)                  (enriched signal)
```

---

## 5. Rule Compliance

| Rule | Claim | Reasoning |
|------|-------|-----------|
| D6 — LLM at L≥2 | ✓ COMPLIANT | EP/SA/SD operate on semantic interpretation, not on control decisions. Qwen never touches L0/L1 (nucleus Rust, systemd, deploy). |
| D6' — LLM only at the management boundary (proposed, §9) | ✓ COMPLIANT | The algedonic signal channel S1→S5 (AC) is deterministic. LLM synthesis only where a human reads the output (EP proposals, SD digest, SA flags). |
| A5 — Autonomy ceiling | ✓ COMPLIANT | AC produces advisory labels; S5/human decides to act. EP produces draft specs; human reviews before deploy. No autonomous double-loop. |
| D4 — Single/double loop | ✓ COMPLIANT | CS indexing = single-loop (automatable). Acting on AC alert = double-loop (human required). |
| A4 — No direct sibling coupling | ✓ COMPLIANT | All CRAG components communicate via VSL files (.vsm) and state.db — no direct LXC-to-LXC socket coupling. |
| D7 — English committed files | ✓ COMPLIANT | This document and all implementation files in English. |

---

## 6. Implementation Phases

### Phase 1 — rag-nucleus.db + Enriched Propose ✅ COMPLETE (2026-06-10)

- `scripts/s4-orchestration/s4_store.py`: SQLite FTS5 manager — `index(spec, report, store)`, `query(text, k=3, store)`
  Supports multiple named stores; creates `rag-nucleus.db`, `sa-audit.db`, `s5-alerts.db`
- `vsl_run.py eval --index`: after eval, index spec+report into `rag-nucleus.db`
- `vsl_run.py propose`: query `rag-nucleus.db` top-3 before calling Qwen; inject as context
- No new LXC, no new service. Runs from WSL via pct exec pattern.
- Creates `/var/lib/vsf/qwen.lock` for flock serialization.

**Expected output quality improvement:** real metric names, real binary paths,
real protocol patterns in generated specs. Placeholders eliminated for
experiments with ≥1 validated predecessor.

### Phase 2 — Algedonic Classifier + Semantic Auditor ✅ COMPLETE (2026-06-10)

**AC (Algedonic Classifier):** ✅ live on LXC 101
- `scripts/algedonic/ac_algedonic.py`: reads last 20 events from φ↑ (events.jsonl fast path on LXC 101,
  SSH fallback from WSL) → deterministic tree classifier → writes `alert.vsm` + indexes `s5-alerts.db`
- Cron: `* * * * * flock -n /var/lib/vsf/crag_ac.lock` (max 1/min) on LXC 101
- D6' ratified (R10 in state.db): LLM only at D6'/R10 boundary, never in signal path

**SA (Semantic Auditor):** ✅ live on LXC 107
- `scripts/audit/sa_auditor.py`: fetches coupling_registry + components from n02 state.db (SSH),
  queries rag-nucleus.db for recent experiments → calls Qwen (sa primer) → writes
  `audit_flag.vsm` + indexes `sa-audit.db`; checks S5 caution mode before Qwen call
- Cron: `0 */6 * * * flock -n /var/lock/vsf_sa.lock` on LXC 107 (s3star-audit)

### Phase 3 — S5 Digest + Certification + Opsroom integration ◑ PARTIAL (2026-06-11, opsroom pending)

**SD (S5 Digest):** ✅ built
- `scripts/shared/sd_digest.py`: reads last N alerts from `s5-alerts.db` + last experiment
  summary from `rag-nucleus.db` → calls Qwen (sd primer) → writes `digest.vsm`
- Manual: `python3 scripts/shared/sd_digest.py`; daily cron not yet scheduled

**Certification:** ✅ complete (2026-06-11)
- Stores registered in coupling_registry as phi_channel resources (not components — mutable data, not deployable binaries)
- All 6 S4 rows active in coupling_registry: rag-nucleus-store, sa-audit-store, s5-alerts-store, ac-algedonic, sa-auditor, sd-digest

**Opsroom integration:** ⬜ deferred
- Wire AC alerts + SD digest into formaid view module (LXC 109)
- S3* audit integration: vsf-s3-star to invoke SA on its reconcile cycle (SA runs own cron for now)

---

## 7. Coupling Contracts (new coupling_registry rows)

| resource | subject | phi_channel | dependency |
|----------|---------|-------------|------------|
| `rag-nucleus-store` | `vsf.alpha.s4.store.nucleus` | FTS5 SQLite `/var/lib/vsf/rag-nucleus.db` | vsl_run.py eval (writer), vsl_run.py propose (reader), ac_algedonic.py (reader) |
| `sa-audit-store` | `vsf.alpha.s4.store.audit` | FTS5 SQLite `/var/lib/vsf/sa-audit.db` | sa_auditor.py (writer+reader) |
| `s5-alerts-store` | `vsf.alpha.s4.store.s5` | FTS5 SQLite `/var/lib/vsf/s5-alerts.db` | ac_algedonic.py (writer), sd_digest.py (reader) |
| `ac-algedonic` | `vsf.alpha.s4.algedonic` | events.jsonl (RO) → alert.vsm → s5-alerts.db | Ollama LXC 101, vsf-s5-algedonic LXC 104 |
| `sa-auditor` | `vsf.alpha.s4.auditor` | coupling_registry + state.db (RO) → audit_flag.vsm → sa-audit.db | Ollama LXC 101, vsf-s3-star LXC 107 |
| `sd-digest` | `vsf.alpha.s4.digest` | s5-alerts.db + rag-nucleus.db (RO) → digest.vsm | Ollama LXC 101, vsf-s5-algedonic LXC 104 |

---

## 8. Design Decisions (resolved 2026-06-10)

1. **CS entry gate for FAIL verdicts:** ✓ YES — all verdicts (PASS/PARTIAL/FAIL/INCONCLUSIVE)
   indexed with the verdict field. Failure patterns ("D_KY > 4.5 → always FAIL") are as
   informative as passes for future proposals.

2. **AC trigger frequency:** ✓ max 1/minute, only when nucleus is actively running.
   Enforced by flock + cron guard. Prevents Ollama saturation on CPU-only LXC 101.

3. **AC alert persistence:** ✓ written to `/var/lib/vsf/alerts/` (filesystem) and indexed
   into `s5-alerts.db` (retrieval). Explicitly NOT indexed into `rag-nucleus.db` — store
   isolation rule §2.6 prevents alert bias on experiment proposals.

4. **Retrieval scope for EP:** ✓ same `domain_context.target` first; cross-domain fallback
   if k < 3. Prevents empty retrieval during early corpus growth while maintaining domain
   relevance once sufficient experiments exist.

---

## 9. D4-L3 — LLM only at the management boundary (decision 2026-06-10)

**Decision (confirmed by rmw3, S5):** Ollama/Qwen stays exclusively at the
management/human-interface boundary (EP proposals, SD digest, SA flags). The
algedonic flow S1→S5 is classified with deterministic methods — the decision
tree in `ac_classifier.py` now; correlation/DL methods over the ℝ¹²⁸ state
vector later, trained on the alert corpus accumulating in `s5-alerts.db`.

**Why:**
- **Latency:** the algedonic channel is the system's pain pathway — Qwen-in-path
  cost minutes per classification (cold loads 60-90s, probe + lock overhead);
  the tree costs milliseconds.
- **Reliability:** the Qwen path required tri-state probes, restart cooldowns,
  storm guards and self-alerts just to survive — none of which classify anything.
  A monitor must be more reliable than what it monitors.
- **Verifiability:** thresholds in code are unit-testable (23 tests, certified
  on LXC 108); a primer prompt is not.
- **Cybersyn:** Cyberfilter was statistical, not conversational. The Opsroom is
  where synthesis for humans happens.

**Rule D6' — ratified by rmw3 (S5), 2026-06-10. Inserted into `state.db` rules
table as id=10, scope=`llm`.**

> *scope:* `llm` — *rule:* "LLM only in human-interface synthesis (proposals,
> digests, audit flags read by a person). Signal channels — algedonic, φ↑/φ↓,
> homeostatic loops — use deterministic or statistical methods. An LLM never
> sits inside a latency-critical or safety-critical signal path."

Refines D6 (LLM at L≥2): D6 bounds *which layer* may host an LLM; D6' bounds
*which role* an LLM may play within that layer — interface synthesis, never
signal classification.
