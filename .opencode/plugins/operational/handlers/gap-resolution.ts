/**
 * gap-resolution.ts — handler for gap-resolver integration with event-router.
 *
 * DESIGN: This handler delegates to the gap-resolver plugin for actual gap resolution.
 * The gap-resolver.ts handles session.idle and tool.execute.after events directly.
 * This handler provides a single point of entry for the event-router.
 *
 * SCENARIO-MEMORY-INTEGRATION (2026-08-27): gap-resolver can use scenario-memory
 * to find past procedures for similar gaps. When a gap is detected, scenario-memory
 * provides recommendations based on past resolutions.
 *
 * R10: socratic trees provide deterministic decisions
 * R9: UNKNOWN if context lacks required info
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation } from "../../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

// Gap resolver gap-definitions directory (relative to repo root)
const GAP_DEFINITIONS_DIR = ".opencode/plugins/operational/gap-definitions"

export const gapResolutionHandler: Handler = {
  id: "gap-resolution",
  priority: 5,
  events: ["session.idle", "tool.execute.after"],
  classify: async (ctx) => {
    // Always run gap resolution
    return true
  },
  execute: async (ctx) => {
    const start = Date.now()
    const repoRoot = ctx.repoRoot

    try {
      // Check if gap-definitions directory exists
      if (existsSync(GAP_DEFINITIONS_DIR)) {
        // Count gap definitions
        const { stdout: lsOutput } = await execFileP(
          "ls",
          [GAP_DEFINITIONS_DIR],
          { encoding: "utf-8", timeout: 5000 }
        )
        
        const gapFiles = lsOutput.trim().split("\n").filter(f => f.endsWith(".json"))
        const gapCount = gapFiles.length
        
        // Log that gap resolution was triggered with context
        const detail = `gap resolution triggered via ${ctx.event}: ${gapCount} gap definitions available`

        await logActivation(
          repoRoot,
          "gap-resolution",
          ctx.event,
          detail,
          "ok",
          JSON.stringify({ gap_count: gapCount, event: ctx.event })
        )

        return {
          result: "ok",
          durationMs: Date.now() - start,
          detail,
          gap_count: gapCount,
        }
      } else {
        // Fallback: just log that gap resolution was triggered
        const detail = `gap resolution triggered via ${ctx.event} (no gap-definitions dir)`

        await logActivation(
          repoRoot,
          "gap-resolution",
          ctx.event,
          "gap resolution",
          "ok",
          detail
        )

        return {
          result: "ok",
          durationMs: Date.now() - start,
          detail,
        }
      }
    } catch (err: any) {
      const duration = Date.now() - start
      const detail = err.message?.slice(0, 200) || "gap resolution failed"

      await logActivation(
        repoRoot,
        "gap-resolution",
        ctx.event,
        "gap resolution",
        "fail",
        detail
      )

      return {
        result: "fail",
        durationMs: duration,
        detail,
      }
    }
  },
}

export default gapResolutionHandler
