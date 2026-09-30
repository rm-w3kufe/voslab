-- kpi_manifests — Formal KPI declarations for Cyberfilter F3.c per-variable SPC.
-- Mirror of scripts/kpi_manifests.json (state.db = authoritative record; JSON = LXC-local copy).
-- Ratified: 2026-06-12 rmw3(S5) — F3.c gate: DSN-COUPLE-01 manifests declare KPIs.
--
-- Deploy:
--   scp scripts/state/kpi_manifests.sql root@n02:/tmp/
--   ssh root@n02 'sqlite3 /var/lib/vsf-state/state.db < /tmp/kpi_manifests.sql'
-- NOTE: canonical state.db = /var/lib/vsf-state/state.db (vsf-q target).
--       2026-06-12: an accidental copy at /var/lib/vsf/state.db was created by the
--       first deploy of this file and deleted the same day (single-source rule).

CREATE TABLE IF NOT EXISTS kpi_manifests (
    component       TEXT NOT NULL,
    variable        TEXT NOT NULL,
    unit            TEXT,
    expected_min    REAL,
    expected_max    REAL,
    ewma_alpha      REAL    NOT NULL DEFAULT 0.2,
    cusum_direction TEXT    NOT NULL DEFAULT 'lower',  -- 'lower' | 'upper'
    cusum_k         REAL    NOT NULL DEFAULT 0.01,     -- CUSUM slack (natural units)
    cusum_h         REAL    NOT NULL DEFAULT 0.05,     -- CUSUM decision threshold
    cooldown_ticks  INTEGER NOT NULL DEFAULT 5,        -- ticks before re-alerting
    source_ref      TEXT,
    ratified_by     TEXT    DEFAULT 'rmw3(S5)',
    ratified_ts     TEXT    DEFAULT '2026-06-12',
    PRIMARY KEY (component, variable)
);

INSERT OR REPLACE INTO kpi_manifests VALUES
  ('vsf-nucleus-operational','stasis_cos','dimensionless',
   0.90,1.0, 0.2,'lower',0.01,0.05, 5,
   'norm.vsm stasis_cos.nominal_min=0.90','rmw3(S5)','2026-06-12'),

  ('vsf-nucleus-operational','trust','dimensionless',
   0.80,1.0, 0.2,'lower',0.01,0.05, 5,
   'norm.vsm trust.warn_below=0.80','rmw3(S5)','2026-06-12'),

  ('vsf-nucleus-operational','viable','bool_as_int',
   1.0,1.0, 0.5,'lower',0.1,0.5, 5,
   'norm.vsm regime.viable_full=true','rmw3(S5)','2026-06-12'),

  ('vsf-s3-star','exception_count','count_per_poll',
   0.0,1.0, 0.2,'upper',0.5,4.0, 5,
   'S3* normal operation: 0-1 exceptions per poll','rmw3(S5)','2026-06-12');
