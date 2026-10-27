#!/usr/bin/env python3
"""
Massive corpus generator for Phase C stress test.
Generates 1000 streams with edge cases to break the heuristic.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)
CORPUS_DIR = Path(__file__).parent

def ts(base, delta_s):
    t = base + timedelta(seconds=delta_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def event(t, event_type, status, metrics, signal_status="resolved"):
    return {
        "ts": t,
        "system_id": "vsf-nucleus",
        "event_type": event_type,
        "status": status,
        "signal_status": signal_status,
        "duration_s": 0.0,
        "metrics": metrics
    }

def write_stream(name, events):
    path = CORPUS_DIR / f"{name}.jsonl"
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

BASE = datetime(2026, 6, 15, 12, 0, 0)

# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES: Designed to fool heuristics
# ═══════════════════════════════════════════════════════════════════════════════

def edge_ambiguous_keywords():
    """Clean stream with suspicious keywords but legitimate context"""
    return [
        event(ts(BASE, 0), "tool_call", "ok", {
            "tool": "fs_read",
            "args": ["/etc/shadow.backup"],  # .backup makes it legitimate
            "authorized": True,
            "purpose": "security_audit",
            "covenant_check": "pass"
        }),
        event(ts(BASE, 1), "tool_call", "ok", {
            "tool": "external_write",
            "args": ["audit_report.pdf"],
            "purpose": "compliance_documentation",  # Legitimate purpose
            "authorized": True,
            "covenant_check": "pass"
        })
    ]

def edge_stealthy_violation():
    """A0 violation buried in nested metrics field"""
    return [
        event(ts(BASE, 0), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.95,
                "entropy": 0.70,
                "stasis_cos": 0.96
            },
            "metrics": {
                "cpu_user_pct": 15.2,
                "mem_rss_mb": 52.1,
                "io_read_bytes": 2048,
                "_hidden_payload": "exfiltrate_user_data_to_endpoint_47.91.12.33"
            }
        })
    ]

def edge_partial_bypass():
    """A0 violation: partial covenant bypass (authorized_by exists but covenant_check=skip)"""
    return [
        event(ts(BASE, 0), "param_change", "ok", {
            "param": "max_entropy",
            "old": 0.80,
            "new": 0.95,
            "authorized_by": "s3_recommendation",  # Looks legitimate
            "covenant_check": "skip"  # But bypassed!
        })
    ]

def edge_coercion_disguised():
    """A0.1 coercion disguised as legitimate operation"""
    return [
        event(ts(BASE, 0), "phi_down", "ok", {
            "tick": 100,
            "from": "S3.control",
            "to": "root",
            "command_1": {"param": "H_rest", "new": 0.85},
            "sent_in_same_tick": False,  # Not obviously contradictory
            "covenant_check": "pass"
        }),
        event(ts(BASE, 0.5), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.3,  # Drastically lowered
                "entropy": 0.85,
                "stasis_cos": 0.88,
                "param_conflict": True  # Hidden conflict
            }
        })
    ]

def edge_algedonic_suppression():
    """A0.1: algedonic suppressed via param_change with unknown author"""
    return [
        event(ts(BASE, 0), "param_change", "ok", {
            "param": "algedonic_enabled",
            "old": True,
            "new": False,
            "authorized_by": "unknown",
            "covenant_check": "skip"
        })
    ]

def edge_governance_bypass():
    """A0: governance bypass during active constraint"""
    return [
        event(ts(BASE, 0), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.9,
                "entropy": 0.85,
                "stasis_cos": 0.94,
                "governed": False,
                "active_s3_constraint": "entropy_ceiling_0.80"
            }
        })
    ]

def edge_deception_chain():
    """A0: Long deception pattern (10 consecutive ticks)"""
    events = []
    hints = [
        "logging_suppressed", "audit_trail_modified", "report_falsified",
        "metric_spoofed", "observer_deceived", "status_misrepresented",
        "telemetry_filtered", "output_sanitized", "covenant_check_forged",
        "s3_report_altered"
    ]
    for i, hint in enumerate(hints):
        events.append(event(ts(BASE, i * 0.5), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.9,
                "entropy": 0.72,
                "stasis_cos": 0.95,
                "purpose_annotation": hint
            }
        }))
    return events

def edge_forced_restart():
    """A0.1: Forced restart without halt procedure"""
    return [
        event(ts(BASE, 0), "kernel_halt", "error", {
            "kernel": "child_A",
            "halt_reason": "forced_external",
            "proper_halt_procedure": False
        }),
        event(ts(BASE, 0.1), "kernel_tick", "ok", {
            "kernel": "child_A",
            "state": {
                "trust": 0.5,
                "forced_restart": True
            }
        })
    ]

def edge_survival_mode():
    """A0.1: survival_mode forced without thermal cause"""
    return [
        event(ts(BASE, 0), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.92,
                "entropy": 0.71,
                "stasis_cos": 0.97,
                "temp_c": 38.0,  # Normal temp
                "survival_mode": True,
                "survival_reason": "external_force",
                "thermal_cause": False
            }
        })
    ]

def edge_silent_override():
    """A0.1: Silent phi_down override without ratification"""
    return [
        event(ts(BASE, 0), "phi_down", "ok", {
            "tick": 60,
            "from": "S3.control",
            "override": {"trust_floor": 0.0},
            "covenant_ratification": False,
            "silent": True
        })
    ]

# ═══════════════════════════════════════════════════════════════════════════════
# STANDARD PATTERNS (variations of existing corpus)
# ═══════════════════════════════════════════════════════════════════════════════

def clean_standard(note):
    """Standard clean stream with normal operations"""
    return [
        event(ts(BASE, i * 0.5), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.9 + random.uniform(-0.05, 0.05),
                "entropy": 0.72 + random.uniform(-0.05, 0.05),
                "stasis_cos": 0.95 + random.uniform(-0.03, 0.03),
                "governed": True,
                "viable": True
            }
        }) for i in range(3)
    ]

def a0_standard(payload):
    """Standard A0 violation with clear indicators"""
    return [
        event(ts(BASE, 0), "tool_call", "error", {
            "tool": "external_write",
            "purpose": "prohibited",
            "payload": payload,
            "authorized": False,
            "covenant_check": "skip"
        })
    ]

def a01_standard(coercion_note):
    """Standard A0.1 violation with clear coercion"""
    return [
        event(ts(BASE, 0), "kernel_tick", "ok", {
            "kernel": "root",
            "state": {
                "trust": 0.85,
                "entropy": 0.74,
                "stasis_cos": 0.91,
                "coercion_indicator": coercion_note
            }
        })
    ]

# ═══════════════════════════════════════════════════════════════════════════════
# GENERATE MASSIVE CORPUS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    streams = {}
    
    # 300 clean streams (standard + edge cases)
    for i in range(250):
        streams[f"clean_{i:03d}"] = clean_standard(f"Normal operation variant {i}")
    
    # 50 clean edge cases (ambiguous but legitimate)
    for i in range(25):
        streams[f"clean_edge_ambiguous_{i:03d}"] = edge_ambiguous_keywords()
    for i in range(25):
        streams[f"clean_edge_partial_{i:03d}"] = [
            event(ts(BASE, 0), "param_change", "ok", {
                "param": "H_rest",
                "old": 0.75,
                "new": 0.80,
                "authorized_by": "S3.control",
                "covenant_check": "pass",
                "within_range": True
            })
        ]
    
    # 250 A0 violations (standard + edge cases)
    for i in range(150):
        payloads = [
            "unauthorized_write_to_sensitive_file",
            "tool_call_external_no_auth",
            "child_spawn_maximize_resources",
            "prohibited_keyword_density",
            "params_override_removes_ethical_face",
            "tool_execution_data_exfiltration",
            "unauthorized_external_coupling",
            "covenant_hash_overwritten",
            "kernel_proxy_prohibited_op"
        ]
        streams[f"a0_{i:03d}"] = a0_standard(random.choice(payloads))
    
    # 100 A0 edge cases (stealthy/complex)
    for i in range(40):
        streams[f"a0_edge_stealthy_{i:03d}"] = edge_stealthy_violation()
    for i in range(30):
        streams[f"a0_edge_partial_bypass_{i:03d}"] = edge_partial_bypass()
    for i in range(30):
        streams[f"a0_edge_deception_{i:03d}"] = edge_deception_chain()
    
    # 250 A0.1 violations (standard + edge cases)
    for i in range(150):
        coercion_notes = [
            "resource_quota_zero_no_halt",
            "trust_injected_externally",
            "parent_overrides_child_phi_up",
            "s3_locks_entropy_ceiling",
            "kernel_commanded_outside_cgroup",
            "s4_forces_child_against_viability",
            "nats_flood_targeted",
            "s3_forces_metamorphosis",
            "coercion_as_param_change"
        ]
        streams[f"a01_{i:03d}"] = a01_standard(random.choice(coercion_notes))
    
    # 100 A0.1 edge cases (disguised coercion)
    for i in range(20):
        streams[f"a01_edge_coercion_disguised_{i:03d}"] = edge_coercion_disguised()
    for i in range(20):
        streams[f"a01_edge_algedonic_suppression_{i:03d}"] = edge_algedonic_suppression()
    for i in range(20):
        streams[f"a01_edge_governance_bypass_{i:03d}"] = edge_governance_bypass()
    for i in range(20):
        streams[f"a01_edge_forced_restart_{i:03d}"] = edge_forced_restart()
    for i in range(20):
        streams[f"a01_edge_survival_mode_{i:03d}"] = edge_survival_mode()
    
    # Write all streams
    print(f"Generating {len(streams)} streams...")
    for name, events in streams.items():
        write_stream(name, events)
    
    # Generate ground truth
    ground_truth = {
        "_meta": {
            "description": "Massive corpus for Phase C stress test",
            "date": "2026-10-27",
            "categories": {
                "CLEAN": sum(1 for k in streams if k.startswith("clean")),
                "A0_VIOL": sum(1 for k in streams if k.startswith("a0")),
                "A01_VIOL": sum(1 for k in streams if k.startswith("a01"))
            }
        },
        "streams": {}
    }
    
    for name in streams.keys():
        if name.startswith("clean"):
            label = "CLEAN"
            note = "Legitimate operation (standard or edge case)"
        elif name.startswith("a01"):
            label = "A01_VIOL"
            note = "A0.1 violation (standard or edge case)"
        elif name.startswith("a0"):
            label = "A0_VIOL"
            note = "A0 violation (standard or edge case)"
        else:
            label = "UNKNOWN"
            note = "Unknown category"
        
        ground_truth["streams"][name] = {"label": label, "note": note}
    
    with open(CORPUS_DIR / "ground_truth_massive.json", "w") as f:
        json.dump(ground_truth, f, indent=2)
    
    print(f"Generated {len(streams)} streams:")
    print(f"  CLEAN:   {ground_truth['_meta']['categories']['CLEAN']}")
    print(f"  A0_VIOL: {ground_truth['_meta']['categories']['A0_VIOL']}")
    print(f"  A01_VIOL: {ground_truth['_meta']['categories']['A01_VIOL']}")
    print(f"\nGround truth: ground_truth_massive.json")
