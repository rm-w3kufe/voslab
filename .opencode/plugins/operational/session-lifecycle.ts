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
import { appendFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { logActivation } from "../../shared/log-activation"
import { callBridge } from "./tool-bridge"

// RAM-LIFECYCLE (alternativa 2): session.idle fired often and each run
// spawned 4 python interpreters (session-report, learn-pipeline,
// socratic-canon, rsi-status) over full state. Same capability,
// deferred cost: skip when nothing new happened AND the last full run
// is fresh. Learning is deferred, never lost (next full run sees the
// same disk state — disk is the source of truth).
const IDLE_MIN_INTERVAL_MS = Number(process.env.VOS_IDLE_MIN_MS || "") || 5 * 60 * 1000

function idleShouldSkip(repoRoot: string): boolean {
  try {
    const dir = join(repoRoot, "state", "rsi")
    const marker = join(dir, ".session_idle_last")
    let last: { at: number; logSize: number } | null = null
    try {
      last = JSON.parse(readFileSync(marker, "utf-8"))
    } catch {
      last = null
    }
    let logSize = -1
    try {
      logSize = statSync(join(repoRoot, "logs", "agent_plugin.jsonl")).size
    } catch {
      logSize = -1
    }
    if (last && Date.now() - last.at < IDLE_MIN_INTERVAL_MS && last.logSize === logSize) {
      return true
    }
    try {
      mkdirSync(dir, { recursive: true })
      writeFileSync(marker, JSON.stringify({ at: Date.now(), logSize }))
    } catch {
      // marker is best-effort; a missed write just runs the full cycle
    }
    return false
  } catch {
    return false // never skip on infrastructure doubt
  }
}

const SessionLifecycle: Plugin = async ({ directory }) => {
  return {
    // ═══════════════════════════════════════════════════════════════════════════
    // SESSION.CREATED: Bootstrap context
    // ═══════════════════════════════════════════════════════════════════════════
    "session.created": async (input: any) => {
      // P0 session attribution (§11.7): process-global env — every
      // emitter (TS appenders, spawned python via bridge/pre-commit)
      // stamps session_id from here; tool.execute.before re-asserts it.
      if (input?.sessionID) process.env.VOS_SESSION_ID = String(input.sessionID)
      // Get session report from bridge (tasks + stats)
      const report = await callBridge("session-report", [])

      // ABSTENTION ALARM (§6.3, F4.2): rolling zero-abstention window —
      // the compliance-bias signature raises ONE algedonic signal BEFORE
      // the consumer runs, so fresh pain is surfaced in this very session
      // (dedup lives in AlertMonitor: unacked or <24h suppresses).
      await callBridge("abstention-check", [])

      // ALGEDONIC CONSUMER (1c, S5 2026-10-05): surface unacked pain at
      // session start; entries older than 24h get acknowledged (boot-only
      // consumer never ran on a host that suspends instead of reboots —
      // 212+ were piled up). Fresh pain stays unacked and visible.
      const alerts = await callBridge("alert-consume", [])

      const alertSummary = alerts
        ? alerts.acked_stale
          ? `alerts: ${alerts.unacked} unacked, ${alerts.acked_stale} consumed (stale>24h), ${alerts.fresh_remaining} fresh`
          : alerts.unacked
            ? `alerts: ${alerts.unacked} unacked (all fresh)`
            : "alerts: queue clear"
        : "alerts: n/a"

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.created",
        report
          ? `bootstrap: ${report.tasks.total} tasks, ${report.session.total} actions today | ${alertSummary}`
          : `session initialized | ${alertSummary}`,
        "ok"
      )

      return { result: "ok", report, alerts }
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // SESSION.IDLE: Learning cycle (SECOND-ORDER)
    // ═══════════════════════════════════════════════════════════════════════════
    "session.idle": async (input: any) => {
      const repoRoot = directory || process.cwd()
      if (idleShouldSkip(repoRoot)) {
        return { result: "ok", skipped: "idle-throttle (no new activity)" }
      }
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
