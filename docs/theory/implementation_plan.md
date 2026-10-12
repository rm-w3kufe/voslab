> ⚠️ DEPRECATED 2026-05-25 — Canonical source is now **docs/spec_revision/system/plan/strategy_plan.vsm**.
> This file is kept for historical traceability. Do not use as live reference.

# VSF Implementation Plan — Canonical (post Qwen round 4)

**Document version:** 1.0 — FINAL after 4 consensus rounds
**Date:** 2026-05-24
**Status:** ✅ CONSENSUADO PARA IMPLEMENTACIÓN
**Source rounds:** Claude+Qwen ronda 1 (NATS), 2 (refinements), 3 (canonical close), 4 (plan validation)
**Parent docs:**
- [information_flow_architecture.md](./information_flow_architecture.md)
- [per_system_requirements_method.md](./per_system_requirements_method.md)
- [systems/README.md](./systems/README.md)

---

## 0. Pre-conditions (must be true before any γ/β step)

| # | Pre-condition | How to verify |
|---|---|---|
| P.1 | `core/connection_schema.json` updated to v0.2.1 | new fields: `variety_delta`, `trust_score`, `algedonic_seq` in event_schema |
| P.2 | NATS server installed and tested in LXC 106 | ✓ already done (Gate 1 validated) |
| P.3 | tmpfs mount available at `/run/vsf/` in target LXC | mount -t tmpfs verify |
| P.4 | rsync installed in n01 for offsite backup | apt install rsync on n01 |
| P.5 | Backup of LXC 101 + LXC 102 state | ✓ already done (lxc-backups-pre-cleanup-2026-05-23) |

---

## 1. Production track (γ) — feature-flagged, in-place LXC 101

**Strategy**: every γ step is behind feature flag `--telemetry-canonical`. Code without the flag preserves current behaviour. Toggle ON when validated.

### γ.0 — Dry-run in LXC 107 (NEW, mandatory per Qwen round 4)

Before any change to LXC 101 productive:

```
- Deploy γ-aware binary in LXC 107 (test environment)
- Feed 2h of recorded telemetry replay
- Verify:
  ✓ dual-write events.jsonl + NATS publish works
  ✓ NATS reconnect after kill -9 nats-server
  ✓ algedonic gate doesn't fire on normal noise
  ✓ invariant_checker probes produce data (γ.6 needs this)
- Pass criterion: 2h replay with zero crashes + invariants in range
- Estimated: 4-6h
```

### γ.1 — `telemetry_canonical.rs` module

```yaml
purpose: Wrapper over TelemetryWriter that adds tmpfs staging + hash chain
files_to_create:
  - projects/vsf-nucleus/src/telemetry_canonical.rs
files_to_NOT_TOUCH:
  - projects/vsf-nucleus/src/telemetry.rs  (defense in depth — original kept intact)
deps: sha2 (already in Cargo.toml)
implements:
  - tmpfs append at /run/vsf/{system_id}/events.jsonl
  - async timer flush every 100ms to /var/lib/vsf/{system_id}/events.jsonl
  - hash chain inline (prev_hash field per event)
tests:
  - unit: append + flush + verify chain valid
  - unit: chain breaks if event modified
estimated: 2-3h
```

### γ.2 — `nats_publisher.rs` module (parallel to γ.1)

```yaml
purpose: Optional NATS client per "núcleo primero" — UDS-first
files_to_create:
  - projects/vsf-nucleus/src/nats_publisher.rs
deps: async-nats (add to Cargo.toml)
implements:
  - NATS connection (UDS preferred: nats://unix:/tmp/nats.sock, fallback TCP)
  - Subject builder: vsf.{vsf_id}.{system_id}.{channel}.{detail}
  - Buffered async publisher (if NATS down, buffer locally + retry exponential)
  - DOES NOT block nucleus if NATS unreachable
config:
  - NATS_URL env var (optional; default: UDS preferred, then 127.0.0.1:4222)
  - if NATS_URL absent: NO publishes, only events.jsonl writes
tests:
  - unit: publish to test NATS in LXC 106
  - unit: kill nats-server + verify buffer + reconnect
estimated: 3-4h
```

### γ.3 — Integration in `operational.rs`

```yaml
purpose: Wire telemetry_canonical + nats_publisher behind feature flag
files_to_modify:
  - projects/vsf-nucleus/src/operational.rs
  - projects/vsf-nucleus/src/main.rs (add --telemetry-canonical flag parsing)
implements:
  - if NUCLEUS_MODE=operational AND --telemetry-canonical:
      spawn telemetry_canonical worker (60s cycles, same as existing)
      spawn nats_publisher worker (drains events.jsonl tail)
  - else: existing behaviour (preserve compat)
tests:
  - smoke: binary --help shows new flag
  - smoke: flag OFF → behaviour unchanged
  - smoke: flag ON → events.jsonl appears + NATS publishes (if NATS_URL)
estimated: 2h
```

### γ.6 — `invariant_checker.rs` (NEW position: BEFORE γ.4)

```yaml
purpose: Probes for VAR-1, TRUST-1, ALG-1; produces baseline that γ.4 needs
files_to_create:
  - projects/vsf-nucleus/src/invariant_checker.rs
files_to_modify (P.1 dep):
  - core/connection_schema.json → v0.2.1
implements:
  - probe locations annotated per invariant
  - rolling window stats (N=100 samples)
  - drift detection: k * stddev threshold
  - circuit breaker on M consecutive failures
  - emit invariant_check events to events.jsonl
  - baseline computation for stasis_cos (used by γ.4)
tests:
  - inject ΔV imbalance → VAR-1 alert
  - inject trust chain break → TRUST-1 alert
  - feed algedonic cascade → ALG-1 alert
estimated: 3-4h
```

### γ.4 — `algedonic.rs` (depends on γ.6 baseline)

```yaml
purpose: Algedonic emission + gate (BINARY, NATS Core)
files_to_create:
  - projects/vsf-nucleus/src/algedonic.rs
depends_on: γ.6 baseline stasis_cos
implements:
  - emit_algedonic(reason, evidence) — binary signal
  - algedonic_gate:
      hysteresis based on γ.6 baseline
      decay: exp(-λ·t) per emitter
      rate_limit: max 2 emissions/sec per origin
  - NATS Core (not JetStream) — subject vsf.{vsf_id}.algedonic
tests:
  - emit + verify NATS delivery sub-ms
  - emit 100 in burst, verify gate limits
  - inject cascade across N levels, verify decay
estimated: 3h
```

### γ.8 — Observability light (NEW per Qwen round 4)

```yaml
purpose: Healthcheck + watchdog so γ.6 drift detection isn't blind
files_to_create:
  - /var/lib/vsf/health.json writer
  - systemd unit update: WatchdogSec=30s
implements:
  - nucleus writes health.json every 5s with last invariant_check results
  - systemd watchdog: if nucleus stops writing → auto-restart
  - simple monitoring script (cat health.json + alert if old)
tests:
  - kill -STOP nucleus → systemd restarts within 30s
  - inspect health.json shows real metrics
estimated: 2h
```

### γ.7 — Deploy to production LXC 101 + 24h validation

```yaml
purpose: Final deployment
prerequisites: γ.0-γ.4, γ.6, γ.8 all green
steps:
  1. cargo build --release (with all γ flags)
  2. strip binary (DEBT-38 mitigation already done)
  3. scp + pct push to LXC 101
  4. pct stop 101 (ventana de mantenimiento — uptime se reinicia)
  5. backup /root/vsf-nucleus → vsf-nucleus.before-γ
  6. install new binary
  7. update systemd unit: add --telemetry-canonical flag
  8. pct start 101
  9. monitor health.json + events.jsonl + NATS subjects 24h
rollback_path:
  1. pct stop 101
  2. mv vsf-nucleus.before-γ back
  3. systemd unit revert (remove flag)
  4. pct start 101
estimated: 2h deploy + 24h monitoring
```

---

## 2. PoC track (β) — parallel to γ.0, isolated LXC 107

### β.1 — Recycle LXC 102 → LXC 107

```yaml
purpose: Fresh container for collapsed PoC
prerequisites: backup of LXC 102 already done (DEBT-31)
steps:
  1. pct destroy 102 (post backup verified)
  2. pct create 107 with: 4 GB RAM, 4 cores, Debian 12
  3. hostname: vsf-collapsed-poc
  4. Network: VLAN as needed
estimated: 30 min
```

### β.2 — NATS sidecar (UDS-first) on LXC 107

```yaml
purpose: NATS server local to LXC 107
config:
  - bind: nats://unix:///tmp/nats.sock (UDS, no TCP)
  - JetStream enabled, max_file_store: 1GB
verify:
  - nats bench works
  - no TCP listeners on 4222 (UDS only)
estimated: 1h
```

### β.3 — Deploy γ-aware nucleus to LXC 107

```yaml
purpose: Same binary as production target
prerequisites: γ.1-γ.4 + γ.6 + γ.8 compiled
config:
  NUCLEUS_MODE=operational
  --telemetry-canonical
  NATS_URL=unix:///tmp/nats.sock
estimated: 1h
```

### β.4 — Tokio supervision pattern (CRITICAL CHANGE per Qwen round 4)

```yaml
purpose: Subsystem isolation that ACTUALLY WORKS in async Rust
correction_from_plan: ✗ catch_unwind does NOT capture async panics in Tokio
correct_pattern:
  - tokio::task::JoinSet per subsystem (S1, S2, S3, S3*, S4, S5)
  - AbortOnPanic guards
  - state_checkpoint() called pre-spawn for restartability
  - supervisor loop:
      if S_X task returns Err / panics:
        log + emit algedonic if S_X = S5 (terminal)
        else restart S_X with last checkpoint state
  - S5 panic = FULL halt (covenant violation)
files_to_create:
  - projects/vsf-nucleus/src/supervisor.rs
tests:
  - inject panic in S1 task → S5 still running
  - inject panic in S5 task → full halt + algedonic
  - verify state checkpoints restorable
estimated: 5-7h (longer than initial estimate; this is the hard part)
```

### β.5 — cgroup v2 budgets per subsystema

```yaml
purpose: Resource isolation
implements:
  - lxc.cgroup2.memory.high per S task
  - lxc.cgroup2.cpu.weight per S task
  - lxc.cgroup2.blkio.weight=30 (LXC 107 lower than LXC 101=default)
tests:
  - stress S1, verify others continue
estimated: 2h
```

### β.6 — 24h panic injection test

```yaml
purpose: Validate isolation works under sustained adversarial load
methodology:
  - inject panic in random S_X every 30s for 24h
  - measure stasis_cos doesn't degrade > 0.05
  - measure S5 survives (never panics from S1/S2/S3/S3*/S4 panics)
  - measure algedonic_gate doesn't saturate
pass_criterion:
  - 24h without S5 termination
  - stasis_cos always > 0.85
  - max_escals_per_sec ≤ 2 (per Qwen ALG-1)
estimated: 24h running + 2h analysis
```

---

## 3. Deprecation track — sequential, after γ + β validated

### D.1 — Motor 2 (SQLite BBS embedded) → read-only

```yaml
prerequisite: γ.7 deployed + 24h stable + β.4-β.6 passed
steps:
  1. telemetry_publisher.rs continues running (NO removal yet)
  2. ADD: BBS SQLite opened with read-only flag
  3. S4 reads events.jsonl directly via tail -f
  4. Verify S4 cycles work without Motor 2 writes
estimated: 2h + 5-10 min observation
```

### D.2 — Validation 2 cycles dual operation

```yaml
prerequisite: D.1 done
steps:
  cycle 1 (5 min): events.jsonl + read-only SQLite both active
  cycle 2 (5 min): Motor 2 freezing, only events.jsonl active
verify:
  - events.jsonl growth normal
  - S4 cycles healthy
  - NATS publishes continue
estimated: 15 min
```

### D.3 — Remove Motor 2 from compile

```yaml
prerequisite: D.2 passed
steps:
  1. Remove telemetry_publisher from operational.rs::run_parallel
  2. cargo build → smaller binary
  3. Deploy as γ.7 sub-revision
  4. Keep code in tree (for reference/rollback)
estimated: 1h
```

---

## 4. Post-stabilization (deferred per Qwen round 4)

| Step | Reason for deferral |
|---|---|
| γ.5 params.json hot-reload | fs watcher race conditions; env vars sufficient for γ |
| ψ handshake implementation | only needed when 2nd VSF exists |
| Human approval gate code-level | A5 enforced by policy now; code enforcement requires UI |
| Multi-VSF federation | post-replication phase |

---

## 5. Total estimated effort

| Track | Hours |
|---|---|
| γ.0 dry-run | 4-6 |
| γ.1 telemetry_canonical | 2-3 |
| γ.2 nats_publisher | 3-4 |
| γ.3 integration | 2 |
| γ.6 invariant_checker | 3-4 |
| γ.4 algedonic | 3 |
| γ.8 observability | 2 |
| γ.7 deploy + 24h | 2 + 24 |
| β.1 LXC recycle | 0.5 |
| β.2 NATS sidecar UDS | 1 |
| β.3 nucleus deploy | 1 |
| β.4 Tokio supervision | **5-7** |
| β.5 cgroup budgets | 2 |
| β.6 24h test | 24 + 2 |
| D.1-D.3 deprecation | 3 |
| **Active work** | **~32-44 hours** |
| **Plus monitoring** | **~48 hours** |

---

## 6. Critical adjustments from Qwen round 4 (must apply)

✓ **β.4 must use Tokio supervision tree** (`JoinSet + AbortOnPanic + checkpoint`), not `catch_unwind`. This is the most important correction.

✓ **γ.0 dry-run is mandatory** before LXC 101 deploy. Catch issues in isolated environment.

✓ **γ.5 deferred** to post-stabilization. Env vars are sufficient for γ phase.

✓ **γ.6 schema gap**: `connection_schema.json` must reach v0.2.1 with new fields BEFORE γ.6 probes are coded.

✓ **γ.4 depends on γ.6 baseline**: gate hysteresis needs reference metric. Reorder accordingly.

✓ **γ.8 observability light** added between γ.7 and 24h run.

---

## 7. Confidence

| Section | Marker |
|---|---|
| Plan structure | ✓ VERIFIED — 4 consensus rounds |
| Effort estimates | ◐ ROUGH — actual will vary |
| β.4 Tokio pattern | ◐ DESIGN — requires implementation discovery |
| Rollback paths | ✓ VERIFIED — feature-flagged everywhere |

---

## 8. Decision required from owner before coding starts

1. **Schedule for γ.7 deploy** — ventana de mantenimiento (LXC 101 restart, ~10 min downtime)
2. **NATS_URL strategy**: empty (no NATS in γ) OR `unix:///tmp/nats.sock` (NATS in same LXC) OR `nats://10.10.x.x:4222` (cross-LXC)
3. **24h test scheduling**: ¿week vs weekend?
4. **Tokio supervision pattern**: implementarlo en β o también backportarlo a γ.7 production?
5. **¿Empezamos por γ.0 dry-run o por β.1 LXC 107 setup?** Pueden paralelar.
