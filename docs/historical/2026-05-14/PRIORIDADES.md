# ANÁLISIS DE PRIORIDADES — VSF Project 2026-05-14
## Dependencias Lógicas (IF/THEN ONLY — no estimaciones temporales)

**Estado total:** 43 tasks
- ✅ Completadas: 18
- 🔴 Abiertas: 16
- 🌱 Seeds: 6
- ⏸️ Deferred: 1

**Ramas exploradas:**
1. **VSF Core** (viability framework + recursive VSM)
2. **vOS Stage 1** (vsf-nucleus kernel, Rust implementation)
3. **vOS Stage 2** (BBH integration, S4 intelligence, Qwen as evaluator)
4. **Paper Cycle 1** (attractor_convergence v1.0 → v1.5 → v2.0, SUSPENDED)
5. **Paper Cycle 2** (Markov + Monte Carlo formalization)
6. **Security & Infrastructure** (Proxmox hardening, disclosure, audit)

---

## 📊 MATRIZ DE PRIORIDADES POR RAMA

### RAMA 1: VSF CORE + VIABILITY THEORY ⚙️

| Task | Status | Priority | Esfuerzo | Bloqueadores | Desbloquea |
|------|--------|----------|----------|--------------|-----------|
| **task(V)** Paper review calibration (D_KY→effective_dims, stasis_cos, alignment, Limitations) | 🔴 OPEN | 🔴 CRITICAL | 2-3h | — | Paper v1.0 submission |
| **task(P)** Tita collaboration: VSL math validation | 🔴 OPEN | 🟡 HIGH | TBD | — | Academic credibility |
| **task(O)** PSI protocol: Viable System Interface spec | 🔴 OPEN | 🟡 HIGH | TBD | task(F5.x.6) | Vendor-neutral standard |
| **task(T)** VSL v1.0: formal grammar + parser | ✅ DONE | 🟡 HIGH | ✅ | — | task(S), task(O), Beer community |
| **task(S)** Qwen VSL compilation (direct spec reading) | 🔴 OPEN | 🟡 HIGH | TBD | task(T) ✅ | Qwen S4 autonomy |
| **task(U)** VSL v2.0: intérprete (spec→run→eval→report) | 🔴 OPEN | 🟡 HIGH | TBD | task(T) ✅, task(S) | vOS Stage 2 |
| **task(R)** File format standardization (.vsm/.vsl/.vsf) | 🔴 OPEN | 🟢 LOW | 3-4h | — | Pre-work D10 v3 |
| **THEORY-COMP** docs/theory/composition_proof.vsm (Cor_1-4) | 🔴 OPEN | 🔴 CRITICAL | 3-4h | — | vOS Stage 2 foundation |
| **COVENANT-V04** covenant.vsm v0.4 (G1+G5 axioms) | 🔴 OPEN | 🟡 HIGH | 1-2h | THEORY-COMP | Recursive axioms |

---

### RAMA 2: vOS STAGE 1 — Rust Kernel Implementation 🦀

| Task | Status | Priority | Esfuerzo | Bloqueadores | Desbloquea |
|------|--------|----------|----------|--------------|-----------|
| **task(F5.x.1)** src/kernel/operator.rs (SplitOperator + SoftmaxMixing) | 🔴 OPEN | 🔴 CRITICAL | 3-5h | — | F5.x.2, F5.x.4 |
| **task(F5.x.2)** src/kernel/lyapunov.rs + formal proof | 🔴 OPEN | 🔴 CRITICAL | 6-9h | F5.x.1 | Governed definition |
| **task(F5.x.3)** src/adaptive_clock.rs (SeqLock + Δt adaptativity) | 🔴 OPEN | 🟡 HIGH | 3-4h | — | Parallel with F5.x.1 |
| **task(F5.x.4)** src/kernel/omega_validator.rs (Ω membership check) | 🔴 OPEN | 🟡 HIGH | 2-3h | F5.x.1 | Kernel validation |
| **task(F5.x.5)** src/topology/vr_complex.rs (persistent homology layer) | 🔴 OPEN | 🟡 HIGH | 5-7h | EXP-TDA-01 | TDA metrics |
| **task(F5.x.6)** src/kernel/coupling.rs (bilinear coupling, PSI handshake) | 🔴 OPEN | 🟡 HIGH | 4-6h | — | task(O) PSI protocol |
| **task(F5.x.7)** src/kernel/reframe.rs (staged reframing, recert epoch) | 🔴 OPEN | 🟡 HIGH | 3-4h | — | Double-loop corrections |
| **task(F5.x.8)** src/kernel/trust_axes.rs (4-axis trust model) | 🔴 OPEN | 🟢 MEDIUM | 2-3h + EXP | EXP-TRUST-01 | Trust composition |
| **task(F5.x.9)** src/hardware/ingest.rs (L+4 sensor layer) | 🔴 OPEN | 🟢 MEDIUM | 3-4h | — | Hardware metrics |

**Dependencia crítica:** F5.x.1 → F5.x.2 (bloqueante para "governed" certification)

---

### RAMA 3: vOS STAGE 2 — Intelligence + BBH Integration 🧠

| Task | Status | Priority | Esfuerzo | Bloqueadores | Desbloquea |
|------|--------|----------|----------|--------------|-----------|
| **task(S)** Qwen VSL compilation | 🔴 OPEN | 🟡 HIGH | TBD | task(T) ✅ | Qwen S4 operacional |
| **task(U)** VSL v2.0 intérprete | 🔴 OPEN | 🟡 HIGH | TBD | task(S) | Auto-experiment loop |
| **task(X)** vsf-indexer (semantic search) | ⏸️ DEFERRED | 🟡 HIGH | TBD | vOS Stage 2 | Self-querying system |
| **EXP-PHI-02** VSL grammar v2.0 fidelity test | 🌱 SEED | 🟡 HIGH | 4h (spec+run+analysis) | task(T) ✅ | Paper 2 empirics |

---

### RAMA 4: PAPER CYCLE 1 — attractor_convergence v1.0 → v1.5 → v2.0 📄

**🔴 CRITICAL STATUS: v1.0 SUSPENDED until experiments + Fierro feedback**

#### Phase 0: Response to Prof. Fierro (gate_A)
| Task | Status | Effort | Blocker | Unblocks |
|------|--------|--------|---------|----------|
| **V1-V6 Enmiendas** (rename D_KY, stasis_cos proxy, Limitations §11, etc.) | 🔴 OPEN | 1-2h | — | Paper submission readiness |
| **Send RESPUESTA_ITERACION_01_Qwen_VSL-MATH-01** to Prof. Fierro | 🔴 PENDING | <30min | — | gate_A (triggers experiments) |

#### Phase 1: Experimental Validation (gates B-E)
| Task | Status | Effort | Blocker | Unblocks |
|------|--------|--------|---------|----------|
| **EXP-LY-01** Lyapunov via Benettin (L measurement) | 🌱 SEED | 4-6h setup + 2h run | — | Contractividad proof |
| **EXP-JAC-01** Jacobiana analysis (L certification) | 🌱 SEED | 2-3h analysis | — | §4.2 data |
| **EXP-NC-01** S5 removal (negative control) | 🌱 SEED | 2-3h | EXP-LY-01, EXP-JAC-01 | Two-layer necessity |
| **EXP-NC-02** Trust freeze (negative control) | 🌱 SEED | 2-3h | EXP-LY-01, EXP-JAC-01 | — |
| **EXP-NC-03** S2 removal (negative control) | 🌱 SEED | 2-3h | EXP-LY-01, EXP-JAC-01 | — |
| **22 Graphics Artifacts** (14 new + 8 revision) | 🟡 DRAFT | TBD (IF/THEN logic) | Experiments data | Paper visualization |
| **§4 Integration** (new section: Ω, L, σ_max, theorem, validation) | 🔴 BLOCKED | 2-3h | Experiment data | main.pdf v1.5 |

#### Phase 2: Integration + Iteration (gate_D-E)
| Task | Status | Effort | Blocker | Unblocks |
|------|--------|--------|---------|----------|
| **FEEDBACK_PROF_FIERRO_RONDA1** analysis | 🔴 PENDING | TBD | Prof. Fierro response | ITERACION_02 |
| **main.pdf v1.5 compilation** (§4 + Fierro feedback + V1-V6) | 🔴 BLOCKED | 2-3h | Experiments + feedback | v2.0 decision |

#### Phase 3: Decision Point (gate_F)
| Task | Status | Decision | Outcome |
|------|--------|----------|---------|
| **Prof. Fierro approval?** | ⏳ PENDING | → YES | v2.0 final release |
| **Prof. Fierro suggests refinements?** | ⏳ PENDING | → NO → ITERACION_03 | Iteration 3 needed |

**Key metrics from ITERACION_01:**
- ✅ Ω is convex (5 gates verified)
- ✅ L ≈ 0.85 < 1 in Ω_A
- ✅ σ_max = 0.42, ε_frontier = 0.78, margin 1.86x
- ✅ Krasnoselskii + Lyapunov hybrid approach validated

---

### RAMA 5: PAPER CYCLE 2 — Markov + Monte Carlo Formalization 📚

| Task | Status | Priority | Esfuerzo | Bloqueadores | Desbloquea |
|------|--------|----------|----------|--------------|-----------|
| **task(AA)** Markov chain §Theory (Perron-Frobenius) | 🌱 SEED | 🟢 MEDIUM | 2h | Paper v1.5 ✅ | Stronger convergence proof |
| **task(AB)** EXP-MC-01 Monte Carlo basin volume | 🌱 SEED | 🟢 MEDIUM | 2h + 2h run | Paper v1.5 ✅ | Formal basin bound |
| **EXP-TDA-01** Persistent homology calibration | 🌱 SEED | 🟢 MEDIUM | 2-3h analysis + 1h | — | task(F5.x.5) unblock |

---

### RAMA 6: SECURITY + INFRASTRUCTURE 🔒

| Task | Status | Priority | Esfuerzo | Bloqueadores | Desbloquea |
|------|--------|----------|----------|--------------|-----------|
| **task(Y)** cargo --locked enforcement | 🔴 OPEN | 🔴 CRITICAL | 30min | — | Pre-deploy checklist |
| **task(Z)** Pre-deploy security checklist (Z1-Z7) | 🔴 OPEN | 🔴 CRITICAL | 1h | task(Y) | Public GitHub release |
| **SEC M5** cargo --locked in CI | Part of task(Y) | 🔴 CRITICAL | — | — | Supply chain security |
| **SEC M6** S3* binary integrity cron | 🔴 OPEN | 🟡 HIGH | 1h | — | Anomaly detection |
| **SEC M7** HMAC alert chain | 🔴 OPEN | 🔴 CRITICAL | 2h | — | S1 autonomous write access |
| **SEC M9** Two-axis trust (behavioral + structural) | 🔴 OPEN | 🟡 HIGH | 3h | — | Trust model completion |

---

## 🎯 TRES ESCENARIOS DE PRIORIZACIÓN

### ESCENARIO A: "Ship Paper v1.0 Fast" ⚡
**Objetivo:** Enviar paper a Prof. Fierro lo antes posible

**Orden crítico:**
1. ✅ task(V) — V1-V6 enmiendas (2-3h) → release v1.0
2. task(O) — PSI protocol (foundational for paper 2)
3. task(S) — Qwen VSL (S4 autonomy)
4. Pausar: F5.x.* (Rust), EXP-* (no bloqueadores)

**Ventaja:** v1.0 en manos de Fierro dentro de 1-2 días
**Riesgo:** Feedback extenso → ITERACION_03 larga

---

### ESCENARIO B: "Complete vOS Stage 1 First" 🏗️
**Objetivo:** Kernel Rust completo + theory proofs antes del paper final

**Orden crítico:**
1. task(F5.x.1) → task(F5.x.2) (operator + lyapunov, 6-9h)
2. task(F5.x.3) ∥ task(F5.x.4) (adaptive_clock + omega_validator, parallelizable)
3. THEORY-COMP (composition proofs, 3-4h)
4. COVENANT-V04 (axiom update, 1-2h)
5. task(V) — Paper enmiendas (1-2h)
6. Send paper to Fierro

**Ventaja:** Paper v1.5/v2.0 con kernel completo + rigor teórico maximal
**Riesgo:** Delay 2-3 semanas, Fierro espera feedback

---

### ESCENARIO C: "Parallel Tracks" (RECOMENDADO) 🚀
**Objetivo:** Maximizar velocidad sin sacrificar rigor

**Pista A (Rápida — Paper):**
- task(V) V1-V6 enmiendas (1-2h)
- task(O) PSI protocol spec (parallel with Rust)
- Send to Prof. Fierro (gate_A)
- EXP-LY-01 ∥ EXP-JAC-01 (experiments parallel)
- EXP-NC-01..03 (negative controls sequential)

**Pista B (Mediano — Rust Implementation):**
- task(F5.x.1) operator.rs (3-5h)
- task(F5.x.3) adaptive_clock.rs ∥ with F5.x.1 (3-4h parallel)
- task(F5.x.2) lyapunov.rs (blocks on F5.x.1, 6-9h)
- task(F5.x.4) omega_validator.rs (blocks on F5.x.1, 2-3h)

**Pista C (Soporte — Theory + Security):**
- THEORY-COMP composition proofs (3-4h)
- task(Y) + task(Z) security checklist (1.5h)
- COVENANT-V04 (1-2h)
- task(S) Qwen VSL (medium effort, parallel)

**Convergencia:** semana 1 paper enviado + semana 2 kernel Stage 1 + theory locked

---

## 📈 DEPENDENCIAS CRÍTICAS (Blocking Chains)

### Chain 1: Paper Submission
```
task(V) enmiendas
    ↓ (1-2h)
Send to Fierro (gate_A)
    ↓
EXP-LY-01 ∥ EXP-JAC-01 (parallel)
    ↓ (data ready)
EXP-NC-01..03 (sequential)
    ↓ (all experiments complete)
§4 integration + graphics
    ↓ (3-4h writing + rendering)
main.pdf v1.5
    ↓ (wait for Fierro feedback)
gate_D: ITERACION_02 or gate_F: v2.0 decision
```

### Chain 2: Kernel Implementation
```
task(F5.x.1) operator.rs
    ├→ task(F5.x.2) lyapunov.rs (CRITICAL blocker)
    ├→ task(F5.x.4) omega_validator.rs
    └→ THEORY-COMP composition proofs (parallel)
        ↓
COVENANT-V04 (update axioms)
    ↓
vOS Stage 1 complete
```

### Chain 3: S4 Intelligence
```
task(T) VSL v1.0 ✅ DONE
    ↓
task(S) Qwen VSL compilation
    ↓
task(U) VSL v2.0 interpreter
    ↓
task(X) vsf-indexer (when Stage 2 deploys)
    ↓
vOS Stage 2 operational
```

### Chain 4: Security Certification
```
task(Y) cargo --locked
    ↓
task(Z) pre-deploy checklist
    ├→ SEC M5 cargo enforcement
    ├→ SEC M7 HMAC alert chain
    └→ SEC M9 two-axis trust
    ↓
GitHub public release ready
```

---

## 🎲 RECOMENDACIÓN FINAL

**Adoptar ESCENARIO C (Parallel Tracks)** porque:

1. **Velocidad:** Paper Fierro en 1-2 días (task V)
2. **Rigor:** Kernel Stage 1 en paralelo (F5.x.1-4 + THEORY)
3. **Flexibilidad:** Si Fierro feedback es extenso → iteración sin bloquear kernel
4. **Impacto:** Múltiples ramas avanzan simultáneamente
5. **Risk management:** Critical paths (F5.x.1→F5.x.2, paper→experiments) bien separadas

**Orden de inicio recomendado:**
```
DÍA 1:
  [ ] task(V) — V1-V6 enmiendas (2-3h, rdm3 autoriza)
  [ ] task(F5.x.1) — operator.rs kick-off (3-5h)
  [ ] task(O) — PSI protocol (concurrent)

DÍA 2:
  [ ] Send paper to Prof. Fierro (gate_A)
  [ ] task(F5.x.2) lyapunov.rs (awaits F5.x.1 completion)
  [ ] task(F5.x.3) adaptive_clock.rs ∥ F5.x.1 (parallelizable)
  [ ] THEORY-COMP proofs (3-4h)

SEMANA 1:
  [ ] EXP-LY-01 ∥ EXP-JAC-01 experiments
  [ ] task(F5.x.4) omega_validator
  [ ] task(Y) + task(Z) security checklist

SEMANA 2:
  [ ] EXP-NC-01..03 negative controls
  [ ] §4 integration if experiments complete
  [ ] Await Prof. Fierro feedback
  [ ] F5.x.5 (TDA, blocked on EXP-TDA-01)
```

---

## 📋 OPEN QUESTIONS FOR rmw3

1. **Paper primero o kernel primero?** (Escenario recomendado = paralelo)
2. **Timeout esperado para feedback de Fierro?** (estimación actual: 10-21 días)
3. **Si Fierro pide ITERACION_03:** ¿cuántos refinamientos se toleran antes de v2.0 "final"?
4. **vOS Stage 2 timeline:** ¿después que paper v2.0 sea final, o en paralelo?
5. **Security baseline:** ¿task(Y/Z) completar ANTES de cualquier público release?

