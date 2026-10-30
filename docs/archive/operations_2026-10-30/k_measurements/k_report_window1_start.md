# K Measurement — Window 1 START

**Window:** W1
**Start (UTC):** 2026-05-25T14:42:00Z
**Expected close:** 2026-06-01T14:42:00Z (7 days)
**Source:** γ.7 LXC 101 `/var/lib/vsf/vsf_nucleus/events.jsonl`
**Collector PID:** 309142 (host: n01, ssh tail -F)
**Sink:** `/home/rmw3/vsf-measurements/raw/events-window1.jsonl`
**Protocol:** `docs/operational/k_measurement_protocol_2026-05-25.md` §3
**Status:** ⏳ COLLECTING

---

## T=0 baseline (backfilled events at start)

- Events parsed: **729**
- Event types: `kernel_tick` only (γ.7 single S1 instance, no recursion yet)
- Merkle chain: ✓ continuous (verified by collector tail)
- K_φ↑ baseline: **1.0000** (1 kernel_tick per 60s bucket → 1 phi_up per state change)
- K_φ↓: **undefined** (no S5 decisions yet — Motor 2 not active in γ.7)
- τ: **undefined** (no paired s4→param_change yet)

## Interpretation

- ✓ baseline K_φ↑ = 1.0 matches protocol §3.2 expectation
- ◐ K_φ↓ requires either:
  - param_change emission from γ.5 reload path (§4.1) — VSF backlog
  - S4 cycle reactivation in production — depends on Ollama load policy
- ◐ τ measurement needs both above

## Validity for GATE_3 close

W1 collects nucleus-only telemetry. **GATE_3 CLOSE requires BBH integration as S1**
so that there are multiple state changes per minute, generating measurable
attenuation. Until BBH integration:
- W1 establishes baseline (K_φ↑ = 1.0 in steady state, no anomalies)
- Validates collector pipeline + scripts
- Pre-commits the G(jω) sanity check (peak = K_total at ω→0)

## Synthetic sanity check (scripts work)

```
K_φ↑ = 0.85, K_φ↓ = 1.0, τ = 5.0, T_poll = 5.0
max|G(jω)| = 0.8500 at ω = 0.0010 rad/s
Math stability < 1.0:  PASS
BBH covenant < 0.8:    WARN (right at boundary, expected)
```

## Next checkpoints

- **2026-05-26 14:42 UTC** (T+24h): first daily roll-up, verify collector alive
- **2026-06-01 14:42 UTC** (T+7d): close W1, produce `k_report_window1.md`
- **GATE_3 close** depends on BBH integration as S1 → W2 with real load

## References

- Protocol: `docs/operational/k_measurement_protocol_2026-05-25.md`
- Scripts: `/home/rmw3/vsf-measurements/scripts/{k_compute.py,g_jw_verify.py}`
- BBH covenant: `bbh/spec/bbh_vsf_protocol_v3.vsm` §loop_stability
