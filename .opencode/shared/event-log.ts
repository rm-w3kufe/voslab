/**
 * event-log.ts — Centralized event logging for vOS plugins.
 *
 * UNIFIED LOG FORMAT v2.0 (2026-09-08):
 * All logging writes to logs/agent_plugin.jsonl in a unified JSONL schema
 * compatible with n02's VSF kernel for interoperability and visualization.
 *
 * Schema v2.0 (with traceability):
 * {
 *   "ts": "ISO8601 UTC",
 *   "pid": number,
 *   "level": "trace" | "summary" | "activation" | "decision",
 *   "source": "instrument or component name",
 *   "event_type": "hook or event category",
 *   "event_id": "unique event identifier",
 *
 *   // TRAZABILIDAD: Contexto del trigger
 *   "trigger": {
 *     "event": "session.idle|tool.execute|user_command",
 *     "source": "qué componente disparó esto",
 *     "timestamp": "cuándo se disparó"
 *   },
 *
 *   // RAZONAMIENTO: Por qué se hizo
 *   "reasoning": {
 *     "why": "razón de la acción",
 *     "prerequisites": ["condición1", "condición2"],
 *     "alternatives": ["opción1", "opción2"],
 *     "chosen": "opción elegida y por qué"
 *   },
 *
 *   // ACCIÓN: Qué se hizo
 *   "action": "descripción de la acción",
 *   "result": "ok|error|skip|warn",
 *   "detail": "detalles del resultado",
 *
 *   // IMPACTO: Qué afecta
 *   "impact": {
 *     "scope": "qué componentes afecta",
 *     "reversible": true|false,
 *     "side_effects": ["efecto1", "efecto2"]
 *   },
 *
 *   // MÉTRICAS: Cuantificación
 *   "metrics": {
 *     "duration_ms": number,
 *     "items_processed": number,
 *     "success_rate": number
 *   },
 *
 *   "context": { optional structured context }
 * }
 *
 * Fire-and-forget: logging must never break the instrument it observes.
 */
import { exec } from "node:child_process";
import { promisify } from "node:util";
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

const execP = promisify(exec);

/** Trigger context - what initiated this action. */
export interface LogTrigger {
  event: string;           // session.idle, tool.execute, user_command
  source: string;          // qué componente disparó esto
  timestamp?: string;      // cuándo se disparó
}

/** Reasoning context - why this action was taken. */
export interface LogReasoning {
  why: string;             // razón de la acción
  prerequisites?: string[]; // condiciones que se evaluaron
  alternatives?: string[]; // opciones que había
  chosen?: string;         // opción elegida y por qué
}

/** Impact context - what this action affects. */
export interface LogImpact {
  scope?: string;          // qué componentes afecta
  reversible?: boolean;    // si se puede deshacer
  side_effects?: string[]; // efectos secundarios
}

/** Metrics context - quantification of the action. */
export interface LogMetrics {
  duration_ms?: number;
  items_processed?: number;
  success_rate?: number;
  [key: string]: number | undefined;
}

/** Unified log record shape (schema v2.0). */
export interface LogRecord {
  ts: string;
  pid: number | null;
  level: "trace" | "summary" | "activation" | "decision";
  source: string;
  event_type: string;
  event_id: string;

  // Traceability
  trigger?: LogTrigger;
  reasoning?: LogReasoning;

  // Action
  action: string;
  result: string;
  detail?: string;

  // Impact
  impact?: LogImpact;

  // Metrics
  metrics?: LogMetrics;

  // Legacy context
  context?: Record<string, any>;
}

/**
 * Resolve the log file path, creating directory if needed.
 */
function getLogPath(repoRootDir: string): string {
  const logDir = join(repoRootDir, "logs");
  if (!existsSync(logDir)) {
    mkdirSync(logDir, { recursive: true });
  }
  return join(logDir, "agent_plugin.jsonl");
}

/**
 * Append a record to the unified JSONL log.
 * Synchronous write (fire-and-forget pattern).
 */
function appendLog(repoRootDir: string, record: LogRecord): void {
  try {
    const logPath = getLogPath(repoRootDir);
    appendFileSync(logPath, JSON.stringify(record) + "\n");
  } catch {
    // Never throw
  }
}

/**
 * Log a trace event (detailed, for debugging).
 * Matches event-router call signature:
 *   logTrace(repoRoot, eventId, eventType, handlerId, result, durationMs, detail)
 */
export async function logTrace(
  repoRootDir: string,
  eventId: string,
  eventType: string,
  handlerId: string,
  result: string,
  durationMs?: number,
  detail?: string,
): Promise<void> {
  const record: LogRecord = {
    ts: new Date().toISOString(),
    pid: process.pid,
    level: "trace",
    source: handlerId,
    event_type: eventType,
    event_id: eventId,
    action: `${eventType}:${handlerId}`,
    result,
    duration_ms: durationMs ?? undefined,
    detail,
    trigger: {
      event: eventType,
      source: "event-router",
    },
    metrics: durationMs ? { duration_ms: durationMs } : undefined,
  };
  appendLog(repoRootDir, record);
}

/**
 * Log a summary event (important, for review).
 * Matches event-router call signature:
 *   logSummary(repoRoot, eventId, eventType, total, ok, skip, totalDuration, summaryParts)
 */
export async function logSummary(
  repoRootDir: string,
  eventId: string,
  eventType: string,
  total: number,
  ok: number,
  skip: number,
  totalDuration: number,
  summary?: string,
): Promise<void> {
  const record: LogRecord = {
    ts: new Date().toISOString(),
    pid: process.pid,
    level: "summary",
    source: "event-router",
    event_type: eventType,
    event_id: eventId,
    action: `summary:${eventType}`,
    result: ok === total ? "ok" : skip === total ? "skip" : "partial",
    detail: summary,
    trigger: {
      event: eventType,
      source: "event-router",
    },
    reasoning: {
      why: `Resumen de ${total} handlers ejecutados`,
    },
    metrics: {
      duration_ms: totalDuration,
      items_processed: total,
      success_rate: total > 0 ? ok / total : 0,
    },
  };
  appendLog(repoRootDir, record);
}

/**
 * Log a plugin activation (for handlers that use this directly).
 * Enhanced with reasoning and impact context.
 */
export async function logActivation(
  repoRootDir: string,
  instrument: string,
  hook: string,
  action: string,
  result: string,
  detail?: string,
  options?: {
    durationMs?: number;
    reasoning?: LogReasoning;
    impact?: LogImpact;
    trigger?: LogTrigger;
    metrics?: LogMetrics;
  },
): Promise<void> {
  const record: LogRecord = {
    ts: new Date().toISOString(),
    pid: process.pid,
    level: "activation",
    source: instrument,
    event_type: hook,
    event_id: `${hook}:${instrument}:${Date.now()}`,
    action,
    result,
    detail,
    trigger: options?.trigger ?? {
      event: hook,
      source: instrument,
    },
    reasoning: options?.reasoning,
    impact: options?.impact,
    metrics: options?.durationMs
      ? { duration_ms: options.durationMs, ...options?.metrics }
      : options?.metrics,
  };
  appendLog(repoRootDir, record);
}

/**
 * Log a socratic decision (for bridge components).
 * Includes reasoning about tree evaluation.
 */
export async function logDecision(
  repoRootDir: string,
  source: string,
  tree: string,
  truth: string,
  certified: boolean,
  detail?: string,
  context?: Record<string, any>,
): Promise<void> {
  const record: LogRecord = {
    ts: new Date().toISOString(),
    pid: process.pid,
    level: "decision",
    source,
    event_type: "socratic.evaluate",
    event_id: `decision:${source}:${Date.now()}`,
    action: `eval tree: ${tree}`,
    result: truth,
    detail,
    trigger: {
      event: "socratic.evaluate",
      source,
    },
    reasoning: {
      why: `Evaluar árbol socrático: ${tree}`,
      prerequisites: ["árbol válido", "contexto proporcionado"],
      chosen: `Truth=${truth}, Certified=${certified}`,
    },
    impact: {
      scope: "decisión socrática",
      reversible: true,
    },
    context: { tree, certified, ...context },
  };
  appendLog(repoRootDir, record);
}

/**
 * Log a gate evaluation (for gate suite).
 * Includes reasoning about why the gate was checked.
 */
export async function logGateEval(
  repoRootDir: string,
  gateName: string,
  result: string,
  passed: boolean,
  detail?: string,
  durationMs?: number,
  options?: {
    reasoning?: LogReasoning;
    impact?: LogImpact;
  },
): Promise<void> {
  const record: LogRecord = {
    ts: new Date().toISOString(),
    pid: process.pid,
    level: "activation",
    source: gateName,
    event_type: "gate.evaluate",
    event_id: `gate:${gateName}:${Date.now()}`,
    action: `gate: ${gateName}`,
    result: passed ? "ok" : "error",
    detail,
    trigger: {
      event: "gate.evaluate",
      source: "gate-suite",
    },
    reasoning: options?.reasoning ?? {
      why: `Evaluar gate: ${gateName}`,
      prerequisites: ["negative control test"],
      chosen: passed ? "PASS - gate rechaza su caso negativo" : "FAIL - gate no rechaza su caso negativo",
    },
    impact: {
      scope: "integridad del sistema",
      reversible: false,
      side_effects: passed ? [] : ["gate deshabilitado"],
    },
    metrics: durationMs ? { duration_ms: durationMs } : undefined,
  };
  appendLog(repoRootDir, record);
}

export default { logTrace, logSummary, logActivation, logDecision, logGateEval };
