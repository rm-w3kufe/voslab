/**
 * services-handler.ts — handler for services scripts.
 *
 * Runs: service_watchdog.py, vsf-compact.py, vsf_cgroup_reallocate.py.
 * Trigger: session.idle (periodic, low frequency).
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

interface ServicesResult {
  script: string
  result: string
  detail: string
  durationMs: number
}

async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<ServicesResult> {
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

export const servicesHandler: Handler = {
  id: "services",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results: ServicesResult[] = []

    // Run each services script
    for (const script of [
      "scripts/state/services/service_watchdog.py",
      "scripts/state/services/vsf-compact.py",
      "scripts/state/services/vsf_cgroup_reallocate.py",
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
