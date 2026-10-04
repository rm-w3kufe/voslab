> ⚠️ DEPRECATED 2026-05-25 — Canonical source is now **HANDOFF.vsm.md**.
> This file is kept for historical traceability. Do not use as live reference.

# VSF Plan Status — Snapshot 2026-05-25

**Document version:** 1.0
**Date:** 2026-05-25 (closing snapshot)
**Author:** rmw3 + Claude (Opus 4.7)
**Sources of truth:**
- `implementation_plan.md` — canonical plan (post 4 Qwen consensus rounds)
- `information_flow_architecture.md` — architectural spec
- `per_system_requirements_method.md` — per-system template
- Git history (commits `9893f27` through `ffc33ea`)
- Production deploy verified in LXC 101

---

## 0. Quick state summary

```
┌────────────────────────────────────────────────────────┐
│  γ-aware nucleus IS LIVE in LXC 101 production        │
│  Deployed: 2026-05-25 02:36:32 UTC                    │
│  PID 135600 — uptime growing                          │
│  All γ modules + β.4 supervisor active                │
│  3500+ BBS messages preserved + growing               │
│  NATS publish to vsf-nats-test (LXC 106)              │
│  events.jsonl Merkle chain active                     │
│  Rollback path documented                             │
└────────────────────────────────────────────────────────┘
```

---

## 1. Fase 1 — Limpieza inicial ✅ DONE

| Item | Status | Evidence |
|---|---|---|
| Destroy LXC 102 deprecated | ✓ | n02 inventory |
| Rename LXC 106: bbs → vsf-nats-test | ✓ | hostnamectl + ssh config |
| Update `~/.bashrc` vsf-tunnels alias | ✓ | local |
| Update `~/.ssh/config` n02-bbs → n02-nats | ✓ | local |
| `connection_schema.json` v0.2.0 → v0.2.1 (P.1) | ✓ | commit `9893f27` |
| rsync install on n01 (P.4) | ✓ | manual by user |
| LXC 101/102 backups verified | ✓ | n02:/root/lxc-backups-pre-cleanup-2026-05-23/ |

---

## 2. Fase 2 — Implementación γ + β

### 2.1 γ track (production path) — MOSTLY DONE

| Step | Status | Tests | Commit |
|---|---|---|---|
| γ.0 dry-run LXC 107 vsf-collapsed-poc | ✓ VERIFIED | end-to-end | `9ae8b66` |
| γ.1 `telemetry_canonical.rs` (events.jsonl + Merkle + tmpfs) | ✓ | 2 PASS | `80175f4` |
| γ.2 `nats_publisher.rs` (optional, UDS-first) | ✓ | 2 PASS | `80175f4` |
| γ.3 integration `--telemetry-canonical` flag | ✓ | smoke | `80175f4` |
| γ.4 `algedonic.rs` (binary, gate, NATS Core) | ✓ | 5 PASS | `1d741fa` |
| γ.6 `invariant_checker.rs` (VAR-1/TRUST-1/ALG-1) | ✓ | 8 PASS | `1d741fa` |
| γ.7 deploy LXC 101 production | ✓ VERIFIED | logs | `bd8b123` |
| γ.8 `observability.rs` (health.json + watchdog) | ✓ | 3 PASS | `1d741fa` |
| **γ.5 params.json hot-reload** | ⏳ DEFERRED | per Qwen ronda 4 (env vars sufficient) | — |

### 2.2 β track (PoC collapsed) — PARTIAL

| Step | Status | Tests | Commit |
|---|---|---|---|
| β.1 LXC 107 created (4GB/4cores) | ✓ | runtime | n02 |
| β.2 NATS sidecar (TCP 127.0.0.1) | ✓ | runtime | n02 |
| β.3 γ-aware nucleus deployed | ✓ | runtime | n02 |
| **β.4 Tokio supervision tree** | ✓ INTEGRATED | 4 PASS isolation S1↔S5 | `b81e426`+`8ca2cfd` |
| **β.5 cgroup v2 budgets** | ◐ PARTIAL | config present, runtime restricted by unprivileged LXC | — |
| **β.6 24h panic injection test** | ⏳ pending (passive, requires 24h) | — | — |

### 2.3 Deprecation track — NOT YET STARTED

| Step | Status | Blocker |
|---|---|---|
| D.1 Motor 2 SQLite → read-only | ⏳ pending | γ.7 stable 24h + β.6 done |
| D.2 Validation 2 cycles dual | ⏳ pending | D.1 |
| D.3 Remove Motor 2 from compile | ⏳ pending | D.2 |

---

## 3. Fase 3 — Optimización (LLM agents per subsystem)

### 3.1 Documentation ✓ COMPLETE

| Doc | Status |
|---|---|
| `agents/README.md` (which subsystems get LLM, derivation method) | ✓ |
| `agents/S4_agent_prompt.md` (canonical, documents running S4) | ✓ |
| `agents/S3_star_agent_prompt.md` (DESIGN) | ✓ DESIGN |
| `agents/S5_agent_prompt.md` (DESIGN HIGH RISK) | ✓ DESIGN |

### 3.2 Implementation — partial

| Component | Status | Notes |
|---|---|---|
| **S4 agent** | ✓ ACTIVE in production | Runs as `s4_operational.rs::run_cycle` with Qwen 2.5-coder. Prompt canonical (doc) matches behavior. |
| **S3* agent** | ⏳ pending `s3_star.rs` module | Independent Qwen instance required (per Qwen ronda 3) |
| **S5 agent** | ⏳ pending — HIGH RISK | Requires: witness validation infra + human approval code gate + 30-day shadow mode + external audit |

### 3.3 Runtime validators

Per per_system_requirements_method.md §6 (Verification & Drift Detection):
- ✓ For S4: JSON schema validation, fence stripping, covenant check (implemented in s4_operational.rs)
- ⏳ For S3*: pending implementation
- ⏳ For S5: pending implementation (most complex — witness handshake)

---

## 4. Fase 4 — Limpieza final ⏳ FUTURE

Not yet started. Will include:
- Strip dead Rust modules (e.g. legacy telemetry.rs if Motor 1 fully replaces)
- Strip dead BBS HTTP client (bbs.rs) if no consumer remains
- Reduce 124 compiler warnings (snake_case, dead code) to ≤20
- Consolidate scripts/legacy/ if anything else can be moved
- Documentation alignment (HANDOFF, README, this status doc)
- Re-audit n02 LXC topology (LXC 107 future destiny TBD: keep as PoC sandbox, or destroy)

---

## 5. Production runtime state (LXC 101)

✓ VERIFIED at deploy time 2026-05-25 02:36 UTC. Continuous since.

```
Binary:        /root/vsf-nucleus-operational  (6.0M, γ-aware)
Wrapper:       /root/nucleus-wrapper.sh        (env: NATS_URL, VSF_ID, --telemetry-canonical)
Systemd unit:  Type=notify + WatchdogSec=30s
PID:           135600
RAM:           ~8 MB (tokio runtime + async-nats)
Modules:       canonical + nats_publisher + invariant_checker
                + algedonic + observability + supervisor (β.4 wraps S1)
events.jsonl:  /run/vsf/vsf_nucleus/events.jsonl (tmpfs)
              + /var/lib/vsf/vsf_nucleus/events.jsonl (disk, 100ms flush)
NATS:          nats://10.10.20.20:4222 (vsf-nats-test LXC 106)
BBS preserved: SQLite at /root/bbs.db, 3500+ messages
S4 cycles:     every 300s — Qwen generating decisions
Telemetry:     every 60s — Motor 2 still active (Motor 1 also active per defense in depth)
```

### Rollback path

If anything goes wrong with γ.7 deploy:

```bash
ssh root@n02 'pct exec 101 -- bash -c "
systemctl stop vsf-nucleus-operational
mv /root/vsf-nucleus-operational.before-gamma-20260525-023600 \
   /root/vsf-nucleus-operational
mv /root/nucleus-wrapper.sh.before-gamma-20260525-023600 \
   /root/nucleus-wrapper.sh
mv /etc/systemd/system/vsf-nucleus-operational.service.before-gamma-20260525-023600 \
   /etc/systemd/system/vsf-nucleus-operational.service
systemctl daemon-reload && systemctl start vsf-nucleus-operational
"'
```

---

## 6. Pendientes ordenados por prioridad

### 6.1 Immediate (no human action, passive)

| # | Pendiente | Trigger |
|---|---|---|
| 1 | γ.7 24h stability monitoring | Time-based (24h since 02:36 UTC) |
| 2 | β.6 24h panic injection LXC 107 | Time-based — passive observation |

### 6.2 Short-term (code work, 1-3h each)

| # | Pendiente | Esfuerzo | Pre-condition |
|---|---|---|---|
| 3 | D.1 Motor 2 → read-only | 2h Rust + redeploy | γ.7 24h stable |
| 4 | Extend supervisor to S3 + S4 workers | 2h Rust + redeploy | (none) |
| 5 | Implement `s3_star.rs` module | 3-4h Rust | (none, but needs separate Qwen instance) |
| 6 | Reduce compiler warnings to ≤20 | 1-2h | (none) |

### 6.3 Medium-term (3-7h each)

| # | Pendiente | Esfuerzo | Pre-condition |
|---|---|---|---|
| 7 | D.2-D.3 Motor 2 full deprecation | 3h | D.1 + 2 stable cycles |
| 8 | params.json reader (γ.5 deferred) | 2-3h | (none, low priority) |
| 9 | Implement `s2.rs` explicit coordinator | 4-5h | (none, debt-13) |
| 10 | s5_policy.json writer + reader | 3-4h | s5.rs design |

### 6.4 Long-term (design + infra)

| # | Pendiente | Esfuerzo | Pre-condition |
|---|---|---|---|
| 11 | S5 LLM agent infrastructure | 12+ h | witness validation + human gate + shadow mode |
| 12 | ψ handshake protocol implementation | 8-12h | first need for inter-VSF coupling |
| 13 | Migration to SSD/NVMe | hardware | when justified by load |
| 14 | Full collapse to bare metal (α option) | TBD | future scaling decision |

### 6.5 Fase 4 cleanup (after all above)

| # | Pendiente | Notes |
|---|---|---|
| 15 | Strip legacy modules (bbs.rs, telemetry.rs if unused) | post Motor 2 deprecation |
| 16 | LXC 107 destiny decision | keep as sandbox or destroy |
| 17 | docs/* alignment pass | every doc reflects post-γ.7 state |
| 18 | covenant_hash refresh + amendment ceremony | if any axiom additions |

---

## 7. Things explicitly NOT done (and why)

| Skipped | Reason |
|---|---|
| Per-LXC io.weight enforcement | Proxmox unprivileged restricts; "núcleo primero" — not worth privileged container |
| ext4 commit=1 mount option | Empirically NO improvement (Test A1 ronda 4 result) |
| Pause Kali VM permanently | Not the IO bottleneck (load 0.33 verified) |
| SSD migration | Hardware constraint accepted per "viabilidad ≠ hardware capacity" |
| Matrix protocol integration | Qwen ronda 3 → "indefinite defer" (overkill, modeled "human rooms" not VSM channels) |
| MQTT / Kafka / Pulsar | "núcleo primero" — NATS sufficient at this scale |

---

## 8. Open questions for owner (rmw3)

1. **β.6 timing**: ¿corremos el 24h panic injection en LXC 107 (passive) o lo difiere a una sesión futura?
2. **D.1 priority**: ¿procedemos con Motor 2 read-only luego de γ.7 estable (24h+), o difiere?
3. **S3* implementation**: ¿se justifica ya el módulo `s3_star.rs` o esperamos a producción más madura?
4. **LXC 107 destiny**: ¿se mantiene como PoC sandbox permanente o se destruye cuando β termine?
5. **Witness infrastructure**: ¿cuándo iniciar la coordinación con gemini-vsl-core / GPT-4o para validation S5?

---

## 9. Lineage and consensus trail

This plan reached this state via:
- 4 rounds of Claude+Qwen architectural consensus (2026-05-24)
- Empirical validation gates 1-4 (latency, backpressure, atomicity, fsync)
- Cleanup of 6 pre-colapso duplicates (load -70%)
- Hardware diagnosis (TOSHIBA HDD identified as fsync floor)
- γ.0 dry-run validated in LXC 107
- γ.7 production deploy in LXC 101 verified

The plan honors:
- Beer's VSM (1972) — S1-S5 + S3* recursive structure
- Cybersyn lineage — anti-capture via S3* + covenant + witnesses
- A0 + A0.1 axioms — ethical primacy + anti-fragility
- "Núcleo primero" — kernel-closest carrier first, sophistication only when justified
- D6 — LLM at L≥2 (S3*/S4/S5 only, never S1/S2/S3 deterministic)

---

## 10. Next session can resume from

- `HANDOFF.vsm.md` — full session continuity
- This document (`plan_status_2026-05-25.md`) — what's done/pending
- `memory/project_vsf_nucleus_state.md` — production state
- `memory/project_dual_channel_decision.md` — full consensus history

Tested re-entry: a fresh agent reading these can pick up at §6.2 step 3 (D.1) without context loss.
