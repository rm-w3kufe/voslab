/**
 * gap-resolution.ts — handler for gap-resolver integration with event-router.
 *
 * DESIGN: This handler is a thin wrapper that delegates to the gap-resolver
 * plugin. The gap-resolver.ts already handles session.idle and tool.execute.after
 * events directly. This handler exists for explicit registration in the event-router
 * and to provide a single point of entry for gap resolution.
 *
 * SCENARIO-MEMORY-INTEGRATION (2026-08-27): gap-resolver can use scenario-memory
 * to find past procedures for similar gaps. When a gap is detected, scenario-memory
 * provides recommendations based on past resolutions.
 *
 * R10: socratic trees provide deterministic decisions
 * R9: UNKNOWN if context lacks required info
 */
import { logActivation } from "../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

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
      // The gap-resolver plugin handles the actual execution
      // This handler just logs that gap resolution was triggered
      // Scenario Memory integration: gap-resolver can use past procedures
      // to inform gap resolution decisions
      const detail = `gap resolution triggered via ${ctx.event}`

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
