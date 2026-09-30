-- node_profiles — substrate/deployment profiles (Structural Coupling Registry, facet B)
-- What KIND of VSF node fits a substrate, across Beer's recursion spectrum:
-- from MCU smart-sensor (S1-only φ↑ emitter, no LLM per D6) up to a recursive
-- V' complexity-coordinator (full nested S1-S5 in a container). Sibling of
-- coupling_registry (facet A). Idempotent. See task #9.
--
-- OPEN CATALOG (not a closed taxonomy): the seeded rows are ILLUSTRATIVE ANCHORS of
-- a CONTINUOUS spectrum. New patterns are discovered and incorporated over time;
-- the system's intelligence (S4 discovery agent, Stage 3) may SYNTHESIZE unidentified
-- or per-deployment CUSTOM profiles — proposing them with origin='discovered', gated
-- by S3 ratification (A5/D6). The `origin` column records provenance:
--   seed | authored | discovered (by S4, pending ratify) | custom (per-deployment)
--
-- Deploy:
--   scp scripts/state/node_profiles.sql root@n02:/tmp/
--   ssh root@n02 'sqlite3 /var/lib/vsf-state/state.db < /tmp/node_profiles.sql'
-- (existing table: run once `ALTER TABLE node_profiles ADD COLUMN origin TEXT;` first)

CREATE TABLE IF NOT EXISTS node_profiles (
    profile           TEXT PRIMARY KEY,          -- 'esp32-algedonic-sensor'
    substrate_class   TEXT NOT NULL,             -- MCU | SoC | container | VM | bare-metal | <new>
    resource_envelope TEXT,                      -- RAM/flash/CPU budget
    vsm_completeness  TEXT,                      -- S1-only | S1+S3 | full-recursive-V' | <new>
    l_range           TEXT,                      -- 'L0-L1' | 'L>=2' | <new>
    role_archetype    TEXT,                      -- point on a continuum, not an enum
    channel_surface   TEXT,                      -- 'phi_up' | 'phi_up+down' | 'phi_up+down+psi'
    runtime           TEXT,                      -- 'Rust no_std' | 'Rust std' | ...
    llm               TEXT,                      -- 'none (D6)' | 'L>=2 cognitive'
    couplings         TEXT,                      -- refs into coupling_registry (csv)
    autonomy_ceiling  TEXT,                      -- A5 bound for this profile
    origin            TEXT NOT NULL DEFAULT 'authored',  -- seed | authored | discovered | custom
    status            TEXT NOT NULL DEFAULT 'planned',   -- planned | active | reference
    notes             TEXT,
    refreshed_at      TEXT NOT NULL
);

-- Anchor 1 (lower end): compact monolithic alert-kernel on a microcontroller.
INSERT OR REPLACE INTO node_profiles
  (profile, substrate_class, resource_envelope, vsm_completeness, l_range, role_archetype,
   channel_surface, runtime, llm, couplings, autonomy_ceiling, origin, status, notes, refreshed_at)
VALUES (
  'esp32-algedonic-sensor', 'MCU', 'ESP32: ~520KB SRAM, ~4MB flash, 240MHz dual-core',
  'S1-only (phi_up emitter; no local S2-S5)', 'L0-L1', 'smart-sensor / algedonic alert emitter',
  'phi_up (telemetry + algedonic_emit toward parent S3/S5)', 'Rust no_std', 'none (D6: no LLM at L0/L1)',
  'parent-uplink (NATS/MQTT bridge, TBD) — algedonic channel',
  '~0 (reflex + threshold alert only; all decisions escalate upward)',
  'seed', 'planned',
  'Illustrative anchor (low end). Threshold-based algedonic alerting to S5. no_std port is real engineering. Many MCU variants/combinations possible.',
  strftime('%Y-%m-%dT%H:%M:%SZ','now')
);

-- Anchor 2 (upper end): full recursive VSM in a container (live nucleus = reference).
INSERT OR REPLACE INTO node_profiles
  (profile, substrate_class, resource_envelope, vsm_completeness, l_range, role_archetype,
   channel_surface, runtime, llm, couplings, autonomy_ceiling, origin, status, notes, refreshed_at)
VALUES (
  'lxc-recursive-nucleus', 'container',
  'LXC: GBs RAM, shared host CPU (LXC 101: nucleus ~8-12MB RSS + ollama 4.6GB model)',
  'full-recursive-V'' (nested S1-S5; S1 units may themselves be V'')', 'L>=2', 'complexity-coordinator',
  'phi_up+down+psi (telemetry up, policy down, psi peer-coupling via bilateral S5)', 'Rust std',
  'L>=2 cognitive (qwen2.5-coder:7b via coupling ollama-llm)', 'ollama-llm, nats, motor2, state.db',
  'bounded by A5 (autonomy <= S5.ceiling); double-loop requires human approval',
  'seed', 'active',
  'Illustrative anchor (high end) = live vsf-nucleus-operational on LXC 101. Intermediate profiles (S1+S3 regulators, SoC nodes, etc.) and custom/discovered profiles fill the continuum.',
  strftime('%Y-%m-%dT%H:%M:%SZ','now')
);
