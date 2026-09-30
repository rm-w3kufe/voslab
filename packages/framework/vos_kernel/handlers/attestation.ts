/**
 * attestation-handler.ts — handler for attestation checks.
 *
 * Runs: check_agent_log.py (agent log validation),
 *       check_binary_integrity.py (binary integrity).
 * Trigger: session.idle (periodic).
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<{ script: string; result: string; detail: string; durationMs: number }> {
  const start = Date.now()
  const full = join(repoRoot, scriptPath)
  if (!existsSync(full)) {
    return { script: scriptPath, result: "skip", detail: "not found", durationMs: 0 }
  }
  try {
    const { stdout } = await execP(`python3 ${full} ${args.join(" ")}`, {
      cwd: repoRoot,
      timeout: 30_000,
      env: { ...process.env },
    })
    return {
      script: scriptPath,
      result: "ok",
      detail: stdout.trim().slice(0, 500),
      durationMs: Date.now() - start,
    }
  } catch (err: any) {
    return {
      script: scriptPath,
      result: "fail",
      detail: err.message?.slice(0, 300) || "unknown error",
      durationMs: Date.now() - start,
    }
  }
}

export const attestationHandler: Handler = {
  id: "attestation",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results = []

    // S5 decision 2026-09-30 (FND-AGENT-LOG-SCHEMA-DRIFT-01): live schema
    // canonical; declared sources = agent_instruments.vsm
    // activation_log.declared_sources. Validator reads rotations too.
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

    const r2 = await runScript(ctx.repoRoot,
      "scripts/state/attestation/check_binary_integrity.py")
    results.push(r2)

    const allOk = results.every((r) => r.result === "ok" || r.result === "skip")
    return {
      result: allOk ? "pass" : "fail",
      durationMs: Date.now() - start,
      detail: results.map((r) => `${r.script}: ${r.result}`).join("; "),
    }
  },
}
