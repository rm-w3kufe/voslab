// design: docs/spec_revision/design-sources/vsf-event-logging/vsf_event_logging_design.vsm
/**
 * vsf-event-router — event-driven orchestrator for VSF plugin system.
 *
 * DESIGN: a single plugin per event that classifies and routes to
 * specialized handlers. The router contains NO business logic — it only:
 *   1. Receives the event
 *   2. Classifies which registered handlers apply
 *   3. Executes them in priority order
 *   4. Logs everything via event-log
 *
 * HANDLERS register with: { id, priority, classify(), execute() }
 * The router calls classify() first (cheap check), then execute() if it passes.
 *
 * R10: the router decides with structural evidence; it never guesses.
 * R9: unknown handlers are visible, never silent.
 * R16: policy declares, instrument interprets.
 */
import type { Plugin } from "@opencode-ai/plugin"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { logTrace, logSummary } from "../../shared/event-log"

// ─── Handler types ───────────────────────────────────────────────────────────

export interface Handler {
  /** Unique handler ID */
  id: string
  /** Priority (lower = runs first) */
  priority: number
  /** Events this handler subscribes to */
  events: string[]
  /**
   * Quick classification: should this handler run for this context?
   * Return true if execute() should be called.
   * This is a CHEAP check — no side effects, no MCP calls.
   */
  classify: (context: HandlerContext) => Promise<boolean> | boolean
  /**
   * Execute the handler. Called only if classify() returned true.
   * Returns result + optional detail for logging.
   */
  execute: (context: HandlerContext) => Promise<HandlerResult>
}

export interface HandlerContext {
  /** Event type (session.idle, session.start, etc.) */
  event: string
  /** Session directory */
  directory: string
  /** Repo root */
  repoRoot: string
  /** Event timestamp */
  ts: string
  /** Event ID for correlation */
  eventId: string
  /** Event payload (varies by event type) */
  payload: Record<string, any>
}

export interface HandlerResult {
  /** ok | error | skip */
  result: "ok" | "error" | "skip"
  /** Duration in milliseconds */
  durationMs: number
  /** Optional detail string */
  detail?: string
  /** Optional summary line */
  summary?: string
}

// ─── Handler registry ────────────────────────────────────────────────────────

const handlers: Handler[] = []

/**
 * Register a new handler. Called by handler modules at load time.
 */
export function registerHandler(handler: Handler): void {
  handlers.push(handler)
}

// ─── Import built-in handlers (they self-register) ───────────────────────────

import { learningCycleHandler } from "./handlers/learning-cycle"
import { sessionHygieneHandler } from "./handlers/session-hygiene"
import { stateReconcileHandler } from "./handlers/state-reconcile"
import { sessionInitHandler } from "./handlers/session-init"
import { governanceHandler } from "./handlers/governance"
import { attestationHandler } from "./handlers/attestation"
import { tasksHandler } from "./handlers/tasks"
import { lifecycleHandler } from "./handlers/lifecycle"
import { coreHandler } from "./handlers/core-scripts"
import { cyberfilterHandler } from "./handlers/cyberfilter"
import { servicesHandler } from "./handlers/services"
import { sharedHandler } from "./handlers/shared"
import { gapResolutionHandler } from "./handlers/gap-resolution"
import { hookAnalyticsHandler } from "./handlers/hook-analytics"
import { createScenarioMemoryHandler } from "./scenario-memory"
import { scriptsAutomationHandler } from "./handlers/scripts-automation"
import { socraticHookEngineHandler } from "./socratic-hook-engine"

registerHandler(learningCycleHandler)
registerHandler(sessionHygieneHandler)
registerHandler(stateReconcileHandler)
registerHandler(sessionInitHandler)
registerHandler(governanceHandler)
registerHandler(attestationHandler)
registerHandler(tasksHandler)
registerHandler(lifecycleHandler)
registerHandler(coreHandler)
registerHandler(cyberfilterHandler)
registerHandler(servicesHandler)
registerHandler(sharedHandler)
registerHandler(gapResolutionHandler)
registerHandler(hookAnalyticsHandler)
registerHandler(createScenarioMemoryHandler())
registerHandler(scriptsAutomationHandler)
registerHandler(socraticHookEngineHandler)

// ─── Router ──────────────────────────────────────────────────────────────────

/**
 * Find the repo root by walking up from directory.
 */
function findRepoRoot(directory: string): string | null {
  let p = resolve(directory)
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(p, "TASKS.vsm"))) return p
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

// ─── Unified router for all events ─────────────────────────────────────────

/**
 * Find the repo root by walking up from directory.
 */
function findRepoRoot(directory: string): string | null {
  let p = resolve(directory)
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(p, "TASKS.vsm"))) return p
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

/**
 * Route an event to applicable handlers.
 */
async function routeEvent(
  eventType: string,
  directory: string,
  repoRoot: string,
  payload: any,
): Promise<void> {
  const ts = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
  const eventId = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`

  // Filter handlers for this event
  const applicable = handlers
    .filter(h => h.events.includes(eventType))
    .sort((a, b) => a.priority - b.priority)

  if (applicable.length === 0) return

  // Classify phase: check which handlers want to run
  const context: HandlerContext = {
    event: eventType,
    directory,
    repoRoot,
    ts,
    eventId,
    payload,
  }

  const toRun: Handler[] = []
  for (const handler of applicable) {
    try {
      if (await handler.classify(context)) {
        toRun.push(handler)
      }
    } catch {
      // classify failure = don't run this handler
    }
  }

  if (toRun.length === 0) return

  // Execute phase
  const results: { handler: Handler; result: HandlerResult }[] = []
  for (const handler of toRun) {
    const handlerStart = Date.now()
    try {
      const result = await handler.execute(context)
      results.push({ handler, result })

      // Log trace for each handler
      await logTrace(
        repoRoot, eventId, eventType,
        handler.id, result.result,
        result.durationMs, result.detail,
      )
    } catch (e: any) {
      const errResult: HandlerResult = {
        result: "error",
        durationMs: Date.now() - handlerStart,
        detail: String(e?.message || e).slice(0, 200),
      }
      results.push({ handler, result: errResult })

      await logTrace(
        repoRoot, eventId, eventType,
        handler.id, "error",
        errResult.durationMs, errResult.detail,
      )
    }
  }

  // Summary
  const total = results.length
  const ok = results.filter(r => r.result.result === "ok").length
  const skip = results.filter(r => r.result.result === "skip").length
  const totalDuration = results.reduce((sum, r) => sum + r.result.durationMs, 0)
  const summaryParts = results
    .filter(r => r.result.summary)
    .map(r => r.result.summary!)
    .join(";")

  await logSummary(
    repoRoot, eventId, eventType,
    total, ok, skip, totalDuration,
    summaryParts,
  )
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

const UnifiedRouter: Plugin = async ({ directory }) => {
  const repoRoot = findRepoRoot(directory || process.cwd()) || directory

  return {
    // Session events
    "session.created": async (input: any) => {
      await routeEvent("session.created", directory, repoRoot, input)
    },
    "session.idle": async (input: any) => {
      await routeEvent("session.idle", directory, repoRoot, input)
    },
    "session.start": async (input: any) => {
      await routeEvent("session.start", directory, repoRoot, input)
    },
    // Tool events
    "tool.execute.before": async (input: any) => {
      await routeEvent("tool.execute.before", directory, repoRoot, input)
    },
    "tool.execute.after": async (input: any) => {
      await routeEvent("tool.execute.after", directory, repoRoot, input)
    },
  }
}

export default UnifiedRouter
