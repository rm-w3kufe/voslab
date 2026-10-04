# VSF view-module contract — modular, certified φ↑ (v0.2.2)
> **STATUS: historical_record** — consumido por fuse S4-ANTICIPATION → s4_anticipation.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

> **Status:** `feat/cybernetic-rag`, **v0.2.1.** v0.1 was a concession (no attestation); v0.2 over-corrected
> (signed every frame); **v0.2.1** (review fix): certify the SOURCE, project the view, verify upstream.
> **Directive (rmw3, 2026-06-05):** NO concessions to legacy. Every coupling/contract passes the
> **validation loop** — conform to the canonical channel standard (`core/connection_schema.json`) +
> **version-check** — before anything builds on it. v0.1 was a silent concession to the legacy opsroom
> `api.py` (HTTP/SSE, unsigned JSON); v0.2 corrects it. See `feedback_validation_loop_no_concessions`.

## 0. The two laws this contract obeys

1. **Validation-loop law.** This contract is VALID only if it (a) conforms to
   `core/connection_schema.json` at a pinned version (version-checked, reject on drift) and (b) the
   **upstream source** it projects is **AX-STATE-attested and the consumer verifies it** (sig + chain +
   freshness). A legacy interface is never adopted as a base without passing this loop. The view itself is
   a projection — it is certified by verifying its source, not by re-signing every frame (see §3).
2. **Modularity law.** The model is a **host for modules**. Modules **integrate and decommission**
   cleanly. The opsroom panel scaffold is **not** load-bearing — it is one possible host; what is
   canonical is the **module abstraction**. *Cybernetic RAG is module #1, not the whole.*

## 1. The module abstraction (what is actually canonical)

A module = a self-describing, certifiable view unit with an explicit lifecycle. Declared, not assumed.

```json
{
  "module_id": "cybernetic-rag",
  "version": "0.2.0",
  "title": "Cybernetic RAG",
  "lifecycle": "proposed | active | decommissioned",
  "coupling_subject": "vsf.{vsf_id}.view.cybernetic-rag",
  "attest_subject":   "vsf.{vsf_id}.attest.view.cybernetic-rag",
  "schema_ref": "connection_schema/0.2.1 + view-module/0.2",
  "certifier": "ed25519:<key_id>"
}
```

- **Integration** = declare a `coupling_registry` row (`kind=phi_channel`) + the host subscribes.
- **Decommission** = retire the row + unsubscribe; the host reflows (no dangling panel).
- **model≡reality:** an `active` module with no live, verifying feed = **ORPHAN** (the S3* reconcile /
  `topology_reconcile` catches it). A module not declared but emitting = **MISSING**. The host renders
  only declared+certified modules.

## 2. Transport — the φ↑ source is the events.jsonl FILE (v0.2.2 correction)

**v0.2.1 wrongly assumed NATS for the φ↑ stream.** Validated against reality (2026-06-05): the canonical
φ↑ channel per `core/connection_schema.json` is `upward_channel.file = telemetry/{system_id}/events.jsonl`
— a **hash-chained append-only FILE** (`prev_hash`/`hash` per line, S3*-validatable). The live source is
`/var/lib/vsf/vsf_nucleus/events.jsonl` on the nucleus (101). **NATS Core is the ALGEDONIC carrier only**
(`vsf.{vsf_id}.algedonic`, the binary urgent signal) — NOT the φ↑ telemetry stream.

- **Source read:** the view-host reads `events.jsonl` **read-only** (a bind-mount into the view-host LXC,
  the same pattern SCADA used for `state.db`). No NATS in the φ↑ path.
- **Integrity:** verify the Merkle chain linkage of the tail (`prev_hash == previous.hash`) — this is the
  connection_schema integrity the standard mandates (R9). Ed25519 SIGNING of the φ↑ is a deeper layer
  (the nucleus signs its events = PROD-A1b / C1 key custody); chain-linkage is the integrity floor.
- **Browser:** the view-host serves the projected view to the browser over a minimal SSE (stdlib), not the
  raw file. The view-host is the φ↑ reader + projector; the browser never touches the source.

## 3. Certification belongs to the SOURCE, not the projection (review fix, v0.2.1)

A view is a **derived projection**, not a source of truth — so it must NOT re-sign/re-chain every frame
(both costly and conceptually wrong: you attest *sources*, not projections). The certified, hash-chained
surface is the **nucleus φ↑ telemetry itself** (already `connection_schema` upward_channel + AX-STATE
attested). The view module therefore has TWO layers:

- **Live tick (ephemeral):** NATS Core, high-frequency, **unsigned** — drives smooth display only. Carries
  `module_id`, the `view` body, `ts`, and a `source_ref` pointing at the attested upstream checkpoint it
  was projected from.
- **Certification (periodic, snapshot-mode):** the visualizer verifies the **upstream source attestation**
  (the nucleus φ↑ checkpoint — sig + chain + freshness, reusing AX-STATE `state_verify`) at a **cadence**
  (mirrors AX-STATE snapshot mode, not per-frame). UI shows *"certified as of <ts>"*; a stale / failed /
  forged source → **degraded/algedonic**, never blindly healthy.

```json
// live tick (ephemeral, NATS Core) — NOT signed per frame
{
  "ts": "2026-06-05T00:00:00Z",
  "system_id": "<vsf_id>",
  "module_id": "cybernetic-rag",
  "view": { "global": { ... }, "nodes": [ ... ], "edges": [ ... ] },   // model-agnostic body (§3.1)
  "source_ref": { "subject": "vsf.{vsf_id}.attest.telemetry", "head_hash": "<sha256>" }
}
```

Conform to `connection_schema` φ↑ ONLY where it is meaningful for a projection: `ts`, `system_id`,
provenance (`source_ref`), and the source's `trust_score`. Do **NOT** fabricate `variety_delta` /
`algedonic_seq` / a per-tick Merkle `hash` on a view — those belong to the emitting regulator (the
nucleus), not to a read-only projection. *(The validation loop cuts both ways: conform to the standard,
but never cargo-cult fields that don't apply.)* The honesty flag `implemented: true|"partial"|false`
stays in each node.

### 3.1 The Cybernetic RAG view body (unchanged from v0.1 — only the envelope changed)

`view.global`: `viability`, `in_omega`, `lyapunov{L,dL,converging}`, `last_algedonic`.
`view.nodes[]`: `id,label,stage,sublevel(A|B),status,implemented,metrics,actions(read-only)`.
`view.edges[]`: `from,to,kind(flow|feedback),state(active|firing|idle|aspirational),guard`.
Stages: retrieval(A) → gate(Ω) → generation → evaluation → recovery → crosscheck → output.

### 3.2 φ↑ coupling map (synthetic → real nucleus — the swap that never touches the visualizer)

| view field | synthetic stub | real nucleus source (φ↑) |
|---|---|---|
| `global.viability` | 0.94 | `stasis_cos` (operator.rs) |
| `global.in_omega` | true | `Omega::canonical().violations(state).is_empty()` (omega_validator.rs) |
| `global.lyapunov` | dL<0 | `LyapunovTracker` per breath cycle (attractor.rs) |
| `global.last_algedonic` | null | `vsf.{id}.algedonic` NATS subject (already published) |
| `crosscheck.metrics.reconciled` | true | `topology_reconcile` exit (S3*) |
| `trust_score` / `hash` chain | computed locally | per `connection_schema` upward_channel |

## 4. The validation loop, made concrete (gates the directive demands)

Before any module is built or integrated:
- **G-V1 version:** `schema_ref` pins `connection_schema` version; reject on drift vs the live file.
- **G-V2 conformance:** the live tick carries valid provenance (`source_ref` + `ts` + `system_id`); a view
  is a projection, so it does NOT need the emitter event_schema (`variety_delta`/`algedonic_seq`/per-tick hash).
- **G-V3 attestation:** the **upstream source checkpoint** the view projects from verifies (sig + chain +
  freshness) under the source certifier key (AX-STATE `state_verify`). The view itself is not re-signed.
- **G-V4 declaration:** the module is a `coupling_registry` `kind=phi_channel` row (model≡reality; else ORPHAN).
A module failing any gate is **not** rendered as live — it shows **uncertified**.

## 5. φ↓ deferred (human-gated)

No directive fields. φ↓ is a SEPARATE channel, A5 (double-loop ⇒ human approval) + D6 (no LLM at L<2)
gated; the panel never emits. Read-only φ↑ first.

## 6. Dependencies / honesty

- **H2 (authenticated NATS):** full *transport* certification (broker auth + message signing) depends on
  H2 — the same dependency AX-STATE flagged for off-host anti-rollback. The **payload attestation lands
  first** (signatures in the record); H2 hardens the transport later.
- The view *body* is identical to v0.1; what changed is the **envelope** (NATS transport + φ↑ shape +
  attestation + the module abstraction). The change is architectural, not cosmetic.

## 7. Next (gated on this contract)

IF accepted THEN, each step gated: (1) the module manifest + a `coupling_registry` `kind=phi_channel`
row for `cybernetic-rag`; (2) the attested φ↑ builder (synthetic source first, conforming to §3,
verified by `state_verify`); (3) NATS subject wiring (or the thin `api.py` bridge); (4) one host module
that renders the **verified** view (mermaid client-side). G-V1..G-V4 run before each integration.
