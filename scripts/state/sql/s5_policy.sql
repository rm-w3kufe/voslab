-- s5_policy — S5 policy key/value store (canonical config; edit here, no code redeploy). task(D.4-1).
-- Moves the algedonic POST allowlist + severity ceiling out of a Python const into state.db so policy
-- edits don't need a deploy. Idempotent (safe to re-run).
--   sqlite3 /var/lib/vsf-state/state.db < scripts/state/s5_policy.sql
--
-- NB: the original consumer (opsroom/scada_api.py) was DECOMMISSIONED in the SCADA cutover (§7.4, 2026-06-06).
-- This is the canonical policy surface; the live consumer (an algedonic POST validator / the s5-policy sink)
-- reads it when/if re-introduced. Recovered list from the removed scada_api.py.

CREATE TABLE IF NOT EXISTS s5_policy (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR REPLACE INTO s5_policy (key, value) VALUES
  ('algedonic.allowed_categories',
   '["operator_note","operator_concern","operator_escalation","ack_alert","manual_recovery_request","scheduled_maintenance"]'),
  ('algedonic.max_normal_severity', '7.0');
