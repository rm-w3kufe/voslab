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
  // ═══════════════════════════════════════════════════════════════════════════
  // SESSION.CREATED: Bootstrap context
  // ═══════════════════════════════════════════════════════════════════════════
  async function createdHandler(input: any): Promise<any> {
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

      // R1 APPROVAL-QUEUE RITUAL (2026-10-12): surface aging learned
      // fixes at boot so the queue cannot stall silently. Best-effort:
      // a digest failure must never break session start.
      let queueSummary = "rsi-queue: n/a"
      try {
        const digest = await callBridge("rsi-queue-digest", [])
        if (digest && typeof digest.pending === "number") {
          queueSummary = digest.pending === 0
            ? "rsi-queue: clear"
            : `rsi-queue: ${digest.pending} pending (${JSON.stringify(digest.by_class)}), oldest ${digest.oldest_days}d`
        }
      } catch { /* digest is advisory */ }

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.created",
        report
          ? `bootstrap: ${report.tasks.total} tasks, ${report.session.total} actions today | ${alertSummary} | ${queueSummary}`
          : `session initialized | ${alertSummary} | ${queueSummary}`,
        "ok"
      )

    return { result: "ok", report, alerts }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SESSION.IDLE: Learning cycle (SECOND-ORDER)
  // ═══════════════════════════════════════════════════════════════════════════
  async function idleHandler(input: any): Promise<any> {
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

      // O-6 DISTILL (R-3, §6.2): periodic trajectory→learning, PROPOSE-
      // ONLY — appends candidates to state/distill/candidates.jsonl;
      // applying them requires S5 ratification (never skills/predicates).
      // Archive features are signature-cached, so steady-state cost is a
      // live-log parse (~1s); first run pays the archive census once.
      let distillResult: any = null
      try {
        distillResult = await callBridge("log-distill", [])
      } catch {
        // distill is advisory — never break the idle cycle
      }

      const learnSummary = learnResult
        ? `learn: ${learnResult.patterns_detected || 0} patterns, ${learnResult.predicates_registered || 0} new predicates`
        : "learn: no patterns"

      const canonSummary = canonResult
        ? `canon: ${canonResult.count || 0} tasks`
        : "canon: no data"

      const rsiSummary = rsiStatus
        ? `rsi: ${rsiStatus.predicate_count || 0} predicates, ${rsiStatus.scenario_count || 0} scenarios`
        : "rsi: no status"

      // R2 LEARNED-PATTERN VISIBILITY (2026-10-12): fires from today's
      // log (blocks/warns by learned patterns, socratic blocks, breaker
      // trips). Zeroes are signal — plan tracks first fire in 30d.
      const fires = report?.rsi_fires
      const firesSummary = fires
        ? `fires: learned ${fires.blocks_learned || 0}b/${fires.warns_learned || 0}w, socratic ${fires.blocks_socratic || 0}b, breaker ${fires.breaker_loop || 0}l/${fires.breaker_error || 0}e`
        : "fires: n/a"

      const distillSummary = distillResult && !distillResult.error
        ? `distill: ${distillResult.input?.archive_records ?? 0}+${distillResult.input?.live_records ?? 0} recs, ${distillResult.candidates?.new?.length ?? 0} new cand`
        : "distill: n/a"

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.idle",
        report
          ? `report: ${report.session.total} actions (${report.session.success} ok, ${report.session.failure} fail) | ${report.tasks.done}/${report.tasks.total} tasks done | ${learnSummary} | ${canonSummary} | ${rsiSummary} | ${firesSummary} | ${distillSummary}`
          : `cognitive integration check | ${learnSummary} | ${canonSummary} | ${rsiSummary} | ${firesSummary} | ${distillSummary}`,
        "ok"
      )

    return { result: "ok", session_report: report, learning: learnResult, canon: canonResult, rsi_status: rsiStatus, distill: distillResult }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // EVENT HOOK (L-OCC round, FIX 2026-10-07): session.* bus events arrive
  // ONLY through the generic `event` hook — the core dispatcher never invokes
  // top-level "session.*" keys (same CC-1 finding as vsf-event-router: it
  // "triggers only tool.execute.*, chat.message, shell.env, …"). The old
  // named keys were structurally dead: VOS_SESSION_ID was never set here and
  // session_id was null in every canonical record (P0 attribution).
  // ═══════════════════════════════════════════════════════════════════════════
  return {
    event: async (input: any) => {
      const ev = input?.event ?? input
      const type = typeof ev?.type === "string" ? ev.type : ""
      if (type !== "session.created" && type !== "session.idle") return
      const props = ev?.properties ?? {}
      const sessionID = props.sessionID ?? ev?.sessionID
      const handlerInput: any = { sessionID, directory }
      return type === "session.created"
        ? await createdHandler(handlerInput)
        : await idleHandler(handlerInput)
    },
  }
}

export default SessionLifecycle
