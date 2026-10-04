# BBH Publisher Contract — VSF γ.9 Subscriber Wire Spec

**Document version:** 1.0
**Date:** 2026-05-25
**Owner:** VSF Validation Team
**Consumed by:** BBH (Claude Code S1)
**Counterpart code:** `vsf/projects/vsf-nucleus/src/bbh_subscriber.rs` (γ.9, deployed LXC 101 PID 173736)
**Status:** READY TO IMPLEMENT — VSF subscriber is live, idle, awaiting first message

---

## 0. TL;DR for BBH

Publish JSON events to NATS subject hierarchy `bbh.<instance>.<channel>.<event_type>`
on `nats://10.10.20.20:4222` (LXC 106 vsf-nats-test). VSF γ.9 catches `bbh.>`,
chains your event into the canonical `events.jsonl` ledger with `system_id="bbh"`,
and the GATE_3 K_φ↑ measurement reads it from there. Phase tag goes in
`metrics.phase`.

You can test by publishing a single event — VSF will emit it to events.jsonl
and you can verify by tailing `/var/lib/vsf/vsf_nucleus/events.jsonl` on LXC 101.

---

## 1. Transport

| Property | Value |
|---|---|
| NATS URL | `nats://10.10.20.20:4222` (LXC 106 testbed) |
| Client name | recommended `bbh-<instance>-publisher` |
| Reconnect | client-side, exponential backoff, retry forever |
| Auth | none in testbed (will tighten before W2 prod) |

VSF γ.9 uses `async-nats 0.35`. BBH can use any NATS client; payloads are plain
UTF-8 JSON lines (no headers required).

## 2. Subject hierarchy

```
bbh.<instance>.<channel>.<event_type>
```

| Token | Examples | Meaning |
|---|---|---|
| `<instance>` | `alpha`, `pilot1`, `prod-h1-jpmorgan` | BBH instance id — stable per-process identity |
| `<channel>` | `phi_up`, `algedonic`, `audit` | matches BBH spec v3.1 §canonical_channels |
| `<event_type>` | `phase_complete`, `tool_run`, `finding_emitted`, `signal_escalated` | semantic event class |

Examples:
- `bbh.alpha.phi_up.phase_complete`
- `bbh.alpha.phi_up.tool_run`
- `bbh.alpha.algedonic` (no event_type token — algedonic is binary)
- `bbh.pilot1.audit.s3_star_sample`

VSF γ.9 subscribes the wildcard `bbh.>`, so the exact granularity is up to BBH.

## 3. Payload schema

Each NATS message body is a single JSON object. All fields are OPTIONAL — γ.9
falls back to safe defaults if a field is missing. **Recommended fields:**

```json
{
  "ts": "2026-05-25T22:01:14.123456Z",        // ISO-8601 UTC, microsecond precision
  "system_id": "bbh",                          // free string, used as filter in analysis
  "event_type": "phase_complete",              // overrides subject-derived event_type
  "status": "ok",                              // "ok" | "error" | "warn" | "info"
  "signal_status": "resolved",                 // "resolved" | "active" | "queued"
  "duration_s": 1.234,                         // wall-clock duration of the unit of work
  "metrics": {
    "phase": "B2_ACTIVE",                      // REQUIRED for Markov analysis — see §4
    "target": "auth.example.com",              // optional, BBH-specific
    "finding_count": 3,                        // optional, BBH-specific
    "vuln_class": "SQLi",                      // optional, BBH-specific
    "tool": "sqlmap",                          // optional, BBH-specific
    "...anything BBH wants to log": "..."
  },
  "variety_delta": 0.15,                       // optional, ΔV for VAR-1 invariant
  "trust_score": 0.92                          // optional, current trust per TRUST-1
}
```

### Fallback behavior (γ.9 lenient parser)

| Missing field | γ.9 fills with |
|---|---|
| `ts` | `Utc::now()` at emit time |
| `system_id` | `"bbh"` |
| `event_type` | last token of subject (e.g. `phase_complete`) |
| `status` | `"ok"` |
| `signal_status` | `"resolved"` |
| `duration_s` | `0.0` |
| `metrics` | wraps `{ "_raw_payload": <whole-payload>, "_origin_subject": <subj> }` |
| `variety_delta` / `trust_score` | `null` |

If the entire payload is unparseable JSON, γ.9 logs and SKIPS the message
(does not enter events.jsonl). Malformed messages do not break the chain.

### Reserved fields (γ.9 OVERWRITES these on every event)

| Field | Why overwritten |
|---|---|
| `prev_hash` | VSF Merkle chain — γ.9 owns the chain order |
| `hash` | computed from event content (with hash=None) |
| `algedonic_seq` | reset to 0 unless `event_type == "algedonic_emit"`, then bumped |

So if BBH includes `prev_hash` / `hash` from its own chain, they will be
silently replaced. This is intentional: VSF's `events.jsonl` is the
**single canonical chain** for GATE_3 measurement.

## 4. The `phase` field — MANDATORY for Markov analysis

Every event SHOULD carry `metrics.phase` set to one of the canonical
BBH workflow states:

```
B0_PROFILE   B1_PASSIVE   B2_ACTIVE   B3_ENUM    B4_ANALYSIS
B5_PARALLEL  B6_AI        B7_TRIAGE   B8_SUBMIT  IDLE   ABORT
```

Reference: `docs/operational/gate3_experimental_plan.md §2.2`.

If `phase` is missing, the event still lands in events.jsonl but the Markov
analysis will not credit it to any state — K_φ↑(i) loses one sample for
that state.

### State transitions

When BBH moves from `B_i` → `B_j`, emit `event_type: "phase_complete"` with
`metrics.phase = "B_j"` (the **new** phase). This is what builds the
empirical transition matrix P. ≥30 such transitions are needed for GATE_3
close.

## 5. Algedonic events

For algedonic signals, emit on `bbh.<instance>.algedonic`:

```json
{
  "ts": "...",
  "event_type": "algedonic_emit",
  "metrics": {
    "phase": "B2_ACTIVE",
    "severity": "high",
    "reason": "trust_score < tau_min",
    "origin": "bbh.alpha.scanner-3"
  },
  "trust_score": 0.42
}
```

VSF γ.4 algedonic gate is a SEPARATE channel from γ.9 — γ.9 will still relay
algedonic events to events.jsonl, but the algedonic gate itself (low-latency
binary path) does NOT consume `bbh.algedonic`. If you want algedonic-rate
limiting and gate fire-resolution, the gate listens on
`vsf.<vsf_id>.algedonic` instead — that is a VSF-internal NATS Core channel,
not for BBH ingress.

For now: just publish to `bbh.<inst>.algedonic` for telemetry purposes.

## 6. Rate limits (informational, will be enforced by S5 in future)

Per `gate3_experimental_plan.md §3` and `s5_policy.default.json`:

| Limit | Target |
|---|---|
| `phi_up_max_per_min` per instance | 10 (steady state) |
| burst tolerance | 60 (1 min) |
| `audit_sample_rate_per_24h` | 0.01 |

If BBH exceeds, γ.9 today just relays everything; in W2 production VSF may
add backpressure. Do not stress-test the testbed without coordination.

## 7. Testing without writing the publisher

BBH can manually verify γ.9 is alive with `nats` CLI:

```bash
# From any host with NATS access:
nats --server nats://10.10.20.20:4222 pub bbh.alpha.phi_up.test_smoke \
  '{"event_type":"smoke_test","metrics":{"phase":"B0_PROFILE","_test":true}}'

# Then on LXC 101:
ssh root@n02 'pct exec 101 -- tail -3 /var/lib/vsf/vsf_nucleus/events.jsonl'
# → should see the event with system_id from the payload (default "bbh"),
#   event_type "smoke_test", and prev_hash/hash overwritten by γ.9
```

## 8. Implementation checklist for BBH

- [ ] Decide instance id naming convention (e.g. `alpha`, `prod-<scope>`)
- [ ] Wire NATS client (any language; existing BBH stack uses Python — `nats-py`)
- [ ] At every workflow transition, publish to `bbh.<inst>.phi_up.phase_complete`
      with `metrics.phase = <new_phase>`
- [ ] At every tool execution, publish to `bbh.<inst>.phi_up.tool_run`
      with `metrics.phase`, `metrics.tool`, `metrics.target`
- [ ] At every finding emission, publish to `bbh.<inst>.phi_up.finding_emitted`
      with `metrics.phase`, `metrics.vuln_class`, `metrics.severity`
- [ ] At algedonic signal, publish to `bbh.<inst>.algedonic`
- [ ] On reconnect, do NOT republish history — γ.9 is at-most-once at message
      level, the chain is reconstructable from disk if needed

## 9. Versioning + compatibility

This contract is `v1.0`. Backward-compatible field additions are allowed
(γ.9 ignores unknown fields). Breaking changes (rename, removal, type change)
require version bump + coordination.

Schema reference (informative, not enforced today):
`/home/rmw3/vsf/core/connection_schema.json` v0.2.1 §upward_channel.

## 10. Coordination

- VSF γ.9 deployed, idle, monitoring `bbh.>` since 2026-05-25 21:54 UTC
- VSF will tail journalctl for γ.9 log lines: `[bbh_subscriber] relayed N events`
- When BBH starts publishing, ask VSF for first 5-event verification
- W2 measurement window opens automatically when γ.9 receives first event
  (no separate W1 → W2 cutover — the same collector keeps tailing)

## 11. References

- VSF subscriber source: `vsf/projects/vsf-nucleus/src/bbh_subscriber.rs`
- BBH spec channels: `bbh/spec/bbh_vsf_protocol_v3.vsm` v3.1 §canonical_channels
- Markov analysis: `vsf/scripts/measurement/markov_analysis.py`
- Experimental plan: `vsf/docs/operational/gate3_experimental_plan.md`
- Subject hierarchy origin: `vsf/docs/theory/information_flow_architecture.md` §7
