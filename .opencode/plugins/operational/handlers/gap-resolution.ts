/**
 * gap-resolution.ts — Handler for gap resolution.
 *
 * Integrates gap-resolver with the event-router system.
 * Runs on tool.execute.after (after file writes) and session.idle.
 *
 * R16: policy declares, instrument interprets.
 * R10: socratic trees provide deterministic decisions.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import type { Handler, HandlerContext, HandlerResult } from "../vsf-event-router"
import { logActivation } from "../../../shared/log-activation"
import { queryScenarioMemoryForGap, type GapContext } from "../scenario-memory-gap-bridge"
import { resolveGap as engineResolveGap } from "../gap-resolver"

// ─── Config ──────────────────────────────────────────────────────────────────

// Engine runs suggest-only here: autoMode=false → actions reported, never
// executed. Execution stays behind GAP_RESOLVER_AUTO=true + S5 decision.
// Writes only: engine evaluation (file reads + tree evals) is bounded to
// file-write events; other events keep the cheap scenario-memory path.
const ENGINE_AUTO_MODE = process.env.GAP_RESOLVER_AUTO === "true"
const ENGINE_WRITE_TOOLS = new Set(["write", "edit"])

// ─── Config ──────────────────────────────────────────────────────────────────

const GAP_DEFINITIONS_DIR = "gap-definitions"

// ─── Types ───────────────────────────────────────────────────────────────────

interface GapResult {
  gapId: string
  trigger: string
  decision: string
  home?: string
  actions: string[]
  autoExecuted: boolean
  timestamp: string
}

// ─── Gap Resolution ──────────────────────────────────────────────────────────

async function resolveGap(
  gapDef: any,
  filePath: string,
  repoRoot: string,
  tool: string = "",
): Promise<GapResult> {
  // Engine path (revived 2026-09-24): full evaluation — trigger patterns,
  // context gatherers, socratic-tree decision — with autoMode from env
  // (default false = suggest-only, identical outward behavior to the old
  // shim). Bounded to file writes; falls back to scenario-memory below.
  if (filePath && ENGINE_WRITE_TOOLS.has(tool)) {
    try {
      const r = await engineResolveGap(gapDef, filePath, repoRoot,
                                       ENGINE_AUTO_MODE)
      if (r.decision && r.decision !== "SKIP") {
        return {
          gapId: r.gapId, trigger: r.trigger, decision: r.decision,
          home: r.home, actions: r.actions,
          autoExecuted: r.autoExecuted, timestamp: r.timestamp,
        }
      }
    } catch {
      // Engine failure must never break the handler — fall through.
    }
  }

  const gapId = gapDef.id || "unknown"
  const trigger = gapDef.trigger?.type || "file-created"

  // Check if trigger matches
  if (trigger === "file-created" && !filePath) {
    return { gapId, trigger, decision: "SKIP", actions: [], autoExecuted: false, timestamp: new Date().toISOString() }
  }

  // Query scenario-memory for suggestions
  const gapContext: GapContext = {
    gapId,
    gapType: gapDef.type || "unknown",
    filePath,
    trigger,
  }
  const suggestions = queryScenarioMemoryForGap(gapContext, repoRoot)

  // If high-confidence suggestion exists, use it
  if (suggestions.length > 0 && suggestions[0].confidence >= 0.8) {
    return {
      gapId,
      trigger,
      decision: "RESOLVE",
      actions: [suggestions[0].suggestion],
      autoExecuted: false,
      timestamp: new Date().toISOString(),
    }
  }

  // Otherwise, skip
  return {
    gapId,
    trigger,
    decision: "SKIP",
    actions: [],
    autoExecuted: false,
    timestamp: new Date().toISOString(),
  }
}

// ─── Handler ─────────────────────────────────────────────────────────────────

export const gapResolutionHandler: Handler = {
  id: "gap-resolution",
  priority: 5,
  events: ["tool.execute.after", "session.idle"], // After scenario-memory (4), before others

  classify: async (ctx: HandlerContext): Promise<boolean> => {
    // Run on file writes and session idle
    return ctx.event === "tool.execute.after" || ctx.event === "session.idle"
  },

  execute: async (ctx: HandlerContext): Promise<HandlerResult> => {
    const start = Date.now()
    const repoRoot = ctx.repoRoot || process.cwd()

    // Load gap definitions from gap-definitions directory
    const defsDir = join(repoRoot, ".opencode/plugins/operational", GAP_DEFINITIONS_DIR)
    if (!existsSync(defsDir)) {
      return { result: "skip", durationMs: 0, detail: "no gap definitions directory" }
    }

    const gapFiles = readdirSync(defsDir).filter((f) => f.endsWith(".gap.json"))
    if (gapFiles.length === 0) {
      return { result: "skip", durationMs: 0, detail: "no gap definitions" }
    }

    // Load all gap definitions
    const gapDefs: any[] = []
    for (const gapFile of gapFiles) {
      const gapPath = join(defsDir, gapFile)
      try {
        const gapDef = JSON.parse(readFileSync(gapPath, "utf-8"))
        gapDefs.push(gapDef)
      } catch {
        // Skip malformed files
      }
    }

    if (gapDefs.length === 0) {
      return { result: "skip", durationMs: 0, detail: "no valid gap definitions" }
    }

    // Resolve gaps for the current file (if tool.execute.after)
    const results: GapResult[] = []
    const filePath = ctx.file || ""
    const tool = (ctx.payload as any)?.tool || (ctx as any).tool || ""

    for (const gapDef of gapDefs) {
      const result = await resolveGap(gapDef, filePath, repoRoot, tool)
      if (result.decision !== "SKIP") {
        results.push(result)
      }
    }

    const duration = Date.now() - start
    const detail = results.length > 0
      ? results.map((r) => `${r.gapId}: ${r.decision}`).join("; ")
      : "no gaps triggered"

    await logActivation(repoRoot, "gap-resolution", ctx.event, "resolve", results.length > 0 ? "ok" : "skip", detail)

    return {
      result: results.length > 0 ? "ok" : "skip",
      durationMs: duration,
      detail,
      summary: `${results.length} gaps resolved`,
    }
  },
}
