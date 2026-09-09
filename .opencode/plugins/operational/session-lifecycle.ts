/**
 * session-lifecycle.ts — Session lifecycle handlers for tool integration.
 *
 * Handles session.created and session.idle events, extracting these
 * from the monolithic tool-integration.ts.
 *
 * session.created:
 *   1. Bootstrap context from state-canon
 *   2. Load recent patterns from vsf-rsi
 *
 * session.idle:
 *   1. Generate session report
 *   2. Learning cycle check
 *   3. Canon query
 *   4. RSI status
 */
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"
import { callBridge } from "./tool-bridge"

const SessionLifecycle: Plugin = async ({ directory }) => {
  return {
    // ═══════════════════════════════════════════════════════════════════════════
    // SESSION.CREATED: Bootstrap context
    // ═══════════════════════════════════════════════════════════════════════════
    "session.created": async (input: any) => {
      // Get session report from bridge (tasks + stats)
      const report = await callBridge("session-report", [])

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.created",
        report
          ? `bootstrap: ${report.tasks.total} tasks, ${report.session.total} actions today`
          : "session initialized",
        "ok"
      )

      return { result: "ok", report }
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // SESSION.IDLE: Learning cycle (SECOND-ORDER)
    // ═══════════════════════════════════════════════════════════════════════════
    "session.idle": async (input: any) => {
      const report = await callBridge("session-report", [])

      // SECOND-ORDER LEARNING: detect patterns → generate predicates → register
      const learnResult = await callBridge("learn-pipeline", [])

      // SOCRATIC INTEGRATION: query canon data for context
      const canonResult = await callBridge("socratic-canon", ["tasks", "{}"])
      
      // RSI STATUS: check RSI observer and cycle status
      const rsiStatus = await callBridge("rsi-status", [])

      const learnSummary = learnResult
        ? `learn: ${learnResult.patterns_detected || 0} patterns, ${learnResult.predicates_registered || 0} new predicates`
        : "learn: no patterns"

      const canonSummary = canonResult
        ? `canon: ${canonResult.count || 0} tasks`
        : "canon: no data"

      const rsiSummary = rsiStatus
        ? `rsi: ${rsiStatus.predicate_count || 0} predicates, ${rsiStatus.scenario_count || 0} scenarios`
        : "rsi: no status"

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.idle",
        report
          ? `report: ${report.session.total} actions (${report.session.success} ok, ${report.session.failure} fail) | ${report.tasks.done}/${report.tasks.total} tasks done | ${learnSummary} | ${canonSummary} | ${rsiSummary}`
          : `cognitive integration check | ${learnSummary} | ${canonSummary} | ${rsiSummary}`,
        "ok"
      )

      return { result: "ok", session_report: report, learning: learnResult, canon: canonResult, rsi_status: rsiStatus }
    },
  }
}

export default SessionLifecycle
