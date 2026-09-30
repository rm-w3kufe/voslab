/**
 * run-script.ts — Shared script runner for handlers.
 *
 * Extracts the common runScript pattern used by all handlers
 * to avoid duplication and ensure consistent behavior.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"

const execFileP = promisify(execFile)

export interface ScriptResult {
  script: string
  result: string
  detail: string
  durationMs: number
}

/**
 * Run a script (Python or Bash) from the repo root.
 * Returns a standardized result object.
 */
export async function runScript(
  repoRoot: string,
  scriptPath: string,
  args: string[] = [],
): Promise<ScriptResult> {
  const start = Date.now()
  const full = join(repoRoot, scriptPath)
  if (!existsSync(full)) {
    return { script: scriptPath, result: "skip", detail: "not found", durationMs: 0 }
  }
  try {
    const cmd = scriptPath.endsWith(".py") ? "python3" : "bash"
    // CC-2 (CYCLE-CLOSE-001): repo modules live outside the script's own
    // dir (vslline → scripts/vsl/parser, vsf_socratic_engine →
    // scripts/vsl/classifier). Scripts were previously spawned with bare
    // env, so any cross-dir import died with ModuleNotFoundError.
    const pyPath = [
      join(repoRoot, "scripts/vsl/parser"),
      join(repoRoot, "scripts/vsl/classifier"),
      join(repoRoot, "system/kernel"),
      process.env.PYTHONPATH || "",
    ].filter(Boolean).join(":")
    const { stdout } = await execFileP(cmd, [full, ...args], {
      cwd: repoRoot,
      timeout: 30_000,
      env: { ...process.env, PYTHONPATH: pyPath },
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
