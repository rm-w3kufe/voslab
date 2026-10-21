/**
 * algedonic-alert (Layer A) — append a curated pain/pleasure signal to the
 * algedonic channel (state/rsi/alerts.jsonl).
 *
 * The channel's only consumer is `_alert_consume_stage` in
 * tool_integration_bridge.py, wired to session.created: it summarises unacked
 * alerts into the unified log and acks anything >24h (gate
 * `algedonic-queue-consumed` fails if unacked rots >48h). So a signal written
 * here is surfaced at the NEXT session start, not mid-cycle — but it is
 * persistent (survives the TUI) and cannot be lost, unlike console.error,
 * which dies with the TUI. (ALGEDONIC-S4-SIGNAL-ROUTING 2026-10-13,
 * second-order-loop F0.)
 *
 * This is the CURATED channel: only real pain/investment/violation signals
 * belong here. Debug/info noise stays as plain console.error (caught instead
 * by Layer B, the console-error net → state/rsi/plugin_stderr.jsonl).
 *
 * DEDUP-ATTENUATOR (T3-F2, structural-tensions plan 2026-10-20): the same
 * (alert_type, source, detail) repeating inside 24h does NOT append a new
 * row — the FIRST row carries the signal and `state/rsi/alerts_dedup.json`
 * carries the counter `{alert_id, count, first_ts, last_ts}` (atomic:
 * unique-tmp + rename). R9 (jamás drop): the signal row stays in
 * alerts.jsonl and the counter preserves magnitude (the 81-row E2BIG burst
 * becomes 1 row + count:81, so the untriaged backlog counts CLASES, not
 * spam — success criterion ≤30 vs 220). Fail-open by construction: any
 * sidecar read/write error falls through to a raw append, so attenuation is
 * an optimization and never a loss path. Window >24h → fresh row + fresh
 * counter (history lives in alerts.jsonl). Pure append + sidecar rewrite —
 * the call site keeps its own console.error for stderr visibility. Never
 * throws: an algedonic emission must not break the caller.
 *
 * Deterministic (R10): wall-clock cutoff only, same semantics as the
 * consumer's ">24h ack" rule. Consumers (alert_consume / alert_triage)
 * keep their row semantics unchanged — they see ≤1 row per class per window.
 */
import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export type AlertLevel = "info" | "warn" | "error" | "critical";

const DEDUP_WINDOW_MS = 24 * 60 * 60 * 1000;

type DedupEntry = {
  alert_id: string;
  count: number;
  first_ts: string;
  last_ts: string;
};

/** Load the counter sidecar. Missing/corrupt → {} (fail-open, never throws). */
function loadDedup(path: string): Record<string, DedupEntry> {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, DedupEntry>;
    }
  } catch { /* unusable sidecar → start fresh; the next append rewrites it */ }
  return {};
}

/** Atomic sidecar write: unique-pid tmp + rename (T6-F1 writer contract). */
function saveDedupAtomic(path: string, dedup: Record<string, DedupEntry>): void {
  const tmp = `${path}.tmp.${process.pid}`;
  writeFileSync(tmp, JSON.stringify(dedup, null, 1), "utf-8");
  renameSync(tmp, path);
}

export function algedonicAlert(
  repoRootDir: string,
  alertType: string,
  source: string,
  level: AlertLevel,
  detail: string,
): void {
  try {
    const dir = join(repoRootDir, "state", "rsi");
    mkdirSync(dir, { recursive: true });
    const record = {
      // unique id: epoch_ms + short random suffix (matches existing alerts;
      // an id, not a predicate — R10 does not apply).
      alert_id: `alert-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
      ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      level,
      alert_type: alertType,
      source,
      detail,
    };
    const dedupPath = join(dir, "alerts_dedup.json");
    // key = exact triple (JSON.stringify → unambiguous, no separator guessing)
    const key = JSON.stringify([alertType, source, detail]);
    const dedup = loadDedup(dedupPath);
    const prev = dedup[key];
    const prevTs = prev ? Date.parse(prev.last_ts) : NaN;
    const nowMs = Date.parse(record.ts);
    if (Number.isFinite(prevTs) && nowMs - prevTs < DEDUP_WINDOW_MS) {
      try {
        const prevCount = Number(prev.count);
        dedup[key] = {
          alert_id: typeof prev.alert_id === "string" ? prev.alert_id : record.alert_id,
          count: (Number.isFinite(prevCount) && prevCount >= 1 ? prevCount : 1) + 1,
          first_ts: Number.isFinite(Date.parse(prev.first_ts)) ? prev.first_ts : record.ts,
          last_ts: record.ts,
        };
        saveDedupAtomic(dedupPath, dedup);
        return; // attenuated: 1 fila + contador, jamás drop (R9)
      } catch {
        // fail-open: counter update failed → append the row anyway
      }
    }
    // first occurrence in the window (or unusable sidecar) → raw append
    appendFileSync(join(dir, "alerts.jsonl"), JSON.stringify(record) + "\n", {
      encoding: "utf-8",
    });
    try {
      dedup[key] = {
        alert_id: record.alert_id,
        count: 1,
        first_ts: record.ts,
        last_ts: record.ts,
      };
      // bounded sidecar: keep only entries from the active 24h window
      for (const [k, v] of Object.entries(dedup)) {
        const t = v ? Date.parse(v.last_ts) : NaN;
        if (!Number.isFinite(t) || nowMs - t >= DEDUP_WINDOW_MS) delete dedup[k];
      }
      saveDedupAtomic(dedupPath, dedup);
    } catch {
      /* row already appended — the sidecar is best-effort (R9: never lose) */
    }
  } catch {
    /* algedonic emission must never break the emitting plugin */
  }
}
