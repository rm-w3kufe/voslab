/**
 * lifecycle-handler.ts — handler for lifecycle scripts.
 *
 * Runs: lifecycle-status.sh, lifecycle-report.sh, lifecycle-dashboard.sh,
 *       lifecycle-init.sh, lifecycle-promote.sh.
 * Trigger: session.idle (periodic reporting)
 *
 * Provides unified lifecycle visibility across all projects.
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

interface LifecycleResult {
  script: string
  result: string
  detail: string
  durationMs: number
}

async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<LifecycleResult> {
  const start = Date.now()
  const full = join(repoRoot, scriptPath)
  if (!existsSync(full)) {
    return { script: scriptPath, result: "skip", detail: "not found", durationMs: 0 }
  }
  try {
    const { stdout } = await execP(`bash ${full} ${args.join(" ")}`, {
      cwd: repoRoot,
      timeout: 30_000,
      env: { ...process.env },
    })
    return {
      script: scriptPath,
      result: "ok",
      detail: stdout.trim().slice(0, 1000),
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

export const lifecycleHandler: Handler = {
  id: "lifecycle-reporting",
  priority: 2,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: LifecycleResult[] = []

    // Run lifecycle scripts
    for (const script of [
      "scripts/state/lifecycle/lifecycle-status.sh",
      "scripts/state/lifecycle/lifecycle-status.sh --extended",
      "scripts/state/lifecycle/lifecycle-init.sh",
      "scripts/state/lifecycle/lifecycle-promote.sh",
    ]) {
      const args = script.includes("--extended") ? ["--extended"] : []
      const scriptPath = script.replace(" --extended", "")
      const r = await runScript(ctx.repoRoot, scriptPath, args)
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
