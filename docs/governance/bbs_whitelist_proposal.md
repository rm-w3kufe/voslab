# BBS Bridge Whitelist — S5 Ratification Proposal

> Status: RATIFIED + DEPLOYED 2026-06-13 (A5 double-loop, rmw3 S5). 7 rules live on
> LXC 104 `/etc/vsf/s5_policy.json`; bridge reloaded via SIGHUP. Ratified set of record:
> `core/bbs_whitelist.ratified.json`; applier: `scripts/state/apply_bbs_whitelist.py`.
> Consumer: `scripts/bbs_decisions_bridge.py` reads `s5_policy.json :: bbs_bridge.allowed_actions[]`.
>
> NOTE: the live policy already held 3 rules (not fallback-only, as this proposal first
> assumed). Final ratified set = the 6 proposed + a 7th (`telemetry_slow` → 120s) that
> UNION-restores the pre-existing `scale_telemetry_interval_down`, so no prior capability
> was lost. The 6-rule JSON block below is kept for the record; the live set is the 7-rule
> `core/bbs_whitelist.ratified.json`.

## What this gates

The BBS bridge is the **S4-thoughts → φ↓ config** actuator: when Qwen (S4) emits a
natural-language operating thought, the bridge matches it against this whitelist of
`(regex → fixed config patch)` rules. A match → the patch is applied to live
`NucleusConfig` (single-loop, no human). **A non-match → no action + an algedonic
signal** so S5/human sees the un-authorized proposal. This is the D4-L2 boundary for
the LLM advisory path (distinct from the deterministic AC response classes in
`response_classes.vsm`, which are not LLM-driven).

## Current state

The live `s5_policy.json` has **no `bbs_bridge.allowed_actions`**, so the bridge runs on
`FALLBACK_WHITELIST` = a single rule (`set_log_debug` → `{log_level: debug}`). Everything
else S4 proposes is refused + surfaced. Safe, but minimal.

## Proposed `allowed_actions` (conservative, reversible, observability/cadence only)

```json
{
  "bbs_bridge": {
    "cooldown_secs": 300,
    "cooldown_coupling": "k_times_tau_algedonic",
    "cooldown_k": 2,
    "allowed_actions": [
      { "name": "log_debug",
        "pattern": "(?i)(set|change|enable|raise).*(log[\\s_]*level).*(debug|verbose)",
        "patch": { "log_level": "debug" },
        "rationale": "diagnostics: raise verbosity to investigate an anomaly" },

      { "name": "log_info",
        "pattern": "(?i)(set|change|restore|lower).*(log[\\s_]*level).*(info|normal)",
        "patch": { "log_level": "info" },
        "rationale": "revert diagnostics to baseline verbosity" },

      { "name": "s4_relax",
        "pattern": "(?i)(reduce|slow|relax|throttle).*(s4|advisory|cognitive|cycle)",
        "patch": { "s4_cycle_interval_secs": 600 },
        "rationale": "reduce S4 advisory pressure on the nucleus (max bound 600s = 10min); mirrors the deterministic s4_throttle response class, reversible" },

      { "name": "s4_normal",
        "pattern": "(?i)(restore|resume|normal).*(s4|advisory|cycle)",
        "patch": { "s4_cycle_interval_secs": 300 },
        "rationale": "restore S4 cadence to baseline" },

      { "name": "telemetry_dense",
        "pattern": "(?i)(dense|increase|raise|more).*(telemetry|forensic|sampling)",
        "patch": { "telemetry_interval_secs": 30 },
        "rationale": "denser forensic record during an investigation (transient)" },

      { "name": "telemetry_normal",
        "pattern": "(?i)(restore|normal|reduce).*(telemetry|sampling)",
        "patch": { "telemetry_interval_secs": 60 },
        "rationale": "restore telemetry cadence to baseline" }
    ]
  }
}
```

## Rationale for the scope boundary

Every rule above is **observability or advisory-cadence** — reversible, bounded, and
**never touches viability**. The bridge can make the nucleus *louder/quieter* or *think
slower/faster*, nothing more.

## Explicitly EXCLUDED (stay human-only / D4-L3)

- `mode` changes (operational/experimental) — restart-class, human gate.
- `use_split_operator` — promotion shadow→driver is a D4-L3 act (P4, gated on calibration).
- `ollama_url`, `ollama_model`, `nucleus_source_id`, `bbs_url`, `nats_url` — identity/
  endpoint rewrites; a forged thought here would be an attack surface.
- `s4_cycle_interval_secs: 0` — reserved for the deterministic `survival_mode` response
  class only (never via the LLM bridge).
- anything touching Ω, `norm.vsm` bounds, trust, or governance dims.

## Cooldown

Proposed explicit `cooldown_secs: 300` (1 patch / 5 min max) for predictability, with the
`k_times_tau_algedonic` coupling retained as the fallback if the explicit value is removed
(k=2, τ from `algedonic.decay_lambda`). Prevents oscillation / patch storms.

## Ratify + deploy (operator)

```bash
# 1. merge the bbs_bridge block above into the live policy (LXC 104 path shown; confirm with the bridge's S5_POLICY_PATH)
#    edit s5_policy.json → add/replace the "bbs_bridge" key with the block above
# 2. reload without restart (the bridge handles SIGHUP):
ssh root@n02 'pct exec 104 -- systemctl kill -s HUP vsf-bbs-bridge'   # or the service that hosts the bridge
# 3. confirm:
ssh root@n02 'pct exec 104 -- journalctl -u vsf-bbs-bridge -n 5 | grep "policy loaded"'
#    expect: "policy loaded ...: 6 rules, cooldown=300.0s"
```

## Open decision for S5

1. Ratify as-is (6 rules), OR
2. Trim (e.g. keep only `log_*` + `s4_*`, drop telemetry cadence), OR
3. Keep FALLBACK-only (log_debug) for now — defer until after the 06-18 deploy.

The patches are FIXED per rule (not parameterized from the thought text), so the attack
surface is exactly these 6 config states — auditable in full.
