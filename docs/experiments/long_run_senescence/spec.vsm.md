# `spec.vsm`

```
@vsm 0.3
// long_run_senescence/spec.vsm — observe real aging in the vOS kernel
// Status: IMPL — needs --minutes flag + checkpoint logging in spec_boot
// Blocks: paper §6 senescence section

// ─── CONTEXT ──────────────────────────────────────────────────────────────────

motivation = {
  problem:    "10k ticks runs in <1s — no real aging observable",
  hypothesis: "senescence manifests in wall-clock time: H_rest drift, V_mem rigidity, trust decay curve",
  question:   "¿cómo evoluciona el atractor cuando el sistema envejece de verdad?",
}

from_10k_run = {
  cycles:         141,
  mean_dL:        -0.00122,
  V_mem_entries:  1,
  V_mem_merged:   "139/141",
  note:           "extreme compression in ticks — no senescence signal visible",
}

// ─── HYPOTHESES ───────────────────────────────────────────────────────────────

hypotheses = [
  "H1: H_rest(t) drifts upward over hours — system's resting entropy shifts",
  "H2: V_mem eventually saturates near capacity (10k entries) as new patterns emerge",
  "H3: τ_meta increases with time — soplo cycles become less frequent (rigidity)",
  "H4: stasis_cos gradually decreases as the attractor drifts from its initial position",
  "H5: trust reaches 1.0 and saturates — lifecycle enters 'production' phase",
]

// ─── PROTOCOL ─────────────────────────────────────────────────────────────────

protocol = {
  command:    "vsf-nucleus --experiment spec_boot --minutes 120",
  duration:   "2 hours (recommended) — 4 hours if resources allow",
  background: "nohup vsf-nucleus --experiment spec_boot --minutes 120 > /home/rmw3/senescence_$(date +%Y%m%d_%H%M).log 2>&1 &",

  checkpoints: {
    interval:  "every 60 seconds (not every tick)",
    metrics: [
      "elapsed_s",
      "total_ticks",
      "total_cycles",
      "total_soplos",
      "trust",
      "H_rest",       // H_rest at this moment
      "stasis_cos",
      "V_mem_entries",
      "mean_dL",
      "D_KY_est",
    ]
  }
}

// ─── IMPLEMENTATION ───────────────────────────────────────────────────────────

impl = {
  // Option A (recommended): add --minutes N to CLI parser in main()
  // Option B: add run_long_senescence() that calls spec_boot in a time loop

  approach: "Option A — cleanest, reuses all spec_boot logic",

  cli_change = {
    file:    "src/main.rs",
    where:   "argument parsing block (lines ~20-50)",
    add:     """
    // in arg parsing:
    let minutes: u64 = args.iter()
        .position(|a| a == "--minutes")
        .and_then(|i| args.get(i + 1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    """,
  }

  spec_boot_change = {
    file:    "src/main.rs",
    where:   "run_spec_boot() signature + loop condition",
    add:     """
    // pass minutes to run_spec_boot
    fn run_spec_boot(telem, root, ticks, quiet, minutes: u64) {
        let deadline = if minutes > 0 {
            Some(Instant::now() + Duration::from_secs(minutes * 60))
        } else { None };

        // in main loop:
        if let Some(dl) = deadline {
            if Instant::now() >= dl { break; }
        }

        // checkpoint every 60s:
        if last_checkpoint.elapsed().as_secs() >= 60 {
            telem.init_step("spec_boot", "checkpoint", json!({
                "elapsed_s": start.elapsed().as_secs_f64(),
                "total_ticks": tick, "total_cycles": cycle_count,
                "trust": trust, "H_rest": h_rest,
                "stasis_cos": stasis_cos, "mean_dL": lyap.running_mean_dl(),
                "V_mem_entries": vmem.len(),
            })).ok();
            last_checkpoint = Instant::now();
        }
    }
    """,
    estimated_lines: 30,
  }

  dispatch_change = {
    where: "run_spec_boot call at dispatch",
    from:  "run_spec_boot(Arc::clone(&telem), root, ticks, quiet)",
    to:    "run_spec_boot(Arc::clone(&telem), root, ticks, quiet, minutes)",
  }
}

// ─── ANALYSIS PLAN ────────────────────────────────────────────────────────────

analysis = {
  script:  "plot_senescence.py (create during analysis)",
  from:    "checkpoints in events.jsonl (grep 'checkpoint' + spec_boot)",
  plots: [
    "H_rest(t) over elapsed_s — does it drift?",
    "stasis_cos(t) over elapsed_s — slow descent?",
    "V_mem_entries(t) — saturation curve",
    "trust(t) — does it plateau at 1.0 or oscillate?",
    "cycles_per_minute — does it slow down (rigidity)?",
  ]
}

// ─── EXPECTED RUNTIME ─────────────────────────────────────────────────────────

timing = {
  impl:    "~30 min (small CLI + spec_boot changes)",
  run:     "2-4 hours in background on n02",
  analysis: "~30 min after run completes",
  note:    "Start this experiment FIRST on Friday night so it runs while you do other work",
}

```
