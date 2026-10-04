> ⚠️ DEPRECATED 2026-05-25 — Canonical source is now **docs/VSF_VSM_SCORING.md**.
> This file is kept for historical traceability. Do not use as live reference.

# VSF — VSM Alignment Analysis (Internal)
# Evaluated against: Beer (1972) Brain of the Firm + Heart of Enterprise
# Date: 2026-04-06 | Status: pre-GitHub migration
# Note: this is a working document — not part of the public framework spec.

---

## Methodology

Each component is evaluated against three questions:
1. Is it correctly defined per Beer?
2. Is it correctly implemented in the spec/code?
3. What is missing or wrong?

Scale: ✅ aligned | ⚠ partial | ❌ critical gap

---

## S1 — Operations

### Beer says:
- S1 units are **maximally autonomous** within the system
- Each S1 has its own **operational environment** (what it faces externally)
- Each S1 has its own **internal management system** (can be another VSM — recursion)
- S1 units do not coordinate with each other directly — that is S2

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| Declared autonomy | ✅ | `autonomy` field per unit |
| Operational environment | ❌ | not modeled — each S1 faces a different environment |
| Recursion | ✅ | `recursive: true` + `vsf_ref` |
| No direct coordination | ⚠ | not validated — validator does not check cross-dependencies |
| Verifiable health check | ✅ | `health_check` field |

### Needed corrections:
- Add `operational_environment` field to each S1 unit (what environment it faces)
- Validator should warn if two S1 units share outputs (implicit dependency)

---

## S2 — Coordination

### Beer says:
- S2 **has no authority over S1** — only prevents resource conflicts
- S2 is anti-oscillatory: detects when two S1 units want the same resource and arbitrates
- S2 passes information from S1 to S3 (amplified) and from S3 to S1 (attenuated)
- **Bidirectional flow**: S2 is not just a scheduler — it is a two-way channel

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| Does not command S1 | ⚠ | documented in concepts.md but not validated |
| Anti-oscillation | ⚠ | mentioned (thermal kills) but not as a general principle |
| Bidirectional channel | ❌ | only modeled as a unidirectional "coordinator" |
| Interface contracts | ❌ | `contracts: 0` field exists but empty and unvalidated |

### Needed corrections:
- Add `channel` field to S2 to explicitly model bidirectional flow
- Validator should verify that S2.coordinator does not have direct access to S1 outputs
- Document: S2 is not the scheduler — it is the anti-conflict protocol the scheduler implements

---

## S3 — Control

### Beer says:
- S3 manages the **internal environment** — what happens inside the system
- S3 conducts **resource bargaining** with S1: negotiates, does not impose
- S3 has accountability — S1 reports to S3 for its outputs
- **Critical distinction**: S3 operates in the present (optimization), S4 in the future (adaptation)

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| Internal management | ✅ | well modeled |
| Resource bargaining | ❌ | does not exist — only "orchestrator" and "prioritizer" |
| Accountability S1→S3 | ❌ | not modeled — S1 does not "report" to S3 |
| Distinction S3 present / S4 future | ⚠ | mentioned in concepts.md but not in the spec |

### Needed corrections:
- Add `accountability_mechanism` field to S3 (how S1 reports to S3)
- Document resource bargaining as a principle — not just orchestration

---

## S3* — Audit (Algedonic Channel)

### Beer says:
- S3* is the **algedonic channel** — pain/pleasure signals that go directly to S5, bypassing S3
- Beer: "algedonic alerts bypass the whole management hierarchy"
- S3* does not just audit S1 — it can alert S5 directly if S3 is failing
- Mode of operation: **sporadic**, not continuous

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| Direct channel to S1 | ✅ | "bypasses S3" documented |
| Bypass to S5 in emergency | ❌ | **CRITICAL GAP**: our S3* only goes to S3, not directly to S5 |
| Sporadic | ✅ | `interval` field |
| Emergency/trajectory mode | ✅ | well modeled |

### Needed corrections:
- **CRITICAL**: S3* must have a direct channel to S5, not just to S3
- Add `escalation_target` field to S3*: when critical anomaly detected, escalate to S5 directly
- Validator must verify this S3*→S5 channel exists

---

## S4 — Intelligence

### Beer says:
- S4 looks **outward and toward the future** — not the present
- S4 interacts with S5: proposes adaptations, S5 approves or rejects
- **Critical distinction**: S4 models the future environment, S3 manages the present environment
- The **S3↔S4 tension** is the adaptation mechanism: S3 wants stability, S4 wants change
- S5 balances this tension

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| External scanning | ✅ | `monitors` field |
| S4↔S5 interaction | ❌ | **GAP**: S4 proposes nothing to S5 in the spec |
| S3↔S4 tension | ❌ | not modeled — fundamental in Beer |
| CHECO as prospection | ✅ | well modeled |
| Models future, not present | ⚠ | mentioned but not structured |

### Needed corrections:
- Add `proposals_to_s5` field to S4 (how S4 proposes adaptations to S5)
- Document and model the S3↔S4 tension as a balance mechanism
- S5 must have `s4_proposals_policy` field (how it processes S4 proposals)

---

## S5 — Identity

### Beer says:
- S5 defines **what the system is** in its environment — not just the internal rules
- S5 balances S3 (internal efficiency) vs S4 (external adaptation)
- S5 **does not manage operations** — establishes identity and limits
- S5 is the only system with complete vision: sees S3, S4, and the environment

### Current evaluation:
| Aspect | Status | Notes |
|--------|--------|-------|
| Identity in environment | ⚠ | `purpose` exists but does not model position in environment |
| S3↔S4 balance | ❌ | not modeled in the spec |
| Does not manage ops | ✅ | well documented |
| Autonomy ceiling | ✅ | well implemented |
| Complete vision | ❌ | S5 has no declared access to S3 + S4 + environment |

### Needed corrections:
- Add `environment_position` field to S5: how the system positions itself in its environment
- Add `s3_s4_balance_policy` field to S5: how S5 arbitrates the tension

---

## Cybersyn Patterns — Evaluation

### Cybernet
| Aspect | Status | Notes |
|--------|--------|-------|
| Bidirectional channel | ❌ | only modeled as "implementation", not as a flow |
| Upward flow S1→S3 | ❌ | not declared |
| Downward flow S3→S1 | ❌ | not declared |

### Cyberfilter
| Aspect | Status | Notes |
|--------|--------|-------|
| Variety attenuation | ✅ | well documented |
| Ashby's Law explicit | ✅ | in concepts.md |
| S3/S1 variety balance | ❌ | variety also rises (S3 amplifies toward S1) |

### Cyberstride
| Aspect | Status | Notes |
|--------|--------|-------|
| Trajectory detection | ✅ | emergency/trajectory modes |
| Definable KSIs | ✅ | well structured |
| Normalized baseline | ✅ | `normalization` field |

### CHECO
| Aspect | Status | Notes |
|--------|--------|-------|
| Prospection before execution | ✅ | well modeled |
| Data threshold | ✅ | `threshold` field |

### Opsroom
| Aspect | Status | Notes |
|--------|--------|-------|
| Ergonomic design | ⚠ | 3 panels OK but principle not documented |
| No raw data to operator | ⚠ | implemented but not as an explicit rule |
| Pre-processed signals | ✅ | Signal Queue panel |
| Accessible action buttons | ✅ | action bar |

---

## Systemic Gaps (not per component)

### G1 — Metasystem not declared
Beer is explicit: S3 + S3* + S4 + S5 form the **metasystem** that supervises S1 + S2.
This distinction does not exist in the spec. It matters because:
- It defines what has authority over what
- The metasystem can act without consulting S1
- It is the foundation of the autonomy ceiling

### G2 — Two environments, not one
Beer distinguishes:
- **Operational environment**: what S1 faces (its market, its inputs/outputs)
- **Exterior environment**: what S4 scans (macro changes, systemic threats)
Currently the spec has only one "env-band" in the diagram — does not model this distinction.

### G3 — Variety is not just attenuation
Ashby's Law requires that the **variety of the controller ≥ variety of the system**.
This means S3 needs to **amplify** its variety toward S1 (more granular control)
And S1 needs to **attenuate** its variety toward S3 (summaries, metrics).
Currently we only model attenuation (Cyberfilter), not amplification.

### G4 — Missing accountability loop
In VSM there is an explicit loop: S1 produces → S3 measures → S3 negotiates resources with S1.
Without this loop, S3 is just a scheduler, not a viable control system.

---

## Correction Summary

| Priority | Change | File |
|----------|--------|------|
| CRITICAL | S3*→S5 direct algedonic channel | viability.yaml + validator.py |
| HIGH | S4↔S5 proposals mechanism | viability.yaml |
| HIGH | S3↔S4 tension field in S5 | viability.yaml |
| HIGH | Metasystem declared | viability.yaml + concepts.md |
| MEDIUM | S1 operational_environment | viability.yaml |
| MEDIUM | S2 bidirectional channel | viability.yaml + concepts.md |
| MEDIUM | S3 accountability_mechanism | viability.yaml |
| MEDIUM | Two environments in Opsroom | opsroom/index.html |
| LOW | Variety amplification documented | concepts.md |
| LOW | Opsroom ergonomics as principle | concepts.md |

---

## What is correct (do not change)

- Autonomy ceiling: correct and validated ✅
- S1 recursion: correct ✅
- Cyberstride emergency/trajectory: correct ✅
- CHECO threshold pattern: correct ✅
- Lifecycle gates: correct ✅
- Single/double learning loops: correct ✅
- Infrastructure profiles: coherent ✅
- Source refs in S1 units: useful innovation, not in Beer but does not contradict ✅
