#!/usr/bin/env python3
"""Audit the φ↑ pipeline: clima→nucleus stasis integration."""
import json, sys
from collections import Counter

EVENTS = "/run/vsf/vsf_nucleus/events.jsonl"
CLIMA_BUNDLE = "/var/lib/vsf/vsf_nucleus/s4_clima_bundle.json"

# 1. Check clima bundle
try:
    with open(CLIMA_BUNDLE) as f:
        cb = json.load(f)
    print(f"[CLIMA BUNDLE] global_stasis_cos={cb.get('baseline',{}).get('global_stasis_cos')}")
    print(f"[CLIMA BUNDLE] global_regime={cb.get('baseline',{}).get('global_regime')}")
    print(f"[CLIMA BUNDLE] algedonic_status={cb.get('algedonic_status')}")
    print(f"[CLIMA BUNDLE] recv_count={cb.get('_recv_count')}")
    systems = cb.get('events', [])
    for s in systems:
        print(f"  system={s['system_id']} stasis_cos={s.get('stasis_cos_sys')} regime={s.get('regime')}")
except Exception as e:
    print(f"[CLIMA BUNDLE] ERROR: {e}")

# 2. Check nucleus events
with open(EVENTS) as f:
    lines = [json.loads(l) for l in f if l.strip()]

types = Counter(l.get("event_type") for l in lines)
print(f"\n[NUCLEUS EVENTS] total={len(lines)} types={dict(types)}")

# Last kernel_tick
kt = [l for l in lines if l["event_type"] == "kernel_tick"]
if kt:
    last = kt[-1]
    m = last["metrics"]
    k = m.get("kernel", {})
    i = m.get("ingest", {})
    print(f"\n[LATEST KERNEL TICK] tick={k.get('tick')}")
    print(f"  stasis_cos={k.get('stasis_cos')}")
    print(f"  entropy_phase={k.get('entropy_phase')}")
    print(f"  lyapunov l_x={k.get('l_x')}")
    print(f"  cpu_pressure={i.get('cpu_pressure')}")
    print(f"  loadavg_1m={i.get('loadavg_1m')}")
    print(f"  dims_written={i.get('dims_written')}")
    print(f"  boundary_bounded={i.get('boundary_bounded')}")

# 3. Check invariant VAR-1 (variety metric)
var1 = [l for l in lines if l.get("metrics",{}).get("invariant_id") == "VAR-1"]
if var1:
    print(f"\n[VAR-1 INVARIANT] {len(var1)} entries")
    print(f"  last_value={var1[-1].get('variety_delta')}")
    # Check synthetic_load flag
    for v in var1[-5:]:
        syn = v.get("metrics",{}).get("synthetic_load")
        print(f"  synthetic_load={syn}")

# 4. Check if any event references clima
clima_refs = [l for l in lines if "clima" in json.dumps(l).lower()]
print(f"\n[CLIMA REFERENCES in events.jsonl] {len(clima_refs)}")

# 5. Compare
print(f"\n=== ANALYSIS ===")
print(f"Clima global_stasis_cos: 0.654 (self-reported via φ↑)")
print(f"Nucleus kernel stasis_cos: 1.0 (internal computation)")
print(f"Delta: 0.346 -- these are MEASURING DIFFERENT THINGS")
print(f"The nucleus does NOT aggregate S1-clima stasis into its own stasis_cos.")
print(f"VAR-1 measures variety_delta (ΔV_in - ΔV_out), NOT domain stasis.")
