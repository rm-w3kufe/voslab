# GATE_3 — Experimental Plan for K_total Validation

**Document version:** 1.0
**Date:** 2026-05-25
**Status:** DRAFT — pending BBH + Qwen review BEFORE data generation
**Owner:** VSF Validation Team
**Supersedes:** `k_measurement_protocol_2026-05-25.md` §3 (extends with statistical method)
**Closes:** GATE_3 (loop gain empirical validation)

---

## 0. Why this document exists

`k_measurement_protocol_2026-05-25.md` §3 specified **what to measure** (K_φ↑, K_φ↓, τ) and **how to compute G(jω)**. It did NOT specify:

1. How to interpret the inevitable variance across BBH workflow phases (B0..B8 have very different emission rates)
2. How many samples are statistically sufficient
3. How to claim `K_total ≤ 0.8` **worst-case** vs **mean** — the covenant says `max_loop_gain`, which is worst-case
4. How to handle rare events (algedonic, signal_escalated) where naive sampling under-counts

This plan addresses those gaps. **It commits to a method BEFORE data is generated**, to prevent post-hoc rationalization.

---

## 1. Honest diagnosis of W1 baseline

W1 collector (running since 2026-05-25T14:42Z) is capturing real events, but the only event_type present is `kernel_tick` at 1/min. Reason: γ.7 nucleus in steady state without S1 load emits nothing else.

This makes W1-as-is **statistically meaningless** for K_total claim. We need:

| Missing | Cause | Fix |
|---|---|---|
| `s4-analysis` in events.jsonl | S4 worker writes to BBS only | P.1 — also emit to events.jsonl |
| `invariant_check` events | γ.6 runs without event emission | P.2 — periodic sample emission |
| `param_change` events | γ.5 reload silent | P.3 — emit on apply |
| BBH events | no cross-system subscriber | P.4 — γ.9 new module |
| Phase variability | no S1 with phases yet | D.* — BBH integration + scans |

---

## 2. Statistical method — Markov chain over BBH phases

### 2.1 Why Markov (not just mean ratios)

Naive estimator: `K_φ↑ = total_phi_up_events / total_state_changes` over the window.

**Problem:** if 80% of measurement time is spent in B1 (passive, low emission) and 20% in B2 (active, high emission), naive mean **under-estimates the burst regime**. The covenant `max_loop_gain ≤ 0.8` is a worst-case claim. A point estimate of mean K is the **wrong statistic**.

Markov approach is appropriate because:

- BBH workflow is **state-dependent**: emission rate is a function of current phase
- Transitions B_i → B_j are **memoryless first-order** for the pipeline as specified (workflow A-G are deterministic given inputs; randomness comes from findings/scope)
- State space is **finite and small** (≤11 states)
- Estimation is **closed-form** (P_ij = #transitions / #visits, π = leading eigenvector)

### 2.2 State space

```
S = { B0_PROFILE, B1_PASSIVE, B2_ACTIVE, B3_ENUM, B4_ANALYSIS,
      B5_PARALLEL, B6_AI, B7_TRIAGE, B8_SUBMIT, IDLE, ABORT }
```

11 states. B0..B8 transient, IDLE recurrent (return after submit), ABORT absorbing.

### 2.3 Transition matrix P

Empirically: `P_ij = N(B_i → B_j) / N(B_i visits)`.

Minimum data: **N ≥ 30 transitions** to estimate P with reasonable precision. Each BB scan produces ~9-12 transitions. Therefore **≥ 5 scans** needed (D.2 + D.3 + D.5).

### 2.4 Stationary distribution π

For ergodic part (B0..B8 + IDLE):
```
π = πP   subject to   Σπ_i = 1
```
Computed via dominant eigenvector. `π_i` = long-run fraction of time in state i.

### 2.5 Per-state K_φ↑(i)

For each state i with n_i ≥ 5 visit-minutes:
```
K_φ↑(i) = total_phi_up_in_state_i / total_state_changes_in_state_i
```

Bootstrap CI (resample with replacement over visit-minutes, B=10000) gives 95% interval.

### 2.6 Worst-case claim

```
K_φ↑_worst = max { K_φ↑(i) : π_i ≥ 0.01 }
K_φ↓_worst = max K_φ↓(i)   (analogous)
K_total_worst = K_φ↑_worst · K_φ↓_worst
```

**`K_total_worst < 0.8` is the actual covenant claim**, not `mean(K_total)`.

### 2.7 What Markov does NOT capture (declared limitations)

- **Concurrency in B5 parallel**: state is not scalar when N workers run in parallel. Workaround: model per-worker chain, aggregate.
- **Findings-dependent dwell times** (semi-Markov): how long a scan spends in B2 depends on findings count.
- **Hidden state**: WAF detection, OPSEC switches change emission rate within nominal "B2 phase".

### 2.8 REFINED per Qwen P5 review 2026-05-25

Original plan committed to "plain Markov sufficient for first certification, refinements deferred." **Qwen pushed back:**

> "BBH tiene dependencias de estado (semi-Markov). Primer orden memoryless subestima colas de fallo. n=30 es insuficiente para CI robusto."

**Method updated:**

1. **Adopt semi-Markov** (or 2nd-order Markov if data permits) for K_total worst-case estimation. Treat dwell time per state as a random variable with its own distribution.
2. **Minimum sample size n ≥ 100 transitions** (was 30). Below this, P_ij estimates have CI too wide to anchor covenant.
3. **Use Dirichlet priors** for transition probabilities (Bayesian conjugate to multinomial). Compute credible intervals, not just bootstrap. This handles sparse transitions (some B_i → B_j combinations never observed in small samples) gracefully.

Plain Markov pipeline (`scripts/measurement/markov_analysis.py`) remains useful for sanity checks but is no longer the certification method.

This pushes back the analysis side of W2; the data collection side (P.1/P.2/P.3/P.4 already deployed) is unaffected.

---

## 3. Sample size targets

| Metric | Target | Rationale |
|---|---|---|
| Total events in events.jsonl | ≥ 1000 | per protocol §3.6 |
| Distinct event_types | ≥ 6 | covers φ↑ enumeration |
| Phase transitions | **≥ 100** (was 30, Qwen P5) | enables P_ij + Dirichlet credible intervals |
| Visits per state (active states) | ≥ 5 | per-state K_φ↑(i) computable |
| S5 decisions (param_change preceded by s4-analysis) | ≥ 30 | K_φ↓ and τ paired |
| BB scans completed | ≥ 3 across different targets | inter-target variance |
| Sustained burst sample (B5 parallel) | ≥ 1 run with N≥4 workers | peak K_φ↑ observed |

If any target is missed, **GATE_3 closes with PARTIAL marker** + explicit gap statement.

---

## 4. Event taxonomy (canonical mapping)

This fixes the semantics so VSF and BBH count the **same things**.

### 4.1 φ↑ events (numerator for K_φ↑)

| event_type | Source | Counts as |
|---|---|---|
| `kernel_tick` | VSF nucleus heartbeat | φ↑ (baseline) |
| `anomaly_detected` | S3* audit | φ↑ |
| `phase_complete` | BBH workflow transition | φ↑ + state change marker |
| `tool_run` | BBH probe execution | φ↑ |
| `thermal_wait` | BBH throttle event | φ↑ |
| `signal_escalated` | algedonic burst | φ↑ + algedonic_seq increment |
| `invariant_check` | γ.6 periodic | φ↑ |
| `drift_alert` | γ.6 anomaly | φ↑ |
| `finding_emitted` | BBH B4/B7 output | φ↑ |

### 4.2 State-change events (denominator for K_φ↑)

| event_type | Source | Counts as state change |
|---|---|---|
| `phase_complete` | BBH | yes (carries `new_phase` field) |
| `bounded_self_correction` | S1 self-adjust | yes |
| `kernel_tick` | nucleus | only if no other state change in window (baseline) |

### 4.3 K_φ↓ events

| event_type | Source | Role |
|---|---|---|
| `s4-analysis` | S4 Qwen cycle output | denominator (decision) |
| `s5_decision` | S5 policy override | denominator (override) |
| `param_change` | γ.5 reload apply | numerator (application) |

### 4.4 τ pairing

For each `param_change` event, find the **most recent** `s4-analysis` OR `s5_decision` event from the same `system_id` within 60s lookback. τ = ts(param_change) − ts(s4-analysis).

If no antecedent within 60s, sample is censored (used in Kaplan-Meier).

---

## 5. Pass criteria (binding)

GATE_3 closes when ALL of:

1. ✓ Dataset meets §3 sample size targets (or PARTIAL with explicit gaps)
2. ✓ Markov matrix P estimated with N≥30 transitions
3. ✓ Stationary distribution π computed (left eigenvector check `‖πP − π‖ < 10⁻⁶`)
4. ✓ `K_total_worst < 0.8` with bootstrap 95% CI upper bound also < 0.8
5. ✓ `p99(τ) ≤ 30s` (Kaplan-Meier with right-censoring)
6. ✓ `max|G(jω)| < 0.8` with `(K_φ↑_worst, K_φ↓_worst, τ_p99)`
7. ✓ Report committed at `docs/operational/k_measurements/k_report_window2.md`
8. ✓ Raw data archived `docs/operational/k_measurements/raw/events-window2.jsonl.gz`

If `K_total_worst ∈ [0.8, 1.0)`: GATE_3 closes with **WARN** + rate limit tightening required before BBH-VSF goes live with autonomy.

If `K_total_worst ≥ 1.0`: GATE_3 **FAILS**. Loop is unstable. Halt integration, redesign rate limits, re-measure.

---

## 6. Phase plan (logical gates, no time estimates)

### Phase P (Plumbing) — VSF Rust

- **P.1** Wire `s4-analysis` to also emit events.jsonl (currently BBS-only)
- **P.2** Periodic `invariant_check` event sample emission (γ.6)
- **P.3** `param_change` event emit from `config.rs` reload (γ.5)
- **P.4** γ.9 new module `bbh_subscriber.rs`: subscribe NATS `bbh.>`, persist with `system_id="bbh"`, chain Merkle continuously
- **P.5** Documentation update: `connection_schema.json` v0.2.2 with all new event_types

Gate P closes when: `events.jsonl` shows ≥6 distinct event_types in 1h sample under no load.

### Phase D (Data generation) — joint BBH+VSF

- **D.1** BBH publisher implements NATS subjects `bbh.<inst>.phi_up.<event_type>` with `phase` field
- **D.2** BBH executes 1 full workflow (B0→B8) on 1 target → seeds dataset
- **D.3** Repeat D.2 with 2 additional targets (3 total) → inter-target variance
- **D.4** Synthetic injection: forced `signal_escalated` events via test harness → rare-event coverage
- **D.5** B5 parallel stress run (max_workers=4) on 1 target → peak K observation

Gate D closes when: §3 sample size targets met.

### Phase A (Analysis) — Python, after data ready

- **A.1** Point estimate K_total + bootstrap 95% CI (sanity check)
- **A.2** Estimate P transition matrix
- **A.3** Compute π via eigenvector
- **A.4** Compute K_φ↑(i), K_φ↓(i) per state with CI
- **A.5** Compute K_total_worst
- **A.6** Survival analysis for τ (Kaplan-Meier)
- **A.7** G(jω) verification with worst-case inputs
- **A.8** Sensitivity: perturb P_ij ±20%, recompute K_worst

Gate A closes = GATE_3 closes.

---

## 7. Tools committed

All scripts in `vsf/scripts/measurement/`:

| Script | Purpose | Status |
|---|---|---|
| `k_compute.py` | Naive K stats (A.1 sanity) | ✓ exists |
| `g_jw_verify.py` | G(jω) corrected Padé | ✓ exists |
| `markov_analysis.py` | A.2-A.5 Markov fit + worst-case | ⏳ scaffold this round |
| `tau_survival.py` | A.6 Kaplan-Meier | ⏳ this round |
| `sensitivity.py` | A.8 perturbation | ⏳ this round |

All pure stdlib + numpy + scipy. No ML/heavy deps.

---

## 8. Coordination with BBH and Qwen

### Required from BBH before D.* starts

- [ ] Confirm event_type names match BBH spec (§4.1)
- [ ] Confirm `phase` field semantics (BBH publisher must tag every event with current phase ∈ S)
- [ ] Approve §4 taxonomy
- [ ] Approve §5 pass criteria (incl. WARN/FAIL thresholds)
- [ ] Provide test target list for D.2/D.3

### Required from Qwen (optional but desirable)

- [ ] Review Markov model assumption (memorylessness justified?)
- [ ] Review sample size targets (§3)
- [ ] Review worst-case vs mean interpretation of covenant `max_loop_gain`

### VSF unilateral (this session)

- [x] Document this plan
- [ ] Implement P.3 (param_change emit)
- [ ] Implement P.4 (γ.9 bbh_subscriber)
- [ ] Scaffold markov_analysis.py + tau_survival.py with synthetic data
- [ ] Run synthetic-data round-trip to validate analysis pipeline

---

## 9. Risks declared upfront

| Risk | Mitigation |
|---|---|
| Markov assumption (memorylessness) violated | A.8 sensitivity + explicit semi-Markov flag in report |
| Dataset insufficient (BBH availability) | PARTIAL close with gap statement, refine in follow-up |
| Phase tagging inconsistent BBH↔VSF | §4.1 taxonomy review BEFORE D.1 |
| Rare event under-sampling (algedonic) | D.4 synthetic injection |
| `K_total_worst ≥ 0.8` actually | Then the covenant was wrong — escalate to rmw3 (S5) for retune. Not a measurement failure. |

---

## 10. References

- `k_measurement_protocol_2026-05-25.md` §3 (predecessor — measurement procedure)
- `core/connection_schema.json` v0.2.1 (event schema)
- `bbh/spec/bbh_vsf_protocol_v3.vsm` v3.1 (canonical channels)
- `bbh/docs/theory/mathematical_foundations.md` (G(s) form)
- Norris, J.R. *Markov Chains* (1997) — standard reference for §2.5 eigenvector method
- Kaplan, E.L. & Meier, P. (1958). "Nonparametric Estimation from Incomplete Observations" — for §A.6

---

## 11. Status

✓ Plan drafted
⏳ Awaiting BBH + Qwen review of §4 taxonomy, §5 criteria, §8 coordination items
⏳ VSF starting P.3, P.4, A.* scaffold in parallel
⏳ D.* on hold until P.* lands AND BBH approves taxonomy

**Sign-off when GATE_3 closes:** VSF + BBH + Qwen joint signature on `k_report_window2.md`.
