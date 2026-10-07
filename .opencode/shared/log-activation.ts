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
 * P0/P1 LOG-QUALITY-2026-10-07 (§11.7): session_id (from
 * process.env.VOS_SESSION_ID, set on session.created/tool.execute.before)
 * + duration_ms revived from the (previously ignored) 8th-param outcome
 * bag — both injected here so every plugin emitter gets them at once.
 *
 * One implementation, all plugins (A6). Never throws: logging must never
 * break the instrument it observes.
 */
import { appendFileSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

/** Max bytes for the live log before rotation (RAM-LIFECYCLE Tier0). */
const MAX_LOG_BYTES =
  Number(process.env.VOS_LOG_MAX_BYTES || "") || 5 * 1024 * 1024;

/** UTC stamp matching scripts/state/agent-plugin-log (+00:00, no fraction). */
function utcStamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}` +
    `T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}+00:00`
  );
}

function levelFor(result: string): string {
  if (result === "error") return "error";
  if (result === "warn" || result === "warning") return "warning";
  return "activation";
}

/**
 * Rotate the live log when it exceeds MAX_LOG_BYTES.
 * Same audit guarantee (append-only history preserved as
 * agent_plugin.<epoch>.jsonl.gz); the live path stays small so
 * readers never need the whole history in heap. Best-effort:
 * a rotation race between two opencode processes must never
 * break the caller — on any failure we just append.
 */
function rotateIfNeeded(logFile: string): void {
  let size = -1;
  try {
    size = statSync(logFile).size;
  } catch {
    return; // no file yet — nothing to rotate
  }
  if (size <= MAX_LOG_BYTES) return;
  try {
    const archive = `${logFile}.${Date.now()}.jsonl`;
    renameSync(logFile, archive);
    try {
      writeFileSync(`${archive}.gz`, gzipSync(readFileSync(archive)));
      unlinkSync(archive);
    } catch {
      // gzip is a nicety; the uncompressed archive is still valid audit
    }
  } catch {
    // lost the rotation race (or read-only checkout) — append anyway
  }
}

/** Outcome of a socratic decision (Scenario Memory Phase 1). */
export interface ActivationOutcome {
  success: boolean;
  detail?: string;
  durationMs?: number;
  context?: Record<string, any>;
}

/**
 * Append one activation record (direct fs append, no subprocess).
 * Same JSONL schema as scripts/state/agent-plugin-log used to write
 * (same file, same keys) — readers need no change.
 * Fire-and-forget; never rejects the caller.
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
  // RAM-LIFECYCLE Tier0: direct append, same JSONL schema as
  // scripts/state/agent-plugin-log (same file, same keys). The old
  // path spawned 1 bash + 5 python interpreters PER LINE — the top
  // RAM/CPU churn in long sessions. No subprocess here: bounded
  // memory (one line), disk stays the source of truth.
  try {
    const logFile = join(repoRootDir, "logs", "agent_plugin.jsonl");
    try {
      mkdirSync(join(repoRootDir, "logs"), { recursive: true });
    } catch {
      // read-only checkout: degrade silently (as the bash logger did)
    }
    rotateIfNeeded(logFile);
    const record: Record<string, unknown> = {
      ts: utcStamp(),
      pid: process.pid,
      level: levelFor(result),
      source,
      event_type,
      event_id: `${source}:${event_type}:${Date.now()}`,
      action,
      result,
      detail: detail ?? "",
      context: context ?? {},
      // P0: session attribution (null when session never announced).
      session_id: process.env.VOS_SESSION_ID || null,
    };
    // P1: duration_ms — the outcome bag (8th param) was documented but
    // never read since the procedures-writer removal (2026-09-24).
    if (outcome?.durationMs !== undefined && Number.isFinite(outcome.durationMs)) {
      record.duration_ms = Math.round(outcome.durationMs);
    }
    if (outcome?.success !== undefined) {
      (record.context as Record<string, unknown>) = {
        ...(context ?? {}),
        outcome_success: outcome.success,
      };
      if (outcome.detail) {
        (record.context as Record<string, unknown>).outcome_detail =
          String(outcome.detail).slice(0, 300);
      }
    }
    appendFileSync(logFile, JSON.stringify(record) + "\n", { encoding: "utf-8" });
  } catch (e: any) {
    console.error(`[log-activation] fast append failed: ${e?.message || e}`);
    // logging must never break the instrument it observes
  }
  // NOTE (2026-09-24, updated 2026-10-07): the TS procedures/* writer lived
  // here but NEVER fired (procedures landed in Python scenario_memory) and
  // was removed to avoid dual-write redundancy — see ledger §7. The outcome
  // bag ITSELF was revived by P0/P1 log-quality: duration_ms/success now
  // flow into the record above (tool-integration passes them). Python
  // scenario_memory remains the canonical procedural store (510 records);
  // CC-4 readers delegate to scripts/vsl/tools/match_procedure.py.
}
