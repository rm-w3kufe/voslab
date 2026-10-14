/**
 * console-error-net (Layer B) — safety net under the curated algedonic channel.
 *
 * Layer A (algedonic-alert) routes curated pain/investment/violation signals to
 * state/rsi/alerts.jsonl (session-consumed). But console.error is the default
 * sink for ~33 plugin emissions and dies with the TUI — anything NOT migrated
 * to Layer A left NO persistent trace. This net intercepts console.error at the
 * source (installed once at the event-router bootstrap) and ALSO appends every
 * emission to state/rsi/plugin_stderr.jsonl — a catch-all audit layer, kept
 * separate from the curated channel so alerts.jsonl stays clean of debug/info.
 *
 * Defence in depth (rmw3 2026-10-13: "canal B en otra capa"):
 *   A = curated signal  → alerts.jsonl     → session-created surface + 48h gate
 *   B = everything      → plugin_stderr.jsonl → persistent catch-all (audit)
 * Nothing that reaches console.error dies invisibly again, future signals
 * included — B catches what A has not yet explicitly migrated.
 *
 * Never throws; preserves the original stderr behaviour exactly.
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

let installed = false;

function safeStringify(v: unknown): string {
  try {
    return typeof v === "object" ? JSON.stringify(v) : String(v);
  } catch {
    return "[unstringifiable]";
  }
}

export function installConsoleErrorNet(repoRoot: string): void {
  if (installed) return;
  installed = true;
  const original = console.error.bind(console);
  const dir = join(repoRoot, "state", "rsi");
  const sink = join(dir, "plugin_stderr.jsonl");
  console.error = (...args: unknown[]) => {
    original(...args); // preserve stderr exactly
    try {
      const detail = args.map(safeStringify).join(" ");
      mkdirSync(dir, { recursive: true });
      const record = {
        ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
        source: "console-error-net",
        detail: detail.slice(0, 2000),
      };
      appendFileSync(sink, JSON.stringify(record) + "\n", { encoding: "utf-8" });
    } catch {
      /* the net must never break the original console.error */
    }
  };
}
