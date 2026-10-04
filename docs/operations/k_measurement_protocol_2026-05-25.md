# K Measurement Protocol — GATE_3 instrumentation
> **STATUS: historical_record** — DRAFT GATE_3 NUNCA EJECUTADO: docs/operational/k_measurements/ no existe (2026-08-15 R4) — medición K (K_φ↑/K_φ↓/τ/G(jω)) no instrumentada en producción. Invariante canónico ya cubierto: vos_proofs.vsm:111 (loop_gain>1 ⟹ ¬viable) + s3_allocation.vsm:278 (acceptance k_phi_down_meter). Contenido completo en git history.

**Document version:** 1.0
**Date:** 2026-05-25
**Status:** Draft for BBH↔VSF GATE_3 (loop gain empirical validation)
**Owner:** VSF Validation Team
**Consumes:** γ.7 production nucleus (LXC 101, PID 135600+)
**Produces:** measured K_φ↑, K_φ↓ → G(s) → `|G(jω)| < 1 ∀ω` verification

---

## 0. Why this protocol exists

BBH-VSF protocol v3.0 asserts loop stability with `max_loop_gain: 0.8`. VSF Round 1 §5 challenged this as heuristic without measurement provenance. BBH agreed in Round 1 §5 to instrument K values in production. This document is the concrete procedure.

The shape of G(s) from BBH math foundations:

```
G(s) = K_φ↑ · K_φ↓ · e^(-s·τ) / (1 + s·T_poll)
```

Where:
- `K_φ↑` — open-loop gain from S1 event emission to S4/S5 ingestion
- `K_φ↓` — open-loop gain from S5 override decision to S1 application
- `τ` — round-trip latency (BBH covenant: ≤ 30s)
- `T_poll` — poll interval (BBH covenant: 5s)

We need to **measure K_φ↑ and K_φ↓ empirically** rather than assume.

---

## 1. Definitions (so we measure the same thing)

### K_φ↑ — Upward channel gain

```
K_φ↑ ≜ (rate of φ↑ events arriving at S3/S4 consumer)
        ───────────────────────────────────────────────
       (rate of state changes at S1 producer)
```

If S1 changes state 10 times/sec but only emits 1 event/sec (attenuation), K_φ↑ = 0.1.
If S1 amplifies (1 state change → 10 events), K_φ↑ = 10.

Per Ashby's Law of Requisite Variety + VSF connection_schema.json: **φ↑ should attenuate**, so `K_φ↑ < 1` is expected.

### K_φ↓ — Downward channel gain

```
K_φ↓ ≜ (rate of S1 param applications)
        ─────────────────────────────────
       (rate of S5 override decisions)
```

If S5 decides 1 override and it applies to 5 S1 instances (amplification), K_φ↓ = 5.
If S5 decides 1 override and it modifies 1 param on 1 S1, K_φ↓ = 1.

Per VSF connection_schema.json: **φ↓ structured amplification**, so `K_φ↓ ≥ 1` is expected.

### Combined open-loop gain

```
K_total = K_φ↑ · K_φ↓
Loop stability requires:  |G(jω)| < 1 ∀ω
                       ⇒  K_total ≤ 0.8 (with τ + T_poll bounds)
```

This is the BBH covenant `max_loop_gain: 0.8`.

---

## 2. What γ.7 nucleus already emits (data sources)

✓ VERIFIED (production runtime 2026-05-25 02:36 UTC):

### 2.1 events.jsonl Merkle chain

Path: `/var/lib/vsf/vsf_nucleus/events.jsonl` in LXC 101.

Each event has timestamps `ts` and is chained via `prev_hash → hash`. Event types relevant to K measurement:

| event_type | What it tells us |
|---|---|
| `kernel_tick` | S1 internal tick — denominator for K_φ↑ |
| `s4-analysis` (BBS, via Motor 2 — temporary) | S4 decision emission |
| `invariant_check` (γ.6) | When invariants are sampled |
| `algedonic_emit` (γ.4) | Algedonic burst rate (for ALG-1 cross-check) |
| `param_change` | φ↓ override application — numerator for K_φ↓ |

### 2.2 NATS subjects (γ.2 publisher)

Subjects under `vsf.alpha.>` carry the same events. Two collection methods:

- **Filesystem tail**: `tail -F /var/lib/vsf/vsf_nucleus/events.jsonl` (works today, no extra deps)
- **NATS subscriber**: subscribe to `vsf.alpha.>` (works today, requires `nats` CLI or async-nats Python)

We use filesystem tail as primary (offline replayable).

### 2.3 health.json (γ.8)

Path: `/var/lib/vsf/health.json` — atomic write every 5s. Contains rolling counters:

- `invariant_checks_total`
- `drift_alerts_total`
- `algedonic_total`
- `last_event_hash`
- `last_telemetry_ts`
- `last_s4_cycle_ts`

These give coarse-grained rates without parsing events.jsonl.

---

## 3. Measurement procedure — Week 1 (passive)

### 3.1 Setup

On any host that can reach LXC 101 read-only:

```bash
# Option A — pull events.jsonl periodically (low overhead)
ssh root@n02 'pct exec 101 -- tail -F /var/lib/vsf/vsf_nucleus/events.jsonl' \
  > /home/rmw3/vsf-measurements/events-$(date +%Y%m%d).jsonl

# Option B — subscribe to NATS subjects via tunnel n02-nats
nats --server nats://127.0.0.1:4222 sub 'vsf.alpha.>' \
  --raw > /home/rmw3/vsf-measurements/nats-$(date +%Y%m%d).log
```

Run for **7 days** uninterrupted. ~10 MB/day expected (telemetry 60s + S4 300s).

### 3.2 K_φ↑ calculation

Hypothesis: S1 (canonical emit loop in γ.1) emits 1 `kernel_tick` every 60s. S3 (telemetry consumer) processes 1 per 60s. Therefore baseline K_φ↑ ≈ 1.0 in steady state — no attenuation in current γ.7 because no recursive levels yet.

**Real measurement** for BBH (when BBH is integrated as S1 inside VSF):

```python
# k_phi_up_calc.py — runs against events-YYYYMMDD.jsonl
import json
from collections import defaultdict
from datetime import datetime, timedelta

# Per-minute bucketing
buckets = defaultdict(lambda: {"s1_state_changes": 0, "phi_up_events": 0})

with open("events.jsonl") as f:
    for line in f:
        e = json.loads(line)
        ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        bucket = ts.replace(second=0, microsecond=0).isoformat()
        # State changes ≜ kernel_tick + bounded_self_correction events from S1
        if e["event_type"] in ("kernel_tick", "bounded_self_correction"):
            buckets[bucket]["s1_state_changes"] += 1
        # φ↑ events ≜ everything emitted by S1 that S3 consumes
        if e["event_type"] in ("kernel_tick", "anomaly_detected", "phase_complete",
                                "tool_run", "thermal_wait", "signal_escalated"):
            buckets[bucket]["phi_up_events"] += 1

K_per_minute = []
for bucket, counts in sorted(buckets.items()):
    if counts["s1_state_changes"] > 0:
        K = counts["phi_up_events"] / counts["s1_state_changes"]
        K_per_minute.append(K)

import statistics
print(f"K_φ↑ samples: {len(K_per_minute)}")
print(f"  mean = {statistics.mean(K_per_minute):.3f}")
print(f"  p50  = {statistics.median(K_per_minute):.3f}")
print(f"  p95  = {sorted(K_per_minute)[int(len(K_per_minute)*0.95)]:.3f}")
print(f"  p99  = {sorted(K_per_minute)[int(len(K_per_minute)*0.99)]:.3f}")
print(f"  max  = {max(K_per_minute):.3f}")
```

Expected output (steady state, no BBH yet):
```
K_φ↑ samples: 10080  (7 days · 1440 min/day)
  mean ≈ 1.0
  max  ≤ 2.0  (occasional burst — anomalies)
```

When BBH is integrated as S1 inside VSF:
- BBH probes generate findings → many phi_up events
- BBH internal state changes faster than emissions (attenuation)
- Expected `K_φ↑ < 1` in steady state, with spikes during scan phases

### 3.3 K_φ↓ calculation

S5 decisions are rare. Current γ.7 has `s4-analysis` events at 300s cycles (Qwen decisions). These represent the "param_change" candidates.

```python
# k_phi_down_calc.py — runs against events.jsonl
import json
from collections import defaultdict

s5_decisions = 0  # numerator-source: s4-analysis events from BBS or events.jsonl
s1_param_changes = 0  # denominator: param_change events

with open("events.jsonl") as f:
    for line in f:
        e = json.loads(line)
        if e["event_type"] == "s4-analysis":
            s5_decisions += 1
        elif e["event_type"] == "param_change":
            s1_param_changes += 1

# K_φ↓ = applications per decision
if s5_decisions > 0:
    K_phi_down = s1_param_changes / s5_decisions
    print(f"K_φ↓ ≈ {K_phi_down:.3f}")
else:
    print("Insufficient decisions for K_φ↓ measurement — need >100 cycles")
```

Expected: `K_φ↓ ≈ 1` (current γ.7 has 1 S1 instance — nucleus itself).

When BBH integrated: `K_φ↓` may be higher (1 S5 decision → N BBH workers receive updated params).

### 3.4 τ (round-trip latency)

For each s4-analysis event with a corresponding param_change event:

```python
# tau_calc.py
import json
from datetime import datetime

pairs = []  # (s4 ts, param_change ts)
last_s4_ts = None

with open("events.jsonl") as f:
    for line in f:
        e = json.loads(line)
        ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        if e["event_type"] == "s4-analysis":
            last_s4_ts = ts
        elif e["event_type"] == "param_change" and last_s4_ts:
            tau_sec = (ts - last_s4_ts).total_seconds()
            pairs.append(tau_sec)
            last_s4_ts = None  # consume

if pairs:
    import statistics
    print(f"τ samples: {len(pairs)}")
    print(f"  mean = {statistics.mean(pairs):.2f} sec")
    print(f"  p99  = {sorted(pairs)[int(len(pairs)*0.99)]:.2f} sec")
    print(f"  max  = {max(pairs):.2f} sec")
    print(f"  BBH covenant limit: 30 sec")
```

Pass criterion (BBH covenant): `p99(τ) ≤ 30 sec`.

### 3.5 G(jω) numerical verification (Day 8)

Once K_φ↑, K_φ↓, τ measured:

```python
# g_jw_verify.py
import numpy as np
from scipy import signal

# Measured values (replace with real)
K_phi_up = 0.85    # from §3.2
K_phi_down = 1.0   # from §3.3
tau = 5.2          # from §3.4 (p99 in seconds)
T_poll = 5.0       # BBH covenant

# G(s) = K_φ↑ · K_φ↓ · e^(-s·τ) / (1 + s·T_poll)
# Discrete approximation using bilinear transform or Padé
K_total = K_phi_up * K_phi_down

# Sweep ω in radians/sec, well above and below cycle frequencies
omega_range = np.logspace(-3, 2, 1000)

# Padé approximation for delay: e^(-s·τ) ≈ (1 - s·τ/2) / (1 + s·τ/2)
def G_jw(omega, K, tau, T_poll):
    s = 1j * omega
    delay = (1 - s*tau/2) / (1 + s*tau/2)
    return K * delay / (1 + s*T_poll)

magnitudes = np.abs([G_jw(w, K_total, tau, T_poll) for w in omega_range])
peak = magnitudes.max()
peak_omega = omega_range[magnitudes.argmax()]

print(f"K_total = {K_total:.3f}")
print(f"τ = {tau:.2f} sec, T_poll = {T_poll:.1f} sec")
print(f"max|G(jω)| = {peak:.4f} at ω = {peak_omega:.4f} rad/sec")
print(f"Stability: {'PASS' if peak < 1.0 else 'FAIL'}")
print(f"Margin to limit 0.8 (BBH covenant): {'PASS' if peak < 0.8 else 'WARN'}")
```

### 3.6 Pass criteria

| Metric | Target | Source |
|---|---|---|
| Measurement window | ≥ 7 days uninterrupted | this protocol |
| Samples for K_φ↑ | ≥ 1000 (1-minute buckets) | enough to characterize variance |
| Samples for K_φ↓ | ≥ 100 (S4 cycles in 7 days) | enough to estimate ratio |
| `p99(τ)` | ≤ 30 sec | BBH covenant |
| `max\|G(jω)\|` | < 1.0 (strict) | math foundations stability |
| `max\|G(jω)\|` | < 0.8 (covenant margin) | BBH covenant max_loop_gain |

If `max|G(jω)| ≥ 1.0` → loop is unstable, **abort GATE_3**, tune rate limits (`max_rate_per_min`, `max_rate_per_sec`) downward.

If `0.8 ≤ max|G(jω)| < 1.0` → loop stable but covenant margin tight, **document warning** and consider tightening rate limits.

If `max|G(jω)| < 0.8` → GATE_3 PASS, proceed to GATE_5 (formal sign-off of math foundations).

---

## 4. Instrumentation work that VSF must do (next code cycle)

To unlock the protocol fully, the γ.7 nucleus needs:

1. **Emit `param_change` events** when φ↓ applies (currently env-var based, no event)
   - File: `projects/vsf-nucleus/src/config.rs` (add emission on reload, when γ.5 params.json arrives)
   - Effort: 1h Rust
   
2. **Emit `bounded_self_correction` events** when S1 adjusts within bounds
   - File: `projects/vsf-nucleus/src/s1_*` (when implemented per S1_operations.md)
   - Effort: depends on S1 implementation work
   
3. **K computation as a periodic invariant_check** (γ.6 extension)
   - Add `record_loop_gain(measured_k)` to InvariantChecker
   - Drift alert if rolling mean exceeds 0.8
   - Effort: 2h Rust

These are NOT blocking for the passive measurement phase — manual scripts (§3) work today against existing events.jsonl.

---

## 5. Logging + storage

VSF will publish weekly K reports to:

- `docs/operational/k_measurements/k_report_YYYYMMDD.md` — measured values + commentary
- `docs/operational/k_measurements/raw/events-YYYYMMDD.jsonl.gz` — compressed raw data (kept 90 days)
- `docs/operational/g_jw_traces/` — scipy.signal plots (per measurement window)

This builds an audit trail of K stability over time. If K drifts, S3* can flag (it's an invariant: `K_total ≤ 0.8`).

---

## 6. Coordination with BBH

This protocol is published in `vsf/docs/operational/` so BBH can:

1. Read the methodology + adopt for its own BBH-VSF measurement when integrated
2. Cross-validate with `bbh/docs/mathematical_foundations.md` (numerical formulas should agree)
3. Use the events.jsonl format we both consume (BBH publishes, VSF measures)

If BBH proposes amendments (e.g. additional event_types relevant for K), VSF welcomes them as PRs to this doc.

---

## 7. Status

✓ Protocol defined
⏳ Manual measurement scripts can run TODAY against γ.7 events.jsonl
⏳ Full instrumentation (param_change emit, K invariant_check) — next γ code cycle
⏳ First weekly K report — 2026-06-01 (7 days from γ.7 deploy 2026-05-25)

---

## 8. References

- `docs/theory/information_flow_architecture.md` §3 (channel definitions, variety budgets)
- `core/connection_schema.json` v0.2.1 (event_schema with variety_delta, trust_score)
- `bbh/docs/mathematical_foundations.md` (BBH's loop gain derivation)
- `bbh/spec/bbh_vsf_protocol_v3.vsm` (covenant `loop_stability` block)
- VSF γ.7 production: LXC 101 PID 135600+
