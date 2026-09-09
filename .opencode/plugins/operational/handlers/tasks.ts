/**
 * tasks-handler.ts — handler for task maintenance scripts.
 *
 * Runs: tasks_archive.py, tasks_reconcile.py, tasks_validate.py,
 *       maintain.py, handoff_archive.py.
 * Trigger: session.idle (periodic).
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execFileP = promisify(execFile)

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
    const { stdout } = await execFileP("python3", [full, ...args], {
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

export const tasksHandler: Handler = {
  id: "tasks-maintenance",
  priority: 3,
  events: ["session.idle"],

  classify: async () => true,

  execute: async (ctx) => {
    const start = Date.now()
    const results = []

    for (const script of [
      "scripts/state/tasks/tasks_validate.py",
      "scripts/state/tasks/tasks_reconcile.py",
      "scripts/state/tasks/maintain.py",
      "scripts/state/tasks/tasks_archive.py",
      "scripts/state/tasks/handoff_archive.py",
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
