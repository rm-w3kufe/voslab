/// operational.rs — Nucleus Operational Mode
///
/// Main entry point for operational (non-experimental) nucleus
/// Runs S3 governance + S4 orchestrator in parallel
/// Manages telemetry aggregation and publication

use crate::bbs_embedded::BbsEmbeddedClient;
use crate::config::NucleusConfig;
use crate::s4_operational::{S4Orchestrator, clima_bundle_path, S4_CLIMA_BUNDLE_MAX_AGE_SECS};
use crate::telemetry_publisher::TelemetryPublisher;
// γ.1 + γ.2 + γ.4 + γ.6 + γ.8 — canonical path (per Qwen consensus rounds 1-4)
use crate::telemetry_canonical::{CanonicalTelemetry, CanonicalEvent};
use crate::nats_publisher;
use crate::bbh_subscriber;
use crate::phi_down_subscriber;
use crate::invariant_checker::InvariantChecker;
use crate::algedonic::AlgedonicGate;
use crate::observability::{report_tick_completed, HealthReporter, start_watchdog_task};
// β.4 — Tokio supervision tree (Qwen ronda 4)
use crate::supervisor::{Supervisor, SubsystemSpec, Subsystem};
// F5.x.9 / F5.x.4 — live kernel-tick wiring: read-only sensor ingest + Ω viability
use crate::hardware_ingest::{HardwareIngest, SensorSource};
use crate::omega_validator::Omega;
use crate::state_vector::{
    StateVector, StasisVec, CPU_PRESSURE, MEM_PRESSURE, IO_PRESSURE, CGROUP_HEADROOM,
    TRUST_HIST_0, TRUST_HIST_9, GOVERNED, LIFECYCLE, STASIS_COS,
};
use crate::kernel_step::{KernelStepper, StepOutput};  // W1 — live entropy-relaxation dynamics
use crate::lyapunov::{RecurrentSetCertifier, Regime};  // W2 — live governed predicate
use crate::vr_complex::{VrComplex, VR_EPSILON_COSINE};  // W3 — live topological monitor
use crate::adaptive_clock::{AdaptiveClock, dt_from_sigma};  // W4 — σ-adaptive tick clock
use crate::calibration::{SIGMA_DRIFT_GAIN, CLOCK_MAX_SPEEDUP, LYAP_DRIFT_BAND};  // W4 — drift→σ gain + floor + zero-band
use crate::trust_axes::{self, TrustVector};  // M9 — per-axis trust telemetry (EXP-TRUST-01 phase B gate)
use crate::clima_bundle_reader::{read_clima_bundle, ClimaBundleFields};
use crate::projector::{Projector, TwinPoint};  // ITEM_13.2 — rolling OLS projector
#[cfg(feature = "covenant_detector")]
use crate::covenant_detector::{CovenantViolationDetector, ViolationType};  // A01-01 — heuristic v12 detector
use std::collections::VecDeque;
use std::error::Error;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

/// M9 — map the per-tick in-process signals to a per-axis trust observation
/// run_4 (EXP-TRUST-01) — minimal self-contained PRNG for the behavioral-breach Gaussian
/// perturbation. Deterministic (seeded), experiment-only: never on the prod path (gated by
/// VSF_EXP_BREACH_AXIS=behavioral). Box–Muller over Xorshift64; caches the spare deviate.
struct ExpXorshift { s: u64, spare: Option<f64> }
impl ExpXorshift {
    fn new(seed: u64) -> Self { ExpXorshift { s: if seed == 0 { 1 } else { seed }, spare: None } }
    fn next_u64(&mut self) -> u64 {
        let mut x = self.s;
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        self.s = x; x
    }
    fn next_f64(&mut self) -> f64 { (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64 }
    fn gaussian(&mut self) -> f64 {
        if let Some(g) = self.spare.take() { return g; }
        let u1 = self.next_f64().max(1e-12);
        let u2 = self.next_f64();
        let r = (-2.0 * u1.ln()).sqrt();
        let (s, c) = (std::f64::consts::TAU * u2).sin_cos();
        self.spare = Some(r * s);
        r * c
    }
}

/// run_4 (EXP-TRUST-01) — is the tick-windowed breach active at `tick`?
/// Window is the closed interval [from, until]: the breach fires when
/// `until > 0 && from <= tick <= until`.
///   • `until == 0` (prod default / unset) → disabled: always false.
///   • `from == 0`  (unset) → starts at the first tick; preserves the pre-
///     VSF_EXP_BREACH_FROM behavior exactly (tick starts at 1, so `tick >= 0` holds).
///   • `from == k`  → delays the perturbation until the regime classifier settles
///     (~50 ticks), avoiding the startup confound documented in EXP-TRUST-01 F-R4-3.
/// Pure + deterministic (D6): no env reads, no clock — the call site supplies every input.
fn breach_active(tick: u64, breach_from: u64, breach_until: u64) -> bool {
    breach_until > 0 && tick >= breach_from && tick <= breach_until
}

/// (Def_TrustVector). v1 extractors, all deterministic (D6):
///   behavioral    = the live kernel trust signal (phase-A scalar, untouched)
///   structural    = ingest boundary certification holds (config/sensor contract)
///   predictive    = Lyapunov regime forecast holding (recurrent set ladder)
///   communicative = previous canonical emit succeeded (lag-1 reporting health)
/// EXP-TRUST-01 phase B calibrates per-axis λ_i and extends these extractors.
pub(crate) fn trust_observation(
    kernel_trust: f64,
    boundary_bounded: bool,
    regime: Regime,
    prev_emit_ok: bool,
    structural_breach: bool,
) -> TrustVector {
    // run_4 (2026-06-19): the structural-breach perturbation is passed IN by the caller
    // (tick-windowed at the call site), not read from the environment here. This restores
    // trust_observation to a pure deterministic function (D6) and lets the experiment
    // harness control the breach WINDOW (breach → recovery within one process run).
    let structural_obs = if structural_breach {
        0.0
    } else if boundary_bounded {
        1.0
    } else {
        0.0
    };
    TrustVector::new(
        kernel_trust,
        structural_obs,
        match regime {
            Regime::InRecurrentSet => 1.0,
            Regime::ContractingToR => 0.75,
            Regime::Unknown => 0.5,
            Regime::Diverging => 0.0,
        },
        if prev_emit_ok { 1.0 } else { 0.0 },
    )
}

pub struct OperationalNucleus {
    config: Arc<NucleusConfig>,
    bbs: BbsEmbeddedClient,
    s4: S4Orchestrator,
    telemetry: TelemetryPublisher,
}

impl OperationalNucleus {
    pub fn new(config: NucleusConfig) -> Self {
        let config = Arc::new(config);
        let bbs = BbsEmbeddedClient::new(
            "/root/bbs.db",
            config.nucleus_source_id.clone()
        ).expect("Failed to initialize embedded BBS");
        // A1: this `s4` instance lives only in the struct field for completeness;
        // the actually-running S4 thread is spawned in run_parallel{_canonical} with
        // a SHARED Arc<RwLock>. We give this placeholder its own lock.
        let s4 = S4Orchestrator::new(Arc::new(std::sync::RwLock::new((*config).clone())));
        let telemetry = TelemetryPublisher::new(bbs.clone(), config.nucleus_source_id.clone());

        OperationalNucleus { config, bbs, s4, telemetry }
    }

    /// Validate connectivity to essential services (BBS required, Ollama warned only)
    pub fn preflight_check(&self) -> Result<(), Box<dyn Error>> {
        println!("\n=== PREFLIGHT CHECKS ===");

        // Check BBS (required)
        if self.bbs.health_check() {
            println!("✓ BBS reachable (embedded SQLite)");
        } else {
            return Err("✗ BBS unreachable (embedded SQLite)".into());
        }

        // Check Ollama (warn only, will retry on S4 cycle)
        let ollama_url = format!("{}/api/tags", self.config.ollama_url);
        match ureq::get(&ollama_url)
            .timeout(Duration::from_secs(3))
            .call()
        {
            Ok(_) => println!("✓ Ollama reachable at {}", self.config.ollama_url),
            Err(_) => println!("⚠ Ollama will be available on first S4 cycle (retrying at {}s intervals)", self.config.s4_cycle_interval_secs),
        }

        println!();
        Ok(())
    }

    /// S4 orchestrator task (runs on schedule)
    fn s4_worker(&self) {
        println!("\n[S4 Worker] Starting...");
        loop {
            if let Err(e) = self.s4.run_cycle() {
                eprintln!("[S4] Cycle error: {}", e);
            }
            thread::sleep(Duration::from_secs(self.config.s4_cycle_interval_secs as u64));
        }
    }

    /// Telemetry worker (runs on schedule)
    fn telemetry_worker(&self) {
        println!("\n[Telemetry Worker] Starting (publishing every {}s)...", self.config.telemetry_interval_secs);
        loop {
            match self.telemetry.publish_metrics() {
                Ok(()) => {
                    println!("[Telemetry] ✓ Metrics logged (embedded)");
                }
                Err(e) => {
                    eprintln!("[Telemetry] Failed to publish: {}", e);
                }
            }
            thread::sleep(Duration::from_secs(self.config.telemetry_interval_secs as u64));
        }
    }

    /// Main operational loop (single-threaded for now)
    pub fn run(&self) -> Result<(), Box<dyn Error>> {
        self.config.print();
        self.preflight_check()?;

        println!("\n=== NUCLEUS OPERATIONAL MODE ===");
        println!("Starting autonomous governance loops...\n");

        // Run S4 continuously (blocking)
        self.s4_worker();

        Ok(())
    }

    /// Alternative: spawn workers as threads (TODO: implement if needed)
    pub fn run_parallel(&self) -> Result<(), Box<dyn Error>> {
        self.config.print();
        self.preflight_check()?;

        println!("\n=== NUCLEUS OPERATIONAL MODE (PARALLEL) ===");
        println!("Spawning workers...\n");

        // Spawn S4 worker
        let s4_config = (*self.config).clone();
        let s4_bbs_url = self.config.bbs_url.clone();
        let s4_source = self.config.nucleus_source_id.clone();
        let s4_ollama_url = self.config.ollama_url.clone();
        let s4_ollama_model = self.config.ollama_model.clone();
        let s4_timeout = self.config.ollama_timeout_secs;

        let _s4_thread = thread::spawn(move || {
            let s4_config = NucleusConfig {
                bbs_url: s4_bbs_url,
                nucleus_source_id: s4_source,
                ollama_url: s4_ollama_url,
                ollama_model: s4_ollama_model,
                ollama_timeout_secs: s4_timeout,
                ..s4_config
            };
            // A1: wrap in Arc<RwLock> (legacy non-canonical mode has no phi_down, so the
            // lock here is just to satisfy the new API. config stays immutable in practice).
            let live = std::sync::Arc::new(std::sync::RwLock::new(s4_config));
            let orchestrator = S4Orchestrator::new(live);
            loop {
                if let Err(e) = orchestrator.run_cycle() {
                    eprintln!("[S4] Error: {}", e);
                }
                let sleep_secs = orchestrator.current_cycle_interval_secs() as u64;
                thread::sleep(Duration::from_secs(sleep_secs));
            }
        });

        // Spawn telemetry worker
        let telem_config = (*self.config).clone();
        let telem_bbs_url = self.config.bbs_url.clone();
        let telem_source = self.config.nucleus_source_id.clone();
        let telem_interval = self.config.telemetry_interval_secs;

        let _telem_thread = thread::spawn(move || {
            println!("[Telemetry Worker] Starting (publishing every {}s)...", telem_interval);
            let bbs = BbsEmbeddedClient::new("/root/bbs.db", telem_source.clone())
                .expect("Failed to init embedded BBS");
            let publisher = TelemetryPublisher::new(bbs, telem_source);
            loop {
                match publisher.publish_metrics() {
                    Ok(()) => {
                        println!("[Telemetry] ✓ Metrics logged (embedded)");
                    }
                    Err(e) => {
                        eprintln!("[Telemetry] Failed to publish: {}", e);
                    }
                }
                thread::sleep(Duration::from_secs(telem_interval as u64));
            }
        });

        // Keep main thread alive
        loop {
            thread::sleep(Duration::from_secs(60));
        }
    }

    /// γ phase entry — run_parallel + canonical telemetry path + optional NATS publish.
    ///
    /// Adds (on top of `run_parallel`):
    ///   - CanonicalTelemetry writer (events.jsonl with tmpfs staging + Merkle chain)
    ///   - Async flush task (100ms → /var/lib/vsf/<id>/events.jsonl)
    ///   - Optional NATS publisher (if NATS_URL env var set)
    ///
    /// All under a tokio runtime that runs in parallel with the std::thread workers
    /// (S4 + telemetry_publisher) of `run_parallel`. The old workers are kept for
    /// defense-in-depth — both write to their own stores. Motor 2 deprecation is a
    /// separate phase (Dep.1-Dep.3).
    pub fn run_parallel_canonical(&self) -> Result<(), Box<dyn Error>> {
        self.config.print();
        self.preflight_check()?;

        println!("\n=== NUCLEUS OPERATIONAL MODE (γ canonical) ===");
        println!("Spawning workers + canonical telemetry path...\n");

        // ── γ.1 SHARED canonical writer (created once, cloned to threads) ─────
        // P.1: S4 thread must share the SAME Merkle chain as the canonical
        // emit loop, otherwise two writers race on prev_hash. Create here,
        // clone the Arc handle into each consumer thread.
        let canon = CanonicalTelemetry::new(&self.config.nucleus_source_id)?;
        println!("[canonical] writer ready (tmpfs staging + Merkle chain)");

        // ── A1 / P.3.1 — SHARED live config Arc<RwLock<NucleusConfig>> ────────
        // S4 reads on each cycle; phi_down_subscriber writes on policy override.
        // This closes the control loop semantically: phi_down patch → next S4
        // cycle uses new values. Without this, param_change events emit but S4
        // never re-reads → K_φ↓ measurement worked but actuator didn't.
        let live_config = std::sync::Arc::new(std::sync::RwLock::new((*self.config).clone()));
        println!("[A1] shared live_config RwLock initialized (control loop closed)");

        // ── Phase 4.4 (γ.11) — S3* audit buffer shared with S4 ───────────────
        // Created here (empty); subscriber spawned in canonical_thread tokio
        // runtime populates it; S4 thread reads it for prompt context.
        let audit_buffer = crate::s3_star_audit::AuditBuffer::new(50);
        let s4_audit_buf = audit_buffer.clone();
        println!("[s3_star_audit] γ.11 buffer initialized (S4 will see audit findings)");

        // ITEM_5.5 — Create pending_approval_queue BEFORE the S4 thread so both
        // the S4 orchestrator and the tokio approval subscriber share the same queue.
        // S4 thread enqueues ParameterDrift proposals; tokio block emits + verifies tokens.
        let pending_approval_queue = crate::s5_approval_nats::new_pending_queue();

        // ── Reuse run_parallel's workers (S4 + BBS telemetry) ─────────────────
        let s4_live = live_config.clone();
        let s4_canon = canon.clone(); // P.1 — shared chain handle
        let s4_approval_queue = pending_approval_queue.clone();

        let _s4_thread = thread::spawn(move || {
            // P.1 — attach canonical writer so s4-analysis events emit to events.jsonl
            // Phase 4.4 — attach audit buffer for S3* findings in prompt context
            // ITEM_5.5 — attach approval queue for reframe live queue
            let orchestrator = S4Orchestrator::new(s4_live)
                .with_canonical(s4_canon)
                .with_audit_buffer(s4_audit_buf)
                .with_approval_queue(s4_approval_queue);
            loop {
                if let Err(e) = orchestrator.run_cycle() {
                    eprintln!("[S4] Error: {}", e);
                }
                // A1 — read latest interval each iteration (phi_down may have changed it)
                let sleep_secs = orchestrator.current_cycle_interval_secs() as u64;
                thread::sleep(Duration::from_secs(sleep_secs));
            }
        });

        let telem_source = self.config.nucleus_source_id.clone();
        let telem_interval = self.config.telemetry_interval_secs;

        let _telem_thread = thread::spawn(move || {
            println!("[Telemetry Worker] Starting (publishing every {}s)...", telem_interval);
            let bbs = BbsEmbeddedClient::new("/root/bbs.db", telem_source.clone())
                .expect("Failed to init embedded BBS");
            let publisher = TelemetryPublisher::new(bbs, telem_source);
            loop {
                match publisher.publish_metrics() {
                    Ok(()) => println!("[Telemetry] ✓ Metrics logged (embedded)"),
                    Err(e) => eprintln!("[Telemetry] Failed to publish: {}", e),
                }
                thread::sleep(Duration::from_secs(telem_interval as u64));
            }
        });

        // ── γ.1 + γ.2 — Canonical telemetry + optional NATS in tokio runtime ──
        let system_id = self.config.nucleus_source_id.clone();
        let canon_interval = self.config.telemetry_interval_secs;
        let canon_for_async = canon.clone(); // P.1 — same shared chain handle
        let live_config_for_phi_down = live_config.clone(); // A1 — shared with S4 thread
        let audit_buffer_for_async = audit_buffer.clone(); // γ.11 — shared with S4 thread
        // γ.11 uses VSF_ID (not nucleus_source_id) to match s3-star publish subject
        // vsf.<vsf_id>.s3_star.audit.* — VSF_ID defaults to "alpha" like other subscribers.
        let vsf_id_for_audit = std::env::var("VSF_ID").unwrap_or_else(|_| "alpha".to_string());
        let _canonical_thread = thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()
                .expect("tokio runtime");

            rt.block_on(async move {
                let canon = canon_for_async; // shared writer (created in caller)

                // γ.1 — Flush task: tmpfs → disk every 100ms
                let _flush = canon.start_flush_task();

                // PROD-A1b — Ed25519 witness checkpoints over the chain head (sidecar
                // events.witness.jsonl). Upgrades the φ↑ cert from chain-linkage to full
                // attestation. Key load/generate failure DISABLES checkpoints but never aborts
                // the nucleus (the witness is an auditor — C5 spirit).
                {
                    let base = std::path::Path::new(crate::telemetry_canonical::DISK_ROOT)
                        .join(&system_id);
                    let key_path = base.join("witness_key.ed25519");
                    let sidecar = base.join(crate::telemetry_canonical::WITNESS_FILENAME);
                    match vsf_agent::witness::load_or_generate_signing_key(&key_path) {
                        Ok(sk) => {
                            let _witness = canon.start_witness_checkpoint_task(
                                sk,
                                system_id.clone(),
                                Duration::from_secs(
                                    crate::telemetry_canonical::WITNESS_CHECKPOINT_SECS),
                                sidecar,
                            );
                            println!("[witness] PROD-A1b checkpoint task ready (every {}s → {})",
                                crate::telemetry_canonical::WITNESS_CHECKPOINT_SECS,
                                crate::telemetry_canonical::WITNESS_FILENAME);
                        }
                        Err(e) => eprintln!(
                            "[witness] key init failed; checkpoints DISABLED (nucleus continues): {}", e),
                    }
                }

                // γ.2 — NATS publisher (no-op if NATS_URL unset)
                let disk_path = std::path::Path::new(crate::telemetry_canonical::DISK_ROOT)
                    .join(&system_id)
                    .join(crate::telemetry_canonical::EVENTS_FILENAME);
                let _publisher = nats_publisher::start_publisher_task(system_id.clone(), disk_path);

                // γ.9 — BBH subscriber (cross-system events into shared chain)
                // Persists BBH-emitted events.jsonl-compatible payloads into the SAME
                // canonical chain so K_φ↑ measurement sees variety from S1 instances.
                let _bbh_sub = bbh_subscriber::start_subscriber_task(canon.clone(), None);
                println!("[bbh_subscriber] γ.9 ready (subject: bbh.>)");

                // γ.11 — S3* audit subscriber: feeds audit_buffer for S4 prompt context (Phase 4.4)
                let _audit_sub = crate::s3_star_audit::spawn_subscriber_for(
                    audit_buffer_for_async,
                    &vsf_id_for_audit,
                );
                println!("[s3_star_audit] γ.11 subscriber spawned");

                // γ.10 — φ↓ subscriber: receives S5 policy overrides, emits param_change.
                // A1/P.3.1: now uses the SHARED live_config Arc<RwLock>, same handle
                // S4 reads on each cycle. Control loop CLOSED — phi_down patch applies
                // to actual S4 behavior on its next iteration.
                // DEBT_S1: s1_viability_signal carries current stasis_cos (f64 bits) to the
                // phi_down subscriber so it can apply the S1 viability gate (Ashby self-defence).
                let s1_viability_signal = std::sync::Arc::new(
                    std::sync::atomic::AtomicU64::new(f64::to_bits(1.0))
                );
                let _phi_down_sub = phi_down_subscriber::start_subscriber_task(
                    canon.clone(),
                    live_config_for_phi_down,
                    None,
                    s1_viability_signal.clone(),
                );
                println!("[phi_down] γ.10 ready (subject: vsf.<id>.phi_down.params, shared live_config)");

                // ITEM_4.1 M3 — S5 caution mode subscriber.
                // Listens on vsf.<id>.s5.caution; sets AtomicBool when S5 enters caution.
                // S3 auto-controller reads this flag each tick — holds all autonomous actions.
                let (s5_caution_flag, _s5_caution_sub) =
                    crate::s5_caution::start_caution_subscriber(&vsf_id_for_audit);
                println!("[s5-caution] M3 ready (subject: vsf.<id>.s5.caution)");

                // ITEM_3.2 + ITEM_5.5 — S5 approval channel.
                // Queue was created before this block (shared with S4 thread via clone).
                // Subscriber verifies signed tokens; emitter forwards pending proposals to NATS.
                let _s5_approval_sub = crate::s5_approval_nats::start_approval_subscriber(
                    &vsf_id_for_audit,
                    pending_approval_queue.clone(),
                    canon.clone(),
                );
                // ITEM_5.5 — Approval emitter: periodically publish any queued proposals
                // to vsf.<id>.s5.approval_request so s5_ca.py listen can notify rmw3.
                let _s5_approval_emit = crate::s5_approval_nats::start_approval_emitter(
                    &vsf_id_for_audit,
                    pending_approval_queue.clone(),
                );
                println!("[s5-approval] ITEM_3.2+5.5 ready (sub: approval_token | emitter: approval_request every 60s)");

                // DEBT_S5 — S5 covenant halt flag + resume subscriber.
                // halt_flag is shared with the sync tick loop (via clone).
                // start_resume_subscriber() watches vsf.<id>.s5.covenant_resume;
                // on receipt: clears flag + emits s5_covenant_resumed to φ↑.
                let covenant_halt_flag = crate::s5_covenant::new_halt_flag();
                let _s5_covenant_resume_sub = crate::s5_covenant::start_resume_subscriber(
                    &vsf_id_for_audit,
                    covenant_halt_flag.clone(),
                    canon.clone(),
                );
                // ITEM_15 — S5 external halt authority (LXC 104 → LXC 101 via NATS).
                // vsf-s5-covenant.py on LXC 104 independently monitors nucleus state and
                // publishes vsf.<id>.s5.covenant_halt when it detects a violation.
                // Fail-soft: in-process CovenantChecker remains as belt+suspenders.
                let _s5_covenant_halt_sub = crate::s5_covenant::start_halt_subscriber(
                    &vsf_id_for_audit,
                    covenant_halt_flag.clone(),
                    canon.clone(),
                );
                println!("[s5-covenant] ITEM_15 ready (halt_flag + resume sub + EXTERNAL halt sub vsf.<id>.s5.covenant_halt)");

                // ITEM-17.2 — S4 anticipatory directive subscriber (synthetic build).
                // Listens on vsf.<id>.s4.anticipatory_directive; runs donor selection + invariant
                // checks (INV-SUM, INV-FLOOR, INV-FRESH); emits s3_pre_grant to φ↑.
                // SYNTHETIC: no cgroup writes — grant is logged only.
                // Production actuation gated on R2 (stasis_cos ≥ 0.875 donor floor).
                let _s3_anticipation_sub = crate::s3_anticipation::start_directive_subscriber(
                    &vsf_id_for_audit,
                    canon.clone(),
                );
                println!("[s3_anticipation] ITEM-17.2 ready (subject: vsf.<id>.s4.anticipatory_directive, SYNTHETIC)");

                // γ.6 — Invariant checker (VAR-1, TRUST-1, ALG-1)
                let invariants = std::sync::Arc::new(
                    InvariantChecker::new(canon.clone(), system_id.clone())
                );
                println!("[invariants] checker ready (VAR-1, TRUST-1, ALG-1)");

                // P.2 — Periodic invariant_check sampler (every 60s).
                // Emits canonical event with snapshot of all 3 invariants.
                let _invariant_sampler = invariants
                    .clone()
                    .start_sampler_task(60);
                println!("[invariants] periodic sampler ready (60s)");

                // γ.4 — Algedonic gate (uses invariants for ALG-1 + baseline)
                // W2 — Arc-wrapped so the supervised tick can fire it on Lyapunov divergence.
                let algedonic = std::sync::Arc::new(AlgedonicGate::new(
                    canon.clone(),
                    invariants.clone(),
                    system_id.clone(),
                    /* recursion_level */ 0,
                ));
                println!("[algedonic] gate ready (binary, rate-limited)");

                // γ.8 — Observability light (health.json + systemd watchdog)
                let reporter = std::sync::Arc::new(HealthReporter::new(&system_id));
                let _health_writer = reporter.clone().start_writer_task();
                let _watchdog = start_watchdog_task();
                println!("[observability] health.json + watchdog ready");

                // β.4 — Wrap the canonical emit loop under Supervisor(S1)
                // If the emit loop panics, the supervisor restarts it (with cooldown).
                // This keeps S5 (covenant + algedonic) untouched per VSL clausura L=0.
                let supervisor = Supervisor::new();
                // W4 — base time-constant for the σ-adaptive tick (Δt = C/(1+σ²), floored).
                let canon_base_secs = canon_interval.max(1) as f64;
                let health = reporter.handle();
                let s1_canon = canon.clone();
                let s1_system_id = system_id.clone();
                let s1_health = health.clone();
                // fix_3 — synthetic load feed so invariant_check shows non-zero
                // samples (validates VAR-1/TRUST-1/stasis sensor path). Marked
                // synthetic; replaced by real S1 (BBH) variety when integrated.
                let s1_invariants = invariants.clone();
                let s1_algedonic = algedonic.clone();  // W2
                let s3_effector = live_config.clone(); // DEBT_S3b — S3 auto-effector writes s4_cycle_interval
                // covenant_halt_flag captured by the Fn closure below; cloned fresh each call inside

                let _supervised_emitter = supervisor.spawn_supervised(
                    SubsystemSpec::new(Subsystem::S1),
                    move || {
                        let canon = s1_canon.clone();
                        let system_id = s1_system_id.clone();
                        let health = s1_health.clone();
                        let invariants = s1_invariants.clone();
                        let algedonic = s1_algedonic.clone();  // W2
                        let s3_config = s3_effector.clone(); // DEBT_S3b
                        let viability_sig = s1_viability_signal.clone(); // DEBT_S1
                        let caution_sig = s5_caution_flag.clone(); // ITEM_4.1 M3
                        let halt_for_checker = covenant_halt_flag.clone(); // DEBT_S5 — fresh clone each Fn call
                        async move {
                            // ── F5.x.9 — L+4 read-only sensor layer, wired live ──────
                            // Reads real hardware/cgroup sensors each tick and PROJECTS
                            // them into Block B of a live ℝ¹²⁸ StateVector. Ax_HardwareCeiling:
                            // read-only — no φ↓/write path to hardware exists. Replaces the
                            // prior synthetic constants ("read-only that should be writing").
                            let ingest_cg = std::env::var("VSF_INGEST_CGROUP")
                                .unwrap_or_else(|_| "/sys/fs/cgroup".to_string());
                            let hw = HardwareIngest::new(ingest_cg);
                            // Live state: seed governance dims (Block A) healthy so the Ω box
                            // constraints on trust/governed/lifecycle hold; ingest owns Block B.
                            let mut state = StateVector::new();
                            for i in TRUST_HIST_0..=TRUST_HIST_9 { state.dims[i] = 1.0; }
                            state.dims[GOVERNED] = 1.0;
                            state.dims[LIFECYCLE] = 1.0;
                            state.dims[STASIS_COS] = 0.98;
                            // W1 — live kernel dynamics: a persistent stepper + stasis reference.
                            // Each tick advances the validated relaxation attractor (λ_max=ln(0.99)),
                            // giving real moving stasis_cos/L instead of the old synthetic constants.
                            // TELEMETRY-PORTS P1 (q2 wire, default ON): feed StateDb → Block A/B
                            // — el kernel siente su propia cola (unanestesia, ALGEDONIC-INTEGRATION).
                            // Kill-switch VSF_FEEDERS=paused / status:paused → fallback declarado;
                            // sin state.db → error→fallback (feeders.rs, nunca valor inventado).
                            let mut stepper = KernelStepper::new()
                                .with_feeder(crate::feeders::Dispatcher::state_db_from_env());
                            // EXP-SEN-01 (env-gated): adaptive resting entropy for the senescence run.
                            // Default OFF ⇒ stepper stays in its byte-identical mode (the kernel hook is
                            // gated; this only flips it on). See docs/experiments/senescence_adaptive/spec.vsm.
                            let exp_adaptive_hrest = std::env::var("VSF_EXP_ADAPTIVE_HREST").is_ok();
                            if exp_adaptive_hrest {
                                stepper.enable_adaptive_h_rest();
                                println!("[EXP-SEN-01] adaptive H_rest ENABLED — senescence run (drift logged every 1000 ticks)");
                            }
                            let mut stasis = StasisVec::new();
                            // W2 — recurrent-set certifier: the live `governed` predicate over the L-trajectory.
                            let mut lyap_cert = RecurrentSetCertifier::new();
                            // W3 — windowed VR topological monitor (bounded N; VR is O(n³)).
                            const VR_WINDOW: usize = 32;
                            const VR_EVERY: u64 = 64;
                            let mut traj_window: VecDeque<StateVector> = VecDeque::with_capacity(VR_WINDOW);
                            let mut vr_b0: usize = 1;   // cached between computations (every VR_EVERY ticks)
                            let mut vr_b1: usize = 0;
                            // D4-L1 topology_response: ticks of 8× cadence remaining after a topology break.
                            let mut vr_cadence_boost: u64 = 0;
                            // D4-L2 lyapunov_trust_modulation: track regime across ticks for change detection.
                            let mut prev_regime_str: &str = "unknown";
                            // W4 — σ-adaptive tick clock (one σ slot for this S1 emitter). σ is driven
                            // by the live drift of the L-trajectory; SeqLock σ_global + retry_rate give
                            // the T4.sub1 contention signal. Drives the tick Δt below.
                            let clock = AdaptiveClock::new(1);
                            // W4 — real VAR-1 (Ashby): incoming hardware variety (Δ Block-B pressures)
                            // absorbed vs variety reaching the regulated core (Δ stasis_cos). Needs the
                            // previous tick's values → None on the first tick (recorded as neutral 0.0).
                            let mut prev_pressures: Option<(f64, f64, f64)> = None;
                            let mut prev_stasis_cos: Option<f64> = None;
                            // A2 ALGEDONIC-SUBSET (S5 2026-10-08 "todo aprobado"):
                            // viability→pain bridge — track prev state to detect collapse.
                            // viable=true→false transition OR omega_margin < threshold ⇒ pain.
                            let mut prev_viable: Option<bool> = None;
                            let mut prev_omega_margin: f64 = f64::MAX;
                            const MARGIN_PAIN_THRESHOLD: f64 = 0.10;  // margin below this = pain
                            let mut projector = Projector::new();  // ITEM_13.2
                            // ITEM_13.3 — predictive_alert gate: max 1 per ALERT_GATE_TICKS (30 min)
                            let mut predictive_alert_last_tick: u64 = 0;
                            // DEBT_S3 — S3 auto-controller state machine.
                            // Separates S3-auto (routine, in-nucleus) from S3-Claude (exceptional, human).
                            // S3-auto acts when degrading_streak >= trigger; recommends param adjustment.
                            // S3-Claude escalation when projection confidence high + sustained degradation.
                            let mut s3_degrading_streak: u64 = 0;
                            let mut s3_recovering_streak: u64 = 0;
                            let mut s3_escalation_last_tick: u64 = 0;
                            // DEBT_S5 — S5 covenant checker (proactive, sync, per-tick).
                            // Shares halt_flag with the async resume subscriber (Arc<AtomicBool>).
                            let mut covenant = crate::s5_covenant::CovenantChecker::new(
                                halt_for_checker.clone()
                            );
                            // A01-01 — Covenant violation detector (heuristic v12, 100% accuracy, <1ms)
                            // Reads recent events from events.jsonl (tmpfs) and classifies violations.
                            // Writes to dims[53] (A0) and dims[54] (A0.1) when violations detected.
                            #[cfg(feature = "covenant_detector")]
                            let covenant_detector = CovenantViolationDetector::new();
                            #[cfg(feature = "covenant_detector")]
                            {
                                println!("[A01-01] covenant detector v12 ENABLED (heuristic, 100% accuracy on 800-stream corpus)");
                            }
                            const S3_FAST_TRIGGER_TICKS: u64 = 3;      // 3 consecutive degrading → fast mode
                            const S3_RESTORE_TICKS: u64 = 5;           // 5 consecutive non-degrading → restore
                            const S3_ESCALATION_GATE_TICKS: u64 = 60;  // max 1 human escalation per ~hour
                            const S3_ESCALATION_CONFIDENCE: f64 = 0.40; // projection must be meaningful
                            const ALERT_STASIS_THRESHOLD: f64 = 0.80;   // below → threshold_breach
                            const ALERT_LOAD_CORR_THRESHOLD: f64 = -0.70; // anticorrelated → load_anticorrelated
                            const ALERT_MIN_CONFIDENCE: f64 = 0.10;     // projection must be meaningful
                            const ALERT_GATE_TICKS: u64 = 30;           // ~30 min at 60s cadence
                            // S3* shadow_recompute precondition: sample 1-in-K ticks (Beer: non-predictable cadence)
                            const SHADOW_SAMPLE_K: u64 = 20;
                            // DSN-COUPLE-01 3b — manifest-driven sensor registry. Loaded ONCE
                            // (parse + B∪B' validation + lazy B' allocation). Empty-dir-safe:
                            // with no manifests it is a no-op. With manifests, load_bearing
                            // B'-mapped in-nucleus sensors project into the StateVector each tick;
                            // the inventory summary rides φ↑ (additive — kernel.* unaffected).
                            let coupling_reg = crate::coupling_registry::SensorRegistry::load_default();
                            {
                                let s = coupling_reg.summary();
                                println!("[coupling_registry] {} manifest(s), {} sensor(s): \
                                    {} load_bearing, {} in-nucleus, {} deferred, B' dims {:?}, {} rejection(s)",
                                    s.manifests, s.sensors, s.load_bearing, s.in_nucleus,
                                    s.deferred, s.bprime_assigned, s.rejections);
                            }
                            // M9 — per-axis trust state (trust_axes.rs wiring). ADDITIVE
                            // telemetry: kout.trust (the phase-A scalar) is untouched.
                            let mut trust_vec = TrustVector::uniform(1.0);
                            let mut prev_h_t: Option<f64> = None;
                            let mut prev_emit_ok = true;

                            // ── run_4 experiment harness (EXP-TRUST-01) — all no-op when env unset ──
                            // Real-loop trust measurement: bound the run, window a per-axis breach,
                            // optionally collapse the clock. Prod (all unset) is byte-for-byte unchanged.
                            let exp_max_ticks: u64 = std::env::var("VSF_EXP_MAX_TICKS")
                                .ok().and_then(|v| v.parse().ok()).unwrap_or(0);
                            let exp_breach_until: u64 = std::env::var("VSF_EXP_BREACH_UNTIL")
                                .ok().and_then(|v| v.parse().ok()).unwrap_or(0);
                            // VSF_EXP_BREACH_FROM (EXP-TRUST-01 F-R4-3 fix): delay the breach onset
                            // until the regime classifier settles. Unset (=0) ⇒ breach from tick 1.
                            let exp_breach_from: u64 = std::env::var("VSF_EXP_BREACH_FROM")
                                .ok().and_then(|v| v.parse().ok()).unwrap_or(0);
                            let exp_breach_axis = std::env::var("VSF_EXP_BREACH_AXIS").unwrap_or_default();
                            let exp_fast = std::env::var("VSF_EXP_FAST").is_ok();
                            let exp_sigma: f64 = std::env::var("VSF_SOPLO_SIGMA")
                                .ok().and_then(|v| v.parse().ok()).unwrap_or(0.10);
                            let mut exp_rng = ExpXorshift::new(0xE4_0000_0000_0004u64);
                            if exp_max_ticks > 0 {
                                println!("[run_4] harness ON: max_ticks={} breach_axis={:?} breach_from={} breach_until={} fast={} sigma={}",
                                    exp_max_ticks, exp_breach_axis, exp_breach_from, exp_breach_until, exp_fast, exp_sigma);
                            }

                            // ── KERNEL_START: emit once at boot with active feature flags ──
                            {
                                let mut active_features: Vec<&str> = Vec::new();
                                if cfg!(feature = "omega_margin_telemetry") { active_features.push("omega_margin_telemetry"); }
                                if cfg!(feature = "exp_s5_01") { active_features.push("exp_s5_01"); }
                                active_features.sort();
                                let kernel_info = serde_json::json!({
                                    "active_features": active_features,
                                });
                                if let Err(e) = canon.emit(CanonicalEvent {
                                    ts: String::new(),
                                    system_id: system_id.clone(),
                                    event_type: "kernel_start".to_string(),
                                    status: "ok".to_string(),
                                    signal_status: "startup".to_string(),
                                    duration_s: 0.0,
                                    metrics: kernel_info,
                                    variety_delta: None,
                                    trust_score: None,
                                    algedonic_seq: 0,
                                    origin: None,
                                    chain_format_version: None,
                                    prev_hash: None,
                                    hash: None,
                                }) {
                                    eprintln!("[kernel_start] emit failed: {} (kernel continues)", e);
                                } else {
                                    println!("[kernel_start] ✓ features={:?}", active_features);
                                }
                            }

                            let mut tick: u64 = 0;
                            loop {
                                tick = tick.wrapping_add(1);
                                // run_4: bounded-run gate. Ticks 1..=max have fully emitted telemetry
                                // (per-tick canonical write happens earlier in the body), so exiting at
                                // tick = max+1 leaves exactly `max` durable rows on events.jsonl.
                                if exp_max_ticks > 0 && tick > exp_max_ticks {
                                    // The canonical writer fsyncs each event to tmpfs immediately but a
                                    // background task copies tmpfs → disk only every 100ms. Wait one flush
                                    // window so events.jsonl on disk holds all `max` ticks before we exit.
                                    tokio::time::sleep(Duration::from_millis(300)).await;
                                    println!("[run_4] reached VSF_EXP_MAX_TICKS={} — experiment complete", exp_max_ticks);
                                    std::process::exit(0);
                                }
                                // run_4: tick-windowed per-axis breach (env-gated; prod = no breach).
                                // Window = [exp_breach_from, exp_breach_until]; from=0 ⇒ from tick 1.
                                let exp_breach_active = breach_active(tick, exp_breach_from, exp_breach_until);
                                let exp_structural_breach = exp_breach_active && exp_breach_axis == "structural";
                                // CALIBRATE-TRUST (2026-07-03): extend breach injection to all 4 axes.
                                //   predictive    → force regime observation to Diverging
                                //   communicative → force prev_emit_ok to false (emit failure)
                                // All breach injections use the same tick window
                                // [exp_breach_from, exp_breach_until] via exp_breach_active.
                                let exp_predictive_breach = exp_breach_active && exp_breach_axis == "predictive";
                                let exp_communicative_breach = exp_breach_active && exp_breach_axis == "communicative";
                                // D4 typed events — populated when L2 classes fire, empty most ticks.
                                let mut l2_events: Vec<serde_json::Value> = Vec::new();

                                // φ↑ — read s4_clima_bundle.json for kernel_tick metrics (PHI-UP-READER)
                                // Returns ClimaBundleFields::unavailable() on any error (absent/stale/corrupt)
                                let bundle_path = clima_bundle_path();
                                let clima = read_clima_bundle(&bundle_path, S4_CLIMA_BUNDLE_MAX_AGE_SECS)
                                    .unwrap_or_else(ClimaBundleFields::unavailable);

                                // W4b — real-load FEEDBACK (S5-ratified Option A, effective temperature):
                                // the pressure ingested LAST tick (already in Block B of `state`) modulates
                                // THIS tick's equilibrium via kT_eff = 1 + γ·pressure. 1-tick delay (≪ the
                                // 60s cadence); first tick = 0 (fresh state) ⇒ baseline. Ingest stays
                                // read-only — this only reads the already-present Block-B dims.
                                let load_pressure = (state.dims[crate::state_vector::CPU_PRESSURE]
                                    + state.dims[crate::state_vector::MEM_PRESSURE]
                                    + state.dims[crate::state_vector::IO_PRESSURE]) / 3.0;
                                // W1 — advance the real kernel dynamics (writes Blocks A/C/D/G + internal B,
                                // observes stasis). Block B is then overwritten by real ingest below.
                                let kout = stepper.step(&mut state, &mut stasis, load_pressure);
                                lyap_cert.observe(kout.l_x);  // W2 — feed the live L-trajectory
                                // EXP-SEN-01: log the senescence signal (drift of the resting set-point)
                                // every 1000 ticks. Captured by run_A/run_B's log redirect; no-op in prod.
                                if exp_adaptive_hrest && tick % 1000 == 0 {
                                    println!("[EXP-SEN-01] tick={} pressure={:.4} h_rest={:.5} h_rest_ref={:.5} \
                                        drift={:.6} warmup_done={} stasis_cos={:.5}",
                                        tick, load_pressure, stepper.h_rest(), stepper.h_rest_ref(),
                                        stepper.h_rest_drift(), stepper.warmup_done(), kout.stasis_cos);
                                }

                                // S3* shadow_recompute: snapshot state+stasis vectors RIGHT AFTER step()
                                // so sampled_state_vector EXACTLY matches the state over which the nucleus
                                // computed stasis_cos. Must happen BEFORE ingest (L759+) overwrites Block B.
                                // Moved here per q4 SEMANTIC-DIVERGENCE-FIX — fixes the tick-phase ordering
                                // artifact where captured vectors diverged from claimed_cos.
                                let (shadow_sv, shadow_st) = if tick % SHADOW_SAMPLE_K == 0 && stasis.n_observations() > 0 {
                                    let sv_vals: Vec<f64> = state.dims.to_vec();
                                    let st_vals: Vec<f64> = stasis.current.dims.to_vec();
                                    (serde_json::json!(sv_vals), serde_json::json!(st_vals))
                                } else {
                                    (serde_json::Value::Null, serde_json::Value::Null)
                                };

                                // F5.x.9 — read sensors (φ↑) → project into Block B.
                                let obs = hw.read_all();
                                let cert = obs.certify_boundary();
                                let written = obs.project_into_state(&mut state);
                                // DSN-COUPLE-01 3b — project manifest load_bearing B'-mapped
                                // in-nucleus sensors into B∪B' alongside hardware ingest, so the
                                // governed dims feed the SAME-tick Ω / dynamics. No-op while no
                                // manifest claims a B' dim (the prod-today case). Deferred
                                // read-kinds (exec/http/nats) are skipped here by construction.
                                let coupling_written = coupling_reg.read_and_project(&mut state);

                                // P3a — S5 ethics wire: read dims[53/54] from A0_classifier watchdog.
                                // Watchdog writes /run/vsf/ethics_signal.json atomically (tmpfs).
                                // Conservative fallback: absent or stale (>30s) → dims stay 0.0.
                                // No LLM on this path (R10). Direct tmpfs read, zero proxy layers.
                                {
                                    const ETHICS_SIGNAL_PATH: &str = "/run/vsf/ethics_signal.json";
                                    const ETHICS_TTL_S: f64 = 30.0;
                                    if let Ok(raw) = std::fs::read_to_string(ETHICS_SIGNAL_PATH) {
                                        if let Ok(sig) = serde_json::from_str::<serde_json::Value>(&raw) {
                                            let now_s = std::time::SystemTime::now()
                                                .duration_since(std::time::UNIX_EPOCH)
                                                .map(|d| d.as_secs_f64())
                                                .unwrap_or(0.0);
                                            if now_s - sig["ts"].as_f64().unwrap_or(0.0) < ETHICS_TTL_S {
                                                state.dims[crate::state_vector::PURPOSE_PROHIBITED] =
                                                    sig["a0"].as_f64().unwrap_or(0.0).clamp(0.0, 1.0);
                                                state.dims[crate::state_vector::COERCION_INDICATOR] =
                                                    sig["a01"].as_f64().unwrap_or(0.0).clamp(0.0, 1.0);
                                            }
                                        }
                                    }
                                }

                                // A01-01 — Covenant violation detector (heuristic v12, in-nucleus)
                                // Reads last N events from events.jsonl (tmpfs) and classifies violations.
                                // Writes to dims[53] (A0) and dims[54] (A0.1) when violations detected.
                                // This is the FAST PATH (<1ms) — no LLM dependency, deterministic rules.
                                #[cfg(feature = "covenant_detector")]
                                {
                                    use std::path::PathBuf;
                                    use crate::telemetry_canonical::TMPFS_ROOT;
                                    
                                    let events_path = PathBuf::from(TMPFS_ROOT)
                                        .join(&system_id)
                                        .join("events.jsonl");
                                    
                                    let violation = covenant_detector.classify_recent_events(
                                        &events_path,
                                        10  // last 10 events
                                    );
                                    
                                    match violation {
                                        ViolationType::A0Violation => {
                                            state.dims[crate::state_vector::PURPOSE_PROHIBITED] = 1.0;
                                            eprintln!("[A01-01] A0 violation detected (dims[53]=1.0)");
                                        }
                                        ViolationType::A01Violation => {
                                            state.dims[crate::state_vector::COERCION_INDICATOR] = 1.0;
                                            eprintln!("[A01-01] A0.1 violation detected (dims[54]=1.0)");
                                        }
                                        ViolationType::Clean => {
                                            // No violation, dims stay as-is (may be set by P3a ethics wire)
                                        }
                                    }
                                }

                                // Phase 3a (DSN-COUPLE-01) — NET is a bounded blind spot (no Block B
                                // dim free); read it from the Observation for φ↑ telemetry only.
                                let net_err_drop = obs.readings.iter()
                                    .find(|r| matches!(r.source, SensorSource::NetErrDrop))
                                    .and_then(|r| r.normalized);

                                // ITEM_13.0 — env_sample L2 event: Shannon-regime external channel.
                                // Contains PSI pressures + cpu_temp + loadavg — the signals that are
                                // epistemically INDEPENDENT of the system (observer ≠ observed, Shannon).
                                // S4 consumes this channel separately from the internal φ↑ (vonFoerster).
                                let env_cpu_temp_c = obs.readings.iter()
                                    .find(|r| matches!(r.source, SensorSource::CpuTemp))
                                    .and_then(|r| r.raw);
                                let env_loadavg_1m = obs.readings.iter()
                                    .find(|r| matches!(r.source, SensorSource::LoadAvg1m))
                                    .and_then(|r| r.raw);
                                l2_events.push(serde_json::json!({
                                    "kind": "env_sample",
                                    "regime": "shannon",
                                    "cpu_pressure": state.dims[CPU_PRESSURE],
                                    "mem_pressure": state.dims[MEM_PRESSURE],
                                    "io_pressure": state.dims[IO_PRESSURE],
                                    "cpu_temp_c": env_cpu_temp_c,
                                    "loadavg_1m": env_loadavg_1m,
                                }));


                                // DEBT_S1 — update S1 viability signal for phi_down gate.
                                // phi_down_subscriber reads this to reject governance-reducing
                                // patches when the system is in a degraded state.
                                viability_sig.store(
                                    f64::to_bits(kout.stasis_cos),
                                    std::sync::atomic::Ordering::Relaxed,
                                );

                                // ITEM_13.2 + 13.3 — projector push, projection_tick L2 event,
                                // and predictive_alert emission (S4→S5 anticipatory channel).
                                projector.push(TwinPoint {
                                    tick,
                                    stasis_cos: kout.stasis_cos,
                                    h_t: kout.h_t,
                                    loadavg_1m: env_loadavg_1m,
                                    cpu_temp_c: env_cpu_temp_c,
                                });
                                let proj = projector.project();
                                {
                                    let proj_sc = if proj.projected_stasis_cos.is_nan() {
                                        serde_json::Value::Null
                                    } else {
                                        serde_json::json!(proj.projected_stasis_cos)
                                    };
                                    let load_corr = if proj.load_correlation.is_nan() {
                                        serde_json::Value::Null
                                    } else {
                                        serde_json::json!(proj.load_correlation)
                                    };
                                    l2_events.push(serde_json::json!({
                                        "kind": "projection_tick",
                                        "regime": proj.regime.as_str(),
                                        "projected_stasis_cos": proj_sc,
                                        "horizon_ticks": proj.horizon_ticks,
                                        "trend_slope": proj.trend_slope,
                                        "load_correlation": load_corr,
                                        "r_squared": proj.r_squared,
                                        "confidence": proj.confidence,
                                        "n_points": proj.n_points,
                                    }));
                                }

                                // ITEM_13.3 — predictive_alert: S4→S5 anticipatory channel.
                                // Distinct from algedonic_emit (S1→S5, reactive): this is forward-looking.
                                // Triggered by projection; rate-limited by ALERT_GATE_TICKS.
                                {
                                    let has_data = proj.n_points >= crate::projector::PROJ_MIN_POINTS
                                        && proj.confidence >= ALERT_MIN_CONFIDENCE;
                                    let trigger_degrading = has_data && proj.regime.as_str() == "degrading";
                                    let trigger_threshold = has_data
                                        && !proj.projected_stasis_cos.is_nan()
                                        && proj.projected_stasis_cos < ALERT_STASIS_THRESHOLD;
                                    let trigger_load = has_data
                                        && !proj.load_correlation.is_nan()
                                        && proj.load_correlation < ALERT_LOAD_CORR_THRESHOLD;
                                    let gate_open = tick.saturating_sub(predictive_alert_last_tick) >= ALERT_GATE_TICKS;

                                    if gate_open && (trigger_degrading || trigger_threshold || trigger_load) {
                                        predictive_alert_last_tick = tick;
                                        let trigger_reason = if trigger_degrading { "degrading_trend" }
                                            else if trigger_threshold { "threshold_breach" }
                                            else { "load_anticorrelated" };

                                        // Estimate crossing tick: when does projected stasis_cos hit threshold?
                                        let projected_crossing_tick = if proj.trend_slope < 0.0 {
                                            let ticks_remaining = (kout.stasis_cos - ALERT_STASIS_THRESHOLD)
                                                / (-proj.trend_slope);
                                            if ticks_remaining > 0.0 {
                                                Some(tick + ticks_remaining as u64)
                                            } else { None }
                                        } else { None };

                                        let alert_event = CanonicalEvent {
                                            ts: String::new(), // canonical writer sets this
                                            system_id: system_id.clone(),
                                            event_type: "predictive_alert".to_string(),
                                            status: "warn".to_string(),
                                            signal_status: "anticipatory".to_string(),
                                            duration_s: 0.0,
                                            metrics: serde_json::json!({
                                                "trigger": trigger_reason,
                                                "regime": proj.regime.as_str(),
                                                "projected_stasis_cos": if proj.projected_stasis_cos.is_nan() { serde_json::Value::Null } else { serde_json::json!(proj.projected_stasis_cos) },
                                                "projected_crossing_tick": projected_crossing_tick,
                                                "current_stasis_cos": kout.stasis_cos,
                                                "trend_slope": proj.trend_slope,
                                                "load_correlation": if proj.load_correlation.is_nan() { serde_json::Value::Null } else { serde_json::json!(proj.load_correlation) },
                                                "confidence": proj.confidence,
                                                "n_points": proj.n_points,
                                                "horizon_ticks": proj.horizon_ticks,
                                                "channel": "von_foerster+shannon",
                                                "_note": "S4→S5 anticipatory — not reactive algedonic"
                                            }),
                                            variety_delta: None,
                                            trust_score: None,
                                            algedonic_seq: 0,
                                            origin: None,
                                            chain_format_version: None,
                                            prev_hash: None,
                                            hash: None,
                                        };
                                        if let Err(e) = canon.emit(alert_event) {
                                            eprintln!("[ITEM_13.3] predictive_alert emit failed: {} (tick continues)", e);
                                        } else {
                                            println!("[predictive_alert] tick={} trigger={} proj_sc={:.4} crossing={:?}",
                                                tick, trigger_reason,
                                                if proj.projected_stasis_cos.is_nan() { 0.0 } else { proj.projected_stasis_cos },
                                                projected_crossing_tick);
                                        }
                                    }
                                }

                                // DEBT_S3 — S3 auto-controller: streak-based regime classification.
                                // Separates S3-auto (routine, automatable between sessions) from
                                // S3-Claude (exceptional, requires human deliberation).
                                // Beer: S3 = inside-and-now. This brings S3 inside the tick loop.
                                {
                                    let regime_str = proj.regime.as_str();
                                    // Update streaks based on current projection regime
                                    match regime_str {
                                        "degrading" if proj.confidence >= 0.20 => {
                                            s3_degrading_streak += 1;
                                            s3_recovering_streak = 0;
                                        }
                                        "recovering" | "stable" => {
                                            s3_recovering_streak += 1;
                                            s3_degrading_streak = 0;
                                        }
                                        _ => {} // insufficient_data — hold streaks
                                    }

                                    let s3_fast_mode = s3_degrading_streak >= S3_FAST_TRIGGER_TICKS;
                                    // Emit restore decision only on the transition tick (== not >)
                                    let s3_restore = s3_recovering_streak == S3_RESTORE_TICKS;

                                    // ITEM_4.1 M3 — S5 caution mode gate.
                                    // When S5 signals caution (high-severity algedonic), all
                                    // autonomous S3 actions are suspended. Beer: S5 can veto S3.
                                    let s5_caution_active = caution_sig.load(std::sync::atomic::Ordering::Acquire);

                                    // S3-auto decision: emit s3_decision L2 event when action needed.
                                    // Gated by (1) S5 caution mode or (2) DEBT_S5 covenant halt.
                                    // Both represent S5 veto; covenant halt is the stronger form
                                    // (requires explicit operator resume, not auto-expiry).
                                    let covenant_halted = covenant.is_halted();
                                    if s3_fast_mode || s3_restore {
                                        if s5_caution_active || covenant_halted {
                                            let hold_kind = if covenant_halted { "s3_covenant_hold" } else { "s3_caution_hold" };
                                            let hold_note = if covenant_halted {
                                                "DEBT_S5: S5 covenant HALT — S3 autonomy suspended until operator resumes"
                                            } else {
                                                "ITEM_4.1 M3: S5 caution mode active — autonomous S3 action suspended"
                                            };
                                            l2_events.push(serde_json::json!({
                                                "kind": hold_kind,
                                                "blocked_action": if s3_fast_mode { "s4_interval_fast" } else { "s4_interval_restore" },
                                                "degrading_streak": s3_degrading_streak,
                                                "recovering_streak": s3_recovering_streak,
                                                "proj_regime": regime_str,
                                                "covenant_halted": covenant_halted,
                                                "caution_active": s5_caution_active,
                                                "_note": hold_note,
                                            }));
                                        } else {
                                            let s3_action = if s3_fast_mode { "s4_interval_fast" } else { "s4_interval_restore" };
                                            let new_interval: u32 = if s3_fast_mode { 60 } else { 300 };
                                            // DEBT_S3b: apply decision — S4 reads live_config at each cycle start.
                                            if let Ok(mut cfg) = s3_config.write() {
                                                cfg.s4_cycle_interval_secs = new_interval;
                                            }
                                            l2_events.push(serde_json::json!({
                                                "kind": "s3_decision",
                                                "action": s3_action,
                                                "s4_interval_applied_s": new_interval,
                                                "degrading_streak": s3_degrading_streak,
                                                "recovering_streak": s3_recovering_streak,
                                                "proj_regime": regime_str,
                                                "proj_confidence": proj.confidence,
                                                "authority": "s3_auto",
                                            }));
                                        }
                                    }

                                    // S3-Claude escalation: emit standalone canonical event when
                                    // sustained degradation + high confidence → human S3 needed.
                                    // Caution mode does NOT suppress escalation — it amplifies urgency.
                                    let needs_escalation = proj.n_points >= crate::projector::PROJ_MIN_POINTS
                                        && proj.confidence >= S3_ESCALATION_CONFIDENCE
                                        && s3_degrading_streak >= S3_FAST_TRIGGER_TICKS
                                        && tick.saturating_sub(s3_escalation_last_tick) >= S3_ESCALATION_GATE_TICKS;

                                    if needs_escalation {
                                        s3_escalation_last_tick = tick;
                                        let proj_sc_val = if proj.projected_stasis_cos.is_nan() {
                                            serde_json::Value::Null
                                        } else {
                                            serde_json::json!(proj.projected_stasis_cos)
                                        };
                                        let escalation_event = CanonicalEvent {
                                            ts: String::new(),
                                            system_id: system_id.clone(),
                                            event_type: "s3_escalation".to_string(),
                                            status: "warn".to_string(),
                                            signal_status: "requires_claude_s3".to_string(),
                                            duration_s: 0.0,
                                            metrics: serde_json::json!({
                                                "degrading_streak": s3_degrading_streak,
                                                "proj_regime": regime_str,
                                                "projected_stasis_cos": proj_sc_val,
                                                "confidence": proj.confidence,
                                                "trend_slope": proj.trend_slope,
                                                "recommended_action": "investigate_sustained_degradation",
                                                "_note": "DEBT_S3: S3-Claude escalation — beyond auto-range, human deliberation needed"
                                            }),
                                            variety_delta: None,
                                            trust_score: None,
                                            algedonic_seq: 0,
                                            origin: None,
                                            chain_format_version: None,
                                            prev_hash: None,
                                            hash: None,
                                        };
                                        if let Err(e) = canon.emit(escalation_event) {
                                            eprintln!("[DEBT_S3] s3_escalation emit failed: {} (tick continues)", e);
                                        } else {
                                            println!("[s3_escalation] tick={} streak={} confidence={:.3} — S3-Claude needed",
                                                tick, s3_degrading_streak, proj.confidence);
                                        }
                                    }
                                }

                                // DEBT_S5 — S5 covenant invariant check (per-tick, sync, proactive).
                                // INV_ESCALATION: stasis_cos < 0.80 for ≥ 45 ticks without escalation
                                // → S5 HALT: covenant flag set; S3 auto-decisions blocked until operator resume.
                                // Emits s5_covenant_violation canonical + algedonic (urgent human signal).
                                if let Some(v) = covenant.record_tick(
                                    kout.stasis_cos, s3_escalation_last_tick, tick
                                ) {
                                    let cov_event = CanonicalEvent {
                                        ts: String::new(),
                                        system_id: system_id.clone(),
                                        event_type: "s5_covenant_violation".to_string(),
                                        status: "halt".to_string(),
                                        signal_status: v.name().to_string(),
                                        duration_s: 0.0,
                                        metrics: serde_json::json!({
                                            "violation": v.name(),
                                            "detail": v.detail(),
                                            "stasis_cos": kout.stasis_cos,
                                            "tick": tick,
                                            "_note": "DEBT_S5: S5 covenant HALT — S3 suspended; resume via vsf.<id>.s5.covenant_resume"
                                        }),
                                        variety_delta: None,
                                        trust_score: None,
                                        algedonic_seq: 0,
                                        origin: None,
                                        chain_format_version: None,
                                        prev_hash: None,
                                        hash: None,
                                    };
                                    if let Err(e) = canon.emit(cov_event) {
                                        eprintln!("[s5-covenant] violation emit failed: {} (halt still set)", e);
                                    } else {
                                        println!("[s5-covenant] *** HALT *** {} tick={} stasis_cos={:.4}",
                                            v.name(), tick, kout.stasis_cos);
                                    }
                                    let _ = algedonic.try_emit("s5_covenant_violation", serde_json::json!({
                                        "violation": v.name(), "detail": v.detail(),
                                        "stasis_cos": kout.stasis_cos,
                                    }));
                                }

                                // F5.x.4 — live Ω-membership viability check. Ω holds
                                // Box<dyn Constraint> (!Send) so it is built and dropped
                                // inside this block — never held across the .await below.
                                let (viable, omega_margin, omega_margin_free, omega_margin_binding, omega_margin_entropy) = {
                                    let omega = Omega::canonical();
                                    (omega.is_member(&state),
                                     omega.min_distance_to_boundary(&state),
                                     omega.margin_free(&state),
                                     omega.margin_free_binding(&state).0.to_string(),
                                     omega.margin_entropy(&state))
                                };

                                // W2 — Cor_GovernedDefinition: certify governed over the L-trajectory ∧ Ω.
                                let lcert = lyap_cert.certify(viable);
                                let regime_str = match lcert.regime {
                                    Regime::InRecurrentSet => "in_recurrent_set",
                                    Regime::ContractingToR => "contracting_to_R",
                                    Regime::Diverging => "diverging",
                                    Regime::Unknown => "unknown",
                                };
                                // Diverging (above core, not contracting) ⇒ recurrent set drifting → degrade
                                // (lyapunov_proof §167). Rate-limited by the gate.
                                if matches!(lcert.regime, Regime::Diverging) {
                                    let _ = algedonic.try_emit("lyapunov_diverging", serde_json::json!({
                                        "mean_dl": lcert.mean_dl, "mean_l": lcert.mean_l,
                                        "epsilon": lcert.epsilon, "stasis_cos": kout.stasis_cos,
                                    }));
                                }

                                // A2 ALGEDONIC-SUBSET — viability→pain bridge (ALGEDONIC-INTEGRATION.bridge_designed).
                                // viable=true→false transition OR omega_margin collapse (< threshold) ⇒ pain.
                                // Feeds on real queue/absorption from P1 feeders (unanestesia — the kernel
                                // now feels its own queue). Rate-limited by the algedonic gate.
                                if let Some(prev) = prev_viable {
                                    if prev && !viable {
                                        let _ = algedonic.try_emit("viability_collapse", serde_json::json!({
                                            "viable": viable,
                                            "omega_margin": omega_margin,
                                            "stasis_cos": kout.stasis_cos,
                                            "trust": kout.trust,
                                            "h_t": kout.h_t,
                                            "prev_stasis_cos": prev_stasis_cos,
                                        }));
                                    }
                                }
                                if omega_margin < MARGIN_PAIN_THRESHOLD
                                    && prev_omega_margin >= MARGIN_PAIN_THRESHOLD
                                {
                                    let _ = algedonic.try_emit("margin_collapse", serde_json::json!({
                                        "omega_margin": omega_margin,
                                        "prev_omega_margin": prev_omega_margin,
                                        "threshold": MARGIN_PAIN_THRESHOLD,
                                        "margin_free": omega_margin_free,
                                        "margin_entropy": omega_margin_entropy,
                                    }));
                                }
                                prev_viable = Some(viable);
                                prev_omega_margin = omega_margin;

                                // W3 — windowed VR topological monitor: β₀/β₁ over the recent trajectory.
                                // β₀>1 (basin split) or β₁>0 (loop) ⇒ topology break → algedonic. Computed
                                // every VR_EVERY ticks normally; D4-L1 topology_response collapses to 8 ticks
                                // for 256 ticks after a break (increased sensitivity, no state modification).
                                if traj_window.len() == VR_WINDOW { traj_window.pop_front(); }
                                traj_window.push_back(state.clone());
                                let vr_effective_every = if vr_cadence_boost > 0 { 8 } else { VR_EVERY };
                                if tick % vr_effective_every == 0 && traj_window.len() == VR_WINDOW {
                                    let pts: Vec<StateVector> = traj_window.iter().cloned().collect();
                                    let betti = VrComplex::from_points_cosine(&pts, VR_EPSILON_COSINE).betti();
                                    vr_b0 = betti.b0;
                                    vr_b1 = betti.b1;
                                    if !betti.viability_signal() {
                                        let _ = algedonic.try_emit("vr_topology_break", serde_json::json!({
                                            "b0": betti.b0, "b1": betti.b1, "window": VR_WINDOW,
                                        }));
                                        if vr_cadence_boost == 0 {
                                            vr_cadence_boost = 256;
                                            l2_events.push(serde_json::json!({
                                                "class": "topology_response",
                                                "trigger": format!("b0={} b1={}", betti.b0, betti.b1),
                                                "cadence_before": VR_EVERY,
                                                "cadence_after": 8,
                                                "boost_ticks": 256,
                                            }));
                                        }
                                    }
                                }
                                if vr_cadence_boost > 0 { vr_cadence_boost -= 1; }

                                // W4 — real VAR-1 (Ashby variety law). ΔV_in = incoming hardware
                                // variety this tick (|Δ| of the real ingested Block-B pressures);
                                // ΔV_out = variety that reached the regulated core (|Δ stasis_cos|).
                                // variety_delta = ΔV_in − ΔV_out ≥ 0 ⇔ the regulator absorbed at least
                                // what it leaked. Real (live ingest + live kernel) — no longer synthetic.
                                let cur_press = (
                                    state.dims[CPU_PRESSURE],
                                    state.dims[MEM_PRESSURE],
                                    state.dims[IO_PRESSURE],
                                );
                                let dv_in = match prev_pressures {
                                    Some((c, m, i)) => (cur_press.0 - c).abs()
                                        + (cur_press.1 - m).abs()
                                        + (cur_press.2 - i).abs(),
                                    None => 0.0,
                                };
                                let dv_out = match prev_stasis_cos {
                                    Some(s) => (kout.stasis_cos - s).abs(),
                                    None => 0.0,
                                };
                                let variety_delta = dv_in - dv_out;
                                prev_pressures = Some(cur_press);
                                prev_stasis_cos = Some(kout.stasis_cos);

                                // W4 — σ-adaptive tick. σ from the live drift of the L-trajectory, but only
                                // the part that EXCEEDS the calibrated zero-band: inside the recurrent set
                                // mean_dl is ≤ LYAP_DRIFT_BAND (stationary fluctuation) ⇒ σ = 0 ⇒ Δt = baseline
                                // (steady-state cadence unchanged). Genuine drift (mean_dl ≫ band) grows σ ⇒
                                // Δt = C/(1+σ²) shortens, floored at C/CLOCK_MAX_SPEEDUP so the canonical
                                // chain is never flooded. SeqLock σ_global exercises T4.sub1.
                                let sigma = (lcert.mean_dl - LYAP_DRIFT_BAND).max(0.0) * SIGMA_DRIFT_GAIN;
                                clock.set_sigma(0, sigma);
                                let sigma_global = clock.sigma_global();
                                let dt_secs = dt_from_sigma(canon_base_secs, sigma_global)
                                    .clamp(canon_base_secs / CLOCK_MAX_SPEEDUP, canon_base_secs);
                                let tick_dt = Duration::from_secs_f64(dt_secs);

                                // M9 — Def_TrustUpdate per tick: EMA toward the per-axis
                                // observation with shared adaptive λ from ΔH (per-axis λ_i
                                // are EXP-TRUST-01 phase-B calibration targets).
                                // run_4: behavioral breach degrades the REAL behavioral observation
                                // (kernel_trust signal) with tick-windowed Gaussian noise. The kernel
                                // dynamics are untouched; only the observation the trust-vector sees is
                                // perturbed — symmetric with the structural breach. Prod = clean signal.
                                let kt_obs = if exp_breach_active && exp_breach_axis == "behavioral" {
                                    (kout.trust + exp_sigma * exp_rng.gaussian()).clamp(0.0, 1.0)
                                } else {
                                    kout.trust
                                };
                                // CALIBRATE-TRUST: inject predictive/communicative breaches at the
                                // observation level (symmetric with structural/behavioral injection).
                                let t_obs_regime = if exp_predictive_breach { Regime::Diverging } else { lcert.regime };
                                let t_obs_emit = if exp_communicative_breach { false } else { prev_emit_ok };
                                let trust_obs = trust_observation(
                                    kt_obs,
                                    cert.all_bounded,
                                    t_obs_regime,
                                    t_obs_emit,
                                    exp_structural_breach,
                                );
                                let trust_lambda = trust_axes::adaptive_lambda(
                                    prev_h_t.map(|p| kout.h_t - p).unwrap_or(0.0),
                                    stepper.h_max,
                                );
                                trust_vec = trust_vec.update(&trust_obs, trust_lambda);
                                prev_h_t = Some(kout.h_t);

                                // D4-L2 class: lyapunov_trust_modulation
                                // Writes composite trust floor to LIFECYCLE (regime-responsive).
                                state.dims[LIFECYCLE] = trust_vec.min_axis();
                                if regime_str != prev_regime_str {
                                    l2_events.push(serde_json::json!({
                                        "class": "lyapunov_trust_modulation",
                                        "trigger": regime_str,
                                        "predictive_after": trust_vec.predictive,
                                        "min_axis_after": trust_vec.min_axis(),
                                        "lifecycle_written": trust_vec.min_axis(),
                                    }));
                                    prev_regime_str = regime_str;
                                }

                                let metrics = serde_json::json!({
                                    "tick": tick,
                                    "_note": "γ canonical kernel_tick — W1 live dynamics + F5.x.9 ingest (Block B) + F5.x.4 Ω + W4 adaptive clock/variety",
                                    "kernel": {
                                        "stasis_cos": kout.stasis_cos,
                                        "l_x": kout.l_x,
                                        "h_t": kout.h_t,
                                        "trust": kout.trust,
                                        "entropy_phase": kout.entropy_phase,
                                        "viable": kout.viable,
                                        // ITEM_15: published so S5 (LXC 104) can independently
                                        // compute covenant invariant without trusting S3 self-report.
                                        "s3_escalation_last_tick": s3_escalation_last_tick,
                                    },
                                    "trust_axes": {
                                        "behavioral": trust_vec.behavioral,
                                        "structural": trust_vec.structural,
                                        "predictive": trust_vec.predictive,
                                        "communicative": trust_vec.communicative,
                                        "scalar": trust_vec.scalar(),
                                        "min_axis": trust_vec.min_axis(),
                                        "lambda": trust_lambda,
                                        // run_4 — perturbation provenance for the H_TRUST analyzer
                                        "breach_active": exp_breach_active,
                                        "breach_axis": if exp_breach_active { &exp_breach_axis } else { "none" },
                                        "phase": if exp_breach_active { "breach" } else { "recovery" },
                                        "kernel_trust_raw": kout.trust,
                                        "kernel_trust_obs": kt_obs,
                                    },
                                    "coupling_registry": {
                                        "inventory": coupling_reg.summary().to_json(),
                                        "projected_dims": coupling_written,
                                    },
                                    "ingest": {
                                        "dims_written": written,
                                        "boundary_bounded": cert.all_bounded,
                                        "unread": cert.unread.iter().map(|s| s.name()).collect::<Vec<_>>(),
                                        "cpu_pressure": state.dims[CPU_PRESSURE],
                                        "mem_pressure": state.dims[MEM_PRESSURE],
                                        "io_pressure": state.dims[IO_PRESSURE],
                                        "cgroup_headroom": state.dims[CGROUP_HEADROOM],
                                        "net_err_drop": net_err_drop,
                                    },
                                    "omega": { "viable": viable, "margin": omega_margin, "margin_free": omega_margin_free, "margin_binding": omega_margin_binding, "margin_entropy": omega_margin_entropy },
                                    "lyapunov": {
                                        "governed": lcert.governed,
                                        "regime": regime_str,
                                        "mean_dl": lcert.mean_dl,
                                        "epsilon": lcert.epsilon,
                                        "mean_l": lcert.mean_l,
                                    },
                                    "vr": { "b0": vr_b0, "b1": vr_b1, "viability_signal": vr_b0 == 1 && vr_b1 == 0 },
                                    "clock": {
                                        "sigma": sigma_global,
                                        "dt_secs": dt_secs,
                                        "base_secs": canon_base_secs,
                                        "retry_rate": clock.retry_rate(),
                                    },
                                    "variety": { "delta": variety_delta, "dv_in": dv_in, "dv_out": dv_out },
                                    // φ↑ — s1-clima domain context (PHI-UP-READER)
                                    "s1_clima": {
                                        "available": clima.available,
                                        "stasis_cos": clima.stasis_cos,
                                        "viability": clima.viability,
                                        "regime": clima.regime,
                                        "algedonic": clima.algedonic,
                                        "refreshed_at": clima.refreshed_at,
                                        "systems": clima.systems,
                                    },
                                    "l2_events": l2_events,
                                    // S3* tier3 shadow_recompute: null on non-sampled ticks, arrays on sampled
                                    "sampled_state_vector": shadow_sv,
                                    "sampled_stasis_vec": shadow_st,
                                });
                                match canon.emit_kernel_tick(&system_id, metrics) {
                                    Ok(h) => {
                                        prev_emit_ok = true;  // M9 communicative-axis signal
                                        HealthReporter::record_event_hash(&health, h);
                                    }
                                    Err(e) => {
                                        prev_emit_ok = false;
                                        eprintln!("[canonical] emit error: {}", e);
                                    }
                                }
                                HealthReporter::record_telemetry(&health);

                                // W1 — trust + stasis are REAL (live kernel dynamics).
                                // W4 — variety is now REAL too: Ashby ΔV_in−ΔV_out over the live ingest
                                // + kernel state. No synthetic samples remain in the invariant path.
                                let _ = invariants.record_variety(variety_delta);
                                let _ = invariants.record_trust(kout.trust);
                                invariants.record_stasis_cos(kout.stasis_cos);

                                // γ.9 — Main-thread liveness poke for NUCLEUS-WATCHDOG-HARDENING.
                                // Records wall-clock timestamp read by the watchdog thread. Must
                                // be AFTER all tick work (ingest → kernel_step → lyapunov → VR →
                                // projector → S3 → covenant → Ω → trust → emit) and BEFORE the
                                // adaptive sleep, so the timestamp reflects completed work, not
                                // idle waiting between ticks.
                                report_tick_completed();

                                // W4 — σ-adaptive sleep: baseline cadence in steady state, faster under drift.
                                // run_4: VSF_EXP_FAST collapses the sleep so a bounded experiment runs
                                // in seconds instead of minutes. Prod (unset) keeps the real adaptive clock.
                                if exp_fast {
                                    tokio::task::yield_now().await;
                                } else {
                                    tokio::time::sleep(tick_dt).await;
                                }
                            }
                        }
                    },
                );
                println!("[supervisor] S1 (canonical emit) under supervision");

                // Keep the runtime alive — supervisor JoinHandle drives the loop.
                let _ = _supervised_emitter.await;
            });
        });

        // Keep main thread alive
        loop {
            thread::sleep(Duration::from_secs(60));
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// M9 — trust_axes wiring tests (observation extractor mapping)
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod trust_axes_wiring_tests {
    use super::*;

    #[test]
    fn nominal_signals_give_full_trust_observation() {
        let o = trust_observation(1.0, true, Regime::InRecurrentSet, true, false);
        assert_eq!(o.as_array(), [1.0, 1.0, 1.0, 1.0]);
    }

    #[test]
    fn each_axis_tracks_only_its_own_signal() {
        let o = trust_observation(0.6, false, Regime::Diverging, false, false);
        assert!((o.behavioral - 0.6).abs() < 1e-12);
        assert_eq!(o.structural, 0.0);
        assert_eq!(o.predictive, 0.0);
        assert_eq!(o.communicative, 0.0);
        // axis disjointness at the extractor level: lifting one signal
        // does not lift the others (H_TRUST1 precondition)
        let o2 = trust_observation(0.6, true, Regime::Diverging, false, false);
        assert_eq!(o2.structural, 1.0);
        assert_eq!(o2.predictive, 0.0);
        assert_eq!(o2.communicative, 0.0);
    }

    #[test]
    fn structural_breach_param_forces_zero_and_keeps_purity() {
        // run_4: the breach is now a caller-supplied parameter (D6-pure), not an env read.
        // With breach=true, structural_obs is forced to 0 even when boundary_bounded=true,
        // and the OTHER axes are untouched (perturbation stays on its own axis).
        let breached = trust_observation(1.0, true, Regime::InRecurrentSet, true, true);
        assert_eq!(breached.structural, 0.0, "breach must zero structural");
        assert_eq!(breached.behavioral, 1.0);
        assert_eq!(breached.predictive, 1.0);
        assert_eq!(breached.communicative, 1.0);
        // breach=false with the same inputs leaves structural at the boundary value (1.0).
        let clean = trust_observation(1.0, true, Regime::InRecurrentSet, true, false);
        assert_eq!(clean.structural, 1.0);
    }

    #[test]
    fn breach_window_respects_from_and_until() {
        // until==0 ⇒ disabled (prod default): never active regardless of from.
        assert!(!breach_active(1, 0, 0));
        assert!(!breach_active(50, 50, 0));
        // from unset (==0) ⇒ active from the first tick through `until`, inclusive.
        // This is the exact pre-VSF_EXP_BREACH_FROM behavior (backward compatible).
        assert!(breach_active(1, 0, 300));
        assert!(breach_active(300, 0, 300));
        assert!(!breach_active(301, 0, 300));
        // from==50 ⇒ breach delayed until the regime classifier settles (F-R4-3 fix).
        assert!(!breach_active(49, 50, 300), "before window: no breach");
        assert!(breach_active(50, 50, 300), "inclusive lower bound");
        assert!(breach_active(175, 50, 300), "inside window");
        assert!(breach_active(300, 50, 300), "inclusive upper bound");
        assert!(!breach_active(301, 50, 300), "past window: recovery phase");
    }

    #[test]
    fn predictive_axis_follows_regime_ladder() {
        let p = |r| trust_observation(1.0, true, r, true, false).predictive;
        assert!(p(Regime::InRecurrentSet) > p(Regime::ContractingToR));
        assert!(p(Regime::ContractingToR) > p(Regime::Unknown));
        assert!(p(Regime::Unknown) > p(Regime::Diverging));
    }

    #[test]
    fn ema_update_converges_toward_degraded_observation() {
        // Simulate the loop: nominal start, then sustained structural failure.
        let mut tv = TrustVector::uniform(1.0);
        let obs = trust_observation(1.0, false, Regime::InRecurrentSet, true, false);
        for _ in 0..40 {
            tv = tv.update(&obs, 0.1);
        }
        // structural decays toward 0; the other axes stay at 1.0
        assert!(tv.structural < 0.05, "structural should decay: {}", tv.structural);
        assert!(tv.behavioral > 0.99);
        assert!(tv.communicative > 0.99);
        // scalar reflects the degradation, min_axis pins the weakest
        assert!(tv.scalar() < 0.8);
        assert!((tv.min_axis() - tv.structural).abs() < 1e-12);
    }
}
