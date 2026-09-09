/**
 * design: docs/spec_revision/system/s5-policy/agent-policy/agent-instruments-v1/agent_instruments.vsm
 * log-activation — shared activation logger for VSF opencode plugins (A6).
 *
 * AGENT-CYCLE-OBSERVABILITY-2026-08-17 (directiva S5 rmw3: "observa y
 * mejora"): every hook/plugin activation appends a deterministic JSONL
 * record (scripts/state/agent-plugin-log) — timestamp ISO 8601 UTC,
 * instrument, hook, action, result. Without an activation log there is no
 * observability of the agent layer (lesson AGENT-PLUGIN-CYCLE-REPAIR: the
 * learning-cycle-scan was dead and NOTHING logged it).
 *
 * SCENARIO-MEMORY-FASE-1 (2026-08-27): optional outcome field for
 * procedural memory. When present, records the outcome of a decision
 * (success, duration, context) for future pattern matching.
 *
 * FORMAT-OVERRIDE-2026-09-09: standardized to new format:
 *   {ts, pid, level, source, event_type, event_id, action, result, detail, context}
 *
 * One implementation, all plugins (A6). Never throws: logging must never
 * break the instrument it observes.
 */
import { exec } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

const execP = promisify(exec);

/** Outcome of a socratic decision (Scenario Memory Phase 1). */
export interface ActivationOutcome {
  success: boolean;
  detail?: string;
  durationMs?: number;
  context?: Record<string, any>;
}

/**
 * Append one activation record via the deterministic logger script.
 * Resolves the logger from the repo root derived from a known repo file
 * (the caller passes repoRootDir, e.g. derived from the found scan path or
 * from findScript on .opencode/plugins/). Fire-and-forget; never rejects
 * the caller.
 *
 * NEW FORMAT (2026-09-09):
 *   {ts, pid, level, source, event_type, event_id, action, result, detail, context}
 */
export async function logActivation(
  repoRootDir: string,
  source: string,
  event_type: string,
  action: string,
  result: string,
  detail?: string,
  context?: Record<string, any>,
  outcome?: ActivationOutcome,
): Promise<void> {
  const logger = join(repoRootDir, "scripts/state/agent-plugin-log");
  if (!existsSync(logger)) {
    console.error(`[log-activation] Logger not found at ${logger} (repoRootDir=${repoRootDir})`);
    return;
  }

  // Build event_id from source and timestamp
  const event_id = `${source}:${event_type}:${Date.now()}`;

  // Build context JSON string
  const contextStr = context ? JSON.stringify(context) : "{}";

  // Pass the opencode process PID to the logger so two opencode processes
  // (user session + child) writing to the same log are distinguishable
  // (CLASSIFY-READ-TOOL-NOISE lesson, 2026-08-19). process.pid is the
  // opencode process; the logger falls back to $$ when the var is absent.
  const args = [logger, source, event_type, event_id, action, result, detail ?? "", contextStr]
    .map((a) => `"${String(a).replace(/"/g, '\\"')}"`)
    .join(" ");
  try {
    await execP(`AGENT_PLUGIN_PID=${process.pid} bash ${args}`, { timeout: 3_000 });
  } catch (e: any) {
    console.error(`[log-activation] execP failed: ${e?.message || e}`);
    // logging must never break the instrument it observes
  }
  // Scenario Memory: write outcome to procedures/ if present
  if (outcome) {
    await logOutcome(repoRootDir, source, event_type, action, outcome);
  }
}

/**
 * Write outcome record to learning_records/procedures/ for Scenario Memory.
 * Creates the directory if it doesn't exist. Fire-and-forget.
 */
async function logOutcome(
  repoRootDir: string,
  source: string,
  event_type: string,
  action: string,
  outcome: ActivationOutcome,
): Promise<void> {
  const proceduresDir = join(repoRootDir, "docs/spec_revision/learning_records/procedures");
  try {
    const { mkdirSync, writeFileSync } = await import("node:fs");
    mkdirSync(proceduresDir, { recursive: true });
    // Generate procedure filename: YYYYMMDD_HHMMSS_source.json
    const now = new Date();
    const ts = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "");
    const safeSource = source.replace(/[^a-zA-Z0-9_-]/g, "_");
    const filename = `${ts}_${safeSource}.json`;
    const record = {
      id: filename.replace(".json", ""),
      type: "procedure",
      version: "1.0",
      source: { instrument: source, hook: event_type },
      action,
      decision: { result },
      outcome: {
        success: outcome.success,
        detail: outcome.detail,
        durationMs: outcome.durationMs,
      },
      context: outcome.context,
      metadata: {
        timestamp: now.toISOString(),
        pid: process.pid,
      },
    };
    writeFileSync(join(proceduresDir, filename), JSON.stringify(record, null, 2));
  } catch {
    // logging must never break the instrument it observes
  }
}
