/**
 * design: docs/spec_revision/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
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
      // Get session report from bridge (tasks + stats). Advisory: a failure
      // must never abort session start (R1 resilience — an unguarded throw
      // here used to skip the algedonic consumer below, letting unacked pain
      // age past 48h; found 2026-10-14 when algedonic-queue-consumed went red).
      let report: any = null
      try { report = await callBridge("session-report", []) } catch { /* advisory */ }

      // ABSTENTION ALARM (§6.3, F4.2): rolling zero-abstention window —
      // the compliance-bias signature raises ONE algedonic signal BEFORE
      // the consumer runs, so fresh pain is surfaced in this very session
      // (dedup lives in AlertMonitor: unacked or <24h suppresses).
      try { await callBridge("abstention-check", []) } catch { /* advisory */ }

      // ALGEDONIC CONSUMER (1c, S5 2026-10-05): surface unacked pain at
      // session start; entries older than 24h get acknowledged (boot-only
      // consumer never ran on a host that suspends instead of reboots —
      // 212+ were piled up). Fresh pain stays unacked and visible.
      // GUARD: the pain consumer MUST run even if the calls above failed —
      // a skipped consumer is exactly the silent-pain failure this design
      // exists to prevent (CC-8: pain reaches S5 unfiltered).
      let alerts: any = null
      try {
        alerts = await callBridge("alert-consume", [])
        if (!alerts) throw new Error("bridge returned null")
      } catch (e: any) {
        // E1 (2026-10-16): a failed consumer must leave a trace — the
        // silent catch hid the dead-consumer state for 48h+ (R9: the
        // anti-R9 path itself must not be silent).
        await logActivation(
          directory || process.cwd(),
          "session-lifecycle",
          "alert-consume",
          `consumer failed on create: ${String(e?.message || e).slice(0, 200)}`,
          "error"
        )
      }

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

      // T3-F3 (structural-tensions 2026-10-20): clasificación AUS del
      // backlog unacked EN el primer reporte a S5 — la línea "N unacked"
      // daba volumen, nunca urgencia (220 sin triage = spam invisible).
      // Best-effort como rsi-queue-digest, pero un fallo LOGGEA (R9: el
      // path anti-R9 no puede quedar silencioso).
      let triageSummary = "triage: n/a"
      try {
        const t: any = await callBridge("alerts-triage", [])
        if (t && typeof t === "object" && t.error) throw new Error(String(t.error))
        if (t && t.counts && typeof t.counts.unacked === "number") {
          const c = t.counts
          triageSummary = c.unacked === 0
            ? "triage: clear (0 sin clasificar)"
            : `triage: ${c.unacked} sin clasificar → NOW ${c.now} / DEFER ${c.defer} / ACC ${c.accumulate_alerts}·${c.accumulate_groups}g`
          if (Array.isArray(t.top_now) && t.top_now.length > 0) {
            triageSummary += ` | top: ${t.top_now.slice(0, 3)
              .map((a: any) => String(a.alert_type || "?").slice(0, 40))
              .join(", ")}`
          }
        }
      } catch (e: any) {
        await logActivation(
          directory || process.cwd(),
          "session-lifecycle",
          "alerts-triage",
          `triage failed on create: ${String(e?.message || e).slice(0, 200)}`,
          "error"
        )
      }

      await logActivation(
        directory || process.cwd(),
        "session-lifecycle",
        "session.created",
        report
          ? `bootstrap: ${report.tasks.total} tasks, ${report.session.total} actions today | ${alertSummary} | ${queueSummary} | ${triageSummary}`
          : `session initialized | ${alertSummary} | ${queueSummary} | ${triageSummary}`,
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
      // Each callBridge is guarded individually (same pattern as
      // createdHandler, 70ab553): one failing stage must never abort the
      // rest of the idle pipeline (learn/canon/rsi/remediate all still run).
      let report: any = null
      try { report = await callBridge("session-report", []) } catch { /* advisory */ }

      // ALGEDONIC CONSUMER — IDLE ANCHOR (E1, 2026-10-16, S5 order):
      // the createdHandler anchor failed in practice — 5 session.created
      // vs 315 session.idle in the whole log; resumes after an opencode
      // restart never re-emit session.created, so the consumer silently
      // died (evidence: unacked pain >48h, gate red, task
      // ALGEDONIC-CONSUMER-STALLED). Same semantics as session start
      // (S5 1c: surface unacked + ack >24h, fresh stays visible);
      // idempotent and gated by idleShouldSkip above. R9: this is the
      // path that must not go silent — a failure LOGS, never tapes.
      let consumeResult: any = null
      try {
        consumeResult = await callBridge("alert-consume", [])
        if (!consumeResult) throw new Error("bridge returned null")
      } catch (e: any) {
        await logActivation(
          directory || process.cwd(),
          "session-lifecycle",
          "alert-consume",
          `consumer failed on idle: ${String(e?.message || e).slice(0, 200)}`,
          "error"
        )
      }

      // SECOND-ORDER LEARNING: detect patterns → generate predicates → register
      let learnResult: any = null
      try { learnResult = await callBridge("learn-pipeline", []) } catch { /* advisory */ }

      // SOCRATIC INTEGRATION: query canon data for context
      let canonResult: any = null
      try { canonResult = await callBridge("socratic-canon", ["tasks", "{}"]) } catch { /* advisory */ }

      // RSI STATUS: check RSI observer and cycle status
      let rsiStatus: any = null
      try { rsiStatus = await callBridge("rsi-status", []) } catch { /* advisory */ }

      // ALGEDONIC SLOW-PATH (ALGEDONIC-TRIAGE-v1): reverify NOW alerts —
      // non-destructive only (R17); acks alerts whose condition is now clear.
      // Advisory: a remediation failure never breaks the idle cycle.
      let remediateSummary = "remediate: n/a"
      try {
        const rem = await callBridge("algedonic-remediate", [])
        if (rem && !rem.error) {
          remediateSummary = `remediate: NOW=${rem.now ?? 0} acked=${rem.acked_resolved ?? 0}`
        }
      } catch { /* advisory */ }

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

      // R7-B COLLAPSE REVIEW (2026-10-12, S5 approved option B):
      // streak-collapse (>=5 failures / trailing 50 evaluate events)
      // pages S5 review via caution-signal ADVISORY. No behavior change,
      // no auto-trigger — the triage (R4) is the only path to action.
      let collapseSummary = "collapse: n/a"
      try {
        const collapse = await callBridge("pleasure-collapse-check", [])
        if (collapse && !collapse.error) {
          if (collapse.collapse) {
            await callBridge("caution-signal", [
              "pleasure-collapse",
              `streak collapse: ${collapse.failures}/${collapse.window} failures (threshold ${collapse.threshold})`,
            ])
            collapseSummary = `collapse: PAGED review (${collapse.failures}/${collapse.window})`
          } else {
            collapseSummary = `collapse: clear (${collapse.failures}/${collapse.window})`
          }
        }
      } catch {
        // collapse review is advisory — never break the idle cycle
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
          ? `report: ${report.session.total} actions (${report.session.success} ok, ${report.session.failure} fail) | ${report.tasks.done}/${report.tasks.total} tasks done | ${learnSummary} | ${canonSummary} | ${rsiSummary} | ${firesSummary} | ${collapseSummary} | ${distillSummary} | ${remediateSummary}`
          : `cognitive integration check | ${learnSummary} | ${canonSummary} | ${rsiSummary} | ${firesSummary} | ${collapseSummary} | ${distillSummary} | ${remediateSummary}`,
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
