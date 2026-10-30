# VSL Primer — Minimal Briefing for External AI

@vsl_core.v1.2 | VSF Project | 2026-04-09

---

## What is VSL

**VSL (Viable System Language)** is a formal notation for designing and operating viable systems — systems that can maintain identity and adapt under environmental pressure.

Based on Beer's Viable System Model (1972) and Cybersyn (1971).
Governs: agent coordination, resource budgets, signal routing, inter-system coupling.

---

## System structure

Every viable system V has five subsystems:

```
V ::= ⟨S1, S2, S3, S4, S5, S3*⟩

S1  = execute          // operational units — do the work
S2  = coordinate       // prevent sibling conflicts
S3  = control          // allocate resources, triage signals
S3* = audit            // sporadic direct channel — sees what S3 misses
S4  = adapt            // environment model, drift detection
S5  = govern           // policy — sets rules nobody overrides
```

V is **recursive**: any S1 unit can itself be a full V.

---

## Core axioms

```
A1: V ⊃ V                          // recursive containment
A2: B(child) ≤ B(parent)           // budget hierarchy
A3: B = min(tokens, compute, time) // budget is the binding constraint
A4: ¬sibling_coupling              // siblings never talk directly
A5: autonomy ≤ S5.ceiling          // policy caps all autonomous action
A6: Var(E) ≤ Var(S3 ⊕ S2)         // Ashby's requisite variety
A7: resolve(s,V)=∅ ∧ urgency > τ → escalate φ↑
A8: absorption bounded             // signal volume decreases upward
A9: B_exhausted → degrade ∨ abort
A11: S4_active ⟺ drift > ε        // S4 gates on drift only
```

---

## Signals

```
urgency  ∈ { CRITICAL, HIGH, MEDIUM, LOW }
status   ∈ { pending, resolved, undecidable, deferred }

routing (A7 + A10):
  resolve(s) = ok          → absorbed locally
  resolve(s) = ∅ ∧ urgency > τ_L:
    LOW    → S3 (local regulation)
    MEDIUM+ → S5 (policy level)
  resolve(s) = ∅ ∧ urgency ≤ τ_L → deferred pool (D10)

meta_shift (D12):
  |deferred| / |total| > μ  ∧  CalibScore < 0.7
  → structural inadequacy — candidate for reframe()
  → always requires human approval (A5)
```

---

## Execution cycle

```
tick(L):
  1. read φ↓(params)       // receive config from parent
  2. S2: coordinate        // resolve sibling conflicts
  3. S3: triage signals    // route per A7/D10 above
  4. S1: execute units     // each unit may tick(L+1)
  5. S4: update env model  // only if drift > ε (A11)
  6. emit φ↑(events)       // report upward
```

Channels:
```
φ↑  events.jsonl   child → parent   (append-only telemetry)
φ↓  params.json    parent → child   (configuration)
ψ   S4_A ↔ S4_B   inter-VSM        (requires credential-manager + S5 approval)
```

---

## Degradation and abort

```
B_exhausted → minimal_governance_mode ⊂ degrade:
  emit(events_min)   // keep φ↑ alive
  skip(S1)           // stop execution
  restrict(S4)       // no adaptation

abort ⟺ critical_failure ∨ policy_violation
  critical_failure ∈ { system_break, trust_collapse, invariant_violation }
```

---

## Trust (ψ prerequisite)

```
T(t) = 0.6·decay(T(t-1), λ) + 0.4·audit(t)

audit(t) = (0.5·reachability + 0.3·stability + 0.2·drift) · (1 − error_S2)

T = 0 on { compromised, unhealthy } → revoke all ψ immediately

ψ(A,B) requires:
  governed(A) ∧ governed(B)      // both emit φ↑ and accept φ↓
  trust(A,B) ≥ limited
  S5(A).approve ∧ S5(B).approve
```

---

## governed(x)

Minimum condition for any protocol interaction:

```
governed(x) = has(params.json) ∧ emits(events.jsonl)
```

A system that does not participate in φ↑/φ↓ cannot be trusted, coupled, or reframed.

---

## Key invariants

```
governed(V) = True              // always
B_exhausted → governed(V)       // governance survives budget exhaustion
¬critical_failure → ¬abort      // no spurious abort
S4_active = False → stability ≥ baseline
```

---

## Current implementation state

| Component | File | Status |
|-----------|------|--------|
| Spec | `docs/spec/vsm_notation_spec.md` | v0.4 |
| Signal router (S3 tick) | `core/signal_router.py` | done |
| Token telemetry (φ↑) | `~/claude/metrics/session_hook.py` | done |
| Credential manager (ψ prereq) | `projects/credential-manager/` | planned |
| Connection schema | `core/connection_schema.json` | v0.2 |
| Opsroom dashboard | `opsroom/` | done |

---

## What to implement next (task F)

`projects/credential-manager/` — enables ψ channels and reframe():

```
1. viability.yaml          // VSF self-description
2. src/provision.py        // generates SSH keys, writes ~/.ssh/config
3. src/health_check.py     // ssh -T per S1 unit (S3* audit input)
4. src/scanner.py          // reads viability.yaml files → extracts credential needs (S4)
5. src/trust.py            // T(t) computation (D11b)
6. src/handshake.py        // 4-phase ψ establishment: init→validate→negotiate→establish
```

Design reference: `HANDOFF.vsm.md § credential-manager`
