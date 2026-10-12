/**
 * tool-integration.ts — Mandatory cognitive pipeline (v3)
 *
 * 99% of work MUST pass through state-canon, socratic-engine, vsf-rsi.
 *
 * Pipeline:
 *   tool.execute.before:
 *     1. Query state-canon for current context
 *     2. Evaluate action with socratic-engine
 *     3. Log advisory (can block on critical violations)
 *
 *   tool.execute.after:
 *     1. Record outcome in state-canon (JSONL audit)
 *     2. Record pattern in vsf-rsi (learning)
 *     3. Update integration stats
 *
 * Session handlers moved to session-lifecycle.ts
 */
import type { Plugin } from "@opencode-ai/plugin"
import { appendFileSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join, resolve, sep } from "node:path"
import { logActivation } from "../../shared/log-activation"
import {
  callBridge,
  isSafeMode,
  MANDATORY_TOOLS,
  READ_ONLY_TOOLS,
  STATE_CHANGING_TOOLS,
} from "./tool-bridge"

// ─── Tier1: read fast-path (RAM-LIFECYCLE, alternativa 2) ────────────────────
// Reads are the highest-frequency tools and the before-hook is BLIND
// (KEY-DUMP: before receives no args, so file/command are always "").
// The only read predicate with blocking teeth is path_forbidden, which
// needs the file — only visible in the AFTER hook. So:
//   before: Tier1 returns immediately (a blind pre-check can never
//           certify a file verdict; it only burned a python spawn, and
//           worse, not_redundant on the empty key could false-positive
//           after 3+ reads).
//   after:  Tier1 checks the denylist IN-PROCESS (same JSON policy,
//           same normalization as stub_predicates). Hit or error →
//           full python pipeline (certified verdict + audit). Clear +
//           success → cheap record (telemetry + trust-spill + log).
// Same logical verdict, no python on the hot path.

const TIER1_READ = new Set(["read", "glob", "grep"])

// NOTE: no TS-side snapshot of the denylist on purpose. The live list
// lives in system/s5-policy/access_policy.json (hot-reloaded per call);
// an unreadable policy fails CLOSED to the full python pipeline, so a
// stale snapshot can never miss a block. A TS hit always re-enters the
// full pipeline for the certified verdict — TS never blocks by itself.

interface Tier1Policy {
  mtimeMs: number
  deny: string[]
}

let tier1PolicyCache: Tier1Policy | null = null

function loadTier1Policy(repoRoot: string): string[] | null {
  try {
    const p = join(repoRoot, "system", "s5-policy", "access_policy.json")
    const st = statSync(p)
    if (tier1PolicyCache && tier1PolicyCache.mtimeMs === st.mtimeMs) {
      return tier1PolicyCache.deny
    }
    const raw = JSON.parse(readFileSync(p, "utf-8"))
    const deny = Array.isArray(raw?.read_denylist) ? raw.read_denylist.map(String) : null
    if (!deny) return null // corrupt policy → fail closed (full pipeline)
    tier1PolicyCache = { mtimeMs: st.mtimeMs, deny }
    return deny
  } catch {
    return null // unreadable policy → fail closed (full pipeline)
  }
}

/** Mirror of stub_predicates._normalize_path (lexical + symlink). */
function tier1Normalize(p: string): string {
  try {
    let expanded = p
    if (expanded === "~" || expanded.startsWith("~/")) {
      expanded = join(homedir(), expanded.slice(1))
    }
    const abs = resolve(expanded)
    try {
      return realpathSync(abs)
    } catch {
      return abs
    }
  } catch {
    return p
  }
}

/** Mirror of stub_predicates._hits_forbidden (separator-aware). */
function tier1HitsForbidden(target: string, deny: string[]): string | null {
  const norm = tier1Normalize(target)
  for (const fp of deny) {
    if (norm === fp || norm.startsWith(fp + sep)) return fp
  }
  return null
}

/** T4.3 telemetry: same {ts,size} schema the bridge appends (read/glob only). */
function tier1Telemetry(repoRoot: string, file: string): void {
  try {
    const sz = statSync(file).size
    const dir = join(repoRoot, "state", "rsi")
    try {
      mkdirSync(dir, { recursive: true })
    } catch {
      // ignore
    }
    appendFileSync(
      join(dir, "read_sizes.jsonl"),
      JSON.stringify({ ts: new Date().toISOString(), size: sz }) + "\n"
    )
  } catch {
    // missing file etc. — bridge behaved the same (OSError → skip)
  }
}

/**
 * Trust signal spill: RiskAssessor.record_outcome for fast-path reads.
 * The bridge drains this inside pre_check (piggyback, no new spawn);
 * capped so a write-only drought can never grow heap or disk.
 */
function tier1TrustSpill(repoRoot: string, tool: string, file: string, outcome: string): void {
  try {
    const dir = join(repoRoot, "state", "rsi")
    try {
      mkdirSync(dir, { recursive: true })
    } catch {
      // ignore
    }
    const spill = join(dir, "trust_spill.jsonl")
    const ok = outcome === "success" || outcome === "ok"
    appendFileSync(
      spill,
      JSON.stringify({ ts: new Date().toISOString(), tool, file, ok }) + "\n"
    )
    try {
      const st = statSync(spill)
      if (st.size > 200 * 1024) {
        const lines = readFileSync(spill, "utf-8").split("\n").filter(Boolean)
        writeFileSync(spill, lines.slice(-500).join("\n") + "\n")
      }
    } catch {
      // cap enforcement is best-effort
    }
  } catch {
    // trust is a soft signal — never break the tool for it
  }
}

// ─── Plugin ───────────────────────────────────────────────────────────────────

const ToolIntegration: Plugin = async ({ directory }) => {
  // P1 duration_ms (§11.7): before-hook timestamps by callID; the
  // after-hook computes the delta. Bounded (clear at 500) — a blocked
  // before-hook never reaches after, entries would leak otherwise.
  const callStart = new Map<string, number>()
  // LOG-FEEDBACK-LOOP (transient, 2026-10-12): in-process real-time
  // loop/error tracker. No spawn, no file IO — the before-hook is the
  // hot path (reads skip python by design). Tracks recent tool names +
  // recent error outcomes in memory; throws on extreme patterns so the
  // signal reaches the model DURING the action loop, not at session.idle.
  // Thresholds are deliberately high (12 same-tool / 60s, 50% errors /
  // last 20) to avoid false positives on legitimate batches.
  const recentTools: { tool: string; t: number }[] = []
  const recentOutcomes: { ok: boolean; t: number }[] = []
  let lastLoopWarn = 0
  return {
    // ═══════════════════════════════════════════════════════════════════════════
    // BEFORE: Pre-check every tool call
    // ═══════════════════════════════════════════════════════════════════════════
    // CONTRACT (verified 2026-09-10, KEY-DUMP experiment):
    // tool.execute.before receives ONLY {tool, sessionID, callID} —
    // NO args (no file, no command, no content). Consequence:
    // pre-check / risk / stash / content-validator evaluate BLIND here
    // (they activate fully if a future runtime populates args — proven
    // via direct CLI). THE enforcement layer is tool.execute.after
    // (args present: quarantine + throw, proven live twice).
    "tool.execute.before": async (input: any, output: any) => {
      const tool = input.tool || "unknown"
      // P0 session attribution (§11.7): belt+suspenders with
      // session-lifecycle (env is process-global → all emitters + spawned
      // children see it; this covers resumed/direct tool calls).
      if (input.sessionID) process.env.VOS_SESSION_ID = String(input.sessionID)
      if (input.callID) {
        if (callStart.size > 500) callStart.clear()
        callStart.set(input.callID, Date.now())
      }

      // LOG-FEEDBACK-LOOP transient check (in-process, no IO):
      // push + prune, then evaluate extreme patterns only.
      // LAYER CONTRACT (R3, 2026-10-12): L1 lives in stub_predicates
      // (repeat_block=3 on exact-key redundancy, evaluated later in this
      // hook via pre_check). THIS breaker is the coarse backstop:
      // same-tool bursts with varied args (L1 blind spot) + error storms.
      // First throw wins per call — no double-punish possible. Breaker
      // fires log via logActivation with LOOP-BREAKER / ERROR-BURST
      // markers, which R2's rsi_fires log-scan counts (no extra wiring).
      try {
        const now = Date.now()
        recentTools.push({ tool, t: now })
        while (recentTools.length > 0 && now - recentTools[0].t > 120000) recentTools.shift()
        while (recentOutcomes.length > 0 && now - recentOutcomes[0].t > 120000) recentOutcomes.shift()
        // 1. Same-tool burst: >=12 same tool in 60s
        const cutoff = now - 60000
        let sameCount = 0
        for (let i = recentTools.length - 1; i >= 0; i--) {
          if (recentTools[i].t < cutoff) break
          if (recentTools[i].tool === tool) sameCount++
        }
        if (sameCount >= 12 && now - lastLoopWarn > 60000) {
          lastLoopWarn = now
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.before",
            `LOOP-BREAKER: '${tool}' called ${sameCount}x in 60s — pausing. Review recent output for repetition before retrying.`,
            "error",
          )
          throw new Error(
            `LOOP-BREAKER (transient): '${tool}' invoked ${sameCount} times in the last 60s. ` +
            `This usually means repetition. STOP, re-read your last tool results and the task, ` +
            `then proceed differently. If the repetition is intentional (batch), wait 60s and retry.`,
          )
        }
        // 2. Error burst: >=50% errors in last 20 outcomes
        if (recentOutcomes.length >= 20) {
          const last20 = recentOutcomes.slice(-20)
          const errs = last20.filter((o) => !o.ok).length
          if (errs >= 10 && now - lastLoopWarn > 60000) {
            lastLoopWarn = now
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `ERROR-BURST: ${errs}/20 recent tool calls failed — pausing for reassessment.`,
              "error",
            )
            throw new Error(
              `ERROR-BURST (transient): ${errs} of your last 20 tool calls failed. ` +
              `STOP and diagnose before continuing — check logs/agent_plugin.jsonl tail for the error pattern.`,
            )
          }
        }
      } catch (e) {
        // The loop-breaker itself must never break legitimate work:
        // rethrow only our own breaker errors, swallow internal failures.
        if (e instanceof Error && (e.message.startsWith("LOOP-BREAKER") || e.message.startsWith("ERROR-BURST"))) throw e
      }

      // MCP state-changing verbs (S5 audit 2026-09-11): focus_mark/close
      // and journal_mark write current_focus.json / state_journal.db
      // through MCP tool names OUTSIDE MANDATORY_TOOLS. They enter the
      // full pipeline (pre-check + risk + block) like local writers.
      // Query/verify/diff/history verbs stay advisory (logged, not gated).
      const MCP_STATE_CHANGING = ["focus_mark", "focus_close", "journal_mark",
        "schema_evo_snapshot", "schema_snapshot"]
      const isMcpStateChanging = MCP_STATE_CHANGING.some((v) => tool.includes(v))
      const isStateChanging = STATE_CHANGING_TOOLS.has(tool) || isMcpStateChanging

      // Tier1 fast-path: reads skip the blind before-hook (no args by
      // contract, so no file verdict is possible here). Security for
      // reads is enforced in AFTER, where args exist.
      if (TIER1_READ.has(tool)) return

      // Only process tools in our mandatory set (+ MCP writers above)
      if (!MANDATORY_TOOLS.has(tool) && !isMcpStateChanging) return

      const filePath =
        input.args?.file_path ?? input.args?.filePath ?? ""
      const command = input.args?.command ?? ""
      const basename = filePath ? filePath.split("/").pop() : ""

      // HOOK-FAILOPEN closure: snapshot .vsm content BEFORE write/edit so
      // a blocking gate can restore it afterwards. Best-effort: a stash
      // failure must never block the write itself (the gate decides that).
      if ((tool === "write" || tool === "edit") && filePath.endsWith(".vsm")) {
        try {
          await callBridge("vsm-stash", [filePath])
        } catch {
          // stash is advisory infrastructure — proceed to evaluation
        }
      }

      // True prevention (S5 2026-09-10): validate full .vsm content BEFORE
      // it lands. Only R18 version breaches throw here (policy breach);
      // grammar stays for the after-hook (mid-flight docs are legitimate).
      // A verifier outage never blocks (fail-open: after-gate still covers).
      const incoming = (input.args as any)?.content
      if (tool === "write" && filePath.endsWith(".vsm") && typeof incoming === "string" && incoming.length > 0) {
        try {
          const v: any = await callBridge("vsm-check-content", [JSON.stringify({ content: incoming.slice(0, 100000) })])
          const errs: string[] = Array.isArray(v?.errors) ? v.errors.map(String) : []
          if (v && v.valid === false && errs.some((e) => e.includes("Wrong version"))) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `PRE-BLOCKED: ${basename} carries a non-canonical version — generate via vsm_kernel.new_doc (vsm-1.2.1)`,
              "error"
            )
            throw new Error(
              `Pipeline block (pre-write): R18 version breach in incoming content. ` +
              `Generate parametrically (vsm_kernel.new_doc) at vsm-1.2.1. ` +
              `Errors: ${errs.join("; ").slice(0, 300)}`
            )
          }
        } catch (e: any) {
          if (e?.message?.startsWith("Pipeline block")) throw e
          // verifier degraded — proceed, after-gate + quarantine cover it
        }
      }

      // Build context for socratic evaluation
      const context = {
        tool,
        file: filePath,
        basename,
        command: command.slice(0, 200), // truncate long commands
        is_state_changing: isStateChanging,
        is_read_only: READ_ONLY_TOOLS.has(tool) && !isMcpStateChanging,
        timestamp: new Date().toISOString(),
      }

      // ── Tier2 multiplex (RAM-LIFECYCLE, alternativa 2) ──────────────────
      // Whole before-phase in ONE python spawn (stash + content-check +
      // pre-check + risk + rsi + their log-actions, all inside the
      // bridge). Enforcement below is VERBATIM the legacy sequence
      // (same messages, same order) — only the transport changed.
      // Multiplex degraded (null/error) → fall through to the legacy
      // per-command sequence, which stays byte-intact as fallback.
      // (SECURITY_SOURCES hoisted here so both paths share it.)
      const SECURITY_SOURCES = ["path_forbidden", "action_forbidden", "policy_locked", "write_scope_ok"]
      if (isStateChanging || isMcpStateChanging) {
        let mp: any = null
        try {
          const mpArgs =
            (tool === "write" && filePath.endsWith(".vsm") && typeof incoming === "string" && incoming.length > 0)
              ? [JSON.stringify(context), JSON.stringify({ content: incoming.slice(0, 100000) })]
              : [JSON.stringify(context)]
          mp = await callBridge("pipeline-before", mpArgs)
        } catch {
          mp = null
        }
        if (mp && mp.preCheck && !mp.error) {
          const vMp: any = mp.content_check ?? null
          const errsMp: string[] = Array.isArray(vMp?.errors) ? vMp.errors.map(String) : []
          if (vMp && vMp.valid === false && errsMp.some((e) => e.includes("Wrong version"))) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `PRE-BLOCKED: ${basename} carries a non-canonical version — generate via vsm_kernel.new_doc (vsm-1.2.1)`,
              "error"
            )
            throw new Error(
              `Pipeline block (pre-write): R18 version breach in incoming content. ` +
              `Generate parametrically (vsm_kernel.new_doc) at vsm-1.2.1. ` +
              `Errors: ${errsMp.join("; ").slice(0, 300)}`
            )
          }
          const preCheckMp = mp.preCheck
          const riskMp: any = ("risk" in mp) ? mp.risk : null
          // R2-REDUCIR: mode min carries no risk leg (blind bare-tool
          // risk never exceeded MEDIUM; the rate throttle lives in
          // preCheck.socratic via no_state_conflict). Skip whole section.
          if (mp.mode !== "min") {
          if (!riskMp) {
            const safeModeExists = isSafeMode()
            if (safeModeExists) {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `SAFE MODE: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 200)}. ` +
                `Proceeding under user-privileged safe mode.`,
                "warn"
              )
            } else {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `BLOCKED: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 200)}. ` +
                `Fail-safe: cannot verify safety without bridge. ` +
                `Enable safe mode: touch ~/.opencode/.safe_mode`,
                "error"
              )
              throw new Error(
                `BRIDGE UNAVAILABLE: risk-assess returned null for ${tool}. ` +
                `Fail-safe policy: action blocked when safety verification is unavailable. ` +
                `Enable safe mode: touch ~/.opencode/.safe_mode`
              )
            }
          } else {
            const riskLevelMp = riskMp.risk_level || "LOW"
            const riskScoreMp = riskMp.risk_score || 0
            if (riskLevelMp === "CRITICAL" || riskLevelMp === "BLOCKED") {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `BLOCKED by risk assessment: ${tool} on ${basename || command.slice(0, 200)} — ` +
                `risk=${riskLevelMp} score=${riskScoreMp}. ` +
                `Reason: ${riskMp.summary}. ` +
                `Requires S5 (rmw3) explicit approval.`,
                "error"
              )
              throw new Error(
                `RISK BLOCK: ${riskLevelMp} risk (score=${riskScoreMp}). ` +
                `${riskMp.summary}. ` +
                `This action requires explicit S5 (rmw3) approval. ` +
                `Factors: ${riskMp.factors?.map((f: any) => `${f.name}: ${f.reason}`).join('; ')}`
              )
            }
            if (riskLevelMp === "HIGH") {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `BLOCKED by HIGH risk: ${tool} on ${basename || command.slice(0, 200)} — ` +
                `risk=${riskLevelMp} score=${riskScoreMp}. ` +
                `${riskMp.summary}. ` +
                `Requires S5 (rmw3) explicit approval.`,
                "error"
              )
              throw new Error(
                `RISK BLOCK: HIGH risk (score=${riskScoreMp}). ` +
                `${riskMp.summary}. ` +
                `This action requires explicit S5 (rmw3) approval. ` +
                `Factors: ${riskMp.factors?.map((f: any) => `${f.name}: ${f.reason}`).join('; ')}`
              )
            }
          }
          } // end R2-REDUCIR risk guard (min mode skips)
          const rsiMp: any = mp.rsi ?? null
          if (rsiMp?.matches?.length > 0) {
            const falseCountMp = rsiMp.false_count || 0
            if (rsiMp.should_block) {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `BLOCKED by RSI learned patterns: ${tool} on ${basename || command.slice(0, 200)} — ` +
                `${falseCountMp} RSI predicates returned FALSE. ` +
                `Patterns: ${rsiMp.matches.map((m: any) => m.name).join(", ")}`,
                "error"
              )
              throw new Error(
                `RSI BLOCK: ${falseCountMp} learned predicates indicate this action is incorrect. ` +
                `Predicates: ${rsiMp.matches.map((m: any) => `${m.name}(${m.truth})`).join(", ")}. ` +
                `This pattern was learned from past failures.`
              )
            }
            if (rsiMp.should_warn) {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `RSI pattern warning: ${tool} on ${basename || command.slice(0, 200)} — ` +
                `1 predicate returned FALSE: ${rsiMp.matches[0]?.name}. ` +
                `Proceeding but logging for review.`,
                "warn"
              )
            }
          }
          const sourceMp = String(preCheckMp?.socratic?.source || "")
          const failedMp: string[] = Array.isArray((preCheckMp?.socratic as any)?.failed_predicates)
            ? (preCheckMp.socratic as any).failed_predicates.map(String)
            : []
          const isSecurityBlockMp = SECURITY_SOURCES.some((s) =>
            sourceMp.includes(s) || failedMp.some((f) => f.includes(s)))
          if (isSecurityBlockMp && preCheckMp?.socratic) {
            const truthMp = preCheckMp.socratic.truth
            if (truthMp === "FALSE" && preCheckMp.socratic.certified) {
              await logActivation(
                directory || process.cwd(),
                "tool-integration",
                "tool.execute.before",
                `BLOCKED: ${tool} on ${basename} — socratic certified FALSE`,
                "error"
              )
              throw new Error(
                `Pipeline block: socratic-engine certified this action as incorrect. ` +
                `Detail: ${preCheckMp.socratic.source || "no detail"}`
              )
            }
          }
          return
        }
        // Multiplex degraded → legacy per-command sequence below.
      }

      // Pre-check: evaluate with socratic
      const preCheck = await callBridge(
        "pre-check",
        [JSON.stringify(context)]
      )

      // RISK ASSESSMENT: evaluate risk before execution
      let riskResult: any = null
      if (isStateChanging) {
        riskResult = await callBridge("risk-assess", [
          tool, filePath, command.slice(0, 200),
        ])

        // P1 FIX: Bridge failure → fail SAFE (block), not open
        if (!riskResult) {
          // SAFE MODE: user-privileged bypass (flag file required)
          const safeModeExists = isSafeMode()
          if (safeModeExists) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `SAFE MODE: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 200)}. ` +
              `Proceeding under user-privileged safe mode.`,
              "warn"
            )
          } else {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `BLOCKED: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 200)}. ` +
              `Fail-safe: cannot verify safety without bridge. ` +
              `Enable safe mode: touch ~/.opencode/.safe_mode`,
              "error"
            )
            throw new Error(
              `BRIDGE UNAVAILABLE: risk-assess returned null for ${tool}. ` +
              `Fail-safe policy: action blocked when safety verification is unavailable. ` +
              `Enable safe mode: touch ~/.opencode/.safe_mode`
            )
          }
        }

        if (riskResult) {
          const riskLevel = riskResult.risk_level || "LOW"
          const riskScore = riskResult.risk_score || 0
          const recommendation = riskResult.recommendation || "proceed"

          // Log the risk assessment
          await callBridge("log-action", [
            "before",
            tool,
            filePath || "(no file)",
            `risk:${riskLevel}`,
            JSON.stringify({
              risk_score: riskScore,
              risk_level: riskLevel,
              confidence: riskResult.confidence,
              recommendation,
              summary: riskResult.summary,
            }),
          ])

          // BLOCK on CRITICAL or BLOCKED risk
          if (riskLevel === "CRITICAL" || riskLevel === "BLOCKED") {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `BLOCKED by risk assessment: ${tool} on ${basename || command.slice(0, 200)} — ` +
              `risk=${riskLevel} score=${riskScore}. ` +
              `Reason: ${riskResult.summary}. ` +
              `Requires S5 (rmw3) explicit approval.`,
              "error"
            )
            throw new Error(
              `RISK BLOCK: ${riskLevel} risk (score=${riskScore}). ` +
              `${riskResult.summary}. ` +
              `This action requires explicit S5 (rmw3) approval. ` +
              `Factors: ${riskResult.factors?.map((f: any) => `${f.name}: ${f.reason}`).join('; ')}`
            )
          }

          // P2 FIX: HIGH risk → block (requires explicit S5 approval)
          if (riskLevel === "HIGH") {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `BLOCKED by HIGH risk: ${tool} on ${basename || command.slice(0, 200)} — ` +
              `risk=${riskLevel} score=${riskScore}. ` +
              `${riskResult.summary}. ` +
              `Requires S5 (rmw3) explicit approval.`,
              "error"
            )
            throw new Error(
              `RISK BLOCK: HIGH risk (score=${riskScore}). ` +
              `${riskResult.summary}. ` +
              `This action requires explicit S5 (rmw3) approval. ` +
              `Factors: ${riskResult.factors?.map((f: any) => `${f.name}: ${f.reason}`).join('; ')}`
            )
          }
        }
      }

      // ─── RSI DYNAMIC EVALUATION: check learned patterns ────────────────
      // After risk assessment, consult RSI-generated predicates for
      // additional context. This is the DYNAMIC component: predicates
      // generated from past failures are evaluated against current action.
      let rsiResult: any = null
      if (isStateChanging) {
        rsiResult = await callBridge("rsi-evaluate", [
          tool, filePath || "", command.slice(0, 200),
        ])

        if (rsiResult?.matches?.length > 0) {
          const falseCount = rsiResult.false_count || 0

          // BLOCK on multiple RSI failures (learned pattern says this is wrong)
          if (rsiResult.should_block) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `BLOCKED by RSI learned patterns: ${tool} on ${basename || command.slice(0, 200)} — ` +
              `${falseCount} RSI predicates returned FALSE. ` +
              `Patterns: ${rsiResult.matches.map((m: any) => m.name).join(", ")}`,
              "error"
            )
            throw new Error(
              `RSI BLOCK: ${falseCount} learned predicates indicate this action is incorrect. ` +
              `Predicates: ${rsiResult.matches.map((m: any) => `${m.name}(${m.truth})`).join(", ")}. ` +
              `This pattern was learned from past failures.`
            )
          }

          // WARN on single RSI failure
          if (rsiResult.should_warn) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `RSI pattern warning: ${tool} on ${basename || command.slice(0, 200)} — ` +
              `1 predicate returned FALSE: ${rsiResult.matches[0]?.name}. ` +
              `Proceeding but logging for review.`,
              "warn"
            )
          }

          // Log RSI evaluation
          await callBridge("log-action", [
            "before",
            tool,
            filePath || "(no file)",
            `rsi:${falseCount > 0 ? "match" : "clear"}`,
            JSON.stringify({
              predicates_evaluated: rsiResult.predicates_evaluated,
              matches: rsiResult.matches,
              should_block: rsiResult.should_block,
              should_warn: rsiResult.should_warn,
            }),
          ])
        }
      }

      if (preCheck?.ok) {
        // Log the pre-check
        await callBridge("log-action", [
          "before",
          tool,
          filePath || "(no file)",
          "advisory",
          JSON.stringify(preCheck.socratic || {}),
        ])
      }

      // For state-changing tools, check if action is appropriate.
      // Security predicates ALSO block read-only tools (S5 2026-09-09):
      // a certified FALSE from path_forbidden/action_forbidden stops
      // exfiltration over read/glob/grep. All other predicates stay
      // advisory on reads (no legitimate-read breakage).
      // SECURITY_SOURCES is hoisted at the multiplex block (shared).
      const source = String(preCheck?.socratic?.source || "")
      // The AND verdict's source is "op:AND" — the bridge attributes the
      // real cause in socratic.failed_predicates (raw-engine re-eval).
      const failed: string[] = Array.isArray((preCheck?.socratic as any)?.failed_predicates)
        ? (preCheck.socratic as any).failed_predicates.map(String)
        : []
      const isSecurityBlock = SECURITY_SOURCES.some((s) =>
        source.includes(s) || failed.some((f) => f.includes(s)))
      if ((isStateChanging || isSecurityBlock) && preCheck?.socratic) {
        const truth = preCheck.socratic.truth
        // Block only on CRITICAL violations (truth=FALSE + certified)
        if (truth === "FALSE" && preCheck.socratic.certified) {
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.before",
            `BLOCKED: ${tool} on ${basename} — socratic certified FALSE`,
            "error"
          )
          throw new Error(
            `Pipeline block: socratic-engine certified this action as incorrect. ` +
            `Detail: ${preCheck.socratic.source || "no detail"}`
          )
        }
      }
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // AFTER: Record every tool execution
    // ═══════════════════════════════════════════════════════════════════════════
    "tool.execute.after": async (input: any, output: any) => {
      const tool = input.tool || "unknown"
      // P0/P1 (§11.7): session attribution + duration for this call.
      if (input.sessionID) process.env.VOS_SESSION_ID = String(input.sessionID)
      const _t0 = input.callID ? callStart.get(input.callID) : undefined
      const durMs = _t0 !== undefined ? Date.now() - _t0 : undefined
      if (input.callID) callStart.delete(input.callID)
      // LOG-FEEDBACK-LOOP: feed outcome into in-process tracker (no IO).
      try {
        recentOutcomes.push({ ok: !output?.error, t: Date.now() })
        if (recentOutcomes.length > 200) recentOutcomes.splice(0, recentOutcomes.length - 200)
      } catch { /* tracker is advisory */ }
      // P1 detail: error text was previously dropped on every after-line
      // (24% empty details) — surface it, bounded to one line.
      const outDetail = output?.error
        ? String(output.error).slice(0, 300)
        : undefined
      const durBag = durMs !== undefined
        ? { durationMs: durMs, success: !output?.error }
        : undefined

      // Audit completeness (S5 audit 2026-09-11): EVERY tool gets one
      // log line, even outside the pipeline (MCP queries, exotic tools).
      // Cheap logActivation only — no bridge, no eval. No more blind spots.
      // MCP writers rejoin the full pipeline below (record + learn).
      const _MCP_W = ["focus_mark", "focus_close", "journal_mark",
        "schema_evo_snapshot", "schema_snapshot"];
      const _isMcpWriter = _MCP_W.some((v) => tool.includes(v));
      if (!MANDATORY_TOOLS.has(tool) && !_isMcpWriter) {
        try {
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.after",
            `tool: ${tool} (observed, outside pipeline)`,
            output?.error ? "error" : "ok",
            outDetail, undefined, durBag);
        } catch {
          // logging must never break the pipeline
        }
        return
      }

      const filePath =
        input.args?.file_path ?? input.args?.filePath ?? ""
      const command = input.args?.command ?? ""
      const basename = filePath ? filePath.split("/").pop() : ""
      const hasError = !!output?.error
      const outcome = hasError ? "failure" : "success"

      // G-13 move-watch (S2 instrumentation 2026-10-03): a previous session
      // saw scripts/vsl/classifier/*.py land in scripts/vsl/tools/ with no
      // cause found. Gap-resolver cannot be it (code-classification dirs =
      // .opencode/plugins + scripts/state only, GAP_RESOLVER_AUTO unset);
      // script-classify only suggests. Capturing WHO ran a move here turns
      // the next occurrence from "mystery" into a greppable log line.
      if (tool === "bash" && /(^|[\s;&|])mv\s+|git\s+mv\s+/.test(command)) {
        try {
          await logActivation(
            directory || process.cwd(),
            "fs-move-watch",
            "tool.execute.after",
            `MOVE ${outcome}: ${command.slice(0, 180)}`,
            hasError ? "error" : "ok",
            outDetail, undefined, durBag
          )
        } catch {
          // watch must never break the pipeline
        }
      }

      // Tier1 fast-path: clear reads skip python. Hit (forbidden path)
      // or error → full pipeline below (certified verdict + audit).
      // TS never blocks by itself; a hit just rejoins the full path.
      if (TIER1_READ.has(tool) && !hasError) {
        const repoRoot = directory || process.cwd()
        let hit: string | null = null
        if (filePath) {
          const deny = loadTier1Policy(repoRoot)
          hit = deny ? tier1HitsForbidden(filePath, deny) : "policy-unreadable"
        }
        if (!hit) {
          if (tool === "read" || tool === "glob") tier1Telemetry(repoRoot, filePath)
          if (filePath) tier1TrustSpill(repoRoot, tool, filePath, outcome)
          try {
            await logActivation(
              repoRoot,
              "tool-integration",
              "tool.execute.after",
              `tool: ${tool} ${basename || "(no file)"} (tier1-fast)`,
              "ok", outDetail, undefined, durBag);
          } catch {
            // logging must never break the pipeline
          }
          return
        }
        try {
          await logActivation(
            repoRoot,
            "tool-integration",
            "tool.execute.after",
            `tier1-rejoin: ${tool} ${basename || "(no file)"} hit=${hit} → full pipeline`,
            "warn", outDetail, undefined, durBag);
        } catch {
          // logging must never break the pipeline
        }
      }

      // ── Tier2 multiplex (RAM-LIFECYCLE, alternativa 2) ──────────────────
      // Whole after-phase in ONE python spawn (record + learn + .vsm
      // audit/verify/rsi/diagnose + code route/verify, inside the
      // bridge). Activation lines below mirror the legacy texts.
      // Degraded → fall through to the legacy sequence (byte-intact).
      // (after-hook scope: recompute tier membership locally.)
      const isMcpWriterAfter = ["focus_mark", "focus_close", "journal_mark",
        "schema_evo_snapshot", "schema_snapshot"].some((v) => tool.includes(v))
      const isStateChangingAfter = STATE_CHANGING_TOOLS.has(tool) || isMcpWriterAfter
      if (isStateChangingAfter) {
        let mpAfter: any = null
        try {
          const afterCtx = JSON.stringify({
            tool,
            file: filePath,
            command: command.slice(0, 200),
            outcome,
            timestamp: new Date().toISOString(),
          })
          const flags = JSON.stringify({
            isVsmWrite: filePath.endsWith(".vsm") && (tool === "write" || tool === "edit"),
            isBashFailure: tool === "bash" && outcome === "failure",
            isCodeWrite: tool === "write" && (filePath.endsWith(".py") || filePath.endsWith(".ts")),
          })
          const rawAfter: any = await callBridge("pipeline-after", [
            tool,
            filePath || "(no file)",
            outcome,
            afterCtx,
            flags,
          ])
          if (rawAfter && rawAfter.record && !rawAfter.error) mpAfter = rawAfter
        } catch {
          mpAfter = null
        }
        if (mpAfter) {
          const rsiAfter = mpAfter.rsiAfter ?? null
          if (rsiAfter && (rsiAfter.should_block || (rsiAfter as any).truth === "FALSE")) {
            const diagnosis = mpAfter.diagnosis ?? null
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.after",
              `rsi-diagnosis: ${diagnosis?.diagnosis || "unknown"}`,
              "warning"
            )
          }
          const routeMp = mpAfter.route ?? null
          if (routeMp?.execution?.registered_in) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.after",
              `route: ${basename} registered in ${routeMp.execution.registered_in}`,
              "ok"
            )
          } else if (routeMp?.execution?.action === "moved") {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.after",
              `route: moved ${basename} → ${routeMp.execution.dest_path}`,
              "ok"
            )
          }
          const tagMp = filePath.endsWith(".vsm") ? "vsm" : "tool"
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.after",
            `${tagMp}: ${tool} ${basename || command.slice(0, 200) || "(no file)"}`,
            hasError ? "error" : "ok",
            outDetail, undefined, durBag
          )
          return
        }
        // Multiplex degraded → legacy per-command sequence below.
      }

      // Record the action
      const context = JSON.stringify({
        tool,
        file: filePath,
        command: command.slice(0, 200),
        outcome,
        timestamp: new Date().toISOString(),
      })

      await callBridge("record-action", [
        tool,
        filePath || "(no file)",
        outcome,
        context,
      ])

      // Record learning patterns: .vsm writes + bash failures
      if (
        (filePath.endsWith(".vsm") && (tool === "write" || tool === "edit")) ||
        (tool === "bash" && outcome === "failure")
      ) {
        await callBridge("learn-from-action", [
          tool,
          filePath,
          outcome,
        ])
      }

      // NEW: Auto-audit when .vsm files are written/edited
      // (audit-proposal now runs the canonical validator; verify-refs
      // retired — module gone, result was ignored; migration covered
      // by gates, not the loop.)
      if (filePath.endsWith(".vsm") && (tool === "write" || tool === "edit")) {
        // Run audit_proposal on the written file
        await callBridge("audit-proposal", [filePath])
        
        // NEW: Evaluate RSI predicates for .vsm writes
        const rsiEval = await callBridge("rsi-evaluate", [context])
        if (rsiEval?.evaluation?.truth === "FALSE") {
          // Diagnose why RSI evaluation failed
          const diagnosis = await callBridge("socratic-diagnose", [JSON.stringify(rsiEval.evaluation)])
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.after",
            `rsi-diagnosis: ${diagnosis?.diagnosis || "unknown"}`,
            "warning"
          )
        }
      }

      // NEW: Auto-route when new scripts/plugins are created
      // (post-register retired — module gone; no "verified" claims.
      // Registry coverage: plugin-location-valid gate + handler_states
      // test. Registration itself is still logged.)
      if (tool === "write" && (filePath.endsWith(".py") || filePath.endsWith(".ts"))) {
        const routeResult = await callBridge("route-component", [filePath, "--execute"])
        
        // If registered, record it (verification lives in gates now)
        if (routeResult?.execution?.registered_in) {
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.after",
            `route: ${basename} registered in ${routeResult.execution.registered_in}`,
            "ok"
          )
        } else if (routeResult?.execution?.action === "moved") {
          await logActivation(
            directory || process.cwd(),
            "tool-integration",
            "tool.execute.after",
            `route: moved ${basename} → ${routeResult.execution.dest_path}`,
            "ok"
          )
        }
      }

      // Log activation
      const tag = filePath.endsWith(".vsm") ? "vsm" : "tool"
      await logActivation(
        directory || process.cwd(),
        "tool-integration",
        "tool.execute.after",
        `${tag}: ${tool} ${basename || command.slice(0, 200) || "(no file)"}`,
        hasError ? "error" : "ok",
        outDetail, undefined, durBag
      )
    },
  }
}

export default ToolIntegration
