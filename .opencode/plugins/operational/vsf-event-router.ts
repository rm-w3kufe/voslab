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
import { existsSync, readFileSync, statSync } from "node:fs"
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
 * NOT exported: opencode's plugin loader treats every function export as a
 * Plugin entry (`Object.values(mod)` → each must return Hooks). Exporting
 * this void function made the loader call it as a Plugin, push `undefined`
 * into the hooks list → `N.config` crash + `n.provider` TypeError in
 * Provider.list → "Unexpected server error" on session resume (2026-09-23).
 * Internal use only — handlers self-register via the imports below.
 */
function registerHandler(handler: Handler): void {
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
import { instrumentLoaderHandler } from "./handlers/instrument-loader"

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
registerHandler(instrumentLoaderHandler)

// socratic-hook-engine RETIRED 2026-09-24 (D-1): duplicate hooks +
// invalid Plugin shape; removed from opencode.json plugin[]. File kept
// for reference only.

// ─── PLC-001 thin slice: runtime handler states ────────────────────────────
// Sidecar handler_states.json (enabled/version/depends_on per handler id).
// mtime-cached: one stat per dispatch, re-parse only on change. Missing
// file or entry = enabled/unpinned/no-deps (fail-open catalogue, the
// router never bricks the session for a metadata problem). Disabling a
// handler takes effect WITHOUT restart (next dispatched event skips it).
// Top-level plugin files still need opencode.json + restart (documented
// boundary: this gate covers router handlers, not plugin loading).

interface HandlerState {
  enabled: boolean
  version: string
  depends_on: string[]
}

let handlerStatesCache: { mtimeMs: number; states: Record<string, HandlerState> } | null = null

function loadHandlerStates(repoRoot: string): Record<string, HandlerState> {
  try {
    const p = join(repoRoot, ".opencode", "plugins", "operational", "handler_states.json")
    const st = statSync(p)
    if (handlerStatesCache && handlerStatesCache.mtimeMs === st.mtimeMs) {
      return handlerStatesCache.states
    }
    const raw = JSON.parse(readFileSync(p, "utf-8"))
    const states: Record<string, HandlerState> = {}
    const map = (raw && typeof raw === "object" && (raw as any).handlers) || {}
    for (const id of Object.keys(map)) {
      const e: any = map[id] || {}
      states[id] = {
        enabled: e.enabled !== false,
        version: typeof e.version === "string" ? e.version : "unpinned",
        depends_on: Array.isArray(e.depends_on) ? e.depends_on.map(String) : [],
      }
    }
    handlerStatesCache = { mtimeMs: st.mtimeMs, states }
    return states
  } catch {
    return {}
  }
}

function stateOf(states: Record<string, HandlerState>, id: string): HandlerState {
  return states[id] || { enabled: true, version: "unpinned", depends_on: [] }
}

/** Verify declared deps are registered (warn-only; never bricks). */
let depsVerifiedFor: string | null = null

function verifyDeps(repoRoot: string, registered: string[]): void {
  if (depsVerifiedFor === repoRoot) return
  depsVerifiedFor = repoRoot
  const states = loadHandlerStates(repoRoot)
  const known = new Set(registered)
  for (const id of Object.keys(states)) {
    for (const dep of states[id].depends_on) {
      if (!known.has(dep)) {
        console.error(`[event-router] handler ${id} depends on unknown ${dep} — running anyway`)
      }
    }
  }
  // Cycle detection (iterative DFS over declared deps).
  const WHITE = 0, GRAY = 1, BLACK = 2
  const color: Record<string, number> = {}
  const visit = (id: string, stack: string[]): boolean => {
    color[id] = GRAY
    for (const dep of (states[id]?.depends_on || [])) {
      if (color[dep] === GRAY) {
        console.error(`[event-router] dependency cycle: ${[...stack, id, dep].join(" → ")} — order falls back to priority`)
        return true
      }
      if ((color[dep] ?? WHITE) === WHITE && states[dep] && visit(dep, [...stack, id])) return true
    }
    color[id] = BLACK
    return false
  }
  for (const id of Object.keys(states)) {
    if ((color[id] ?? WHITE) === WHITE) { if (visit(id, [])) break }
  }
}

// ─── Router ──────────────────────────────────────────────────────────────────

/**
 * Find the repo root by walking up from directory.
 */
function findRepoRoot(directory: string): string | null {
  // Root markers: TASKS.vsm (legacy layout) AND current_focus.json
  // (vOSlab layout). Without the second, every summary/trace landed in
  // a random cwd/logs — the reason levels never reached our log.
  let p = resolve(directory)
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(p, "TASKS.vsm"))) return p
    if (existsSync(join(p, "current_focus.json"))) return p
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

// ─── Unified router for all events ─────────────────────────────────────────

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

  // PLC: dep verification (once per repoRoot) + runtime enable map.
  verifyDeps(repoRoot, handlers.map(h => h.id))
  const states = loadHandlerStates(repoRoot)

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

  // CC-1/CC-2: classify in PARALLEL. A slow classify (e.g. state-reconcile
  // does an SSH probe with 5s timeout) must not block dispatch of the other
  // handlers — sequential classify stalled the whole idle pipeline and a
  // one-shot client could die before a single execute ran.
  const enabled: Handler[] = []
  const results_skipped_disabled: string[] = []
  for (const handler of applicable) {
    // PLC: disabled handlers skip WITHOUT classify (no restart needed
    // to silence a noisy/broken handler; the skip is counted below).
    if (stateOf(states, handler.id).enabled) enabled.push(handler)
    else results_skipped_disabled.push(handler.id)
  }
  const classified = await Promise.all(enabled.map(async (handler) => {
    try {
      return await handler.classify(context)
    } catch {
      // classify failure = don't run this handler
      return false
    }
  }))
  const toRun: Handler[] = enabled.filter((_, i) => classified[i])

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
    + (results_skipped_disabled.length
      ? `;disabled-skipped: ${results_skipped_disabled.join(",")}` : "")

  await logSummary(
    repoRoot, eventId, eventType,
    total, ok, skip, totalDuration,
    summaryParts,
  )
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

const UnifiedRouter: Plugin = async ({ directory }) => {
  const repoRoot = findRepoRoot(directory || process.cwd()) || directory

  // CC-1 (CYCLE-CLOSE-001): session.* bus events arrive ONLY through the
  // generic `event` hook — the core hook dispatcher never invokes top-level
  // "session.*" keys (it triggers only tool.execute.*, chat.message,
  // shell.env, ...). Official pattern: opencode docs §Plugins/Events.
  // tool.execute.* remain explicit named hooks and are EXCLUDED from the
  // event hook below to prevent double routing (routeEvent is idempotent
  // only per invocation, not per event).
  return {
    event: async (input: any) => {
      const ev = input?.event ?? input
      const type = typeof ev?.type === "string" ? ev.type : ""
      if (!type.startsWith("session.")) return
      try {
        await routeEvent(type, directory, repoRoot, ev)
      } catch (e: any) {
        // Permanent error path (CC-1 temp traces removed): a throw here
        // would otherwise be swallowed silently by the plugin host.
        try {
          await logTrace(
            repoRoot, `${Date.now().toString(16)}-evt`, type,
            "event-router", "error", 0,
            `routeEvent threw: ${String(e?.message || e).slice(0, 200)}`,
          )
        } catch { /* last resort */ }
      }
    },
    // Tool events (real named hooks — dispatched by the core)
    "tool.execute.before": async (input: any) => {
      await routeEvent("tool.execute.before", directory, repoRoot, input)
    },
    "tool.execute.after": async (input: any) => {
      await routeEvent("tool.execute.after", directory, repoRoot, input)
    },
  }
}

export default UnifiedRouter
