/// s5_covenant.rs — DEBT_S5 — S5 as active governor with veto (Beer: S5 can HALT, not just alert)
///
/// Difference from algedonic/caution:
///   algedonic = reactive alert triggered by severity threshold (S5 may respond)
///   caution   = S5 suspends S3 autonomy after receiving high-severity signal
///   covenant  = S5 checks operational invariants proactively; violation → HALT S3 autonomy
///               HALT persists until rmw3 explicitly resumes via NATS s5.covenant_resume
///
/// Beer: "S5 defines the identity and ethos — the conditions of possibility.
///        Without veto, S5 is merely a suggestion."
///
/// Invariants checked every tick:
///   INV_ESCALATION: stasis_cos < COVENANT_DEGRADED_THRESHOLD for ≥ HALT_AFTER_DEGRADED ticks
///                   AND last escalation was > ESCALATION_GRACE_TICKS ago
///                   → S3 has been autonomously adjusting while degraded without alerting S5
///                   → S5 steps in: halt S3 autonomy, require human deliberation
///
/// Clear path:
///   Operator publishes any payload to vsf.<id>.s5.covenant_resume (NATS).
///   start_resume_subscriber() watches this subject and clears the flag.
///   Cleared as a D4-L2 action: logged to φ↑ as s5_covenant_resumed.
///
/// Fail-safe: NATS unreachable → resume listener disabled; halt is cleared on
/// nucleus restart (no phantom veto on isolation — same pattern as caution_mode).

use crate::telemetry_canonical::{CanonicalEvent, CanonicalTelemetry};
use chrono::Utc;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

// ── Thresholds ───────────────────────────────────────────────────────────────

/// stasis_cos below this → tick is counted as degraded for covenant purposes.
/// EXP-S5-01: override to 1.0 — any sc < 1.0 is "degraded" (always true after tick 1).
/// Previous attempt: 0.998 → attractor self-corrects before streak=5 (H_S501_null confirmed).
/// 1.0 guarantees streak accumulates regardless of attractor strength. Mechanism test only.
#[cfg(not(feature = "exp_s5_01"))]
pub const COVENANT_DEGRADED_THRESHOLD: f64 = 0.80;
#[cfg(feature = "exp_s5_01")]
pub const COVENANT_DEGRADED_THRESHOLD: f64 = 1.0;

/// Halt S3 autonomy after this many consecutive degraded ticks with no escalation
/// (45 ticks × ~57s/tick ≈ 43 min sustained degradation)
/// EXP-S5-01: reduced to 5 so halt fires within ~5 minutes of experiment start.
#[cfg(not(feature = "exp_s5_01"))]
pub const HALT_AFTER_DEGRADED: usize = 45;
#[cfg(feature = "exp_s5_01")]
pub const HALT_AFTER_DEGRADED: usize = 5;

/// Grace window: if an escalation fired within this many ticks, don't halt
/// (must be ≥ S3_ESCALATION_GATE_TICKS = 60; we use 90 for safety margin)
/// EXP-S5-01: reduced to 3 so the grace constraint never blocks the test.
#[cfg(not(feature = "exp_s5_01"))]
pub const ESCALATION_GRACE_TICKS: u64 = 90;
#[cfg(feature = "exp_s5_01")]
pub const ESCALATION_GRACE_TICKS: u64 = 3;

// ── Violation type ───────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub enum CovenantViolation {
    /// S3 has been in degraded regime for too long without escalating to S5.
    /// INV_ESCALATION: A5 ceiling — S3 must not autonomously manage extended degradation.
    MissedEscalation {
        degraded_streak: usize,
        ticks_since_escalation: u64,
    },
}

impl CovenantViolation {
    pub fn name(&self) -> &'static str {
        match self {
            Self::MissedEscalation { .. } => "missed_escalation",
        }
    }

    pub fn detail(&self) -> String {
        match self {
            Self::MissedEscalation { degraded_streak, ticks_since_escalation } => format!(
                "S3 autonomous for {} ticks in degraded regime (sc<{:.2}); {} ticks since last escalation — A5 ceiling breached",
                degraded_streak, COVENANT_DEGRADED_THRESHOLD, ticks_since_escalation
            ),
        }
    }
}

// ── Halt flag ────────────────────────────────────────────────────────────────

/// Shared halt flag: S3 auto-decisions check this before executing.
/// Set by CovenantChecker on violation; cleared by start_resume_subscriber().
pub type CovenantHaltFlag = Arc<AtomicBool>;

pub fn new_halt_flag() -> CovenantHaltFlag {
    Arc::new(AtomicBool::new(false))
}

// ── Checker ──────────────────────────────────────────────────────────────────

pub struct CovenantChecker {
    pub halt_flag: CovenantHaltFlag,
    consecutive_degraded: usize,
    already_halted: bool,
}

impl CovenantChecker {
    pub fn new(halt_flag: CovenantHaltFlag) -> Self {
        Self {
            halt_flag,
            consecutive_degraded: 0,
            already_halted: false,
        }
    }

    /// Called every kernel tick (synchronous, cheap — no I/O).
    ///
    /// Arguments:
    ///   stasis_cos              — current tick's stasis_cos
    ///   s3_escalation_last_tick — tick when S3 last emitted an escalation event (0 if never)
    ///   current_tick            — current tick counter
    ///
    /// Returns Some(violation) on first detection; None when healthy or already halted.
    /// Caller must emit s5_covenant_violation canonical event on Some().
    pub fn record_tick(
        &mut self,
        stasis_cos: f64,
        s3_escalation_last_tick: u64,
        current_tick: u64,
    ) -> Option<CovenantViolation> {
        let degraded = stasis_cos < COVENANT_DEGRADED_THRESHOLD;
        if degraded {
            self.consecutive_degraded += 1;
        } else {
            self.consecutive_degraded = 0;
        }

        // Already halted — don't re-trigger (one canonical event per halt episode)
        if self.already_halted || self.halt_flag.load(Ordering::Acquire) {
            self.already_halted = true;
            return None;
        }

        // INV_ESCALATION: prolonged degradation without escalation to S5
        if self.consecutive_degraded >= HALT_AFTER_DEGRADED {
            let ticks_since = current_tick.saturating_sub(s3_escalation_last_tick);
            if ticks_since > ESCALATION_GRACE_TICKS {
                self.halt_flag.store(true, Ordering::Release);
                self.already_halted = true;
                let v = CovenantViolation::MissedEscalation {
                    degraded_streak: self.consecutive_degraded,
                    ticks_since_escalation: ticks_since,
                };
                eprintln!(
                    "[s5-covenant] *** HALT *** INV_ESCALATION: {} ticks degraded, {} since escalation — S3 autonomy suspended",
                    self.consecutive_degraded, ticks_since
                );
                return Some(v);
            }
        }

        None
    }

    pub fn is_halted(&self) -> bool {
        self.halt_flag.load(Ordering::Acquire)
    }

    /// Clear halt state (called by resume_subscriber when operator resumes).
    /// Resets streak so a fresh degradation cycle starts clean.
    pub fn resume(&mut self) {
        self.halt_flag.store(false, Ordering::Release);
        self.already_halted = false;
        self.consecutive_degraded = 0;
        eprintln!("[s5-covenant] halt cleared — S3 autonomy restored");
    }
}

// ── Resume subscriber ─────────────────────────────────────────────────────────

/// Spawn a NATS subscriber for `vsf.<id>.s5.covenant_resume`.
/// On receipt: clears the halt flag and emits s5_covenant_resumed to φ↑.
/// Fail-soft: NATS_URL unset → disabled (no phantom veto on isolation).
pub fn start_resume_subscriber(
    vsf_id: &str,
    halt_flag: CovenantHaltFlag,
    canon: CanonicalTelemetry,
) -> tokio::task::JoinHandle<()> {
    let vsf_id = vsf_id.to_string();
    tokio::spawn(async move {
        use futures::StreamExt;
        use std::env;

        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!("[s5-covenant] NATS_URL unset — resume subscriber disabled");
                return;
            }
        };
        let subject = format!("vsf.{}.s5.covenant_resume", vsf_id);
        eprintln!("[s5-covenant] resume subscriber: {}", subject);

        loop {
            match vsf_agent::nats::connect(&url, "s5-covenant-resume").await {
                Ok(client) => match client.subscribe(subject.clone()).await {
                    Ok(mut sub) => {
                        while let Some(msg) = sub.next().await {
                            let reason = std::str::from_utf8(&msg.payload)
                                .unwrap_or("operator_resume")
                                .to_string();
                            halt_flag.store(false, Ordering::Release);
                            eprintln!("[s5-covenant] RESUMED via NATS — reason: {}", reason);
                            let event = CanonicalEvent {
                                ts: Utc::now()
                                    .to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                system_id: vsf_id.clone(),
                                event_type: "s5_covenant_resumed".to_string(),
                                status: "ok".to_string(),
                                signal_status: "operator_resume".to_string(),
                                duration_s: 0.0,
                                metrics: serde_json::json!({
                                    "reason": reason,
                                    "_note": "DEBT_S5: S5 covenant halt cleared by operator (D4-L2)"
                                }),
                                variety_delta: None,
                                trust_score: None,
                                algedonic_seq: 0,
                                origin: None,
                                chain_format_version: None,
                                prev_hash: None,
                                hash: None,
                            };
                            if let Err(e) = canon.emit(event) {
                                eprintln!("[s5-covenant] resume emit failed: {} (non-fatal)", e);
                            }
                        }
                        eprintln!("[s5-covenant] subscription ended — reconnecting");
                    }
                    Err(e) => eprintln!("[s5-covenant] subscribe error: {} — retrying", e),
                },
                Err(e) => {
                    eprintln!("[s5-covenant] connect failed: {} — retrying in 10s", e);
                }
            }
            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
        }
    })
}

// ── External halt subscriber (ITEM_15) ───────────────────────────────────────

/// Spawn a NATS subscriber for `vsf.<id>.s5.covenant_halt`.
///
/// ITEM_15: S5 authority separated from S3. vsf-s5-covenant (LXC 104) independently
/// monitors nucleus state and publishes to this subject when it detects a violation.
/// The nucleus sets its halt_flag on receipt — S5 imposes halt from OUTSIDE S3.
///
/// Beer: the custodian cannot be the custodianed. When S3 and S5 share a process,
/// covenant enforcement is a convention, not a constraint. External enforcement
/// makes it a real constraint: a captured/compromised S3 cannot suppress its own halt.
///
/// Fail-soft: NATS_URL unset → subscriber disabled; in-process CovenantChecker
/// remains as fallback so production behavior is unchanged if NATS is unavailable.
pub fn start_halt_subscriber(
    vsf_id: &str,
    halt_flag: CovenantHaltFlag,
    canon: CanonicalTelemetry,
) -> tokio::task::JoinHandle<()> {
    let vsf_id = vsf_id.to_string();
    tokio::spawn(async move {
        use futures::StreamExt;
        use std::env;

        let url = match env::var("NATS_URL").ok().filter(|u| !u.is_empty()) {
            Some(u) => u,
            None => {
                eprintln!(
                    "[s5-covenant] NATS_URL unset — external halt subscriber disabled \
                     (in-process checker remains as sole enforcer)"
                );
                return;
            }
        };
        let subject = format!("vsf.{}.s5.covenant_halt", vsf_id);
        eprintln!("[s5-covenant] ITEM_15 external halt subscriber: {}", subject);

        loop {
            match vsf_agent::nats::connect(&url, "s5-covenant-halt").await {
                Ok(client) => match client.subscribe(subject.clone()).await {
                    Ok(mut sub) => {
                        eprintln!("[s5-covenant] external halt ready — S5 authority on LXC 104");
                        while let Some(msg) = sub.next().await {
                            let reason = std::str::from_utf8(&msg.payload)
                                .unwrap_or("s5_external")
                                .to_string();
                            halt_flag.store(true, Ordering::Release);
                            eprintln!(
                                "[s5-covenant] *** EXTERNAL HALT *** from S5 (LXC 104): {}",
                                reason
                            );
                            let event = CanonicalEvent {
                                ts: Utc::now()
                                    .to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                system_id: vsf_id.clone(),
                                event_type: "s5_covenant_halt_external".to_string(),
                                status: "halt".to_string(),
                                signal_status: "s5_external".to_string(),
                                duration_s: 0.0,
                                metrics: serde_json::json!({
                                    "source":  "s5_external",
                                    "reason":  reason,
                                    "_note":   "ITEM_15: halt imposed by S5 (LXC 104) — authority separated from S3 (LXC 101)"
                                }),
                                variety_delta: None,
                                trust_score: None,
                                algedonic_seq: 0,
                                origin: None,
                                chain_format_version: None,
                                prev_hash: None,
                                hash: None,
                            };
                            if let Err(e) = canon.emit(event) {
                                eprintln!(
                                    "[s5-covenant] halt event emit failed: {} (halt_flag already set)",
                                    e
                                );
                            }
                        }
                        eprintln!("[s5-covenant] external halt subscription ended — reconnecting");
                    }
                    Err(e) => eprintln!("[s5-covenant] halt subscribe({}): {} — retry", subject, e),
                },
                Err(e) => {
                    eprintln!("[s5-covenant] halt connect failed: {} — retry 10s", e);
                }
            }
            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
        }
    })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn checker() -> CovenantChecker {
        CovenantChecker::new(new_halt_flag())
    }

    #[test]
    fn healthy_system_no_halt() {
        let mut c = checker();
        for tick in 0..100 {
            let r = c.record_tick(0.99, 0, tick);
            assert!(r.is_none(), "healthy system should not halt");
        }
        assert!(!c.is_halted());
    }

    #[test]
    fn degraded_with_recent_escalation_no_halt() {
        let mut c = checker();
        // degrade for HALT_AFTER_DEGRADED ticks but escalation happened at tick 40
        for tick in 0..60u64 {
            let r = c.record_tick(0.50, 40, tick);
            assert!(r.is_none(), "recent escalation should prevent halt (tick {})", tick);
        }
        assert!(!c.is_halted());
    }

    #[test]
    fn prolonged_degradation_no_escalation_triggers_halt() {
        let mut c = checker();
        let mut halted_at = None;
        for tick in 0..200u64 {
            // escalation last fired at tick 0 (never, effectively)
            if let Some(v) = c.record_tick(0.50, 0, tick) {
                halted_at = Some((tick, v));
                break;
            }
        }
        let (tick, v) = halted_at.expect("should have halted");
        assert!(c.is_halted());
        // Binding constraint: ticks_since(0) > ESCALATION_GRACE_TICKS AND streak >= HALT_AFTER_DEGRADED.
        // Grace (90) > threshold (45), so grace binds: halt fires at tick > ESCALATION_GRACE_TICKS.
        let min_expected = ESCALATION_GRACE_TICKS;
        assert!(tick >= min_expected, "halt at tick {} < min expected {}", tick, min_expected);
        assert_eq!(v.name(), "missed_escalation");
    }

    #[test]
    fn halt_fires_only_once() {
        let mut c = checker();
        let mut halt_count = 0;
        for tick in 0..500u64 {
            if c.record_tick(0.50, 0, tick).is_some() {
                halt_count += 1;
            }
        }
        assert_eq!(halt_count, 1, "covenant violation should fire exactly once per episode");
    }

    #[test]
    fn resume_clears_halt_and_resets_streak() {
        let mut c = checker();
        // force a halt
        for tick in 0..200u64 {
            c.record_tick(0.50, 0, tick);
            if c.is_halted() { break; }
        }
        assert!(c.is_halted());
        c.resume();
        assert!(!c.is_halted());
        // after resume, healthy ticks should not re-halt
        for tick in 200..300u64 {
            let r = c.record_tick(0.99, tick, tick);
            assert!(r.is_none());
        }
    }

    #[test]
    fn boundary_at_threshold_is_not_degraded() {
        // sc == COVENANT_DEGRADED_THRESHOLD → NOT degraded (strict <).
        // Production threshold = 0.80. sc=0.80 must not accumulate streak.
        let mut c = checker();
        for tick in 0..200u64 {
            let r = c.record_tick(COVENANT_DEGRADED_THRESHOLD, 0, tick);
            assert!(r.is_none(), "sc == threshold should not count as degraded (tick {})", tick);
        }
        assert!(!c.is_halted());
    }

    #[test]
    fn just_below_threshold_accumulates_streak() {
        // sc = threshold - ε → degraded. With HALT_AFTER_DEGRADED=45 ticks, halt fires.
        let sc_just_below = COVENANT_DEGRADED_THRESHOLD - f64::EPSILON * 1000.0; // safely below
        let mut c = checker();
        let mut halted = false;
        for tick in 0..200u64 {
            if c.record_tick(sc_just_below, 0, tick).is_some() {
                halted = true;
                break;
            }
        }
        assert!(halted, "sc just below threshold should eventually trigger halt");
        assert!(c.is_halted());
    }

    #[test]
    fn recovery_resets_streak_before_threshold() {
        let mut c = checker();
        // degrade for HALT_AFTER_DEGRADED - 10 ticks, then recover
        for tick in 0..(HALT_AFTER_DEGRADED as u64 - 10) {
            let r = c.record_tick(0.50, 0, tick);
            assert!(r.is_none());
        }
        // recover — streak should reset
        c.record_tick(0.99, 0, HALT_AFTER_DEGRADED as u64);
        // degrade again: needs another full HALT_AFTER_DEGRADED to trigger
        let mut halted = false;
        for tick in (HALT_AFTER_DEGRADED as u64 + 1)..(HALT_AFTER_DEGRADED as u64 + 40) {
            if c.record_tick(0.50, 0, tick).is_some() {
                halted = true;
                break;
            }
        }
        assert!(!halted, "streak should have reset on recovery — not enough degraded ticks yet");
    }
}
