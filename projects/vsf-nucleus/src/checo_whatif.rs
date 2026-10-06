// checo_whatif.rs — CHECO CH.c — deterministic what-if: excursion-envelope basin probe.
//
// Spec: docs/experiments/CHECO-WHATIF/spec.vsm (CHc_1). Delivers CHECO 55%→~70%.
//
// The Boltzmann relaxation (kernel_step.rs) is GLOBALLY CONTRACTING (p → p_eq at rate 0.99 from
// ANY p), so there is no basin ESCAPE — from any perturbation the system ALWAYS returns. The
// what-if therefore measures the EXCURSION ENVELOPE: given a perturbation of magnitude s∈[0,1],
// how deep does stasis_cos dip before recovering? The deepest dip under MAXIMAL perturbation
// (s=1) is the "critical angle" to compare against the EXP-CA-01 measured value θ_PSI≈0.9377
// ("min_cos=0.9377, viable throughout"). Model ≡ measured reality ⇒ CHECO can forecast unseen δ.
//
// R10: this is the DETERMINISTIC simulator. No LLM. CH.d's narrator will CALL this; never replace it.
// Anti-circularity: the sweep finds θ_env independently; 0.9377 is NOT an input.
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::kernel_step::KernelStepper;
use crate::state_vector::{StasisVec, StateVector};

/// Ticks to settle onto the attractor before perturbing.
pub const CONVERGE_TICKS: usize = 2000;
/// Ticks to relax + measure after the perturbation.
pub const RELAX_TICKS: usize = 4000;
/// stasis_cos at which the trajectory counts as "recovered" to the attractor.
pub const RECOVERY_COS: f64 = 0.999;

/// Outcome of one what-if perturbation.
#[derive(Debug, Clone, Copy)]
pub struct EnvelopeResult {
    /// Perturbation magnitude s∈[0,1] (0 = none, 1 = maximal / uniform occupation).
    pub s: f64,
    /// θ_env (EMA metric) — deepest cos(sv, EMA(sv)) reached. Returns to ~1 at steady state.
    pub min_cos: f64,
    /// θ_env (FIXED-REFERENCE metric, alternative A) — deepest cos(sv, frozen attractor snapshot).
    /// This is the metric comparable to EXP-CA-01 (absolute displacement, not EMA-relative).
    pub min_cos_fixed: f64,
    /// Did the trajectory climb back to RECOVERY_COS within RELAX_TICKS? (globally contracting ⇒ yes)
    pub recovered: bool,
    /// Ticks to recover (RELAX_TICKS if it did not within the window).
    pub recovery_ticks: usize,
    /// Did stasis_cos stay ≥ the θ_PSI floor (0.79) throughout? (EXP-CA-01: "viable throughout")
    pub always_viable: bool,
}

/// One what-if: converge → perturb the occupation by `s` → relax; measure the excursion envelope.
pub fn excursion_envelope(s: f64) -> EnvelopeResult {
    let theta_psi_floor = crate::calibration::THETA_PSI; // 0.79 (EXP-TP-01)
    let mut stepper = KernelStepper::new();
    let mut sv = StateVector::new();
    let mut stasis = StasisVec::new();

    // settle onto the attractor (pressure=0 — pure internal relaxation)
    for _ in 0..CONVERGE_TICKS {
        stepper.step(&mut sv, &mut stasis, 0.0);
    }
    // freeze the converged attractor as the FIXED reference (alternative A metric)
    let attractor = sv.clone();

    // apply the what-if perturbation to the DYNAMICAL state, then relax + measure
    stepper.perturb_occupation(s);
    let mut min_cos = 1.0f64;
    let mut min_cos_fixed = 1.0f64;
    let mut recovered = false;
    let mut recovery_ticks = RELAX_TICKS;
    let mut always_viable = true;
    for t in 0..RELAX_TICKS {
        let o = stepper.step(&mut sv, &mut stasis, 0.0);
        let cos_fixed = sv.cosine_similarity(&attractor); // absolute displacement vs frozen attractor
        if o.stasis_cos < min_cos {
            min_cos = o.stasis_cos;
        }
        if cos_fixed < min_cos_fixed {
            min_cos_fixed = cos_fixed;
        }
        if o.stasis_cos < theta_psi_floor {
            always_viable = false;
        }
        if !recovered && o.stasis_cos >= RECOVERY_COS {
            recovered = true;
            recovery_ticks = t;
        }
    }

    EnvelopeResult { s, min_cos, min_cos_fixed, recovered, recovery_ticks, always_viable }
}

/// θ_env(s) sweep over an evenly-spaced grid s = 0, 1/steps, …, 1.
pub fn sweep(steps: usize) -> Vec<EnvelopeResult> {
    (0..=steps).map(|k| excursion_envelope(k as f64 / steps as f64)).collect()
}

// ──────────────────────────────────────────────────────────────────────────────
// ALT C — THERMAL DIM ANALYSIS
// ──────────────────────────────────────────────────────────────────────────────

/// Block label for a ℝ¹²⁸ dim index.
pub fn dim_block(i: usize) -> &'static str {
    match i {
        0..=15   => "A(trust/health)",
        16..=23  => "B(resources)",
        24..=31  => "C(entropy)",
        32..=47  => "D(organelles)",
        48..=63  => "E(signals)",
        64..=79  => "F(stasis_prev)",
        80..=95  => "F(stasis_curr)",
        96..=115 => "G(learning)",
        _        => "G(rap)",
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// ALT C.2 — SUSTAINED W4B PRESSURE (FROZEN STASIS)
// ──────────────────────────────────────────────────────────────────────────────

/// Ticks to hold sustained pressure before releasing.
pub const HOLD_TICKS: usize = 2000;

/// Result of one sustained-pressure run.
#[derive(Debug, Clone, Copy)]
pub struct ThermalSustainedResult {
    pub pressure: f64,
    /// Deepest cos(sv, frozen_attractor) during hold + relax — the metric comparable to EXP-CA-01 0.9377.
    pub min_cos_fixed: f64,
    /// Deepest EMA stasis_cos (always shallower — stasis tracks the moving attractor).
    pub min_cos_ema: f64,
    /// Did the frozen-ref cosine recover to RECOVERY_COS within RELAX_TICKS after pressure release?
    pub recovered: bool,
    pub recovery_ticks: usize,
    /// Stayed above θ_PSI floor throughout?
    pub always_viable: bool,
}

/// Apply sustained `pressure` via the W4b channel (kT_eff = 1 + γ·pressure) for HOLD_TICKS ticks,
/// measuring cosine against the PRE-HOLD frozen attractor (same stasis-freeze policy as
/// run_critical_angle: stasis frozen at end of warmup, not updated during stress).
///
/// This isolates the THERMODYNAMIC DISPLACEMENT of KernelStepper dynamics: as pressure→1,
/// kT_eff→2, p_eq→uniform, Block B[16] (h_t/h_max) and Block D shift maximally. The frozen-ref
/// cosine shows the absolute displacement from the idle attractor — the quantity comparable to
/// EXP-CA-01's angustia_cos=0.9377.
///
/// A sweep over pressure ∈ [0,1] answers: at what W4b input does KernelStepper reproduce 0.9377?
/// If it never reaches 0.9377, Alt D applies (mechanism-specific envelope). Anti-circularity:
/// 0.9377 is compared as output; it is never tuned into the sweep.
pub fn excursion_thermal_sustained(pressure: f64, hold_ticks: usize) -> ThermalSustainedResult {
    let theta_psi_floor = crate::calibration::THETA_PSI;
    let mut stepper = KernelStepper::new();
    let mut sv     = StateVector::new();
    let mut stasis = StasisVec::new();

    // Phase 1: converge to idle attractor (pressure=0)
    for _ in 0..CONVERGE_TICKS {
        stepper.step(&mut sv, &mut stasis, 0.0);
    }
    let attractor = sv.clone(); // freeze reference — stasis NOT updated after this

    // Phase 2: sustained pressure hold — stasis continues updating (KernelStepper internal),
    // but we measure min_cos against the FROZEN external reference.
    let mut min_cos_fixed = 1.0f64;
    let mut min_cos_ema   = 1.0f64;
    let mut always_viable = true;
    for _ in 0..hold_ticks {
        let o = stepper.step(&mut sv, &mut stasis, pressure);
        let cos_f = sv.cosine_similarity(&attractor);
        if cos_f < min_cos_fixed { min_cos_fixed = cos_f; }
        if o.stasis_cos < min_cos_ema { min_cos_ema = o.stasis_cos; }
        if cos_f < theta_psi_floor { always_viable = false; }
    }

    // Phase 3: release pressure, relax, measure recovery
    let mut recovered      = false;
    let mut recovery_ticks = RELAX_TICKS;
    for t in 0..RELAX_TICKS {
        let o = stepper.step(&mut sv, &mut stasis, 0.0);
        let cos_f = sv.cosine_similarity(&attractor);
        if cos_f < min_cos_fixed { min_cos_fixed = cos_f; }
        if o.stasis_cos < min_cos_ema { min_cos_ema = o.stasis_cos; }
        if cos_f < theta_psi_floor { always_viable = false; }
        if !recovered && cos_f >= RECOVERY_COS {
            recovered      = true;
            recovery_ticks = t;
        }
    }

    ThermalSustainedResult { pressure, min_cos_fixed, min_cos_ema, recovered, recovery_ticks, always_viable }
}

/// Sweep sustained pressure ∈ [0, 1] in `steps` increments; returns the min_cos_fixed profile.
/// At what pressure level does the W4b model reproduce the EXP-CA-01 measured θ_env ≈ 0.9377?
pub fn sweep_sustained(steps: usize, hold_ticks: usize) -> Vec<ThermalSustainedResult> {
    (0..=steps)
        .map(|k| excursion_thermal_sustained(k as f64 / steps as f64, hold_ticks))
        .collect()
}

/// Output of `thermal_dim_analysis`: the cosine excursion and per-dim deltas at peak stress.
#[derive(Debug, Clone)]
pub struct DimAnalysisResult {
    /// cos(sv_peak_stress, sv_attractor) — the deepest excursion critical_angle dynamics produce.
    /// Compare against 0.9377 (EXP-CA-01): if close, the driver is faithful. Output, never input.
    pub peak_stress_cos: f64,
    /// Tick at which peak_stress_cos occurred.
    pub peak_tick: usize,
    /// All 128 dims sorted descending by |sv_peak[i] - sv_attractor[i]|.
    /// Entry: (dim_index, |delta|, block_label).
    pub top_dims: Vec<(usize, f64, &'static str)>,
}

/// CHc_1.2 (Alt C): replay the `critical_angle` thermal/worker-load driver (dry_run mode,
/// same equations as `run_critical_angle`) to identify WHICH ℝ¹²⁸ dims carry the peak-stress
/// excursion. This is the prerequisite for building a faithful multi-dim perturbation for
/// `excursion_envelope` — or for documenting the excursion as thermal-mechanism-specific (Alt D).
///
/// The function replicates `run_critical_angle`'s update equations exactly (warmup 20 ticks →
/// ramp with RAMP_FACTOR=2.5 every 5 ticks, simulated temperature). Stasis is frozen at end of
/// warmup (same as `critical_angle`'s stasis update policy). Per-dim delta is computed against
/// the frozen warmup attractor at the tick of peak excursion.
///
/// Anti-circularity: 0.9377 is compared as OUTPUT; it is never an input to the sweep.
/// R10: no LLM in this path — pure deterministic replay.
pub fn thermal_dim_analysis() -> DimAnalysisResult {
    use crate::state_vector::{EntropyPhase, StasisVec, StateVector};

    // ── replicate run_critical_angle constants (dry_run mode) ─────────────────
    const SAFETY_TEMP:    f64   = 70.0;
    const BASELINE_TICKS: usize = 20;
    const RAMP_INTERVAL:  usize = 5;
    const RAMP_FACTOR:    f64   = 2.5;
    const VECTORS_INIT:   u64   = 200;
    const VECTORS_MAX:    u64   = 50_000;
    const BASELINE_TEMP:  f64   = 35.0;
    const N_WORKERS:      u64   = 4; // dry_run: fixed (available_parallelism().max(2), typical)
    const MAX_TICKS:      usize = 350;
    const H_REST_RATIO:   f64   = 0.20;
    const H_MAX_RATIO:    f64   = 0.85;
    const N_ORG:          f64   = 4.0;

    let h_max  = H_MAX_RATIO * N_ORG.log2();
    let h_rest = H_REST_RATIO * N_ORG.log2();

    let mut sv          = StateVector::new();
    let mut stasis      = StasisVec::new();
    let mut trust       = 0.80f64;
    let mut prev_h      = h_rest;
    let mut activations = [0.25f64; 4];
    let mut lyap_win: std::collections::VecDeque<f64> = std::collections::VecDeque::new();
    let mut vectors_per_tick: u64 = VECTORS_INIT;
    let mut sim_temp    = BASELINE_TEMP;

    let mut attractor_sv: Option<StateVector> = None;
    let mut peak_stress_cos = 1.0f64;
    let mut peak_tick       = 0usize;
    let mut sv_at_peak      = StateVector::new();

    for tick in 0..MAX_TICKS {
        // ── simulated temperature (dry_run, same formula as run_critical_angle) ──
        let load = (vectors_per_tick * N_WORKERS) as f64 / VECTORS_MAX as f64;
        let target_sim = BASELINE_TEMP + load * (80.0 - BASELINE_TEMP);
        sim_temp += (target_sim - sim_temp) * 0.06;
        let temp_c = sim_temp;
        if temp_c >= SAFETY_TEMP { break; }

        // ── phase + ramp ──────────────────────────────────────────────────────
        let in_warmup = tick < BASELINE_TICKS;
        if !in_warmup && tick % RAMP_INTERVAL == 0 && tick > BASELINE_TICKS {
            let new_v = ((vectors_per_tick as f64 * RAMP_FACTOR) as u64).min(VECTORS_MAX);
            vectors_per_tick = new_v;
        }

        // ── entropy + activations (exact critical_angle equations) ────────────
        let cpu_pressure = temp_c / SAFETY_TEMP;
        let pressure = 0.4 * (prev_h / h_max) + 0.3 * (1.0 - trust) + 0.3 * cpu_pressure;
        let focus    = 1.0 - pressure.min(1.0);
        activations[0] = 0.10 + focus * 0.55;
        activations[1] = 0.10 + (1.0 - focus) * 0.30;
        activations[2] = 0.10 + (1.0 - focus) * 0.20;
        activations[3] = 0.10 + (1.0 - focus) * 0.10;
        let act_sum: f64 = activations.iter().sum();
        let h_t: f64 = activations.iter()
            .map(|a| a / act_sum)
            .filter(|&p| p > 1e-10)
            .map(|p| -p * p.log2())
            .sum();
        lyap_win.push_back((h_t - prev_h).abs());
        if lyap_win.len() > 20 { lyap_win.pop_front(); }
        let lambda = lyap_win.iter().sum::<f64>() / lyap_win.len() as f64;
        prev_h = h_t;

        let norm_acts = [
            activations[0]/act_sum, activations[1]/act_sum,
            activations[2]/act_sum, activations[3]/act_sum,
        ];
        sv.update_block_a(trust, trust, 0.0, 1.0, true, 1, 0.7);
        sv.update_block_b(cpu_pressure, 0.0, 0.0, 1.0 - cpu_pressure, 1.0, 0, 0, 0);
        sv.update_block_c(h_t, h_rest, h_max, EntropyPhase::Stasis, &stasis, false, 0, tick as u32);
        sv.update_block_d(&norm_acts);
        sv.update_block_g(lambda, 0.02, true);

        if in_warmup {
            stasis.observe(&sv);
            trust = (trust + 0.001).min(1.0);
            if tick == BASELINE_TICKS - 1 {
                attractor_sv = Some(sv.clone()); // freeze reference at end of warmup
            }
        }

        // ── track peak excursion vs frozen attractor ──────────────────────────
        if let Some(ref att) = attractor_sv {
            let cos = sv.cosine_similarity(att);
            if cos < peak_stress_cos {
                peak_stress_cos = cos;
                peak_tick = tick;
                sv_at_peak = sv.clone();
            }
        }
    }

    // ── per-dim delta: sv_peak vs sv_attractor, sorted descending ─────────────
    let att = attractor_sv.unwrap_or_else(StateVector::new);
    let mut deltas: Vec<(usize, f64, &'static str)> = (0..128)
        .map(|i| (i, (sv_at_peak.dims[i] - att.dims[i]).abs(), dim_block(i)))
        .collect();
    deltas.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    DimAnalysisResult { peak_stress_cos, peak_tick, top_dims: deltas }
}

// ──────────────────────────────────────────────────────────────────────────────
// CHc_3 — REPORT SCHEMA FOR CH.d NARRATOR
// ──────────────────────────────────────────────────────────────────────────────

/// Consolidated what-if report for CH.d narrator consumption.
/// Emitted as JSON by the `checo_whatif` subcommand (R10: no LLM in this path).
#[derive(Debug, Clone)]
pub struct WhatIfReport {
    pub perturbation_type: &'static str,  // "occupation" | "w4b_sustained"
    pub magnitude: f64,
    /// Absolute displacement vs frozen attractor — the primary metric (comparable to EXP-CA-01).
    pub min_cos_fixed: f64,
    /// EMA stasis_cos — always shallower than min_cos_fixed (stasis tracks the moving attractor).
    pub min_cos_ema: f64,
    pub always_viable: bool,
    pub recovered: bool,
    pub recovery_ticks: usize,
    /// EXP-CA-01 real-hardware reference (Alt D: mechanism-specific, not a model input).
    pub hardware_thermal_ref: f64,
    /// min_cos_fixed − hardware_thermal_ref (positive ⇒ model envelope shallower than hardware).
    pub gap_to_hardware: f64,
}

/// Run the what-if engine for `perturbation_type` ("occupation" | "w4b") at `magnitude ∈ [0,1]`.
/// Returns a `WhatIfReport` ready for JSON serialisation by CH.d or the subcommand emitter.
/// R10: deterministic Rust — no LLM in this path.
pub fn whatif_report(perturbation_type: &str, magnitude: f64, hold_ticks: usize) -> WhatIfReport {
    const HARDWARE_THERMAL_REF: f64 = 0.9377; // EXP-CA-01, Alt D
    let mag = magnitude.clamp(0.0, 1.0);
    match perturbation_type {
        "w4b" | "w4b_sustained" => {
            let r = excursion_thermal_sustained(mag, hold_ticks);
            WhatIfReport {
                perturbation_type: "w4b_sustained",
                magnitude: mag,
                min_cos_fixed:       r.min_cos_fixed,
                min_cos_ema:         r.min_cos_ema,
                always_viable:       r.always_viable,
                recovered:           r.recovered,
                recovery_ticks:      r.recovery_ticks,
                hardware_thermal_ref: HARDWARE_THERMAL_REF,
                gap_to_hardware:     r.min_cos_fixed - HARDWARE_THERMAL_REF,
            }
        }
        _ => { // "occupation" (default)
            let r = excursion_envelope(mag);
            WhatIfReport {
                perturbation_type: "occupation",
                magnitude: mag,
                min_cos_fixed:       r.min_cos_fixed,
                min_cos_ema:         r.min_cos,
                always_viable:       r.always_viable,
                recovered:           r.recovered,
                recovery_ticks:      r.recovery_ticks,
                hardware_thermal_ref: HARDWARE_THERMAL_REF,
                gap_to_hardware:     r.min_cos_fixed - HARDWARE_THERMAL_REF,
            }
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unperturbed_stays_at_attractor() {
        let r = excursion_envelope(0.0);
        assert!(r.min_cos > 0.99, "s=0 should not excurse, min_cos={}", r.min_cos);
        assert!(r.always_viable);
    }

    #[test]
    fn deeper_perturbation_lowers_envelope() {
        // H_CHC2 monotonicity: a larger perturbation dips at least as deep.
        let lo = excursion_envelope(0.3);
        let hi = excursion_envelope(1.0);
        assert!(
            hi.min_cos <= lo.min_cos + 1e-9,
            "deeper perturbation must dip ≥ as low: s=1 {} vs s=0.3 {}",
            hi.min_cos, lo.min_cos
        );
    }

    #[test]
    fn max_perturbation_recovers_and_stays_viable() {
        // H_CHC2: globally contracting ⇒ always recovers; viable throughout (≥ θ_PSI 0.79).
        let r = excursion_envelope(1.0);
        assert!(r.recovered, "max perturbation must recover (globally contracting)");
        assert!(r.always_viable, "must stay viable throughout, min_cos={}", r.min_cos);
    }

    #[test]
    fn reports_critical_angle_envelope() {
        // H_CHC1 (REPORT, never tune-to-fit): θ_env(1.0) vs the EXP-CA-01 measured 0.9377.
        let r = excursion_envelope(1.0);
        println!(
            "CHc_1: θ_env(1.0) EMA={:.4}  FIXED-REF={:.4}  recovered={} in {} ticks  (EXP-CA-01 0.9377)",
            r.min_cos, r.min_cos_fixed, r.recovered, r.recovery_ticks
        );
        // loose sanity only: a real excursion below the attractor but above the θ_PSI floor.
        assert!(r.min_cos < 1.0 && r.min_cos > crate::calibration::THETA_PSI);
    }

    // ── Alt C.2: sustained W4b pressure sweep (frozen stasis) ───────────────

    #[test]
    fn sustained_pressure_sweep_finds_thermal_envelope() {
        // CHc_1.2 (Alt C.2): sweep sustained W4b pressure, measure min_cos_fixed vs frozen attractor.
        // Answers: at what pressure does KernelStepper reproduce 0.9377?
        // If never → Alt D (mechanism-specific); if yes → model thermodynamically consistent.
        // REPORT HONESTLY. 0.9377 is compared as output, never tuned.
        let results = super::sweep_sustained(10, 500); // 11 points, 500-tick hold (fast)
        println!("\nCHc_1.2 (Alt C.2) — sustained W4b pressure sweep (frozen stasis, 500-tick hold):");
        println!("  pressure  min_cos_fixed  min_cos_ema  recovered  viable");
        for r in &results {
            println!("  {:.1}       {:.4}         {:.4}       {}          {}",
                r.pressure, r.min_cos_fixed, r.min_cos_ema, r.recovered, r.always_viable);
        }
        // Find closest to 0.9377
        let closest = results.iter().min_by(|a, b|
            (a.min_cos_fixed - 0.9377).abs()
            .partial_cmp(&(b.min_cos_fixed - 0.9377).abs())
            .unwrap_or(std::cmp::Ordering::Equal)
        ).unwrap();
        println!("\n  closest to 0.9377: pressure={:.1}  min_cos_fixed={:.4}  gap={:+.4}",
            closest.pressure, closest.min_cos_fixed, closest.min_cos_fixed - 0.9377);
        println!("  EXP-CA-01 target: 0.9377  |  Alt D if gap > 0.02 at pressure=1.0");
        // Sanity: monotone decreasing (higher pressure → lower min_cos_fixed) and viable throughout
        for r in &results { assert!(r.always_viable, "must stay viable, p={}", r.pressure); }
        let max_pressure_result = results.last().unwrap();
        assert!(max_pressure_result.min_cos_fixed < results[0].min_cos_fixed,
            "pressure=1.0 must cause more excursion than pressure=0.0");
    }

    // ── Alt C: thermal dim analysis ──────────────────────────────────────────

    #[test]
    fn thermal_dim_analysis_identifies_excursion_dims() {
        // CHc_1.2 (Alt C) — replay critical_angle dry_run driver, identify which ℝ¹²⁸ dims
        // carry the peak-stress excursion vs the frozen warmup attractor.
        // REPORT HONESTLY: compare peak_stress_cos to 0.9377; never tune.
        let r = super::thermal_dim_analysis();
        println!("\nCHc_1.2 (Alt C) — thermal_dim_analysis:");
        println!("  peak_stress_cos = {:.4}  at tick {}  (EXP-CA-01 reference: 0.9377  gap={:+.4})",
            r.peak_stress_cos, r.peak_tick, r.peak_stress_cos - 0.9377);
        println!("  top 20 dims by |Δ| (sv_peak − sv_attractor):");
        for (dim, delta, block) in r.top_dims.iter().take(20) {
            println!("    dim[{:3}]  {}  Δ={:.4}", dim, block, delta);
        }
        // Block-level summary: which blocks dominate the excursion?
        let mut block_sum: std::collections::HashMap<&str, f64> = std::collections::HashMap::new();
        for (_, delta, block) in &r.top_dims {
            *block_sum.entry(block).or_insert(0.0) += delta;
        }
        let mut block_vec: Vec<(&&str, &f64)> = block_sum.iter().collect();
        block_vec.sort_by(|a, b| b.1.partial_cmp(a.1).unwrap_or(std::cmp::Ordering::Equal));
        println!("  block-level Σ|Δ|:");
        for (block, sum) in &block_vec {
            println!("    {}  Σ={:.4}", block, sum);
        }
        // Sanity: must produce some excursion and stay viable
        assert!(r.peak_stress_cos < 1.0, "thermal driver must cause excursion");
        assert!(r.peak_stress_cos > crate::calibration::THETA_PSI,
            "must stay above θ_PSI floor, got {}", r.peak_stress_cos);
    }
}
