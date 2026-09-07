/**
 * core-handler.ts — handler for core system scripts.
 *
 * Runs: bootstrap.sh, onboard.sh, populate.sh, q.sh,
 *       rotate_nats_token.sh, state_attest.py, vsf-storage-probe.sh.
 * Trigger: session.idle (periodic, low frequency).
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

interface CoreResult {
  script: string
  result: string
  detail: string
  durationMs: number
}

async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<CoreResult> {
  const start = Date.now()
  const full = join(repoRoot, scriptPath)
  if (!existsSync(full)) {
    return { script: scriptPath, result: "skip", detail: "not found", durationMs: 0 }
  }
  try {
    const ext = scriptPath.endsWith(".py") ? "python3" : "bash"
    const { stdout } = await execP(`${ext} ${full} ${args.join(" ")}`, {
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

export const coreHandler: Handler = {
  id: "core-scripts",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: CoreResult[] = []

    // Run each core script
    for (const script of [
      "scripts/state/core/bootstrap.sh",
      "scripts/state/core/onboard.sh",
      "scripts/state/core/populate.sh",
      "scripts/state/core/q.sh",
      "scripts/state/core/rotate_nats_token.sh",
      "scripts/state/core/state_attest.py",
      "scripts/state/core/vsf-storage-probe.sh",
    ]) {
      const r = await runScript(ctx.repoRoot, script)
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
