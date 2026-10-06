// learned_modes.rs — EXP-MODES-01: learned prototypes under the Ω-guard
//
// See: docs/experiments/EXP-MODES-01/spec.vsm
//
// Three components:
//   1. ModesLearner — learning loop + Ω guard + metrics
//   2. Snapshot writer — hourly dump of μ_s to JSON
//   3. Freeze detector — λ_max monitoring
//
// Watermark: ⟦ vsf-nucleus | vsf-s1-executor | exp-modes-01 ⟧

use crate::operator::{SplitOperator, N_MODES};
use crate::omega_validator::Omega;
use crate::state_vector::*;
use serde_json::json;
use std::fs;
use std::path::PathBuf;

// ─── PROTOTYPE UPDATE ─────────────────────────────────────────────────────────

/// Proposed update to one mode center based on visited state and mixing weight.
/// Uses a softmax-weighted SOM rule: μ_s += lr · w_s · (x - μ_s)
fn propose_mode_update(
    mu_s: &StateVector,
    state: &StateVector,
    weight_s: f64,
    lr: f64,
) -> StateVector {
    let mut updated = mu_s.clone();
    let alpha = lr * weight_s; // learning rate weighted by softmax mass
    for i in 0..128 {
        updated.dims[i] += alpha * (state.dims[i] - mu_s.dims[i]);
    }
    updated
}

/// Propose a full set of mode updates given a visited state and mixing weights.
/// Each μ_s is pulled toward the state proportionally to w_s × lr.
pub fn propose_all_updates(
    modes: &[StateVector; N_MODES],
    state: &StateVector,
    weights: &[f64; N_MODES],
    lr: f64,
) -> [StateVector; N_MODES] {
    let mut candidates = modes.clone();
    for s in 0..N_MODES {
        if weights[s] > 1e-12 {
            candidates[s] = propose_mode_update(&modes[s], state, weights[s], lr);
        }
    }
    candidates
}

// ─── Ω GUARD ──────────────────────────────────────────────────────────────────

/// Parameters for the repulsion constraint.
///   design_min_distance = min_{s≠t} ||μ_s(design) − μ_t(design)||
///   repulsion_threshold = fraction of design_min_distance that must be maintained
pub const REPULSION_FRACTION: f64 = 0.30;

/// Check Ω membership for all candidate modes.
/// Returns list of violations (empty = all pass).
pub fn omega_guard(
    candidates: &[StateVector; N_MODES],
    omega: &Omega,
) -> Vec<String> {
    let mut issues = Vec::new();
    for s in 0..N_MODES {
        let viols = omega.violations(&candidates[s]);
        for (name, _) in &viols {
            issues.push(format!("mode[{}] Ω violation: {}", s, name));
        }
    }
    issues
}

/// Check repulsion constraint: modes must not get too close to each other.
/// Returns list of violations (empty = all pass).
pub fn repulsion_guard(
    candidates: &[StateVector; N_MODES],
    design_modes: &[StateVector; N_MODES],
) -> Vec<String> {
    // Compute design min distance
    let design_min_dist = compute_min_mode_distance(design_modes);
    let threshold = REPULSION_FRACTION * design_min_dist;

    let mut issues = Vec::new();
    for a in 0..N_MODES {
        for b in (a + 1)..N_MODES {
            let d2: f64 = (0..128)
                .map(|i| {
                    let d = candidates[a].dims[i] - candidates[b].dims[i];
                    d * d
                })
                .sum();
            let dist = d2.sqrt();
            if dist < threshold {
                issues.push(format!(
                    "repulsion: ‖μ_{} − μ_{}‖ = {:.6} < threshold {:.6}",
                    a, b, dist, threshold
                ));
            }
        }
    }
    issues
}

/// Compute minimum pairwise distance between modes.
pub fn compute_min_mode_distance(modes: &[StateVector; N_MODES]) -> f64 {
    let mut min_d = f64::INFINITY;
    for a in 0..N_MODES {
        for b in (a + 1)..N_MODES {
            let d2: f64 = (0..128)
                .map(|i| {
                    let d = modes[a].dims[i] - modes[b].dims[i];
                    d * d
                })
                .sum();
            min_d = min_d.min(d2.sqrt());
        }
    }
    min_d
}

/// Compute reconstruction error: how much of the observed state is NOT explained
/// by the closest mode centroid.
/// Uses average distance to nearest mode across the simulation trajectory.
pub fn reconstruction_error(state: &StateVector, modes: &[StateVector; N_MODES]) -> f64 {
    let mut min_d2 = f64::INFINITY;
    for m in modes.iter() {
        let d2: f64 = (0..128)
            .map(|i| {
                let d = state.dims[i] - m.dims[i];
                d * d
            })
            .sum();
        min_d2 = min_d2.min(d2);
    }
    min_d2.sqrt()
}

// ─── MODES LEARNER ────────────────────────────────────────────────────────────

/// A note on the learning rule:
/// The system visits states GENERATED using the modes it is learning: the
/// sampling distribution depends on the parameters being learned. Convergence
/// does not follow from Robbins-Monro (which assumes the sample stream is not
/// controlled by the learner). This closed loop is simultaneously the risk
/// (runaway feedback: modes chase state chases modes) and the novelty — the
/// guard + freeze + decay are the containment that makes the measurement safe
/// to take. See spec §theory_note.

pub struct ModesLearner {
    /// Whether learning is active (false = baseline).
    pub learning_enabled: bool,
    /// Base learning rate.
    pub lr0: f64,
    /// Decay time constant (ticks after which lr halves).
    pub lr_decay_T: f64,
    /// Current tick of the simulation.
    pub tick: u64,
    /// Update cadence — run try_update every N ticks.
    pub update_cadence: u64,
    /// Snapshot interval — dump modes every N ticks (3600 = 1h at 1 tick/s).
    pub snapshot_interval: u64,
    /// Last tick at which we took a snapshot.
    pub last_snapshot_tick: u64,

    /// Immutable design modes (the initial μ_s from default_split_operator).
    pub design_modes: [StateVector; N_MODES],

    // Counters
    pub rejection_count: u64,
    pub total_updates: u64,
    pub freeze_triggered: bool,

    // Data directory for snapshots.
    pub data_dir: PathBuf,
}

impl ModesLearner {
    pub fn new(
        learning_enabled: bool,
        design_modes: [StateVector; N_MODES],
        data_dir: PathBuf,
    ) -> Self {
        ModesLearner {
            learning_enabled,
            lr0: 0.001,
            lr_decay_T: 86400.0, // 1 day in ticks (at 1 tick/s)
            tick: 0,
            update_cadence: 10,
            snapshot_interval: 3600, // hourly at 1 tick/s
            last_snapshot_tick: 0,
            design_modes,
            rejection_count: 0,
            total_updates: 0,
            freeze_triggered: false,
            data_dir,
        }
    }

    /// Compute current learning rate with Robbins-Monro decay.
    /// Returns 0 when learning is disabled (baseline mode).
    pub fn current_lr(&self) -> f64 {
        if !self.learning_enabled {
            0.0
        } else {
            self.lr0 / (1.0 + self.tick as f64 / self.lr_decay_T)
        }
    }

    /// Try to update the modes: propose → guard → apply if clear.
    /// Returns true if the update was accepted.
    pub fn try_update(
        &mut self,
        operator: &mut SplitOperator,
        state: &StateVector,
        weights: &[f64; N_MODES],
        omega: &Omega,
    ) -> bool {
        self.tick += 1;

        if !self.learning_enabled {
            return false; // baseline: no learning
        }

        if self.freeze_triggered {
            return false; // frozen: no updates
        }

        if self.tick % self.update_cadence != 0 {
            return false; // not an update tick
        }

        // 1. Propose
        let lr = self.current_lr();
        let candidates = propose_all_updates(&operator.modes, state, weights, lr);

        // 2. Guard (Ω + repulsion)
        let mut issues = Vec::new();
        issues.extend(omega_guard(&candidates, omega));
        issues.extend(repulsion_guard(&candidates, &self.design_modes));

        self.total_updates += 1;

        if !issues.is_empty() {
            self.rejection_count += 1;
            return false; // rejected
        }

        // 3. Apply
        operator.modes = candidates;
        true
    }

    /// Snapshot current modes to JSON file.
    pub fn write_snapshot(&self, operator: &SplitOperator) -> std::io::Result<()> {
        fs::create_dir_all(&self.data_dir)?;
        let ts = self.tick;
        let path = self.data_dir.join(format!("modes_{:06}.json", ts));

        let mut modes_json = Vec::new();
        let labels = ["S1", "S2", "S3", "S4", "S5"];
        for (s, m) in operator.modes.iter().enumerate() {
            let mut dim_map = serde_json::Map::new();
            for i in 0..128 {
                if m.dims[i].abs() > 1e-6 {
                    dim_map.insert(
                        format!("dim_{}", i),
                        json!(m.dims[i]),
                    );
                }
            }
            modes_json.push(json!({
                "level": labels[s],
                "index": s,
                "dims": dim_map,
            }));
        }

        let snapshot = json!({
            "experiment": "EXP-MODES-01",
            "tick": ts,
            "learning_enabled": self.learning_enabled,
            "lr": self.current_lr(),
            "rejection_count": self.rejection_count,
            "total_updates": self.total_updates,
            "freeze_triggered": self.freeze_triggered,
            "modes": modes_json,
        });

        fs::write(&path, serde_json::to_string_pretty(&snapshot)?)?;
        Ok(())
    }

    /// Write hourly metrics summary.
    pub fn write_metrics(
        &self,
        operator: &SplitOperator,
        lyap_estimate: f64,
        stasis_cos: f64,
        rec_error: f64,
        min_mode_dist: f64,
    ) -> std::io::Result<()> {
        fs::create_dir_all(&self.data_dir)?;
        let path = self.data_dir.join("metrics.jsonl");

        let mut entry = json!({
            "tick": self.tick,
            "learning_enabled": self.learning_enabled,
            "lr": self.current_lr(),
            "lambda_max_est": lyap_estimate,
            "stasis_cos": stasis_cos,
            "reconstruction_error": rec_error,
            "min_mode_distance": min_mode_dist,
            "rejection_count": self.rejection_count,
            "total_updates": self.total_updates,
            "freeze_triggered": self.freeze_triggered,
        });

        // Append-mode write (JSONL)
        let line = serde_json::to_string(&entry)? + "\n";
        use std::io::Write;
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)?;
        f.write_all(line.as_bytes())?;
        Ok(())
    }

    /// Check if freeze condition met: λ_max > 0 over a window.
    /// Returns true if freeze should be triggered.
    pub fn check_freeze(&mut self, lyap_estimates: &[f64]) -> bool {
        if self.freeze_triggered {
            return true;
        }
        if lyap_estimates.len() < 6 {
            return false; // not enough data (6 = ~hour at 10 updates/tick cadence)
        }
        // If any estimate in recent window is > 0, freeze
        let recent = &lyap_estimates[lyap_estimates.len().saturating_sub(6)..];
        if recent.iter().any(|&l| l > 0.0) {
            self.freeze_triggered = true;
            return true;
        }
        false
    }
}

// ─── EXPERIMENT RUNNER ────────────────────────────────────────────────────────

/// Run the EXP-MODES-01 simulation.
///
/// Arguments:
///   minutes  — how many simulated minutes to run (0 = use ticks)
///   ticks    — how many ticks to run
///   learning — true = learning enabled, false = baseline
///   data_dir — directory for snapshots (default: /var/lib/vsf/exp_modes01)
///   quiet    — suppress per-tick output
pub fn run_exp_modes_01(
    minutes: u64,
    ticks: u32,
    learning_enabled: bool,
    data_dir: PathBuf,
    quiet: bool,
) {
    use crate::operator::default_split_operator;
    use crate::operator::GaussianSampler;
    use std::time::Instant;

    let omega = Omega::canonical();
    let mut operator = default_split_operator();
    let design_modes = operator.modes.clone();

    let num_ticks = if minutes > 0 {
        (minutes * 60) as u32 // 1 tick ≈ 1 second
    } else {
        ticks
    };

    println!(
        "\n⟦ EXP-MODES-01 | {} | modes={} | ticks={} | dir={} ⟧\n",
        if learning_enabled { "LEARNING" } else { "BASELINE" },
        N_MODES,
        num_ticks,
        data_dir.display(),
    );

    let mut learner = ModesLearner::new(learning_enabled, design_modes, data_dir);

    // Start from a perturbed healthy state.
    let mut rng = GaussianSampler::new(20260713);
    let mut state = operator.modes[2].clone(); // start at S3 mode (control)
    for i in 0..128 {
        state.dims[i] += 0.02 * rng.next_normal(); // small perturbation
    }
    // Clamp to Ω for initial state
    for i in 0..128 {
        state.dims[i] = state.dims[i].clamp(0.0, 1.0);
    }
    // Set healthy default dims
    state.dims[CPU_PRESSURE] = 0.3;
    state.dims[MEM_PRESSURE] = 0.3;
    state.dims[IO_PRESSURE] = 0.2;
    state.dims[BUDGET] = 0.7;
    state.dims[LIFECYCLE] = 0.7;
    state.dims[GOVERNED] = 1.0;
    state.dims[STASIS_COS] = 0.95;

    let sigma = 0.03; // moderate noise
    let mut lyap_window: Vec<f64> = Vec::new();
    let t0 = Instant::now();

    if !quiet {
        println!("{:>6}  {:>6}  {:>8}  {:>8}  {:>8}  {:>8}  {:>6}  {:>6}  {:>6}",
            "tick", "hour", "λ_est", "cos", "rec_err", "min_dist", "upd", "rej", "frz");
        println!("{:>6}  {:>6}  {:>8}  {:>8}  {:>8}  {:>8}  {:>6}  {:>6}  {:>6}",
            "──────", "──────", "───────", "───────", "───────", "───────", "────", "────", "────");
    }

    let mut last_metrics_tick = 0u64;
    let mut lyap_estimates: Vec<f64> = Vec::new();

    for t in 0..num_ticks {
        // Compute τ from lifecycle
        let tau = crate::operator::tau_from_lifecycle(state.dims[LIFECYCLE]);

        // Step the dynamics
        let (next_state, weights) = operator.step(&state, sigma, &mut rng);

        // Estimate λ_max from displacement: log(‖x(t+1) - f₀(x(t))‖ / σ)
        let det_next = operator.deterministic_step(&state, tau);
        let displacement: f64 = (0..128)
            .map(|i| (next_state.dims[i] - det_next.dims[i]).powi(2))
            .sum::<f64>()
            .sqrt();
        let lyap_est = if sigma > 1e-12 {
            (displacement / sigma).ln()
        } else {
            0.0
        };
        lyap_window.push(lyap_est);
        if lyap_window.len() > 20 {
            lyap_window.remove(0);
        }
        let lyap_avg = lyap_window.iter().sum::<f64>() / lyap_window.len() as f64;

        // Update modes (every 10 ticks if learning enabled)
        let accepted = learner.try_update(&mut operator, &next_state, &weights, &omega);
        let _ = accepted;

        // Compute metrics
        let stasis_cos = state.dims[STASIS_COS];
        let rec_error = reconstruction_error(&next_state, &operator.modes);
        let min_mode_dist = compute_min_mode_distance(&operator.modes);
        state = next_state;

        let hour = t as f64 / 3600.0;

        // Hourly snapshot + metrics
        let metrics_due = (t as u64) - last_metrics_tick >= 3600
            || (t == 0)
            || (t == num_ticks - 1);
        if metrics_due {
            last_metrics_tick = t as u64;
            lyap_estimates.push(lyap_avg);

            let _ = learner.write_snapshot(&operator);
            let _ = learner.write_metrics(
                &operator,
                lyap_avg,
                stasis_cos,
                rec_error,
                min_mode_dist,
            );

            if !quiet {
                println!(
                    "{:>6}  {:>6.1}  {:>8.4}  {:>8.4}  {:>8.4}  {:>8.4}  {:>6}  {:>6}  {:>6}",
                    t,
                    hour,
                    lyap_avg,
                    stasis_cos,
                    rec_error,
                    min_mode_dist,
                    learner.total_updates,
                    learner.rejection_count,
                    if learner.freeze_triggered { 1 } else { 0 },
                );
            }

            // Check freeze condition
            if learner.learning_enabled && learner.check_freeze(&lyap_estimates) {
                println!("\n  ⚠ FREEZE TRIGGERED at tick={} (λ_max > 0 in recent window)", t);
                println!("  Modes frozen. Continuing with fixed modes.\n");
            }
        }
    }

    let elapsed = t0.elapsed();
    let sim_rate = num_ticks as f64 / elapsed.as_secs_f64();

    println!("\n── EXP-MODES-01 complete ──────────────────────────────────────────────────");
    println!("  run:        {}", if learning_enabled { "LEARNING" } else { "BASELINE" });
    println!("  ticks:      {}", num_ticks);
    println!("  wall time:  {:?} ({:.0} ticks/s)", elapsed, sim_rate);
    println!("  snapshots:  {}", last_metrics_tick / 3600 + 1);
    println!("  updates:    {} (accepted/total)", learner.total_updates);
    println!("  rejections: {}", learner.rejection_count);
    println!("  freeze:     {}", if learner.freeze_triggered { "YES" } else { "no" });
    if learner.learning_enabled {
        let reject_rate = if learner.total_updates > 0 {
            learner.rejection_count as f64 / learner.total_updates as f64 * 100.0
        } else {
            0.0
        };
        println!("  reject rate: {:.1}%", reject_rate);
        if reject_rate > 5.0 {
            println!("  ⚠ outcome: D_guard_saturation — >5% rejections, Ω constrains learning");
        }
    }
    println!("  dir:        {}", learner.data_dir.display());

    // Final snapshot
    let _ = learner.write_snapshot(&operator);
    let _ = learner.write_metrics(
        &operator,
        lyap_window.iter().sum::<f64>() / lyap_window.len() as f64,
        state.dims[STASIS_COS],
        reconstruction_error(&state, &operator.modes),
        compute_min_mode_distance(&operator.modes),
    );
}
