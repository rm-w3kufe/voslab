-- D.4 state.db schema extensions (spec §5d)
-- Idempotent: safe to re-run.
--
-- Deploy:
--   scp scripts/state/migrate_d4.sql root@n02:/tmp/
--   ssh root@n02 'sqlite3 /var/lib/vsf-state/state.db < /tmp/migrate_d4.sql'

-- Tracks the last operator-triggered action against a service
-- (refresh, restart-request, log-view, etc). Used by the dashboard
-- to dim recently-touched nodes.
ALTER TABLE services ADD COLUMN last_action_ts TEXT;

-- Lightweight session tracker for the opsroom UI. No auth in Tier-α
-- (loopback / SSH tunnel only); user_id is whatever the client claims.
-- Cleaned up by populate.sh hook when last_heartbeat > 1h old.
CREATE TABLE IF NOT EXISTS opsroom_sessions (
    session_id     TEXT PRIMARY KEY,
    user_id        TEXT,
    started_at     TEXT NOT NULL,
    last_heartbeat TEXT
);

-- R1: filesystem-sourced metadata, mirrored into state.db so the
-- frontend has a single source of truth.
CREATE TABLE IF NOT EXISTS alert_counts (
    category     TEXT PRIMARY KEY,
    count        INTEGER NOT NULL DEFAULT 0,
    last_ts      TEXT,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoint_stats (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    corpus_size     INTEGER NOT NULL DEFAULT 0,
    valid_count     INTEGER NOT NULL DEFAULT 0,
    last_minted_ts  TEXT,
    refreshed_at    TEXT NOT NULL
);
