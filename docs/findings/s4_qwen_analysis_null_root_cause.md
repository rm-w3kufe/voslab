# S4 Qwen Analysis Null — Root cause

**Date:** 2026-07-14
**Task:** S4-QWEN-ANALYSIS-FIX
**Author:** DeepSeek (S1 executor)

## Finding

`s4_intelligence.json` at `/run/vsf/s4_intelligence.json` on LXC 101 shows:
- `qwen_analysis: None`
- `integrity_check: skipped`
- `trigger: clean` (no novel pattern detected)
- `timestamp`: cycle 425

The file exists and is being updated — the S4 cycle runs — but the qwen analysis field is always None.

## Root cause

Ollama was migrated from LXC 101 to LXC 110 (DEBT_S4_ISOLATION, 2026-06-26, W3-OLLAMA-MIGRATE). The intelligence script that calls qwen and populates `qwen_analysis` was not reconfigured to point to the new ollama endpoint (LXC 110, `10.10.20.110:11434`).

The script that writes `s4_intelligence.json` was not found in `/usr/local/bin/` or the Rust binary strings — it may have been:
1. Removed during the migration and not replaced, or
2. Left in place but with a stale endpoint to LXC 101's ollama (which no longer runs)

## Impact

- `integrity_check` is skipped when `qwen_analysis` is None
- S4 has no LLM-based pattern analysis — the `novel_pattern_candidate` defaults to False
- S4 still produces `s4_clima_bundle.json` and `s4_markov_projection.json` (statistical analyses) — only the Qwen-based analysis path is broken
- The system is not degraded, but S4 intelligence is running at reduced capability

## Recommended fix

1. Locate the intelligence script that calls qwen and writes `s4_intelligence.json` (may be a Python script in a non-standard path, or a Rust module)
2. Update the ollama endpoint to `http://10.10.20.110:11434`
3. Re-deploy and verify `qwen_analysis` becomes non-null in the next S4 cycle
4. Re-enable `integrity_check` after qwen analysis is restored
