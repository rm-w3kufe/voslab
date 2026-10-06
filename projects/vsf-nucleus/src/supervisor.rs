/// supervisor.rs — β.4 — Tokio supervision tree for VSM subsystem isolation
///
/// @vsm 0.3
/// canonical: per Qwen consensus ronda 4 — replaces incorrect `catch_unwind` plan
///
/// CRITICAL CORRECTION FROM ROUND 4:
///   `std::panic::catch_unwind` only captures SYNC panics. Tokio tasks (async)
///   abort silently on panic and the supervisor never knows. To preserve VSL
///   clausura L=0 (S1 panic must not kill S5), we need:
///
///     1. Each subsystem runs as a tokio::task::JoinHandle (not std::thread)
///     2. AbortOnPanic guard: tokio task that panicked propagates via JoinError::is_panic
///     3. State checkpoint pre-spawn: restartable state captured
///     4. Supervision loop: on JoinError(panic), restart with checkpointed state
///     5. S5 panic → terminal (full halt + algedonic) per covenant
///
/// Design principle: "núcleo primero" — only tokio + std. No supervision crate.
///
/// Subsystem classification (per per_system_requirements_method.md):
///   S1 (Operations)  → restartable, fresh state on restart
///   S2 (Coordination) → restartable, may restore previous coord policy
///   S3 (Control)     → restartable, restore from S5 policy
///   S3* (Audit)      → restartable, sporadic ok
///   S4 (Intelligence) → restartable, LLM stateless anyway
///   S5 (Policy)      → TERMINAL on panic (covenant breach signal)

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::task::{JoinError, JoinHandle};

/// VSM subsystem identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Subsystem {
    S1,
    S2,
    S3,
    S3Star,
    S4,
    S5,
}

impl Subsystem {
    pub fn as_str(&self) -> &'static str {
        match self {
            Subsystem::S1 => "S1",
            Subsystem::S2 => "S2",
            Subsystem::S3 => "S3",
            Subsystem::S3Star => "S3*",
            Subsystem::S4 => "S4",
            Subsystem::S5 => "S5",
        }
    }

    /// S5 panics are terminal — they cannot be restarted because covenant integrity
    /// must be verified by external authority (human + witnesses).
    pub fn is_terminal_on_panic(&self) -> bool {
        matches!(self, Subsystem::S5)
    }
}

/// Outcome of a subsystem task.
#[derive(Debug)]
pub enum TaskOutcome {
    /// Task completed normally (ran to completion).
    Completed,
    /// Task panicked. JoinError contains diagnostic info.
    Panicked(JoinError),
    /// Task was cancelled by supervisor.
    Cancelled,
}

/// Configuration for one subsystem under supervision.
pub struct SubsystemSpec {
    pub id: Subsystem,
    /// Maximum consecutive restarts before declaring the subsystem failed.
    pub max_restarts: u32,
    /// Cooldown between restarts (exponential up to this max).
    pub restart_cooldown_max: Duration,
}

impl SubsystemSpec {
    pub fn new(id: Subsystem) -> Self {
        Self {
            id,
            max_restarts: 5,
            restart_cooldown_max: Duration::from_secs(30),
        }
    }
}

/// A checkpoint captures restartable subsystem state.
/// For now this is opaque JSON; concrete subsystems can serialize anything.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Checkpoint(pub serde_json::Value);

/// Health report per subsystem.
#[derive(Debug, Clone, Default, Serialize)]
pub struct SubsystemHealth {
    pub running: bool,
    pub restart_count: u32,
    pub last_outcome: Option<String>,
}

/// Supervisor manages a tree of subsystem tasks.
///
/// API:
///   spawn_supervised<F, Fut>(spec, factory) where factory returns the task future.
///   Returns a JoinHandle to a supervisor loop that:
///     1. Awaits the task.
///     2. On panic: increment restart_count, sleep cooldown, re-invoke factory.
///     3. On Completed: log + stop supervising.
///     4. If restart_count > max_restarts OR subsystem is_terminal: emit terminal signal.
pub struct Supervisor {
    health: Arc<Mutex<HashMap<Subsystem, SubsystemHealth>>>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            health: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn health_handle(&self) -> Arc<Mutex<HashMap<Subsystem, SubsystemHealth>>> {
        self.health.clone()
    }

    /// Spawn a supervised subsystem. `factory` is called once per attempt — it must
    /// return a fresh future capable of running the subsystem from its current state.
    ///
    /// The supervisor task itself is what gets returned; cancelling it cancels the chain.
    pub fn spawn_supervised<F, Fut>(
        &self,
        spec: SubsystemSpec,
        factory: F,
    ) -> JoinHandle<TaskOutcome>
    where
        F: Fn() -> Fut + Send + Sync + 'static,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let health = self.health.clone();
        let id = spec.id;
        let is_terminal = id.is_terminal_on_panic();

        tokio::spawn(async move {
            let mut restart_count: u32 = 0;

            loop {
                // Update health: marking as running
                {
                    let mut h = health.lock().await;
                    h.insert(
                        id,
                        SubsystemHealth {
                            running: true,
                            restart_count,
                            last_outcome: None,
                        },
                    );
                }

                let fut = factory();
                let join = tokio::spawn(fut);

                match join.await {
                    Ok(()) => {
                        // Completed normally — supervision ends.
                        let mut h = health.lock().await;
                        h.insert(
                            id,
                            SubsystemHealth {
                                running: false,
                                restart_count,
                                last_outcome: Some("Completed".to_string()),
                            },
                        );
                        return TaskOutcome::Completed;
                    }
                    Err(e) if e.is_cancelled() => {
                        let mut h = health.lock().await;
                        h.insert(
                            id,
                            SubsystemHealth {
                                running: false,
                                restart_count,
                                last_outcome: Some("Cancelled".to_string()),
                            },
                        );
                        return TaskOutcome::Cancelled;
                    }
                    Err(e) => {
                        // Panic captured via JoinError::is_panic
                        eprintln!(
                            "[supervisor] {} panicked (restart_count={}): {}",
                            id.as_str(),
                            restart_count,
                            e
                        );
                        if is_terminal {
                            // S5 panic → terminal, supervisor exits with Panicked
                            eprintln!(
                                "[supervisor] {} is TERMINAL — covenant must verify before any restart",
                                id.as_str()
                            );
                            let mut h = health.lock().await;
                            h.insert(
                                id,
                                SubsystemHealth {
                                    running: false,
                                    restart_count,
                                    last_outcome: Some(format!("PanickedTerminal: {}", e)),
                                },
                            );
                            return TaskOutcome::Panicked(e);
                        }
                        restart_count += 1;
                        if restart_count > spec.max_restarts {
                            eprintln!(
                                "[supervisor] {} exceeded max_restarts ({}); giving up",
                                id.as_str(),
                                spec.max_restarts
                            );
                            let mut h = health.lock().await;
                            h.insert(
                                id,
                                SubsystemHealth {
                                    running: false,
                                    restart_count,
                                    last_outcome: Some(format!("PanickedMaxRestarts: {}", e)),
                                },
                            );
                            return TaskOutcome::Panicked(e);
                        }
                        // Exponential cooldown, capped at restart_cooldown_max
                        let cooldown =
                            Duration::from_millis(100 * (1 << restart_count.min(7)) as u64);
                        let cooldown = cooldown.min(spec.restart_cooldown_max);
                        let mut h = health.lock().await;
                        h.insert(
                            id,
                            SubsystemHealth {
                                running: false,
                                restart_count,
                                last_outcome: Some(format!("Restarting: {}", e)),
                            },
                        );
                        drop(h);
                        tokio::time::sleep(cooldown).await;
                        // Loop to restart
                    }
                }
            }
        })
    }
}

impl Default for Supervisor {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    #[tokio::test]
    async fn s1_panic_restarts_within_budget() {
        let sup = Supervisor::new();
        let counter = Arc::new(AtomicU32::new(0));
        let cc = counter.clone();

        let spec = SubsystemSpec {
            id: Subsystem::S1,
            max_restarts: 3,
            restart_cooldown_max: Duration::from_millis(10),
        };

        let handle = sup.spawn_supervised(spec, move || {
            let cc = cc.clone();
            async move {
                let n = cc.fetch_add(1, Ordering::SeqCst) + 1;
                if n <= 2 {
                    panic!("S1 fail #{}", n);
                }
                // 3rd attempt: complete normally
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        });

        let outcome = handle.await.unwrap();
        assert!(matches!(outcome, TaskOutcome::Completed));
        assert_eq!(counter.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn s5_panic_is_terminal() {
        let sup = Supervisor::new();

        let spec = SubsystemSpec {
            id: Subsystem::S5,
            max_restarts: 10, // ignored for S5 — terminal anyway
            restart_cooldown_max: Duration::from_millis(10),
        };

        let handle = sup.spawn_supervised(spec, move || async move {
            panic!("S5 covenant violation");
        });

        let outcome = handle.await.unwrap();
        assert!(matches!(outcome, TaskOutcome::Panicked(_)));

        let health = sup.health_handle();
        let h = health.lock().await;
        let s5_health = h.get(&Subsystem::S5).unwrap();
        assert!(!s5_health.running);
        assert!(s5_health
            .last_outcome
            .as_ref()
            .map(|s| s.starts_with("PanickedTerminal"))
            .unwrap_or(false));
    }

    #[tokio::test]
    async fn s1_panic_beyond_max_restarts_gives_up() {
        let sup = Supervisor::new();

        let spec = SubsystemSpec {
            id: Subsystem::S1,
            max_restarts: 2,
            restart_cooldown_max: Duration::from_millis(10),
        };

        let handle = sup.spawn_supervised(spec, move || async move {
            panic!("S1 always fails");
        });

        let outcome = handle.await.unwrap();
        assert!(matches!(outcome, TaskOutcome::Panicked(_)));
    }

    #[tokio::test]
    async fn isolation_s1_panic_does_not_kill_s5() {
        // Spawn S1 (panics) and S5 (sleeps OK). Verify S5 keeps running while S1 fails.
        let sup = Supervisor::new();

        let s1_spec = SubsystemSpec {
            id: Subsystem::S1,
            max_restarts: 1,
            restart_cooldown_max: Duration::from_millis(5),
        };
        let s1_handle = sup.spawn_supervised(s1_spec, move || async move {
            panic!("S1 dies");
        });

        let s5_alive = Arc::new(AtomicU32::new(0));
        let s5c = s5_alive.clone();
        let s5_spec = SubsystemSpec::new(Subsystem::S5);
        let s5_handle = sup.spawn_supervised(s5_spec, move || {
            let s5c = s5c.clone();
            async move {
                for _ in 0..5 {
                    s5c.fetch_add(1, Ordering::SeqCst);
                    tokio::time::sleep(Duration::from_millis(2)).await;
                }
            }
        });

        let (s1_out, s5_out) = tokio::join!(s1_handle, s5_handle);
        let s1_out = s1_out.unwrap();
        let s5_out = s5_out.unwrap();
        assert!(matches!(s1_out, TaskOutcome::Panicked(_)));
        assert!(matches!(s5_out, TaskOutcome::Completed));
        assert_eq!(s5_alive.load(Ordering::SeqCst), 5);
    }
}
