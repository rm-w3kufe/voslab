/**
 * gap-resolver.ts — Recursive gap resolution framework.
 *
 * DESIGN: Orchestrates gap definitions through trigger → context → eval → action → log.
 * Each gap is a JSON definition; the resolver executes them recursively.
 *
 * Modes:
 *   - SEMI-AUTOMATIC (default): suggests changes, requires approval
 *   - AUTOMATIC: executes changes directly (flag: GAP_RESOLVER_AUTO=true)
 *
 * R16: policy declares, instrument interprets.
 * R10: socratic trees provide deterministic decisions.
 *
 * INTEGRATION: Uses socratic-shell pattern for tree evaluation.
 * Each gap definition is a declarative config; the resolver is the interpreter.
 *
 * DYNAMIC GATES: Integrates with gate_registry.py to load gates from:
 * - Static gate trees (.opencode/plugins/support/trees/*.tree.vsm)
 * - Gap-definition gates (.opencode/plugins/operational/gap-definitions/*.gap.json)
 * - RSI-generated gates (from rsi_pipeline.py)
 */
import { existsSync, readFileSync, writeFileSync, readdirSync } from "node:fs"
import { join, dirname, basename, extname } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"
import { callBridge } from "./tool-bridge"
import { gatherContext } from "./gap-context"
import { executeAction } from "./gap-actions"
import { loadGapDefinitionsFromRegistry } from "./gap-registry"

// ─── Config ──────────────────────────────────────────────────────────────────

const GAP_DEFINITIONS_DIR = "gap-definitions"
const GAP_LOG_FILE = "logs/gap-resolution.jsonl"

// Auto-mode flag (default: false = semi-automatic)
const AUTO_MODE = process.env.GAP_RESOLVER_AUTO === "true"

// ─── Types ───────────────────────────────────────────────────────────────────

interface GapResult {
  gapId: string
  trigger: string
  decision: string
  /** Why the decision (e.g. `tree not found`, `no doc type`) — surfaced
   *  to gap-resolution detail so ERROR/UNKNOWN are diagnosable (M7). */
  truth?: string
  home?: string
  actions: string[]
  autoExecuted: boolean
  timestamp: string
}

// ─── Socratic Tree Evaluation ────────────────────────────────────────────────

async function evaluateTree(
  treePath: string,
  context: Record<string, any>,
  repoRoot: string
): Promise<{ decision: string; truth: string; certified: boolean; home?: string }> {
  // Resolve tree via repo root (fail-closed: bridge re-checks inside-root)
  const treeAbs = join(repoRoot, treePath)
  if (!existsSync(treeAbs)) {
    return { decision: "ERROR", truth: "tree not found", certified: false }
  }

  try {
    // Build docType from content (same pattern as vsf-classify-on-write).
    // Empty when the file carries no ⟦⟧ header (plain code): type_prefix
    // guards stay UNKNOWN-safe on empty type, so evaluation proceeds —
    // content-gathered trees (classify/conflict/dependency/quality) need
    // the real context, not a doc-type gate. R9 still holds: missing keys
    // evaluate UNKNOWN inside the trees (ctx_has guards), never FALSE.
    const docType = context.content?.match(/⟦\s*[^|]+\|\s*([^|]+)\s*\|/)?.[1] || ""

    // Gap-engine-path fix (found-debt): the old code shelled out to
    // scripts/vsl/classifier/socratic_engine.py, which does not exist —
    // every gap evaluated to engine-not-found. Mediated through the
    // bridge instead (live cycle, RBAC operator, audited).
    // GAP-MEDIDA: timed + audited per eval (spawn count x latency
    // decides daemon with data, not faith).
    // FULL CONTEXT (FND-GAP-TREES-01 fix, 2026-09-29): the bridge used to
    // receive {type} only, so content/imports/exports/syntaxValid never
    // reached any tree (every content predicate evaluated UNKNOWN). Types
    // stay NATIVE (booleans unquoted in VSL match JSON booleans; arrays
    // stay arrays for membership checks) — no stringification.
    const t0 = Date.now()
    const result: any = await callBridge("socratic-tree-file", [
      treeAbs,
      JSON.stringify({ ...context, type: docType }),
    ])
    const elapsed = Date.now() - t0
    try {
      await logActivation(
        repoRoot, "gap-resolver", "gap.evaluate",
        `tree ${(treePath.split("/").pop() || "?").slice(0, 60)} ${elapsed}ms`,
        result && !result.error ? "ok" : "error",
        `decision=${result?.decision || result?.truth || "?"} certified=${result?.certified || false}`)
    } catch {
      // measurement must never break evaluation
    }
    if (!result || result.error) {
      return { decision: "ERROR", truth: (result?.error || "bridge unavailable").slice(0, 200), certified: false }
    }
    return {
      decision: result.home || result.decision || "UNKNOWN",
      truth: result.truth || "UNCERTAIN",
      certified: result.certified || false,
      home: result.home,
    }
  } catch (err: any) {
    return { decision: "ERROR", truth: err.message?.slice(0, 200), certified: false }
  }
}

// ─── Gap Resolver Core ───────────────────────────────────────────────────────

export async function resolveGap(
  gapDef: { id: string; trigger: any; context: any; evaluation: any; actions: any[] },
  filePath: string,
  repoRoot: string,
  autoMode: boolean = AUTO_MODE
): Promise<GapResult> {
  const result: GapResult = {
    gapId: gapDef.id,
    trigger: gapDef.trigger?.type || "always",
    decision: "",
    home: undefined,
    actions: [],
    autoExecuted: autoMode,
    timestamp: new Date().toISOString(),
  }

  // 1. Check trigger match
  const fileExt = extname(filePath)
  const fileDir = dirname(filePath)
  const fileName = basename(filePath)

  let triggerMatch = false
  if (gapDef.trigger.patterns) {
    triggerMatch = gapDef.trigger.patterns.some((p: string) => {
      if (p.startsWith("*")) return fileExt === p.slice(1) || fileExt === p.slice(2)
      return fileName.includes(p)
    })
  }
  if (gapDef.trigger.directories) {
    triggerMatch = triggerMatch || gapDef.trigger.directories.some((d: string) => fileDir.includes(d))
  }

  if (!triggerMatch) {
    result.decision = "SKIP"
    return result
  }

  // 2. Gather context
  const context = await gatherContext(gapDef.context.gatherers, filePath, repoRoot)

  // 3. Evaluate
  if (gapDef.evaluation.type === "socratic-tree" && gapDef.evaluation.tree) {
    const evalResult = await evaluateTree(gapDef.evaluation.tree, context, repoRoot)
    result.decision = evalResult.decision
    result.truth = evalResult.truth
    result.home = evalResult.home

    // Enrich context with evaluation result
    context.decision = evalResult.decision
    context.truth = evalResult.truth
    context.certified = evalResult.certified
    context.home = evalResult.home
  } else {
    // Rule-based evaluation (simple pattern matching)
    result.decision = "RULE_BASED"
  }

  // 4. Execute actions
  for (const actionDef of gapDef.actions) {
    // Evaluate condition
    const condition = actionDef.condition
    let conditionMet = false

    if (condition.includes("decision ===")) {
      const expectedDecision = condition.match(/decision === '([^']+)'/)?.[1]
      conditionMet = result.decision === expectedDecision
    } else if (condition.includes("truth ===")) {
      const expectedTruth = condition.match(/truth === '([^']+)'/)?.[1]
      conditionMet = context.truth === expectedTruth
    } else if (condition === "true" || condition === "always") {
      conditionMet = true
    }

    if (conditionMet) {
      const actionResult = await executeAction(
        actionDef.action,
        actionDef.params || {},
        context,
        repoRoot,
        autoMode
      )
      result.actions.push(actionResult.detail)
    }
  }

  // 5. Log result
  await logGapResolution(result, repoRoot)

  return result
}

async function logGapResolution(result: GapResult, repoRoot: string): Promise<void> {
  const logPath = join(repoRoot, GAP_LOG_FILE)
  const logDir = dirname(logPath)

  if (!existsSync(logDir)) {
    const { mkdirSync } = await import("node:fs")
    mkdirSync(logDir, { recursive: true })
  }

  const logEntry = JSON.stringify(result) + "\n"
  writeFileSync(logPath, logEntry, { flag: "a" })
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

export default (): Plugin => {
  return {
    name: "gap-resolver",
    hooks: [
      // On file write: resolve gaps for new/modified files
      {
        event: "tool.execute.after",
        async handler({ directory, input }) {
          const toolName = input?.tool || ""
          if (!["write", "edit"].includes(toolName)) {
            return { result: "skip", durationMs: 0, detail: "not a write tool" }
          }

          const filePath = input?.filePath || input?.path || ""
          if (!filePath) return { result: "skip", durationMs: 0, detail: "no file path" }

          const start = Date.now()
          const repoRoot = directory || process.cwd()

          // Load gap definitions from registry (unified source)
          let gapDefs: any[] = []
          
          // 1. Try loading from gate registry (includes static + RSI-generated)
          gapDefs = await loadGapDefinitionsFromRegistry(repoRoot)
          
          // 2. Fallback to file-based loading if registry unavailable
          if (gapDefs.length === 0) {
            const defsDir = join(repoRoot, ".opencode/plugins/operational", GAP_DEFINITIONS_DIR)
            if (existsSync(defsDir)) {
              const gapFiles = readdirSync(defsDir).filter((f) => f.endsWith(".gap.json"))
              for (const gapFile of gapFiles) {
                const gapPath = join(defsDir, gapFile)
                const gapDef = JSON.parse(readFileSync(gapPath, "utf-8"))
                gapDefs.push(gapDef)
              }
            }
          }

          if (gapDefs.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no gap definitions" }
          }

          const results: GapResult[] = []
          for (const gapDef of gapDefs) {
            const result = await resolveGap(gapDef, filePath, repoRoot)
            if (result.decision !== "SKIP") {
              results.push(result)
            }
          }

          const duration = Date.now() - start
          const detail = results.length > 0
            ? results.map((r) => `${r.gapId}: ${r.decision}`).join("; ")
            : "no gaps triggered"

          await logActivation(repoRoot, "gap-resolver", "tool.execute.after", "resolve", results.length > 0 ? "ok" : "skip", detail)

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail,
            summary: `${results.length} gaps resolved`,
          }
        },
      },

      // On session idle: resolve gaps for all tracked files
      {
        event: "session.idle",
        async handler({ directory }) {
          const start = Date.now()
          const repoRoot = directory || process.cwd()

          // Load gap definitions from registry (unified source)
          let gapDefs: any[] = []
          
          // 1. Try loading from gate registry (includes static + RSI-generated)
          gapDefs = await loadGapDefinitionsFromRegistry(repoRoot)
          
          // 2. Fallback to file-based loading if registry unavailable
          if (gapDefs.length === 0) {
            const defsDir = join(repoRoot, ".opencode/plugins/operational", GAP_DEFINITIONS_DIR)
            if (existsSync(defsDir)) {
              const gapFiles = readdirSync(defsDir).filter((f) => f.endsWith(".gap.json"))
              for (const gapFile of gapFiles) {
                const gapPath = join(defsDir, gapFile)
                const gapDef = JSON.parse(readFileSync(gapPath, "utf-8"))
                gapDefs.push(gapDef)
              }
            }
          }

          if (gapDefs.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no gap definitions" }
          }

          const results: GapResult[] = []

          // Scan for files that might need gap resolution
          const scanDirs = [".opencode/plugins", "scripts/state"]
          for (const scanDir of scanDirs) {
            const fullDir = join(repoRoot, scanDir)
            if (!existsSync(fullDir)) continue

            // Simple scan: check for .ts, .py, .sh files
            const files = readdirSync(fullDir, { recursive: true })
              .filter((f): f is string => typeof f === "string" && /\.(ts|py|sh)$/.test(f))

            for (const file of files.slice(0, 10)) { // Limit to 10 files per session
              const filePath = join(fullDir, file)
              for (const gapDef of gapDefs) {
                const result = await resolveGap(gapDef, filePath, repoRoot)
                if (result.decision !== "SKIP") {
                  results.push(result)
                }
              }
            }
          }

          const duration = Date.now() - start
          const detail = results.length > 0
            ? results.map((r) => `${r.gapId}: ${r.decision}`).join("; ")
            : "no gaps triggered"

          await logActivation(repoRoot, "gap-resolver", "session.idle", "resolve", results.length > 0 ? "ok" : "skip", detail)

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail,
            summary: `${results.length} gaps resolved`,
          }
        },
      },
    ],
  }
}
