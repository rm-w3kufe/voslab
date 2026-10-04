# ANÁLISIS DE PRIORIDADES — VSF Project 2026-05-14
## Pure Dependency Logic (IF/THEN ONLY)

---

## 📊 ESTADO ACTUAL

**43 tasks inventariadas:**
- ✅ Completadas: 18
- 🔴 Abiertas: 16
- 🌱 Seeds: 6
- ⏸️ Deferred: 1

---

## 🔗 GRAFO DE DEPENDENCIAS — Todas las Ramas

### RAMA 1: VSF CORE + VIABILITY THEORY

```
task(T) VSL v1.0 grammar + parser
  ✓ DONE (2026-04-18)
  ├─→ unblocks task(S)
  ├─→ unblocks task(O)
  └─→ unblocks comunidad_Beer

task(S) Qwen VSL compilation
  🔴 OPEN
  ├─ blockers: task(T) ✓
  └─→ unblocks: task(U)

task(U) VSL v2.0 intérprete
  🔴 OPEN
  ├─ blockers: task(S)
  └─→ unblocks: task(X)

task(X) vsf-indexer (semantic search)
  ⏸️ DEFERRED until vOS Stage 2
  ├─ blockers: task(S) ∧ vos_stage_2
  └─→ unblocks: self-querying system

task(O) PSI protocol spec
  🔴 OPEN
  ├─ blockers: task(F5.x.6) [coupling.rs]
  └─→ unblocks: vendor-neutral standard

task(P) Tita math validation
  🔴 OPEN
  ├─ blockers: (none)
  └─→ unblocks: academic credibility

task(R) File format std (.vsm/.vsl/.vsf)
  🔴 OPEN (low priority)
  ├─ blockers: (none)
  └─→ unblocks: D10 v3 (interpreter)

THEORY-COMP composition proofs
  🔴 OPEN
  ├─ blockers: (none)
  └─→ unblocks: COVENANT-V04

COVENANT-V04 covenant.vsm v0.4
  🔴 OPEN
  ├─ blockers: THEORY-COMP
  └─→ unblocks: Recursive axioms finalized
```

---

### RAMA 2: vOS STAGE 1 — Rust Kernel (9 modules)

```
task(F5.x.1) operator.rs [SplitOperator + SoftmaxMixing]
  🔴 OPEN
  ├─ blockers: (NONE — can start immediately)
  ├─→ unblocks: task(F5.x.2)
  ├─→ unblocks: task(F5.x.4)
  └─→ CRITICAL: blocks kernel baseline

task(F5.x.2) lyapunov.rs [proof + runtime]
  🔴 OPEN
  ├─ blockers: task(F5.x.1) ✓
  └─→ unblocks: governed definition locked

task(F5.x.3) adaptive_clock.rs [SeqLock + Δt]
  🔴 OPEN
  ├─ blockers: (none)
  └─→ can run PARALLEL with F5.x.1

task(F5.x.4) omega_validator.rs [Ω membership]
  🔴 OPEN
  ├─ blockers: task(F5.x.1) ✓
  └─→ unblocks: Kernel validation

task(F5.x.5) vr_complex.rs [TDA layer]
  🔴 OPEN
  ├─ blockers: EXP-TDA-01 [ε-range calibration]
  └─→ unblocks: Topological metrics

task(F5.x.6) coupling.rs [ψ bilinear]
  🔴 OPEN
  ├─ blockers: (none)
  └─→ unblocks: task(O) PSI protocol

task(F5.x.7) reframe.rs [staged reframing]
  🔴 OPEN
  ├─ blockers: (none)
  └─→ unblocks: Double-loop corrections

task(F5.x.8) trust_axes.rs [4-axis trust]
  🔴 OPEN
  ├─ blockers: EXP-TRUST-01 [calibration data]
  └─→ unblocks: Trust model operational

task(F5.x.9) ingest.rs [L+4 sensor layer]
  🔴 OPEN
  ├─ blockers: (none)
  └─→ unblocks: Hardware metrics

vOS Stage 1 Baseline:
  ✓ IF task(F5.x.1) ∧ task(F5.x.2) ∧ task(F5.x.3) ∧ task(F5.x.4)
  ✓ AND THEORY-COMP ✓
  ✓ THEN vOS Stage 1 kernel baseline ready
```

---

### RAMA 3: PAPER CYCLE 1 — attractor_convergence (v1.0 → v1.5 → v2.0)

```
Paper v1.0 BASELINE:
  ✓ DONE (2026-05-13)
  ├─ content: 37pp EN, 38pp ES, 11 experiments locked
  ├─ status: SUSPENDED (not released, awaiting Fierro feedback)
  └─→ unblocks: task(V) enmiendas

task(V) Paper V1-V6 calibration:
  🔴 OPEN
  ├─ blockers: (none)
  └─→ THEN IF ✓ THEN gate_A1: send to Fierro

gate_A1 Send to Prof. Fierro:
  🔴 PENDING
  ├─ blockers: task(V) ✓
  ├─→ THEN spawn experiments (gate_B_0)
  └─→ THEN trigger PHASE 1.5 (wait for feedback)

EXP-LY-01 Lyapunov Benettin:
  🌱 SEED
  ├─ blockers: gate_A1 ✓
  ├─ can run PARALLEL: with EXP-JAC-01
  └─→ unblocks: §4.2 (L measurement)

EXP-JAC-01 Jacobiana analysis:
  🌱 SEED
  ├─ blockers: gate_A1 ✓
  ├─ can run PARALLEL: with EXP-LY-01
  └─→ unblocks: §4.2 (L certification)

EXP-NC-01 S5 removal:
  🌱 SEED
  ├─ blockers: EXP-LY-01 ∧ EXP-JAC-01 (data needed)
  └─→ unblocks: Negative control 1

EXP-NC-02 Trust freeze:
  🌱 SEED
  ├─ blockers: EXP-LY-01 ∧ EXP-JAC-01 (data needed)
  └─→ unblocks: Negative control 2

EXP-NC-03 S2 removal:
  🌱 SEED
  ├─ blockers: EXP-LY-01 ∧ EXP-JAC-01 (data needed)
  └─→ unblocks: Negative control 3

Graphics (22 artefactos):
  🟡 DRAFT
  ├─ blockers: EXP-LY-01 ∧ EXP-JAC-01 ∧ EXP-NC-01/02/03 (all data)
  └─→ unblocks: main.pdf v1.5 compilation

Paper v1.5 Integration:
  🔴 BLOCKED
  ├─ blockers: EXP-LY-01 ∧ EXP-JAC-01 ∧ EXP-NC-01/02/03 (data)
  ├─ blockers: Graphics ✓
  ├─ blockers: Prof. Fierro feedback (IF available)
  └─→ THEN: main.pdf v1.5 ready

gate_F1 Prof. Fierro Verdict:
  ⏳ CONDITIONAL WAIT
  ├─ blockers: main.pdf v1.5 ✓
  ├─ outcomes:
  │   ├─ outcome_A: "v2.0 ready" → PHASE 4
  │   └─ outcome_B: "ITERACION_03 needed" → refinement loop
  └─→ depends on: Prof. Fierro review (not controlled by rmw3)

Paper v2.0 Final:
  🔴 CONDITIONAL
  ├─ blockers: gate_F1 ∧ outcome_A ✓
  └─→ unblocks: v2.0 release + distribution
```

---

### RAMA 4: PAPER CYCLE 2 — Markov + Monte Carlo

```
task(AA) Markov chain §Theory:
  🌱 SEED
  ├─ blockers: Paper v1.5 ✓
  └─→ unblocks: Stronger convergence proof

task(AB) EXP-MC-01 Monte Carlo basin:
  🌱 SEED
  ├─ blockers: Paper v1.5 ✓
  └─→ unblocks: Formal basin bound

EXP-TDA-01 Persistent homology:
  🌱 SEED
  ├─ blockers: (none)
  └─→ unblocks: task(F5.x.5) vr_complex.rs

EXP-PHI-02 VSL v2.0 fidelity:
  🌱 SEED
  ├─ blockers: task(T) ✓ (parser ready)
  └─→ unblocks: Paper 2 §3 empirics
```

---

### RAMA 5: SECURITY + INFRASTRUCTURE

```
task(Y) cargo --locked enforcement:
  🔴 OPEN
  ├─ blockers: (NONE)
  └─→ unblocks: task(Z)

task(Z) Pre-deploy security checklist:
  🔴 OPEN
  ├─ blockers: task(Y) ✓
  ├─→ unblocks: SEC-M5, SEC-M6, SEC-M7
  └─→ unblocks: GitHub public release gate

SEC M5, M6, M7, M9:
  🔴 OPEN (various)
  ├─ blockers: task(Z) ✓
  └─→ unblocks: Production deployment
```

---

## 🎯 TRES ESCENARIOS DE PRIORIZACIÓN

### ESCENARIO A: Paper First
```
task(V) → gate_A1 ✓
  → EXP-LY-01 ∥ EXP-JAC-01
  → EXP-NC-01/02/03
  → Graphics
  → main.pdf v1.5
  → gate_F1 (Fierro verdict)
  
PARALLEL (no dependency on A):
  F5.x.1-9 (kernel)
  THEORY-COMP
  task(O/S/U)

RESULT: Paper to Fierro ASAP, kernel development independent
RISK: If Fierro feedback extensive → ITERACION_03 delays v2.0
```

### ESCENARIO B: Kernel First
```
F5.x.1 → F5.x.2 ✓ (blocker resolved)
  → F5.x.3 ∥ F5.x.4 ∥ F5.x.5-9
  → vOS Stage 1 baseline ready
  
PARALLEL (no dependency on kernel):
  task(V) → gate_A1 ✓
  → experiments → main.pdf v1.5
  
RESULT: Kernel stable BEFORE paper final version
RISK: Paper submission delayed while kernel locks
```

### ESCENARIO C: Parallel Tracks ⭐ RECOMENDADO
```
PISTA A — PAPER:
  task(V) ∅ → gate_A1 ✓
    → EXP-LY-01 ∥ EXP-JAC-01
    → EXP-NC-01/02/03
    → Graphics → main.pdf v1.5
    → gate_F1

PISTA B — KERNEL:
  F5.x.1 ∅ → F5.x.2 ✓
    → [F5.x.3 ∥ F5.x.4] ∥ [F5.x.5-9]
    → vOS Stage 1 baseline

PISTA C — SUPPORT:
  THEORY-COMP ∅ → COVENANT-V04 ✓
  task(Y) ∅ → task(Z) ✓
  task(O/S/U)

DEPENDENCIES: A, B, C are INDEPENDENT
  → Maximum parallelization
  → If paper Fierro feedback delayed → kernel continues
  → If kernel F5.x.2 delayed → paper experiments continue

RESULT: 2-3 branches progress simultaneously without blocking each other
```

---

## ✓ CRITICAL BLOCKING CHAINS

### Chain 1: Paper Release (Fierro)
```
task(V) → gate_A1 → EXP-LY-01 ∧ EXP-JAC-01 → EXP-NC-01/02/03 → Graphics → main.pdf v1.5 → gate_F1

Blocking rule: 
  IF ¬(task(V)) THEN ¬(gate_A1)
  IF ¬(EXP-LY-01 ∧ EXP-JAC-01) THEN ¬(EXP-NC-*)
  IF ¬(all experiments ∧ graphics) THEN ¬(main.pdf v1.5)
  IF ¬(main.pdf v1.5) THEN ¬(gate_F1)
```

### Chain 2: Kernel Stage 1
```
F5.x.1 → F5.x.2
  ∧ (F5.x.3 ∥ with F5.x.1)
  ∧ (F5.x.4 depends on F5.x.1)
  → vOS Stage 1 baseline ✓

Blocking rule:
  IF ¬(F5.x.1) THEN ¬(F5.x.2) ∧ ¬(F5.x.4)
  IF ¬(F5.x.1 ∧ F5.x.2 ∧ F5.x.3 ∧ F5.x.4) THEN ¬(vOS Stage 1 baseline)
```

### Chain 3: S4 Autonomy
```
task(T) ✓ → task(S) → task(U) → task(X)

Blocking rule:
  task(T) ✓ (already satisfied)
  IF ¬(task(S)) THEN ¬(task(U))
  IF ¬(task(U)) THEN ¬(task(X))
```

### Chain 4: Security Gate
```
task(Y) → task(Z) → [SEC-M5 ∧ SEC-M6 ∧ SEC-M7]

Blocking rule:
  IF ¬(task(Y)) THEN ¬(task(Z))
  IF ¬(task(Z)) THEN ¬(GitHub public release)
```

---

## 📋 TABLA: BLOCKERS + UNBLOCKS

| Task | Status | Blocker | Unblocks | Independent? |
|------|--------|---------|----------|--------------|
| task(V) | 🔴 OPEN | — | gate_A1 | ✓ YES |
| gate_A1 | 🔴 PENDING | task(V) ✓ | experiments | depends |
| EXP-LY-01 | 🌱 SEED | gate_A1 ✓ | §4 data | depends |
| EXP-JAC-01 | 🌱 SEED | gate_A1 ✓ | §4 data | depends |
| EXP-NC-01/02/03 | 🌱 SEED | EXP-LY-01 ∧ JAC | §4 data | depends |
| Graphics | 🟡 DRAFT | all exp ✓ | main.pdf v1.5 | depends |
| main.pdf v1.5 | 🔴 BLOCKED | graphics ∧ feedback | gate_F1 | depends |
| gate_F1 | ⏳ WAIT | main.pdf v1.5 ✓ | v2.0 OR ITER03 | depends |
| **F5.x.1** | 🔴 OPEN | — | F5.x.2/4 | ✓ YES |
| F5.x.2 | 🔴 OPEN | F5.x.1 ✓ | Stage 1 | depends |
| F5.x.3 | 🔴 OPEN | — | Clock ready | ✓ YES |
| F5.x.4 | 🔴 OPEN | F5.x.1 ✓ | Validator | depends |
| F5.x.5-9 | 🔴 OPEN | EXP-TDA/TRUST | remainder | depends |
| **THEORY-COMP** | 🔴 OPEN | — | COVENANT-V04 | ✓ YES |
| COVENANT-V04 | 🔴 OPEN | THEORY ✓ | axioms locked | depends |
| **task(Y)** | 🔴 OPEN | — | task(Z) | ✓ YES |
| task(Z) | 🔴 OPEN | task(Y) ✓ | SEC gates | depends |
| **task(O)** | 🔴 OPEN | F5.x.6 ✓ | PSI protocol | depends |
| **task(S)** | 🔴 OPEN | task(T) ✓ | task(U) | depends |
| task(U) | 🔴 OPEN | task(S) ✓ | task(X) | depends |
| task(X) | ⏸️ DEFERRED | task(S) ∧ Stage2 | indexing | depends |

---

## 🚀 RECOMENDACIÓN FINAL

**ESCENARIO C (Parallel Tracks)** porque:

1. ✓ task(V) tiene **blocker: NONE** → inicia inmediatamente
2. ✓ F5.x.1 tiene **blocker: NONE** → inicia inmediatamente  
3. ✓ THEORY-COMP tiene **blocker: NONE** → inicia inmediatamente
4. ✓ Tres pistas INDEPENDIENTES sin acoplamiento
5. ✓ Si paper Fierro feedback demora → kernel progresa
6. ✓ Si kernel F5.x.2 demora → paper experiments continúan

**Next action:** 
```
IF user_approves(Escenario C) THEN:
  start task(V) NOW
  start F5.x.1 NOW
  start THEORY-COMP NOW
```

**No temporal estimates.** Solo lógica de dependencias.
