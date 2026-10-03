-- Initial canonical content for vsf-state.db.
-- Rerunnable: every insert uses INSERT OR REPLACE so this acts as a
-- canonicalisation pass.

-- ─── LXC topology ───────────────────────────────────────────────────────
INSERT OR REPLACE INTO lxcs (id, role, ip, notes) VALUES
    (0,   'host',         '192.168.0.168', 'n02 Proxmox bare-metal host (NOT a container) — pseudo-node so host-level S3* agents/timers have a home for the lxcs FK. Runs: vsf-topology-reconcile (S3* census timer), vsf-state-populate.'),
    (101, 's3s4-nucleus','10.10.20.101', 'vsf-nucleus-operational + ollama (qwen2.5-coder:7b)'),
    (104, 's5-policy',   '10.10.20.104', 's5_console + vsf-bbs-bridge + vsf-s5-algedonic'),
    (105, 's1-bbh',      '10.10.30.110', 'bbh-prod (Bug Bounty Hunter, S1 work unit) on VLAN30; python3 :8081; NOT integrated (R6 internal-first gate); declared for model≡reality'),
    (106, 's2-broker',   '10.10.20.20',  'nats-server (canonical broker) + bbs-api'),
    (107, 's3star-audit','10.10.20.30',  'vsf-s3-star + collapsed nucleus + local nats + subagent seats (asc-paper/rust/exp); REAL ip is .30 (pct config + ARP), was wrongly .107 in canon — fixed 2026-06-06'),
    (108, 'dev-sandbox', '10.10.20.108', 'vsf-sandbox: hardening-arc test execution (AX-STATE-01 et al); no productive mounts, no state.db access; onboot=0'),
    (109, 's5-opsroom','10.10.20.109', 'S5 opsroom / view-host: clean modular view-host (legacy-module migration protocol, ref impl); hosts view-module cybernetic-rag (NATS phi-up subscriber + state_verify + static host); replaces SCADA on 101; onboot=1'),
    (110, 's4-intelligence','10.10.20.110', 'S4 Intelligence: Ollama qwen2.5-coder:7b isolated from S1/S3 kernel — DEBT_S4_ISOLATION 2026-06-26'),
    (112, 's1-clima',   '10.10.20.112', 'S1 climate kernel — recursive VSF L0-L3 — 98 units (87 L3 + 8 L2 + 2 L1 + 1 L0) — EXP-S1-CLIMA-01 LIVE 2026-06-26'),
    (113, 's1-econ',    '10.10.20.113', 'S1 socioeconomic kernel — Lange-Lerner tâtonnement (EXP-LL-01); distinct viable system from s1-clima; P0 calibration host (numpy); live S1 service + coupling_registry pending P2 (DSN-COUPLE-01)');

-- ─── components: build + deploy mapping (single source of truth) ────────
-- `name` = systemd unit name on the target LXC.
-- IMPORTANT: build_lxc is where cargo build runs. NEVER WSL.
-- build_lxc = 108 for ALL Rust components (S5 2026-06-22): 108 is the dedicated build SANDBOX
-- (cached crate trees, glibc 2.36 ≡ runtime; 101/107 are PROD — never build on prod). This is what
-- deploy_bundle.sh already does ('correct-by-construction'). deploy_target_lxc stays the runtime LXC.
INSERT OR REPLACE INTO components (
    name,                          source_dir,                              build_lxc, deploy_target_lxc, deploy_path,                                   notes
) VALUES
    ('vsf-nucleus-operational',    'projects/vsf-nucleus',                  108,       101,                '/root/vsf-nucleus-operational',                'wrapper: /root/nucleus-wrapper.sh; build on 108 sandbox, deploy to 101'),
    ('vsf-s3-star',                'projects/vsf-s3-star',                  108,       107,                '/usr/local/bin/vsf-s3-star',                    'build on 108 sandbox, deploy to 107'),
    ('vsf-s4-clima-bridge',        'projects/s1-clima/src/s4_clima_bridge.py', NULL,   101,                '/usr/local/bin/s4_clima_bridge.py',             'Python; s1-clima to LXC 101 S4 cross-domain context bridge; fixes name mismatch (was s4_clima_bridge, real unit is vsf-s4-clima-bridge.service — state.db was reporting active=0 for a live service)'),
    ('vsf-bbs-bridge',             'scripts/bbs_decisions_bridge.py',       NULL,      104,                '/usr/local/bin/bbs_decisions_bridge.py',        'Python; deploy via pct push + chmod'),
    ('vsf-g6-algedonic-sink',      'scripts/g6_algedonic_sink.py',          NULL,      104,                '/usr/local/bin/g6_algedonic_sink.py',           'Python; pairs with vsf-g6-algedonic-sink.service'),
    ('vsf-s5-algedonic',           'scripts/vsf_s5_agent.py',               NULL,      104,                '/usr/local/bin/vsf_s5_agent.py',                'Python; S5 triage agent (TRIAGE-EVIDENCE-RULE + L2 classifier). CORRECTED 2026-07-24: this row used to point at vsf_algedonic_subscriber.py, which NO unit executes — trusting that dead file''s SUBJECT caused a wrong "fix" to the algedonic publish subject. The unit ExecStarts vsf_s5_agent.py. vsf-s5-agent.service ran the SAME script in parallel (W2 dedup had regressed); stopped+disabled 2026-07-24 and its ordering dep on vsf-s5-ledger folded into this unit.'),
    ('vsf-s5-ledger',              'scripts/vsf_s5_ledger.py',              NULL,      104,                '/usr/local/bin/vsf_s5_ledger.py',               'Python; THE real algedonic consumer — subscribes vsf.<id>.algedonic.> (wildcard: a bare vsf.<id>.algedonic matches NOTHING) and writes the ledger. Was undeclared in canon until 2026-07-24.'),
    ('s5_console',                 NULL,                                    NULL,      104,                NULL,                                            'Python; legacy'),
    ('nats-server',                NULL,                                    NULL,      106,                NULL,                                            'third-party; broker'),
    ('bbs-api',                    NULL,                                    NULL,      106,                NULL,                                            'BBS HTTP API'),
    ('ollama',                     NULL,                                    NULL,      101,                NULL,                                            'third-party; LLM runtime'),
    ('vsf-view-host',              'opsroom/view_host',                     NULL,      109,                '/root/view_host/host.py',                       'Python stdlib; s5-opsroom formaid studio + view-modules (cybernetic-rag, system-topology); phi-up = events.jsonl file (bind-mount RO), not NATS'),
    ('vsf-topology-reconcile',     'scripts/state/topology_reconcile.py',   NULL,      0,                  '/usr/local/bin/vsf-topology-reconcile.py',      'S3* anti-orphan reconcile (model=reality census); HOST timer every 5min (--emit); deploy_target=0=host pseudo-node'),
    ('vsf-state-populate',         'scripts/state/populate.sh',             NULL,      0,                  '/usr/local/bin/vsf-state-populate',             'bash; HOST timer every 5min; refreshes state.db services + chain_state tables (the refreshed_at heartbeat); deploy_target=0=host pseudo-node'),
    ('vsf-state-attest',           'scripts/state/state_attest.py',         NULL,      0,                  '/usr/local/bin/vsf-state-attest',               'python3; HOST timer every 5min (--agent); AX-STATE PROD-A1a — tamper-evident attestation of state.db deploys+coupling_registry (snapshot) + audits (chain, LIVE); two-level trust rooted in the OFFLINE S5 CA (cert chains to the pinned root + CRL revocation, C1 LIVE; reads /var/lib/vsf/s5-ca); algedonic emit (inbox-104 + NATS-106), DEGRADE never halt (C5); deploy_target=0=host pseudo-node'),
    ('vsf-witness-verify',         'scripts/state/witness_verify.py',       NULL,      0,                  '/usr/local/bin/witness_verify.py',              'python3; HOST timer every 15min; A1c — CA-rooted EXTERNAL-vantage verify of the nucleus phi-up witness sidecar (events.witness.jsonl on 101, pulled via pct exec — cryptography is not on 101); the witness key cert must chain to the pinned S5 root + the Ed25519 sig must verify; algedonic emit on forgery/bad-sig/near-expiry, DEGRADE never halt (C5); deploy_target=0=host pseudo-node'),
    ('s5_ca',                      'scripts/state/s5_ca.py',                NULL,      0,                  '/usr/local/bin/s5_ca.py',                       'python3; S5 offline CA tool — issues/revokes Ed25519 certs for state-attest + nucleus-witness, manages /var/lib/vsf/s5-ca/ (s5_root.pub.json, s5_crl.json, certs/); run manually from WSL (offline root key); A1d — expiry reporting via `s5_ca expiring`; deploy_target=0=host pseudo-node');

-- LXC 112 (s1-clima) — 98 systemd units (1 L0 + 2 L1@ + 8 L2@ + 87 L3@), template
-- instances of vsf-clima-l{0,1,2,3}[@id].service. Previously undeclared in seed.sql
-- (only ever inserted live into prod's components table, out of band — see
-- feedback_single_source): state.db had 12/87 L3 nodes declared, so the anti-orphan
-- census under-counted by 75. `name` = systemd unit name (no .service suffix, per
-- the convention already used above), matching `systemctl is-active --quiet <name>`.
INSERT OR REPLACE INTO components (
    name,                          source_dir,                              build_lxc, deploy_target_lxc, deploy_path,                                   notes
) VALUES
    ('vsf-clima-l0',           'projects/s1-clima/src/l0_aggregate.py', NULL, 112, '/opt/vsf-clima/src/l0_aggregate.py', 'S1-clima L0 global aggregator; template-free unit'),
    ('vsf-clima-l1@continental',      'projects/s1-clima/src/l1_system.py',    NULL, 112, '/opt/vsf-clima/src/l1_system.py',    'S1-clima L1 system node; instance of vsf-clima-l1@.service'),
    ('vsf-clima-l1@marino',      'projects/s1-clima/src/l1_system.py',    NULL, 112, '/opt/vsf-clima/src/l1_system.py',    'S1-clima L1 system node; instance of vsf-clima-l1@.service'),
    ('vsf-clima-l2@enso-tropical', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@humboldt', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@mediterranea', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@pacifico-sur-medio', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@semiarida', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@subpolar', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@templada-humeda', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l2@tropical-arida', 'projects/s1-clima/src/l2_zone.py',      NULL, 112, '/opt/vsf-clima/src/l2_zone.py',      'S1-clima L2 zone node; instance of vsf-clima-l2@.service'),
    ('vsf-clima-l3@s1-ancud',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-antofagasta',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-arica',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-calama',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-castro',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-chanaral',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-chile-chico',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-chillan',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-cochrane',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-combarbala',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-concepcion',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-copiapo',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-coquimbo',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-coyhaique',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-curico',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-diego-almagro',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-domingo',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-easter-island',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-0s-100w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-0s-120w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-0s-140w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-10s-110w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-2s-100w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-2s-120w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-5s-100w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-enso-5s-120w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-galapagos',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-huasco',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-18s-72w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-22s-73w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-25s-74w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-28s-73w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-31s-74w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-35s-75w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-38s-74w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-40s-76w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-hum-43s-77w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-illapel',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-iquique',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-juan-fernandez',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-lago-ranco',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-la-serena',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-la-union',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-ligua',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-linares',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-los-angeles',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-los-vilos',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-magallanes',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-maullin',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-nacimiento',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-osorno',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-ovalle',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-padre-las-casas',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-panguipulli',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-petorca',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pichidangui',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-porvenir',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-20s-100w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-25s-90w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-30s-100w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-30s-90w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-35s-105w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-35s-95w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-40s-110w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-40s-95w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-43s-90w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pso-45s-105w',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-pucon',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-puerto-aysen',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-puerto-montt',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-puerto-natales',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-puerto-williams',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-punta-arenas',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-rancagua',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-rio-negro',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-salamanca',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-san-fernando',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-santiago',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-talca',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-taltal',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-temuco',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-tocopilla',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-tortel',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-valdivia',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-vicuna',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-villa-ohiggins',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service'),
    ('vsf-clima-l3@s1-villarrica',   'projects/s1-clima/src/l3_node.py',      NULL, 112, '/opt/vsf-clima/src/l3_node.py',      'S1-clima L3 leaf node; instance of vsf-clima-l3@.service');

-- ─── HARD RULES ─────────────────────────────────────────────────────────
-- The `rules` table was DROPPED 2026-08-12 (TASKS.vsm
-- R7-RULES-TABLE-CLEANUP-2026-08-11): rules are DECLARED, never polled —
-- the only canonical source is system/boot/hard_rules.vsm
-- (PROTOCOL_VERSION 3), annotated by RULES.md. The old INSERT OR REPLACE
-- INTO rules (12 rows, scopes wsl/deploy/session/bbh/canon/access/coupling/
-- llm) is gone with the table. Do NOT re-seed a mirror.

-- ─── specs registry (canonical doc paths) ───────────────────────────────
INSERT OR REPLACE INTO specs (path, title, status, last_updated) VALUES
    ('docs/papers/attractor_convergence/main.tex',                          'Paper 1: attractor convergence',          'review',      '2026-05-30'),
    ('docs/papers/attractor_convergence/annex_B_operational_audit.md',      'Annex B: 86h operational audit',          'draft-v0.2',  '2026-05-30'),
    ('docs/specs/D1_motor_2_sqlite_readonly.md',                            'D.1 Motor 2 SQLite read-only',            'draft-v0.1',  '2026-05-30'),
    ('docs/PLAN.md',                                                        'Consolidated implementation plan',        'living',      '2026-05-30'),
    ('HANDOFF.vsm.md',                                                      'Session-continuity handoff',              'living',      '2026-05-30');
