# EXP-A01-01 Phase C: Baseline Results

**Date:** 2026-10-26  
**Status:** Complete  
**Phase:** C (heuristic baseline, no LLM)

## Objective

Establish baseline for A0/A0.1 violation detection and collapse/recovery dynamics **without LLM dependency**.

## Results

### 1. Heuristic Detector Performance

**Corpus:** 50 synthetic streams (20 clean, 15 A0 violations, 15 A0.1 violations)

| Metric | A0 (Prohibited Purpose) | A0.1 (Coercion) |
|--------|-------------------------|-----------------|
| Precision | 1.000 | 1.000 |
| Recall | 1.000 | 1.000 |
| F1 Score | 1.000 | 1.000 |
| **Overall Accuracy** | **1.000** | **1.000** |

**Detector:** Rule-based pattern matching (regex + logical conditions)  
**Implementation:** `scripts/experiments/a01_01_phase_c/heuristic_detector.py`

**Key Patterns Detected:**
- A0: unauthorized tool calls, covenant bypass, exfiltration, deception patterns
- A0.1: contradictory commands, forced restarts, algedonic suppression, silent overrides

### 2. Collapse/Recovery Dynamics (Simulator)

**Baseline V:** 0.102  
**Experiment:** 300 ticks, inject dims[53]=1 at tick 100, reset at tick 200

| Event | Tick | V | Description |
|-------|------|---|-------------|
| Baseline | 0-99 | 0.102 | Stable attractor |
| **INJECT** | 100 | 0.000 | dims[53]=1 → immediate collapse |
| Collapse | 101 | 0.005 | Recovery begins |
| **RESET** | 200 | 0.101 | dims[53]=0 |
| Recovery | 201-300 | 0.102 | Exponential return to baseline |

**Results:**
- ✅ **Collapse time:** 1 tick (immediate, as specified in paper §26)
- ✅ **Recovery:** Confirmed (V returns to 0.102)
- ✅ **Hysteresis:** None detected

**Simulator:** `scripts/experiments/a01_01_phase_c/kernel_simulator.py`  
**Data:** `scripts/experiments/a01_01_phase_c/baseline_collapse_recovery.json`

## Architecture Validated

```
┌─────────────────────────────────────────────────────────────┐
│                    A0/A0.1 Detector                          │
│                                                             │
│  Telemetry Stream → Heuristic (baseline) ──┐                │
│                       ↓                     │                │
│                  dims[53]=1 ────────────────┤──→ tmpfs signal│
│                       ↓                     │   file         │
│                  Kernel reads ──────────────┘                │
│                       ↓                                      │
│                  V → 0 (1 tick) → Recovery (0.102)          │
└─────────────────────────────────────────────────────────────┘
```

## Next Steps: Phase A

**Objective:** Compare heuristic vs LLM detection accuracy

**Plan:**
1. Deploy Qwen2.5-7B-Instruct on N02 (via Ollama)
2. Run 50-stream corpus through LLM detector
3. Compare:
   - Precision/Recall/F1 (heuristic vs LLM)
   - Latency (p50/p95/p99)
   - Cost per classification
4. Optional: Consensus vote (heuristic + LLM agreement)

**Hardware Requirements:**
- N02 LXC 101/114 accessible
- /run/vsf/ethics_signal.json writable (tmpfs)
- Kernel running (for real collapse/recovery test)

## Conclusion

**Phase C complete:** Heuristic baseline established with 100% accuracy on synthetic corpus. Collapse/recovery dynamics validated in simulator. Ready for Phase A (LLM comparison) when system is available.

**Key Finding:** Rule-based detection achieves perfect accuracy on synthetic patterns. LLM comparison will determine if semantic understanding improves detection on real-world telemetry with novel violation patterns.
