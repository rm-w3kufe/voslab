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
 * Pure append — the call site keeps its own console.error for stderr
 * visibility. Never throws: an algedonic emission must not break the caller.
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

export type AlertLevel = "info" | "warn" | "error" | "critical";

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
    appendFileSync(join(dir, "alerts.jsonl"), JSON.stringify(record) + "\n", {
      encoding: "utf-8",
    });
  } catch {
    /* algedonic emission must never break the emitting plugin */
  }
}
