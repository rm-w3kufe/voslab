-- nats-broker coupling row — C2.e network-layer access model (A4 enforcement).
-- Documents the pve guest-firewall allow-list put live 2026-06-12 (PF.1).
-- Complements the topic-* rows (logical layer) with the network layer.
--
-- Deploy:
--   scp scripts/state/nats_broker_coupling.sql root@n02:/tmp/
--   ssh root@n02 'sqlite3 /var/lib/vsf-state/state.db < /tmp/nats_broker_coupling.sql'

INSERT OR REPLACE INTO coupling_registry
  (resource, kind, endpoint, protocol, capabilities, access_model, couple_proc,
   governance, status, refreshed_at)
VALUES (
  'nats-broker',
  'broker',
  '10.10.20.20 (LXC 106 s2-broker): 4222 NATS | 8222 NATS monitoring | 8600 bbs-api',
  'NATS core pub/sub (JSON payloads) + bbs-api HTTP',
  'all vsf.{vsf_id}.* topics per nats_topic_schema/spec.vsm (phi-up, phi-down, algedonic, psi, s3star-audit, s4-intelligence)',
  'pve guest firewall /etc/pve/firewall/106.fw (ENFORCED 2026-06-12, policy_in DROP):
   4222 = LXC 101/104/105/107/108/109/112/113 + n02 host (10.10.20.1) per-IP allow-list
   (112 s1-clima φ↑; 113 s1-econ φ↑ added 2026-06-28 EXP-LL-01);
   8222 = host + 107 broker_probe tier2; 8600 = 101/104/host; SSH 22 = LAN mgmt 192.168.0.0/24 only',
  'new consumer: S5 approval -> add IN ACCEPT rule to scripts/state/firewall/106.fw
   (repo = source of truth) -> scp + mv to /etc/pve/firewall/106.fw (applies in seconds)',
  'A4/C2.e: no sibling routes — the broker is the only inter-unit network path
   (verified 2026-06-12: 105->107/108/109 BLOCKED, 105->broker OK).
   True per-container source IPs guaranteed by vsf-nat-vlans.service RETURN rule
   (intra-10.10.0.0/16 NAT exemption — pre-existing bridge-nf MASQUERADE bug fixed
   2026-06-12; before the fix ALL inter-LXC flows arrived as the host LAN IP).
   fw sources versioned: scripts/state/firewall/{106,107,108,109}.fw.
   Residual: 101/104 NIC firewall flag deferred to ~2026-06-18 (EXP-TRUST-01 phase A:
   prod 101 untouched).',
  'active',
  strftime('%Y-%m-%d %H:%M:%S', 'now')
);
