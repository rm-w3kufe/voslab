/// kernel.rs — RecursiveKernel (tick engine)
///
/// @vsm 0.3  S1(vsf-nucleus).tick_engine  @status=iterating
///
/// State machine:
///   GOVERNED → (tick) → GOVERNED | COMPLETE | HALTED
///                    ↘ (metamorphosis D4-L2) → SURVIVAL → GOVERNED | HALTED
///
/// VSL invariants enforced every tick:
///   trust > τ_L  ∧  entropy < ε_max  ∧  integrity > 0.0
///
/// D4 taxonomy:
///   L1: step_fn — state evolution, fully autonomous per tick
///   L2: metamorphosis class — S5 pre-authorized, fires automatically
///       spawn class — S5 pre-authorized, fires automatically
///   L3: policy change — never inside a kernel, always human-gated
///
/// Behavioral equivalence target: vsm-kernel/src/kernel.py RecursiveKernel

use serde_json::{json, Value};
use std::sync::Arc;

use crate::vsl::{self, VslSpec};
use crate::telemetry::TelemetryWriter;

// ── KernelMode ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum KernelMode {
    Governed,
    Complete,
    Halted,
    Survival,
}

impl std::fmt::Display for KernelMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            KernelMode::Governed => "GOVERNED",
            KernelMode::Complete => "COMPLETE",
            KernelMode::Halted   => "HALTED",
            KernelMode::Survival => "SURVIVAL",
        };
        write!(f, "{}", s)
    }
}

// ── KernelState ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize)]
pub struct KernelState {
    pub trust:            f64,
    pub entropy:          f64,
    pub integrity:        f64,
    pub autonomy:         f64,
    pub mode:             KernelMode,
    pub tick:             u32,
    pub complexity:       f64,
    pub result:           Option<Value>,
    pub policy_locked:    bool,
    pub active:           bool,
    /// Last VSL violations — used by parent to construct algedonic signal.
    #[serde(skip)]
    pub last_violations:  Vec<String>,
}

impl KernelState {
    pub fn initial(complexity: f64) -> Self {
        Self {
            trust: 1.0, entropy: 0.0, integrity: 1.0, autonomy: 0.5,
            mode: KernelMode::Governed,
            tick: 0, complexity,
            result: None, policy_locked: false, active: true,
            last_violations: Vec::new(),
        }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "autonomy":      self.autonomy,
            "trust":         self.trust,
            "entropy":       self.entropy,
            "integrity":     self.integrity,
            "mode":          self.mode.to_string(),
            "policy_locked": self.policy_locked,
            "complexity":    self.complexity,
            "result":        self.result,
            "active":        self.active,
            "tick":          self.tick,
        })
    }
}

// ── MetamorphosisClass ────────────────────────────────────────────────────────
/// D4-L2: S5-pre-authorized structural adaptation.
/// When trust falls below trigger_trust, the kernel relaxes its VSL spec.
/// Fires at most once per kernel lifetime.
///
/// Matches viability.yaml s5.d4_classes.survival_mode:
///   trigger: trust < 0.8  →  lower τ_L to 0.20
#[derive(Debug, Clone)]
pub struct MetamorphosisClass {
    pub id:                String,
    pub trigger_trust_lt:  f64,    // fire when state.trust < this
    pub new_vsl:           VslSpec,
    pub label:             String,
    executed:              bool,   // once per lifetime — A metamorphosis_per_lifetime=1
}

impl MetamorphosisClass {
    pub fn survival_mode() -> Self {
        Self {
            id:               "survival_mode".into(),
            trigger_trust_lt: 0.8,
            new_vsl:          VslSpec { tau_l: 0.20, ..Default::default() },
            label:            "survival_mode".into(),
            executed:         false,
        }
    }

    /// Returns Some(new_vsl) if the class should fire, None otherwise.
    pub fn should_fire(&self, trust: f64) -> Option<&VslSpec> {
        if !self.executed && trust < self.trigger_trust_lt {
            Some(&self.new_vsl)
        } else {
            None
        }
    }

    pub fn mark_executed(&mut self) { self.executed = true; }
    pub fn executed(&self) -> bool { self.executed }
}

// ── SpawnClass ────────────────────────────────────────────────────────────────
/// D4-L2: S5-pre-authorized recursive task decomposition.
#[derive(Debug, Clone)]
pub struct SpawnClass {
    pub spawn_n_min:   usize,
    pub spawn_n_max:   usize,
    pub threshold_min: f64,
    pub threshold_max: f64,
    pub child_vsl:     VslSpec,
}

impl Default for SpawnClass {
    fn default() -> Self {
        Self {
            spawn_n_min: 2, spawn_n_max: 4,
            threshold_min: 0.1, threshold_max: 0.5,
            child_vsl: VslSpec::default(),
        }
    }
}

// ── StepFn ────────────────────────────────────────────────────────────────────
pub type StepFn = Arc<dyn Fn(&KernelState) -> KernelState + Send + Sync>;

// ── RecursiveKernel ───────────────────────────────────────────────────────────

pub struct RecursiveKernel {
    pub name:         String,
    pub level:        u32,
    pub vsl:          VslSpec,
    pub state:        KernelState,
    pub step_fn:      StepFn,
    pub spawn_class:  Option<SpawnClass>,
    pub meta_classes: Vec<MetamorphosisClass>,
    pub children:     Vec<RecursiveKernel>,
    pub parent_name:  Option<String>,
    telem:            Arc<TelemetryWriter>,
}

impl RecursiveKernel {
    pub fn new(
        name: impl Into<String>,
        level: u32,
        vsl: VslSpec,
        complexity: f64,
        step_fn: StepFn,
        spawn_class: Option<SpawnClass>,
        telem: Arc<TelemetryWriter>,
    ) -> Self {
        Self {
            name: name.into(), level, vsl,
            state: KernelState::initial(complexity),
            step_fn, spawn_class,
            meta_classes: Vec::new(),
            children: Vec::new(),
            parent_name: None,
            telem,
        }
    }

    /// Pre-wire a child kernel (task K — parent-child wiring).
    /// Used to construct experiment trees before the first tick.
    /// Different from dynamic spawn (D4-L2): these children are structural, not computed.
    pub fn add_child(&mut self, mut child: RecursiveKernel) {
        child.parent_name = Some(self.name.clone());
        self.children.push(child);
    }

    /// Add a D4-L2 metamorphosis class (must be S5-authorized in viability.yaml).
    pub fn add_meta_class(&mut self, class: MetamorphosisClass) {
        self.meta_classes.push(class);
    }

    pub fn is_active(&self) -> bool { self.state.active }

    fn resource_health(&self) -> f64 {
        self.state.trust * (1.0 - self.state.entropy)
    }

    fn compute_spawn_n(&self, class: &SpawnClass) -> usize {
        let h = self.resource_health().clamp(0.0, 1.0);
        let n = class.spawn_n_min as f64 + h * (class.spawn_n_max - class.spawn_n_min) as f64;
        (n.round() as usize).clamp(class.spawn_n_min, class.spawn_n_max)
    }

    // ── tick ──────────────────────────────────────────────────────────────────
    /// Execute one tick.
    ///
    /// Order (matches Python kernel exactly):
    ///   1. D4-L2 spawn check (dynamic children only — structural children skip)
    ///   2. Tick children recursively (leaves first)
    ///   3. Absorb algedonic signals from halted children
    ///   4. D4-L2 metamorphosis check (before VSL — survival chance)
    ///   5. Apply step_fn (leaf only)
    ///   6. VSL check → halt or complete
    ///   7. Emit kernel_tick
    pub fn tick(&mut self) {
        if !self.state.active { return; }
        self.state.tick += 1;

        // 1. Dynamic spawn (only if no children at all — structural or dynamic)
        let did_spawn = self.maybe_spawn();

        // 2 + 3. Tick children, absorb algedonic
        let mut any_child_halted_this_tick = false;
        for child in &mut self.children {
            let was_active = child.is_active();
            child.tick();
            if was_active && child.state.mode == KernelMode::Halted {
                any_child_halted_this_tick = true;
                let trust_before = self.state.trust;
                self.state.trust = (self.state.trust - 0.2).max(0.0);
                let _ = self.telem.algedonic(
                    &child.name, &self.name,
                    trust_before, self.state.trust,
                    &child.state.last_violations,
                );
            }
        }

        // 4. D4-L2 metamorphosis check — before VSL so survival can save the kernel
        let mut did_metamorphose = false;
        for class in &mut self.meta_classes {
            if let Some(new_vsl) = class.should_fire(self.state.trust) {
                let old_tau = self.vsl.tau_l;
                self.vsl = new_vsl.clone();
                self.state.mode = KernelMode::Survival;
                self.state.policy_locked = true;
                did_metamorphose = true;
                let _ = self.telem.emit(&crate::telemetry::Event::new(
                    "kernel_metamorphosis", "ok",
                    json!({
                        "kernel":      self.name,
                        "level":       self.level,
                        "tick":        self.state.tick,
                        "class_id":    class.id,
                        "label":       class.label,
                        "old_tau_l":   old_tau,
                        "new_tau_l":   self.vsl.tau_l,
                        "trust":       self.state.trust,
                        "d4_level":    "L2_class_execution",
                        "authorized_by": "S5_viability_yaml",
                    }),
                ));
                class.mark_executed();
                break; // at most one metamorphosis per tick (one per lifetime enforced by executed flag)
            }
        }

        // 5. Step function — leaf kernels only (D4-L1: fully autonomous)
        let is_structural_leaf = self.children.is_empty() && self.spawn_class.is_none();
        let is_dynamic_leaf = self.children.is_empty() && !did_spawn;
        if is_structural_leaf || is_dynamic_leaf {
            let new_state = (self.step_fn)(&self.state);
            self.state.trust      = new_state.trust;
            self.state.entropy    = new_state.entropy;
            self.state.integrity  = new_state.integrity;
            self.state.autonomy   = new_state.autonomy;
            self.state.complexity = new_state.complexity;
            self.state.result     = new_state.result;
        }

        // 6. VSL check
        let vsl_result = vsl::check(&self.vsl, self.state.trust, self.state.entropy, self.state.integrity);
        match vsl_result {
            Ok(()) => {
                if self.state.mode == KernelMode::Survival {
                    // Survived the metamorphosis — stay in SURVIVAL until next tick upgrades
                    // (matches Python: survival mode allows continued operation)
                }
                let all_children_done = !self.children.is_empty()
                    && self.children.iter().all(|c| !c.is_active());
                let leaf_done = self.children.is_empty() && self.state.result.is_some();
                if all_children_done || leaf_done {
                    self.state.mode   = KernelMode::Complete;
                    self.state.active = false;
                } else if self.state.mode != KernelMode::Survival {
                    self.state.mode = KernelMode::Governed;
                }
            }
            Err(ref v) => {
                self.state.last_violations = v.violated.clone();
                self.state.mode   = KernelMode::Halted;
                self.state.active = false;
                let _ = self.telem.kernel_halt(
                    &self.name, self.level, self.state.tick,
                    self.state.trust, &v.violated,
                );
                return;
            }
        }

        // 7. Emit kernel_tick
        let _ = self.telem.kernel_tick(
            &self.name, self.level, self.state.tick,
            did_spawn, did_metamorphose,
            self.state.to_json(),
        );
    }

    // ── D4-L2 dynamic spawn ───────────────────────────────────────────────────
    fn maybe_spawn(&mut self) -> bool {
        if !self.children.is_empty() { return false; }
        let class = match self.spawn_class.clone() { Some(c) => c, None => return false };

        let threshold = class.threshold_min
            + self.resource_health() * (class.threshold_max - class.threshold_min);
        if self.state.complexity <= threshold { return false; }

        let spawn_n   = self.compute_spawn_n(&class);
        let child_cpx = (self.state.complexity / spawn_n as f64).clamp(0.0, 1.0);
        let mut child_names = Vec::new();

        for i in 0..spawn_n {
            let cname = format!("{}.c{}", self.name, i);
            child_names.push(cname.clone());
            let mut child = RecursiveKernel::new(
                cname, self.level + 1,
                class.child_vsl.clone(), child_cpx,
                Arc::clone(&self.step_fn),
                Some(class.clone()),
                Arc::clone(&self.telem),
            );
            child.parent_name = Some(self.name.clone());
            self.children.push(child);
        }

        let _ = self.telem.kernel_spawn(
            &self.name, self.level, self.state.tick, &child_names,
            spawn_n, self.state.complexity, child_cpx, self.resource_health(),
        );
        true
    }

    // ── Tree traversal ────────────────────────────────────────────────────────
    /// Post-order DFS — leaves first, root last (matches Python _collect_kernels).
    pub fn collect_all(&self) -> Vec<&RecursiveKernel> {
        let mut out = Vec::new();
        for child in &self.children { out.extend(child.collect_all()); }
        out.push(self);
        out
    }

    pub fn final_state_json(&self) -> Value { self.state.to_json() }
}
