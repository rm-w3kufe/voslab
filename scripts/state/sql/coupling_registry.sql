-- coupling_registry — Structural Coupling Registry (Stage 0)
-- Catalog of shared-resource coupling contracts in state.db (single source of truth).
-- Realizes the coupling-policy principle (memory: coupling-policy-in-statedb) and
-- seeds the series in task #9. Generalizes connection_schema.json (phi-channels) to
-- shared resources. Idempotent: safe to re-run.
--
-- Deploy:
--   scp scripts/state/coupling_registry.sql root@n02:/tmp/
--   ssh root@n02 'sqlite3 /var/lib/vsf-state/state.db < /tmp/coupling_registry.sql'
--
-- A consumer that wants to couple to a resource reads its row to learn endpoint +
-- protocol + capabilities, and follows couple_proc to obtain permission (A4 / A5 / D6).

CREATE TABLE IF NOT EXISTS coupling_registry (
    resource      TEXT PRIMARY KEY,        -- stable id, e.g. 'ollama-llm'
    kind          TEXT NOT NULL,           -- shared_resource | phi_channel | service | broker
    endpoint      TEXT,                    -- connection target(s)
    protocol      TEXT,                    -- wire protocol / API surface
    capabilities  TEXT,                    -- what it offers (models, topics, methods...)
    access_model  TEXT,                    -- enforcement summary (who may connect)
    couple_proc   TEXT,                    -- how to obtain coupling + permission
    governance    TEXT,                    -- A4/A5/D6 constraints + enforcement location
    status        TEXT NOT NULL DEFAULT 'active',  -- active | planned | deprecated
    refreshed_at  TEXT NOT NULL
);

-- Stage 0 seed: the one real shared resource today (Ollama LLM on LXC 101).
INSERT OR REPLACE INTO coupling_registry
  (resource, kind, endpoint, protocol, capabilities, access_model, couple_proc, governance, status, refreshed_at)
VALUES (
  'ollama-llm',
  'shared_resource',
  '127.0.0.1:11434 (same-LXC loopback) | 10.10.20.10:11434 (VLAN20, firewall-gated)',
  'Ollama HTTP API (OpenAI-compatible: /api/chat, /api/generate, /api/embeddings)',
  'model:qwen2.5-coder:7b',
  'nftables table inet vsf_llm: default-deny tcp dport 11434; allow iif "lo" + ip saddr 10.10.20.10 (self) + @llm_allow set (empty)',
  'request -> S3 approve -> `nft add element inet vsf_llm llm_allow { <consumer_ip> }` -> persist /etc/nftables.d/vsf-llm.nft -> refresh this row',
  'A4 (couple via contract, not direct); A5 (S3 ratifies); D6 (consumer must be L>=2). Enforcement: /etc/nftables.d/vsf-llm.nft on LXC 101.',
  'active',
  strftime('%Y-%m-%dT%H:%M:%SZ','now')
);

-- view-module #1: the Cybernetic RAG visualizer (phi-up projection channel; replaces SCADA). LIVE.
-- v0.2.2: the canonical phi-up is the events.jsonl FILE (Merkle-chained), NOT NATS (NATS = algedonic only).
INSERT OR REPLACE INTO coupling_registry
  (resource, kind, endpoint, protocol, capabilities, access_model, couple_proc, governance, status, refreshed_at)
VALUES (
  'view-cybernetic-rag',
  'phi_channel',
  'phi-up SOURCE: /var/lib/vsf/vsf_nucleus/events.jsonl (nucleus s3s4-nucleus/101) bind-mounted RO into s5-opsroom/109 at /mnt/telemetry; rendered to browser via SSE http://10.10.20.109:8088/view/cybernetic-rag (tunnel :8088)',
  'view-module/0.2.2: connection_schema events.jsonl (file, Merkle-chained) -> state_verify chain-linkage check (G-V3) -> projected view over SSE. Ed25519 source-signing = PROD-A1b. NATS Core = algedonic carrier only.',
  'read-only phi-up projection of the Cybernetic RAG loop (global viability, Omega gate, Lyapunov, nodes/edges); model-agnostic',
  'read-only consumer (the view-host reads events.jsonl RO + verifies the chain; browser gets the projected view via SSE); no phi-down',
  'mount the source events.jsonl RO; verify Merkle chain-linkage before rendering (certified flag); G-V1..G-V4 gate integration',
  'A5/D6: phi-down deferred + human-gated, the panel never emits directives. R9: validated vs connection_schema/0.2.2. Host: opsroom/view_host on 109 (replaces SCADA). Manifest: opsroom/modules/cybernetic-rag.module.json.',
  'active',
  strftime('%Y-%m-%dT%H:%M:%SZ','now')
);

-- view-module #2: the system-topology visualizer (declared self-model + recent algedonic activity).
-- Proves the modular host (N modules). Reads state.db RO + events.jsonl; what SCADA covered.
INSERT OR REPLACE INTO coupling_registry
  (resource, kind, endpoint, protocol, capabilities, access_model, couple_proc, governance, status, refreshed_at)
VALUES (
  'view-system-topology',
  'phi_channel',
  'reads state.db RO (/mnt/state, bind-mount of host /var/lib/vsf-state, mode=ro&immutable=1) + events.jsonl (/mnt/telemetry); rendered via SSE http://10.10.20.109:8088/view/system-topology (tunnel :8088)',
  'system-topology-view/0.1: state.db (lxcs/components/coupling_registry, declared model, RO) + events.jsonl Merkle-chain (algedonic/drift activity)',
  'read-only view of the declared self-model (Sn-function topology, services, couplings) + recent algedonic activity',
  'read-only consumer (the view-host reads state.db + events.jsonl RO; browser gets the projected view via SSE); no phi-down',
  'mount state.db RO + events.jsonl RO; chain-verify the activity window; G-V1..G-V4 gate integration',
  'A5/D6: read-only, no directives. R9: state.db = canonical model (live attestation = PROD-A1a). Host: opsroom/view_host on 109. Manifest: opsroom/modules/system-topology.module.json.',
  'active',
  strftime('%Y-%m-%dT%H:%M:%SZ','now')
);
