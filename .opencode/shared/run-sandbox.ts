/**
 * run-sandbox.ts — confined subprocess runner for VSF opencode plugins.
 *
 * NEXT-3 (sandboxing dynamic evaluations), thin slice: every plugin
 * spawn goes through ONE gate that enforces, structurally (not by
 * convention):
 *   1. execFile ONLY — no shell, ever. Template-string commands cannot
 *      exist here (argv array is the only input shape).
 *   2. Path confinement — the executable is a bare name (PATH lookup)
 *      or an absolute path INSIDE repoRoot. Relative paths with slashes
 *      and absolute paths outside the root fail CLOSED.
 *   3. cwd confinement — defaults to repoRoot, must stay inside it.
 *   4. Env allowlist — the child gets PATH/HOME/lang/TMPDIR/VOS_* plus
 *      explicit extras. Tokens and keys in process.env do NOT cross.
 *   5. Bounded — timeout + maxBuffer on every call.
 *   6. Audited — one cheap log line per exec (who/what/limits/result).
 *
 * Never throws for confinement rejections: returns {ok:false} so the
 * caller degrades (fail-closed execution, fail-open pipeline — the
 * caller decides, this module only refuses to spawn).
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { isAbsolute, relative, resolve, sep } from "node:path"
import { logActivation } from "./log-activation"

const execFileP = promisify(execFile)

export interface SandboxOpts {
  /** Workspace root. Required: confinement anchor. */
  repoRoot: string
  /** Timeout ms (default 15000, bridge parity). */
  timeoutMs?: number
  /** Max stdout+stderr bytes (default 10MB, gap parity). */
  maxBufferBytes?: number
  /** Extra env vars for the child (merged over the allowlist). */
  extraEnv?: Record<string, string>
  /** Audit identity (default: sandbox.exec). */
  auditSource?: string
}

export interface SandboxResult {
  ok: boolean
  stdout: string
  stderr: string
  detail: string
}

const ENV_KEEP = new Set([
  "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
  "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE",
])

function scrubEnv(extra?: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of Object.keys(process.env)) {
    if (ENV_KEEP.has(k) || k.startsWith("VOS_")) {
      const v = process.env[k]
      if (typeof v === "string") out[k] = v
    }
  }
  if (extra) {
    for (const k of Object.keys(extra)) out[k] = extra[k]
  }
  return out
}

function insideRoot(root: string, target: string): boolean {
  const rel = relative(root, target)
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))
}

/**
 * Run argv confined. argv[0] = bare command (PATH) or absolute path
 * inside repoRoot. Returns ok:false (never throws) on confinement
 * rejection or spawn failure.
 */
export async function sandboxedExecFile(
  argv: string[],
  opts: SandboxOpts
): Promise<SandboxResult> {
  const repoRoot = resolve(opts.repoRoot)
  const tag = `exec ${(argv[0] ?? "?").split(sep).pop()}`
  const audit = async (result: string, detail: string) => {
    try {
      await logActivation(
        repoRoot, opts.auditSource ?? "sandbox",
        "sandbox.exec", `${tag} (cwd=root, ${opts.timeoutMs ?? 15000}ms)`,
        result, detail.slice(0, 200))
    } catch {
      // logging must never break the caller
    }
  }

  if (!argv.length || typeof argv[0] !== "string" || !argv[0]) {
    return { ok: false, stdout: "", stderr: "", detail: "empty argv" }
  }
  const bin = argv[0]
  if (bin.includes("/") || bin.includes("\\")) {
    // A path, not a bare name: must be absolute AND inside the root.
    if (!isAbsolute(bin) || !insideRoot(repoRoot, resolve(bin))) {
      await audit("error", `confined: binary outside root: ${bin.slice(0, 120)}`)
      return { ok: false, stdout: "", stderr: "", detail: "binary outside root" }
    }
    try {
      const { statSync } = await import("node:fs")
      if (!statSync(bin).isFile()) {
        return { ok: false, stdout: "", stderr: "", detail: "binary not a file" }
      }
    } catch {
      return { ok: false, stdout: "", stderr: "", detail: "binary unreadable" }
    }
  }
  const cwd = resolve(repoRoot)
  const timeout = opts.timeoutMs ?? 15000
  const maxBuffer = opts.maxBufferBytes ?? 10 * 1024 * 1024

  try {
    const { stdout, stderr } = await execFileP(bin, argv.slice(1), {
      cwd,
      timeout,
      maxBuffer,
      env: scrubEnv(opts.extraEnv),
    })
    await audit("ok", (stdout || "").slice(0, 200))
    return { ok: true, stdout: stdout ?? "", stderr: stderr ?? "", detail: "ok" }
  } catch (e: any) {
    const detail = `exit: ${(e?.message || String(e)).slice(0, 200)}`
    await audit("error", detail)
    return { ok: false, stdout: e?.stdout ?? "", stderr: e?.stderr ?? "", detail }
  }
}
