-- vsf-state.db — canonical lightweight state for the VSF project.
--
-- Lives on n02 at /var/lib/vsf-state/state.db (NOT in any LXC — needs to
-- query across LXCs via `pct exec` which only the host can do). Read by
-- the agent via `ssh root@n02 sqlite3 ... "SELECT ..."`.
--
-- Design principle: every fact the agent might be tempted to guess
-- about "where is X, what is running, who builds what" lives in here.
-- Update by running populate.sh on the host.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ─── HARD RULES ──────────────────────────────────────────────────────────
-- NOTE: the `rules` table was REMOVED 2026-08-12 (TASKS.vsm
-- R7-RULES-TABLE-CLEANUP-2026-08-11). Rules are DECLARED, never polled:
-- the only canonical source is docs/spec_revision/system/boot/hard_rules.vsm
-- (PROTOCOL_VERSION 3), annotated by RULES.md. state.db observes n02's
-- deterministic world; rules live in the agent's non-deterministic world.
-- Do NOT recreate this table — a mirror went stale once already (R7,
-- resolved 2026-08-11).

-- ─── TOPOLOGY ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lxcs (
    id        INTEGER PRIMARY KEY,     -- 101, 104, 106, 107
    role      TEXT    NOT NULL,        -- 'nucleus', 's5-layer', 'broker', 'auditor'
    ip        TEXT,
    notes     TEXT
);

-- ─── COMPONENTS (build + deploy mapping) ─────────────────────────────────
-- `name` is the systemd unit name on the target LXC (e.g. 'vsf-s3-star',
-- 'vsf-nucleus-operational') so populate.sh can address it directly.
-- `source_dir` is NULL for third-party services we don't build (nats, ollama).
CREATE TABLE IF NOT EXISTS components (
    name              TEXT    PRIMARY KEY,
    source_dir        TEXT,                -- NULL if not ours; else relative to repo root
    build_lxc         INTEGER,             -- where to cargo build (NULL = no build)
    deploy_target_lxc INTEGER REFERENCES lxcs(id),
    deploy_path       TEXT,                -- absolute path on target
    notes             TEXT
);

-- ─── SERVICES (live snapshot — refreshed by populator) ───────────────────
CREATE TABLE IF NOT EXISTS services (
    lxc            INTEGER NOT NULL REFERENCES lxcs(id),
    name           TEXT    NOT NULL,
    pid            INTEGER,
    active         INTEGER NOT NULL DEFAULT 0,    -- 0/1
    exec_path      TEXT,
    binary_sha     TEXT,
    active_since   TEXT,
    refreshed_at   TEXT    NOT NULL,
    PRIMARY KEY (lxc, name)
);

-- ─── CHAIN STATE (Merkle ledgers) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chain_state (
    chain_id      TEXT    PRIMARY KEY,    -- 'nucleus' | 's3_star'
    lxc           INTEGER NOT NULL REFERENCES lxcs(id),
    file_path     TEXT    NOT NULL,
    line_count    INTEGER,
    head_hash     TEXT,
    last_event_ts TEXT,
    refreshed_at  TEXT    NOT NULL
);

-- ─── TASKS (mirror of agent TaskList) ────────────────────────────────────
-- Populator does NOT update this — the agent updates it explicitly when it
-- closes a task. Avoids fighting with TaskList ownership.
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY,
    subject      TEXT    NOT NULL,
    status       TEXT    NOT NULL,        -- pending/in_progress/completed/blocked
    blocks_bbh   INTEGER NOT NULL DEFAULT 0,
    description  TEXT,
    updated_ts   TEXT
);

-- ─── SPECS (doc paths with status) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS specs (
    path           TEXT    PRIMARY KEY,    -- relative to repo root
    title          TEXT,
    status         TEXT    NOT NULL,       -- draft/review/locked/implemented
    last_updated   TEXT
);

-- ─── DEPLOY LOG (append-only) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS storage_probe_state (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lv_name       TEXT NOT NULL,
    data_percent  REAL NOT NULL,
    pool_lv       TEXT,
    refreshed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deploys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    component   TEXT    NOT NULL,
    target_lxc  INTEGER NOT NULL REFERENCES lxcs(id),
    from_sha    TEXT,
    to_sha      TEXT    NOT NULL,
    result      TEXT    NOT NULL           -- 'ok' / 'fail' / 'rollback'
);

-- ─── VIEWS for the most common queries ───────────────────────────────────
CREATE VIEW IF NOT EXISTS v_services_summary AS
    SELECT l.id AS lxc, l.role, s.name, s.active, s.pid, s.binary_sha,
           s.refreshed_at
    FROM services s JOIN lxcs l ON s.lxc = l.id
    ORDER BY l.id, s.name;

CREATE VIEW IF NOT EXISTS v_open_blockers AS
    SELECT id, subject, status FROM tasks
    WHERE blocks_bbh = 1 AND status IN ('pending', 'in_progress', 'blocked')
    ORDER BY id;
