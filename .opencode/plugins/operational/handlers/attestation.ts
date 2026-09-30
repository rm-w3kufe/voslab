/**
 * attestation-handler.ts — handler for attestation checks.
 *
 * Runs: check_agent_log.py (agent log validation),
 *       check_binary_integrity.py (binary integrity).
 * Trigger: session.idle (periodic).
 */
import { existsSync } from "node:fs"
import { join } from "node:path"
import { runScript, type ScriptResult } from "../../../shared/run-script"
import type { Handler } from "../vsf-event-router"

export const attestationHandler: Handler = {
  id: "attestation",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ScriptResult[] = []

    // S5 decision 2026-09-30 (FND-AGENT-LOG-SCHEMA-DRIFT-01): the live
    // schema (ts/source/event_type/action/result) is canonical; the old
    // instrument/hook names were the pre-rename taxonomy. Declared sources
    // = activation_log.declared_sources in agent_instruments.vsm (the
    // organ→source mapping lives there). The validator reads current +
    // rotated logs, so idle-only sources count from retained history.
    const logPath = join(ctx.repoRoot, "logs/agent_plugin.jsonl")
    if (!existsSync(logPath)) {
      results.push({
        script: "scripts/state/attestation/check_agent_log.py",
        result: "skip",
        detail: "prereq missing: logs/agent_plugin.jsonl",
        durationMs: 0,
      })
    } else {
      const declared =
        "tool-integration rsi-cycle event-router GATE gap-resolution " +
        "vsl-check-on-write attestation session-hygiene " +
        "lifecycle-reporting hook-analytics scripts-automation " +
        "governance cyberfilter scenario-memory state-reconcile " +
        "tasks-maintenance core-scripts services shared learning-cycle"
      const r = await runScript(ctx.repoRoot,
        "scripts/state/attestation/check_agent_log.py",
        [logPath, declared])
      results.push(r)
    }

    // CC-2: check_binary_integrity reads /var/lib/vsf-state/state.db —
    // that db lives on n02, never on the agent host (FND-S1-HOST-ROLE-SPLIT).
    if (!existsSync("/var/lib/vsf-state/state.db")) {
      results.push({
        script: "scripts/state/attestation/check_binary_integrity.py",
        result: "skip",
        detail: "prereq missing: /var/lib/vsf-state/state.db (n02)",
        durationMs: 0,
      })
    } else {
      const r = await runScript(ctx.repoRoot, "scripts/state/attestation/check_binary_integrity.py")
      results.push(r)
    }

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    return {
      result: allOk ? "pass" : "fail",
      durationMs: Date.now() - start,
      detail: results.map((r) => `${r.script}: ${r.result}`).join("; "),
    }
  },
}
