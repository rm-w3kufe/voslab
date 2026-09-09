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
 *   session.created:
 *     1. Bootstrap context from state-canon
 *     2. Load recent patterns from vsf-rsi
 *
 *   session.idle:
 *     1. Generate session report
 *     2. Learning cycle check
 */
import type { Plugin } from "@opencode-ai/plugin"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation } from "../../shared/log-activation"

const execFileP = promisify(execFile)

const BRIDGE_PATH = join(
  process.env.HOME || ".",
  "vOSlab/.opencode/plugins/operational/tool_integration_bridge.py"
)

const SAFE_MODE_FLAG = join(
  process.env.HOME || ".",
  "vOSlab/.opencode/.safe_mode"
)

// ─── Bridge caller ─────────────────────────────────────────────────────────────

async function callBridge(
  command: string,
  args: string[] = []
): Promise<any | null> {
  if (!existsSync(BRIDGE_PATH)) return null
  try {
    const { stdout } = await execFileP(
      "python3",
      ["-W", "ignore", BRIDGE_PATH, command, ...args],
      { encoding: "utf-8", timeout: 15000 }
    )
    const raw = stdout.trim()
    console.error(`[bridge-debug] raw(${raw.length}): ${raw.slice(0, 500)}`)
    const j = raw.indexOf("{"); const ja = raw.indexOf("["); const s = j === -1 ? ja : ja === -1 ? j : Math.min(j, ja)
    return JSON.parse(s === -1 ? raw : raw.slice(s))
  } catch (e: any) {
    console.error(`[tool-integration] callBridge(${command}) error: ${e?.message || e}`)
    // Try to capture stderr from failed commands
    try {
      const errResult = await execFileP(
        "python3", ["-W", "ignore", BRIDGE_PATH, command, ...args],
        { encoding: "utf-8", timeout: 15000 }
      )
    } catch (e2: any) {
      if (e2?.stderr) console.error(`[bridge-stderr] ${e2.stderr.slice(0, 500)}`)
    }
    return null
  }
}

// ─── Tool classification ──────────────────────────────────────────────────────

/** Tools that MUST go through the pipeline */
const MANDATORY_TOOLS = new Set([
  "write", "edit", "bash", "task", "read", "glob", "grep",
])

/** Tools that are read-only (no state change) */
const READ_ONLY_TOOLS = new Set(["read", "glob", "grep", "list_mcp_resources"])

/** Tools that modify state (require full pipeline) */
const STATE_CHANGING_TOOLS = new Set(["write", "edit", "bash", "task"])

// ─── Plugin ───────────────────────────────────────────────────────────────────

const ToolIntegration: Plugin = async ({ directory }) => {
  return {
    // ═══════════════════════════════════════════════════════════════════════════
    // BEFORE: Pre-check every tool call
    // ═══════════════════════════════════════════════════════════════════════════
    "tool.execute.before": async (input: any, output: any) => {
      const tool = input.tool || "unknown"

      // Only process tools in our mandatory set
      if (!MANDATORY_TOOLS.has(tool)) return

      const filePath =
        input.args?.file_path ?? input.args?.filePath ?? ""
      const command = input.args?.command ?? ""
      const basename = filePath ? filePath.split("/").pop() : ""

      // Build context for socratic evaluation
      const context = {
        tool,
        file: filePath,
        basename,
        command: command.slice(0, 200), // truncate long commands
        is_state_changing: STATE_CHANGING_TOOLS.has(tool),
        is_read_only: READ_ONLY_TOOLS.has(tool),
        timestamp: new Date().toISOString(),
      }

      // Pre-check: evaluate with socratic
      const preCheck = await callBridge(
        "pre-check",
        [JSON.stringify(context)]
      )

      // RISK ASSESSMENT: evaluate risk before execution
      let riskResult: any = null
      if (STATE_CHANGING_TOOLS.has(tool)) {
        riskResult = await callBridge("risk-assess", [
          tool, filePath, command.slice(0, 200),
        ])

        // P1 FIX: Bridge failure → fail SAFE (block), not open
        if (!riskResult) {
          // SAFE MODE: user-privileged bypass (flag file required)
          const safeModeExists = existsSync(SAFE_MODE_FLAG)
          if (safeModeExists) {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `SAFE MODE: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 50)}. ` +
              `Proceeding under user-privileged safe mode.`,
              "warn"
            )
          } else {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.before",
              `BLOCKED: bridge unavailable for risk-assess on ${tool} ${basename || command.slice(0, 50)}. ` +
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
              `BLOCKED by risk assessment: ${tool} on ${basename || command.slice(0, 50)} — ` +
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
              `BLOCKED by HIGH risk: ${tool} on ${basename || command.slice(0, 50)} — ` +
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
      if (STATE_CHANGING_TOOLS.has(tool)) {
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
              `BLOCKED by RSI learned patterns: ${tool} on ${basename || command.slice(0, 50)} — ` +
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
              `RSI pattern warning: ${tool} on ${basename || command.slice(0, 50)} — ` +
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

      // For state-changing tools, check if action is appropriate
      if (STATE_CHANGING_TOOLS.has(tool) && preCheck?.socratic) {
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

      if (!MANDATORY_TOOLS.has(tool)) return

      const filePath =
        input.args?.file_path ?? input.args?.filePath ?? ""
      const command = input.args?.command ?? ""
      const basename = filePath ? filePath.split("/").pop() : ""
      const hasError = !!output?.error
      const outcome = hasError ? "failure" : "success"

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
      if (filePath.endsWith(".vsm") && (tool === "write" || tool === "edit")) {
        // Run audit_proposal on the written file
        await callBridge("audit-proposal", [filePath])
        
        // Check if file needs @var migration
        await callBridge("verify-refs", [filePath])
        
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
      if (tool === "write" && (filePath.endsWith(".py") || filePath.endsWith(".ts"))) {
        const routeResult = await callBridge("route-component", [filePath, "--execute"])
        
        // If registered, verify the registration is valid
        if (routeResult?.execution?.registered_in) {
          const registryType = routeResult.execution.registered_in.includes("tree") ? "tree" : "component"
          const verifyResult = await callBridge("post-register", [registryType, filePath])
          
          if (verifyResult?.action === "ok") {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.after",
              `route+verify: ${basename} registered and verified in ${routeResult.execution.registered_in}`,
              "ok"
            )
          } else if (verifyResult?.action === "reverted") {
            await logActivation(
              directory || process.cwd(),
              "tool-integration",
              "tool.execute.after",
              `route+verify: ${basename} FAILED verification, registration reverted — ${verifyResult.error}`,
              "error"
            )
          }
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
        `${tag}: ${tool} ${basename || command.slice(0, 50) || "(no file)"}`,
        hasError ? "error" : "ok"
      )
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // SESSION.CREATED: Bootstrap context
    // ═══════════════════════════════════════════════════════════════════════════
    "session.created": async (input: any) => {
      // Get session report from bridge (tasks + stats)
      const report = await callBridge("session-report", [])

      await logActivation(
        directory || process.cwd(),
        "tool-integration",
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
        "tool-integration",
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

export default ToolIntegration
