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
import { logActivation } from "../../shared/log-activation"
import {
  callBridge,
  isSafeMode,
  MANDATORY_TOOLS,
  READ_ONLY_TOOLS,
  STATE_CHANGING_TOOLS,
} from "./tool-bridge"

// ─── Plugin ───────────────────────────────────────────────────────────────────

const ToolIntegration: Plugin = async ({ directory }) => {
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

      // MCP state-changing verbs (S5 audit 2026-09-11): focus_mark/close
      // and journal_mark write current_focus.json / state_journal.db
      // through MCP tool names OUTSIDE MANDATORY_TOOLS. They enter the
      // full pipeline (pre-check + risk + block) like local writers.
      // Query/verify/diff/history verbs stay advisory (logged, not gated).
      const MCP_STATE_CHANGING = ["focus_mark", "focus_close", "journal_mark",
        "schema_evo_snapshot", "schema_snapshot"]
      const isMcpStateChanging = MCP_STATE_CHANGING.some((v) => tool.includes(v))
      const isStateChanging = STATE_CHANGING_TOOLS.has(tool) || isMcpStateChanging

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

      // For state-changing tools, check if action is appropriate.
      // Security predicates ALSO block read-only tools (S5 2026-09-09):
      // a certified FALSE from path_forbidden/action_forbidden stops
      // exfiltration over read/glob/grep. All other predicates stay
      // advisory on reads (no legitimate-read breakage).
      const SECURITY_SOURCES = ["path_forbidden", "action_forbidden", "policy_locked", "write_scope_ok"]
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
            output?.error ? "error" : "ok");
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
  }
}

export default ToolIntegration
