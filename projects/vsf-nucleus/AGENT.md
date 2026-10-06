# AGENT.md — vsf-nucleus instructions for Claude Code

This file is for AI agents (Claude Code or any Anthropic API consumer) working with
vsf-nucleus. Read it at session start before touching any code.

---

## What this is

`vsf-nucleus` is a Rust kernel that embeds all five Beer VSM functions (S1–S5) in a
single binary (~5.9 MB). It maintains a ℝ¹²⁸ state vector, enforces viability
invariants (Ω_A = cos ≥ 0.88 contractive core), computes a certified viability
functional V = min(g, c, t, m), and emits Merkle-chained telemetry (φ↑) to
`events.jsonl`. It is a **research kernel** — not production infra.

**Authoritative paper**: `docs/papers/attractor_convergence/main.tex`
**Key measurements**: g = 0.102 (attractor), λ = ln(0.99) (Lyapunov), θ_A = 0.88 (Fierro)

---

## Build

```bash
# On LXC 108 (dev-sandbox) — never on WSL or n02 host
cd /path/to/vsf/projects/vsf-nucleus
cargo build --release           # ~90s cold, ~10s incremental
cargo test                      # 195 tests; all must pass before deploy
```

Build requires: Rust 2024 edition, `libssl-dev`, `libsqlite3-dev`.
Binary output: `target/release/vsf-nucleus`.

**CRITICAL**: `/tmp` on n02 LXCs can fill up. If `cargo test` fails "No space left",
run `rm -rf /tmp/vsf-build/vsf-nucleus /tmp/vsf-build/projects/vsf-nucleus/target/debug`
before retrying.

---

## Deploy

Deploy uses the copy-then-move pattern (atomic, avoids half-written binary):

```bash
# From WSL — push to LXC 108 (test) or 101 (prod)
pct push 108 target/release/vsf-nucleus /tmp/vsf-nucleus-new
pct exec 108 -- chmod +x /tmp/vsf-nucleus-new
pct exec 108 -- mv /tmp/vsf-nucleus-new /root/vsf-nucleus-operational
pct exec 108 -- systemctl restart vsf-nucleus-operational
```

**Never** deploy directly to n02 host (`/root/` on Proxmox). Always deploy to an LXC.
LXC 108 = dev-sandbox (certify here first). LXC 101 = s3s4-nucleus (prod).

---

## Key configuration (env vars)

| Var | Default | Notes |
|-----|---------|-------|
| `OLLAMA_URL` | unset | S4 LLM calls disabled if unset |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | LLM model for S4 orchestration |
| `S4_CYCLE_INTERVAL` | `300` | Seconds between S4 analysis cycles |
| `NUCLEUS_MODE` | `operational` | `operational` or `test` |
| `COVENANT_SHA256` | required at runtime | Must match `dde12ead…` (see covenant.vsm) |
| `VSF_NS_SIGMAS` | — | For `--experiment sustained_noise` |
| `VSF_NS_TICKS` | — | Ticks per σ level |

Set in the systemd unit's `[Service]` block, not in `.env` files.

---

## Module map (src/)

| Module | Function | Notes |
|--------|----------|-------|
| `kernel.rs` | S3 control loop — dispatch, invariant gate | Entry point for one kernel step |
| `kernel_step.rs` | Single tick logic | Calls invariant_checker, attractor |
| `state_vector.rs` | ℝ¹²⁸ state vector type | Core data structure |
| `attractor.rs` | Attractor geometry, stasis_cos, confinement | Ω_A = cos ≥ 0.88 |
| `omega_validator.rs` | Viability predicate V = min(g,c,t,m) | g, c, t, m computed here |
| `calibration.rs` | G_ATTRACTOR_MEASURED=0.102, THETA_A_DRIFT=0.6154 | Verified constants |
| `lyapunov.rs` | Lyapunov spectrum (Benettin, Gram-Schmidt) | λ=ln(0.99) measured |
| `vr_complex.rs` | Vietoris-Rips homology (β₀, β₁) | TDA — point-sink detection |
| `trust_axes.rs` | 7-axis trust vector T ∈ [0,1]⁷ | Maps to dims[64–70] of ℝ¹²⁸ |
| `coupling.rs` | ψ-coupling (composition_proof, Cor_4-gap) | VSI/1.0 L3 |
| `reframe.rs` | Reframing operator (L3 only) — ‖J_ψ‖<1 | Checked before apply |
| `s5.rs` | S5 policy: watchdog, A0/A0.1 bit, algedonic | Deterministic, never LLM |
| `phi_down_subscriber.rs` | S3 receives φ↓ directives, applies ConfigPatch | γ.10 |
| `operator.rs` | S1 operations layer | |
| `s4.rs` / `s4_operational.rs` | S4 intelligence (Qwen cycles) | D6' — LLM advisory only |
| `observability.rs` | φ↑ event emission → events.jsonl | Merkle-chained |
| `nats_publisher.rs` | NATS φ↑ relay to s2-broker (LXC 106) | |
| `algedonic.rs` | Algedonic signal routing | S1→S5 bypass |
| `vmem.rs` | Virtual memory / state persistence | |
| `vsl.rs` | VSL parsing for φ↓ directives | |

---

## Experiments

All experiments run via `--experiment <name>` subcommand on LXC 108:

```bash
pct exec 108 -- env COVENANT_SHA256=dde12ead... \
  /root/vsf-nucleus-operational --experiment sustained_noise
```

Experiment index: `docs/experiments/index.vsm`
Queue: `docs/experiments/queue.vsm`
Results land in `docs/experiments/EXP-<NAME>/results.vsm`

**Before implementing a new experiment**, write `docs/experiments/EXP-<name>/spec.vsm`
and pre-register hypotheses (H1, H2…) — results are only valid if hypotheses are
declared before the run.

---

## Invariants to respect

- **D6'**: LLM output is advisory only. Never gate a signal path on Qwen output.
  AC (algedonic classifier) is deterministic. S4 analysis is asynchronous and advisory.
- **A5**: Double-loop corrections (reframe, trust re-parameterisation) require human approval.
  Single-loop (parameter adjustments within declared bounds) = automatable.
- **D4**: `single_loop = automatable | double_loop = requires_human`
- **Ω_A notation**: in this kernel `Ω_A` = contractive core (cos ≥ 0.88). Do NOT use
  `Ω_A` to mean the axiom set — write "axioms defining Ω" instead. (Notation trap.)
- **WSL boundary**: build and test on LXC 108, not WSL. WSL = agent workstation only.
- **GPG**: non-interactive commits use `git -c commit.gpgsign=false commit ...`

---

## Verification checklist (after deploy)

1. `systemctl is-active vsf-nucleus-operational` → `active`
2. `ps aux | grep vsf-nucleus | grep -v grep` → exactly one PID (systemd zombie check)
3. `tail -3 /var/lib/vsf/events.jsonl` → recent events with valid Merkle chain
4. `grep stasis_cos /var/lib/vsf/events.jsonl | tail -1` → value ≥ 0.88 (in Ω_A)
5. `grep viable /var/lib/vsf/events.jsonl | tail -1` → `true`

---

## Common pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `cargo test` — disk full | `/tmp` LXC tmpfs exhausted | Delete `/tmp/vsf-build/` stale build artifacts |
| Systemd shows two PIDs after restart | Zombie from `systemctl stop` race | `kill -9 <old-pid>` then verify single process |
| S4 cycles fire but produce no output | `OLLAMA_URL` unset or Ollama down | Check `systemctl status ollama` on LXC 101 |
| `phi_down_audit` trajectory checks silent | `OLLAMA_URL` not in vsf-s3-star env | Set in LXC 107 unit env |
| `events.jsonl` Merkle chain broken | Binary redeployed mid-cycle | Stop service, verify chain head, restart |

---

## Where to look for context

- **What's running now**: `ssh root@n02 vsf-q services` (state.db authority)
- **Open experiments**: `docs/experiments/queue.vsm`
- **Paper / theory**: `docs/papers/attractor_convergence/main.tex`
- **Session continuity**: `HANDOFF.vsm.md` last block
- **Task backlog**: `TASKS.vsm`
