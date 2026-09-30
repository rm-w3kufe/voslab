-- recon_allowlist — RECON-BIDIRECTIONAL allowlist table
-- Curation belongs in the canon DB where it is queryable and attested.
-- Single-source rule: NEVER hardcode names in the script.

CREATE TABLE IF NOT EXISTS recon_allowlist (
    lxc       INTEGER,
    pattern   TEXT,
    reason    TEXT,
    added_by  TEXT,
    added_ts  TEXT,
    PRIMARY KEY (lxc, pattern));

-- Seed: netdata monitoring on all LXCs + host
-- (netdata parent is declared in components per container; children are expected)
INSERT OR IGNORE INTO recon_allowlist VALUES
(0, 'netdata', 'monitoring — parent declared on host', 'RECON-BIDIRECTIONAL deploy', ''),
(101, 'netdata', 'monitoring — parent declared via component vsf-nucleus-operational', 'RECON-BIDIRECTIONAL deploy', ''),
(104, 'netdata', 'monitoring — parent declared via component vsf-s5-algedonic', 'RECON-BIDIRECTIONAL deploy', ''),
(106, 'netdata', 'monitoring — parent declared via component nats-server', 'RECON-BIDIRECTIONAL deploy', ''),
(107, 'netdata', 'monitoring — parent declared via component vsf-s3-star', 'RECON-BIDIRECTIONAL deploy', ''),
(108, 'netdata', 'monitoring — dev sandbox', 'RECON-BIDIRECTIONAL deploy', ''),
(109, 'netdata', 'monitoring — parent declared via component vsf-view-host', 'RECON-BIDIRECTIONAL deploy', ''),
(112, 'netdata', 'monitoring — climate domain', 'RECON-BIDIRECTIONAL deploy', ''),
(113, 'netdata', 'monitoring — econ domain', 'RECON-BIDIRECTIONAL deploy', ''),
-- ollama model runner (101/110): parent declared in components, children are expected
(101, 'ollama', 'model server + runner — parent declared', 'RECON-BIDIRECTIONAL deploy', ''),
(110, 'ollama', 'model server + runner — parent declared', 'RECON-BIDIRECTIONAL deploy', '');
