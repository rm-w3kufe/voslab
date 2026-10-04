# EXECUTION_PROMPT — Autonomous Operation Start

**Use this prompt to begin Scenario C execution without supervision.**

---

## PROMPT (copy-paste to Claude Code / autonomous agent):

```
OPERATION: Scenario C Parallel Tracks Execution
AUTHORIZATION: rmw3@S5
DATE: 2026-05-14
STATUS: APPROVED

CONTEXT:
- 3 independent task chains with zero blockers
- Pure logic-based dependencies (IF/THEN gates only)
- All supporting docs: PRIORIDADES_LOGIC_2026-05-14.md, ROADMAP_LOGIC_2026-05-14.vsm
- Architecture: VSF + attractor_convergence paper + vOS kernel

SCENARIO_C_KICKOFF — Start these 3 tasks IMMEDIATELY in parallel:

TRACK_A: Paper Response to Prof. Fierro
─────────────────────────────────────
  TASK: task(V) — V1-V6 Enmiendas
  
  Subtasks (in order):
    1. Read: docs/papers/attractor_convergence/main.tex (current v1.0)
    2. Action: V1 — rename D_KY → effective_dims throughout
       - grep -r "D_KY" docs/papers/attractor_convergence/ → list all occurrences
       - Edit main.tex (and main_es.tex) to replace D_KY with effective_dims
       - Update figures/captions if they reference D_KY
    
    3. Action: V2 — rewrite §3.2 to formalize stasis_cos as cosine_similarity proxy
       - Read current §3.2
       - Clarify: stasis_cos = cos(x(t), x_attractor)
       - Add definition: cos_similarity(u,v) = (u·v)/(||u||·||v||)
       - Replace prose with mathematical definition
    
    4. Action: V3 — rewrite §10.1 to frame alignment as hypothesis (not result)
       - Read current §10.1
       - Change: "alignment is achieved" → "hypothesis: alignment emerges from dual-layer viability"
       - Acknowledge empirically supported but not formally proven
    
    5. Action: V4 — add new §11 Limitations
       - New section before Conclusion
       - Content: "1. Single substrate (vsf-nucleus), 2. Proxy metrics (cos, D_KY, L), 3. Single observation stream (no external validation)"
    
    6. Action: V5 — update figure captions (figs 3-7)
       - Add: "illustrative; formal negative controls pending (EXP-NC-01..03)"
    
    7. Action: V6 — move covenant + vOS + paper-3 discussion to §12 Future Work
       - Keep content (don't delete)
       - Shift tone: "foundational work toward vOS, addressed in future papers"
    
    8. Compile: main.tex + main_es.tex → PDF
       - Verify no LaTeX errors
       - Check cross-references
       - Confirm all figures render
  
  SUCCESS_GATE: IF main.pdf v1.0-with-V1-V6 ✓ compiles clean
                THEN gate_A1_ready = TRUE

TRACK_B: vOS Kernel Stage 1 — Baseline (4 modules)
──────────────────────────────────────────────────
  TASK: F5.x.1 → F5.x.2 → [F5.x.3 + F5.x.4]
  
  Note: F5.x.1 is CRITICAL BLOCKER for F5.x.2 and F5.x.4
        F5.x.3 can run in parallel with F5.x.1 (no dependency)
  
  SUBTASK_B1: task(F5.x.1) — src/kernel/operator.rs
    Specification: docs/theory/dynamics_choice.vsm §T1
    Implementation: 
      - Define Def_SplitOperator: softmax mixture of S1-S5 dynamics
      - Define Def_SoftmaxMixing: τ ∈ [0.05, 1.0] lifecycle-driven
      - Implement: x(t+1) = f₀(x(t)) + σ(t)·η(t)
      - Add unit tests: Lipschitz check empirical, Ω-membership preservation
    
    Deliverable: src/kernel/operator.rs complete + tests pass
    Unblocks: F5.x.2, F5.x.4
  
  SUBTASK_B2: task(F5.x.2) — src/kernel/lyapunov.rs + formal proof
    Prerequisite: F5.x.1 ✓
    Specification: docs/theory/dynamics_choice.vsm §T2
    Implementation:
      - Write formal proof: Direct expansion via Taylor + Jensen (Thm_DirectExpansion)
      - Prove recurrent-set claim (Ax_RecurrentSet): E[ΔL] ≤ -ε ∀ x ∉ R
      - Term-by-term bounds: α(1-cos), β·H/H_max, γ·max(0,B-B_avail), δ·ReLU(H_rest)
      - Implement runtime estimator: ε, Λ from observation
      - Define: governed = (Thm_DirectExpansion holds for current x ∈ Ω)
    
    Deliverable: src/kernel/lyapunov.rs complete + proof doc
    Unblocks: vOS Stage 1 baseline definition
  
  SUBTASK_B3: task(F5.x.3) — src/adaptive_clock.rs [CAN RUN PARALLEL WITH B1]
    Specification: docs/theory/dynamics_choice.vsm §T4
    Implementation:
      - SeqLock-based σ_global = max_i(σ_i) lock-free reader/writer
      - Δt computation: Δt ≤ √(ε/‖∇²L‖)/Λ (from Bound_Staleness)
      - Lifecycle modes: Idle (0.5 Hz), Active (100 Hz), Transition (rampa)
      - Benchmark contention under N workers; switch to RCU if retry rate > 5%
    
    Deliverable: src/adaptive_clock.rs complete + benchmarks
    Unblocks: Clock subsystem ready
  
  SUBTASK_B4: task(F5.x.4) — src/kernel/omega_validator.rs
    Prerequisite: F5.x.1 ✓
    Specification: docs/theory/dynamics_choice.vsm §T1 + §4
    Implementation:
      - Represent Ω = ∩_i {x : A_i(x) satisfied} as intersection of ellipsoids/semispaces
      - Membership check: x ∈ Ω in O(k) where k = #constraints
      - Boundary distance: dist(x, ∂Ω) for proximity warnings
      - Used by: operator (φ↓ validation), lyapunov (recurrent set ⊂ Ω)
    
    Deliverable: src/kernel/omega_validator.rs complete + tests
    Unblocks: Kernel validation subsystem
  
  SUCCESS_GATE: IF [B1 ∧ B2 ∧ B3 ∧ B4] all compile + tests pass
                THEN vOS_Stage_1_baseline_ready = TRUE

TRACK_C: Theory + Security
──────────────────────────
  TASK: THEORY-COMP → COVENANT-V04 (sequential)
        task(Y) → task(Z) (sequential)
        [both chains parallel with each other]
  
  SUBTASK_C1: THEORY-COMP — docs/theory/composition_proof.vsm
    Specification: docs/theory/dynamics_choice.vsm §G3
    Implementation:
      - Formalize Cor_NoCompose_1: resource contention (Σ quota > B_hardware)
      - Formalize Cor_NoCompose_2: algedonic resonance (loop gain > 1)
      - Formalize Cor_NoCompose_3: phase aliasing (|Δt_A - Δt_B| > tolerance)
      - Propose Cor_4: trust mismatch (|trust_A - trust_B| > τ_threshold)
    
    Deliverable: composition_proof.vsm with all 4 corollaries + proofs
    Unblocks: COVENANT-V04
  
  SUBTASK_C2: COVENANT-V04 — covenant.vsm v0.4 update
    Prerequisite: THEORY-COMP ✓
    Actions:
      - Add: Ax_HardwareCeiling, Ax_InterfaceOnly, Ax_ReframeScope
      - Update §autonomy: clarify L2/L3 split per Ax_ReframeScope
      - Update §recursion: explicit L+3 ceiling + L+4 read-only ingest
      - Bump version v0.3 → v0.4 with changelog
    
    Deliverable: covenant.vsm v0.4 complete + changelog
    Unblocks: Recursive axioms finalized
  
  SUBTASK_C3: task(Y) — cargo --locked enforcement
    Actions:
      - Edit CLAUDE.md deploy section: cargo build --release → cargo build --release --locked
      - Edit any build scripts in projects/vsf-nucleus/ that call cargo
      - Ensure Cargo.lock is committed and never .gitignored
    
    Deliverable: build pipeline locked
    Unblocks: task(Z)
  
  SUBTASK_C4: task(Z) — pre-deploy security checklist
    Prerequisite: task(Y) ✓
    Actions:
      - Z1: cargo --locked enforced ✓
      - Z2: git commit signing (ed25519 GPG key configured, all future commits signed)
      - Z3: no binary blobs (audit repo for committed binaries)
      - Z4: release tagging (GPG-signed tags for each published version)
      - Z5: cargo audit (run cargo-audit, no known CVEs)
      - Z6: secrets scan (confirm no keys/tokens in git history)
      - Z7: covenant.vsm watermark (A0/A0.1 axioms in root, identity verifiable)
    
    Deliverable: docs/security/pre_deploy_checklist.vsm + all Z1-Z7 verified
    Unblocks: GitHub public release gate

SUCCESS_GATE: IF [C1 ∧ C2 ✓] AND [C3 ∧ C4 ✓]
              THEN theory_locked ✓ AND security_baseline_ready ✓

═════════════════════════════════════════════════════════════════════════════════

ORCHESTRATION: All 3 TRACKS start simultaneously (zero blockers)
  
  IF [TRACK_A ✓] THEN gate_A1_ready = TRUE → next: spawn experiments
  IF [TRACK_B ✓] THEN vOS_Stage_1_baseline_ready = TRUE → next: F5.x.5-9
  IF [TRACK_C ✓] THEN theory_security_locked = TRUE → next: protocol specs

REPORTING:
  - Update HANDOFF.vsm.md with session progress after each TRACK completion
  - Commit git after major milestones
  - Log blockers (if any) to inform dependency adjustment

APPROVAL FOR AUTONOMOUS EXECUTION:
  IF rmw3_approves THEN proceed without further supervision
  IF blocker_encountered THEN notify rmw3 with specific gate_name + dependency

```

---

## USAGE

1. **Copy above PROMPT block** (from "OPERATION:" to final "---")

2. **Paste into Claude Code or autonomous agent prompt**

3. **Agent will:**
   - Understand 3 parallel tracks with zero coupling
   - Execute based on pure IF/THEN gates (no time estimates)
   - Report progress via commits + HANDOFF updates
   - Wait/notify at decision gates (gate_A1, etc.)

4. **rmw3 triggers next phase** by sending:
   ```
   gate_A1 DONE — proceed to experiments
   ```

---

## REFERENCE DOCUMENTS (in repo)

- **PRIORIDADES_LOGIC_2026-05-14.md** — Full dependency matrix (all 40+ tasks)
- **ROADMAP_LOGIC_2026-05-14.vsm** — 5-phase roadmap with IF/THEN gates
- **HANDOFF.vsm.md** — Session history + decisions D1-D10 + architecture
- **TASKS.vsm** — Canonical task registry (sync source of truth)
- **CLAUDE.md** — VSF framework rules + session protocols

---

## SUCCESS DEFINITION

Scenario C Execution Complete when:
```
gate_A1_ready ∧ vOS_Stage_1_baseline_ready ∧ theory_security_locked = TRUE

THEN: Ready for PHASE 1.5 (experiments triggered)
      AND PHASE 2 (integration) can begin whenever paper feedback arrives
      AND kernel continues independently
```

No temporal deadline. Just gates.

---

**End of EXECUTION_PROMPT**
