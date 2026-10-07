/**
 * lifecycle-autopilot.ts — project-agnostic lifecycle management (P22).
 *
 * S2 REGISTER (design base): docs/spec_revision/sandbox/plugin-s2-coordination-v1/
 * plugin_s2_coordination.vsm →
 *   "P22|lifecycle-autopilot.ts|session.created + session.idle +
 *    tool.execute.after|scope=autonomous lifecycle actions|
 *    autoridad=advisory|órgano=S2"
 *
 * D-28 REDESIGN (S5 2026-10-07 — REDISEÑAR contra P22/P23, no retirar):
 *   - Dispatch: session.* bus events arrive ONLY through the generic `event`
 *     hook (CC-1 finding — same fix as session-lifecycle 2026-10-07); the
 *     named `tool.execute.after` key fires for write tracking (P22's third
 *     event). The old `{name, hooks:[...]}` export was never dispatched AND
 *     never loaded (disconnected at FIX-C 2026-10-07).
 *   - Data model: project registry lives in OWN state file
 *     `state/lifecycle/projects.json` (object schema, gitignored runtime —
 *     .gitignore policy "state/: KNOWLEDGE tracked, RUNTIME excluded").
 *     The old implementation wrote object shape over `current_focus.json`,
 *     which is an ARRAY-format gate artifact (focus-format): the write was a
 *     silent no-op (JSON.stringify drops custom props on arrays) and would
 *     corrupt the array if it ever weren't. Autopilot never touches
 *     current_focus.json.
 *   - Authority advisory (P22): never throws; errors are logged and the
 *     cycle continues.
 *
 * How it works:
 *   1. session.created: scan workspace for project markers, auto-register new
 *   2. session.idle: re-scan, refresh git info, apply state transitions
 *   3. tool.execute.after: track significant writes into tracked projects
 *
 * Project detection: markers (.git, package.json, Cargo.toml, pyproject.toml,
 * go.mod, Makefile, …) in common workspace locations.
 *
 * State machine: draft → design → implementing → testing → consolidating →
 * stable → archived
 *
 * R16: policy declares, instrument interprets.
 * R9: unknown states are visible, never silent.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  statSync,
} from "node:fs"
import { join, basename } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"

const execFileP = promisify(execFile)

// ─── Config ──────────────────────────────────────────────────────────────────

// OWN state file (object schema) — NOT current_focus.json (array gate format).
const STATE_REL = join("state", "lifecycle", "projects.json")
const STATE_VERSION = 1

// Markers that identify a project directory
const PROJECT_MARKERS = [
  ".git",
  "package.json",
  "Cargo.toml",
  "pyproject.toml",
  "go.mod",
  "Makefile",
  "CMakeLists.txt",
  "build.gradle",
  "pom.xml",
  "*.sln", // .NET
]

// Directories to skip when scanning
const SKIP_DIRS = [
  "node_modules",
  ".git",
  "__pycache__",
  "target",
  "dist",
  "build",
  ".venv",
  "venv",
  ".tox",
  ".mypy_cache",
  ".pytest_cache",
]

const STATE_TRANSITIONS: Record<string, string[]> = {
  draft: ["design", "archived"],
  design: ["implementing", "draft", "archived"],
  implementing: ["testing", "design"],
  testing: ["consolidating", "implementing"],
  consolidating: ["stable", "testing"],
  stable: ["archived"],
  archived: [],
}

const STALE_THRESHOLD_DAYS = 7

// ─── State (own file — D-28) ────────────────────────────────────────────────

interface ProjectState {
  version: number
  updated: string
  projects: any[]
}

function statePath(repoRoot: string): string {
  return join(repoRoot, STATE_REL)
}

function loadState(repoRoot: string): ProjectState {
  try {
    const raw = JSON.parse(readFileSync(statePath(repoRoot), "utf-8"))
    if (raw && Array.isArray(raw.projects)) {
      return {
        version: raw.version ?? STATE_VERSION,
        updated: typeof raw.updated === "string" ? raw.updated : "",
        projects: raw.projects,
      }
    }
  } catch {
    // missing/corrupt state → start fresh (advisory, never throws)
  }
  return { version: STATE_VERSION, updated: "", projects: [] }
}

function saveState(repoRoot: string, state: ProjectState): void {
  try {
    state.updated = new Date().toISOString()
    mkdirSync(join(repoRoot, "state", "lifecycle"), { recursive: true })
    writeFileSync(statePath(repoRoot), JSON.stringify(state, null, 2) + "\n")
  } catch {
    // advisory: a failed state write never breaks the lifecycle cycle
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function daysSince(dateStr: string): number {
  if (!dateStr) return 999
  const d = new Date(dateStr)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
}

function hasMarker(dirPath: string): string | null {
  for (const marker of PROJECT_MARKERS) {
    if (marker.includes("*")) {
      // Glob pattern — check if any file matches
      const ext = marker.replace("*", "")
      try {
        const files = readdirSync(dirPath)
        if (files.some((f) => f.endsWith(ext))) return marker
      } catch {}
    } else if (existsSync(join(dirPath, marker))) {
      return marker
    }
  }
  return null
}

async function gitInfo(
  repoPath: string
): Promise<{ branch: string; lastCommit: string; recentCommits: number }> {
  try {
    const { stdout: branch } = await execFileP("git", ["branch", "--show-current"], {
      cwd: repoPath,
      timeout: 5_000,
    })
    const { stdout: lastCommit } = await execFileP("git", ["log", "-1", "--format=%ci"], {
      cwd: repoPath,
      timeout: 5_000,
    })
    const { stdout: recentCommits } = await execFileP(
      "git",
      ["log", "--oneline", "--since=7 days ago", "--no-merges"],
      { cwd: repoPath, timeout: 5_000 }
    )
    return {
      branch: branch.trim(),
      lastCommit: lastCommit.trim().split(" ")[0],
      recentCommits: parseInt(recentCommits.trim()) || 0,
    }
  } catch {
    return { branch: "unknown", lastCommit: "", recentCommits: 0 }
  }
}

// ─── Project scanning ────────────────────────────────────────────────────────

interface ScannedProject {
  id: string
  path: string
  name: string
  marker: string
}

async function scanForProjects(rootDir: string, maxDepth = 3): Promise<ScannedProject[]> {
  const projects: ScannedProject[] = []

  function scan(dir: string, depth: number) {
    if (depth > maxDepth) return
    try {
      const entries = readdirSync(dir)
      for (const entry of entries) {
        if (SKIP_DIRS.includes(entry)) continue
        const fullPath = join(dir, entry)
        try {
          if (!statSync(fullPath).isDirectory()) continue
        } catch {
          continue
        }

        const marker = hasMarker(fullPath)
        if (marker) {
          const id = basename(fullPath)
          projects.push({ id, path: fullPath, name: id, marker })
        } else {
          // Recurse into non-project dirs
          scan(fullPath, depth + 1)
        }
      }
    } catch {}
  }

  scan(rootDir, 0)
  return projects
}

// ─── State transition logic ──────────────────────────────────────────────────

interface TransitionResult {
  project: string
  from: string
  to: string
  reason: string
}

function detectTransitions(state: ProjectState): TransitionResult[] {
  const results: TransitionResult[] = []

  for (const project of state.projects) {
    const current = project.state
    const allowed = STATE_TRANSITIONS[current] || []
    if (allowed.length === 0) continue

    // Check staleness
    const updated = project.updated || project.created
    if (updated && daysSince(updated) > STALE_THRESHOLD_DAYS) {
      if (current === "implementing" || current === "testing") {
        results.push({
          project: project.id,
          from: current,
          to: current,
          reason: `STALE: ${daysSince(updated)} days since last update`,
        })
      }
    }

    // Check if all milestones done → auto-promote
    const milestones = project.milestones || []
    const allDone =
      milestones.length > 0 && milestones.every((m: any) => m.status === "done")
    if (allDone) {
      if (current === "testing" && allowed.includes("consolidating")) {
        results.push({
          project: project.id,
          from: "testing",
          to: "consolidating",
          reason: "All milestones done → auto-promote",
        })
      } else if (current === "consolidating" && allowed.includes("stable")) {
        results.push({
          project: project.id,
          from: "consolidating",
          to: "stable",
          reason: "All milestones done → auto-promote",
        })
      }
    }

    // Check if stable for > 30 days → suggest archive
    if (current === "stable" && updated && daysSince(updated) > 30) {
      results.push({
        project: project.id,
        from: "stable",
        to: "stable",
        reason: `SUGGEST: stable for ${daysSince(updated)} days — consider archiving`,
      })
    }
  }

  return results
}

function registerNew(state: ProjectState, scanned: ScannedProject): ScannedProject[] {
  const existing = new Set(state.projects.map((p: any) => p.id))
  const fresh = scanned.filter((p) => !existing.has(p.id))
  for (const proj of fresh) {
    state.projects.push({
      id: proj.id,
      name: proj.name,
      path: proj.path,
      state: "implementing", // has git = already implementing
      marker: proj.marker,
      branch: "unknown",
      created: new Date().toISOString().split("T")[0],
      updated: new Date().toISOString().split("T")[0],
      milestones: [],
      next_action: "Define milestones",
      auto_detected: true,
    })
  }
  return fresh
}

// ─── Handlers (advisory — never throw) ──────────────────────────────────────

async function createdHandler(directory: string): Promise<any> {
  try {
    const repoRoot = directory || process.cwd()
    const state = loadState(repoRoot)

    // 1. Scan for projects in workspace + auto-register new
    const scanned = await scanForProjects(repoRoot)
    const newProjects = registerNew(state, scanned)

    // Enrich branch info for the freshly registered
    for (const proj of newProjects) {
      const rec = state.projects.find((p: any) => p.id === proj.id)
      if (rec) {
        const info = await gitInfo(rec.path)
        rec.branch = info.branch
        if (info.lastCommit) rec.updated = info.lastCommit
      }
    }

    // 2. Inject status
    const active = state.projects.filter(
      (p: any) => p.state !== "archived" && p.state !== "stable"
    )

    if (active.length === 0 && newProjects.length === 0) {
      return { result: "skip", detail: "no active projects" }
    }

    const lines = active.map((p: any) => {
      const updated = p.updated || p.created
      const stale = updated && daysSince(updated) > STALE_THRESHOLD_DAYS
      const flag = stale ? " ⚠️ STALE" : ""
      const auto = p.auto_detected ? " 🔍" : ""
      return `  • ${p.id} [${p.state}]${flag}${auto} — ${p.next_action || "no next action"}`
    })
    if (newProjects.length > 0) {
      lines.unshift(`  📦 ${newProjects.length} new project(s) auto-detected`)
    }
    const msg = `📋 Projects (${active.length} active):\n${lines.join("\n")}`

    // 3. Persist to OWN state file (never current_focus.json — D-28)
    if (newProjects.length > 0) saveState(repoRoot, state)

    await logActivation(directory, "lifecycle-autopilot", "session.created", "scan", "ok", msg)
    return {
      result: "ok",
      detail: msg,
      summary: `${active.length} active, ${newProjects.length} new`,
    }
  } catch (e: any) {
    const msg = String(e?.message || e).slice(0, 200)
    await logActivation(
      directory,
      "lifecycle-autopilot",
      "session.created",
      "scan",
      "error",
      msg
    )
    return { result: "error", detail: msg } // advisory: log, never throw
  }
}

async function idleHandler(directory: string): Promise<any> {
  const results: string[] = []
  try {
    const repoRoot = directory || process.cwd()
    const state = loadState(repoRoot)

    // 1. Re-scan for new projects
    const scanned = await scanForProjects(repoRoot)
    for (const proj of registerNew(state, scanned)) {
      const rec = state.projects.find((p: any) => p.id === proj.id)
      if (rec) {
        const info = await gitInfo(rec.path)
        rec.branch = info.branch
        if (info.lastCommit) rec.updated = info.lastCommit
      }
      results.push(`new: ${proj.id} (${proj.marker})`)
    }

    // 2. Update existing projects with fresh git info
    for (const project of state.projects) {
      if (!project.path || project.state === "archived") continue
      if (!existsSync(project.path)) continue

      const info = await gitInfo(project.path)
      if (info.lastCommit && info.lastCommit !== project.lastCommit) {
        project.lastCommit = info.lastCommit
        project.updated = info.lastCommit
        project.recentCommits = info.recentCommits
        if (project.branch !== info.branch) project.branch = info.branch
        results.push(
          `${project.id}: updated (branch=${info.branch}, commits_7d=${info.recentCommits})`
        )
      }
    }

    // 3. Detect transitions
    const transitions = detectTransitions(state)
    for (const t of transitions) {
      if (t.from !== t.to) {
        const project = state.projects.find((p: any) => p.id === t.project)
        if (project) {
          project.state = t.to
          project.updated = new Date().toISOString().split("T")[0]
          results.push(`${t.project}: ${t.from}→${t.to}`)
        }
      } else if (t.reason.startsWith("STALE") || t.reason.startsWith("SUGGEST")) {
        results.push(`${t.project}: ${t.reason}`)
      }
    }

    // 4. Persist to OWN state file (never current_focus.json — D-28)
    if (results.length > 0) saveState(repoRoot, state)

    // 5. Run lifecycle-status.sh for additional reporting
    const statusScript = join(repoRoot, "scripts/state/lifecycle/lifecycle-status.sh")
    if (existsSync(statusScript)) {
      try {
        const { stdout } = await execFileP("bash", [statusScript, "--extended"], {
          cwd: repoRoot,
          timeout: 10_000,
        })
        if (stdout.trim()) {
          results.push(`status: ${stdout.trim().split("\n")[0]}`)
        }
      } catch {
        // Ignore errors from status script (advisory)
      }
    }

    const detail = results.join("; ") || "nothing to do"
    await logActivation(directory, "lifecycle-autopilot", "session.idle", "update", "ok", detail)
    return {
      result: results.length > 0 ? "ok" : "skip",
      detail,
      summary: detail,
    }
  } catch (e: any) {
    const msg = String(e?.message || e).slice(0, 200)
    await logActivation(directory, "lifecycle-autopilot", "session.idle", "update", "error", msg)
    return { result: "error", detail: msg } // advisory: log, never throw
  }
}

async function afterHandler(directory: string, input: any): Promise<any> {
  try {
    const toolName = input?.tool || ""
    if (toolName !== "write" && toolName !== "edit") {
      return { result: "skip", detail: "not a write tool" }
    }

    // Real dispatcher shape (same as vsf-classify-on-write):
    //   input.args.file_path | input.args.filePath (fallback legacy keys)
    const filePath = String(
      input?.args?.file_path ?? input?.args?.filePath ?? input?.filePath ?? input?.path ?? ""
    )
    if (!filePath) return { result: "skip", detail: "no file path" }

    const repoRoot = directory || process.cwd()
    const state = loadState(repoRoot)

    for (const project of state.projects) {
      if (project.path && filePath.startsWith(project.path)) {
        project.updated = new Date().toISOString().split("T")[0]
        project.lastActivity = filePath
        saveState(repoRoot, state)
        await logActivation(
          directory,
          "lifecycle-autopilot",
          "tool.execute.after",
          "track",
          "ok",
          `${project.id}: ${filePath}`
        )
        return { result: "ok", detail: `${project.id}: tracked`, summary: `${project.id} updated` }
      }
    }
    return { result: "skip", detail: "file not in tracked project" }
  } catch (e: any) {
    const msg = String(e?.message || e).slice(0, 200)
    await logActivation(
      directory,
      "lifecycle-autopilot",
      "tool.execute.after",
      "track",
      "error",
      msg
    )
    return { result: "error", detail: msg } // advisory: log, never throw
  }
}

// ─── Plugin (D-28 dispatch shape) ───────────────────────────────────────────
// session.* bus events → generic `event` hook only (CC-1); tool.execute.*
// fires as named keys. Matches the session-lifecycle fix pattern 2026-10-07.

const LifecycleAutopilot: Plugin = async ({ directory }) => {
  return {
    event: async (input: any) => {
      const ev = input?.event ?? input
      const type = typeof ev?.type === "string" ? ev.type : ""
      if (type !== "session.created" && type !== "session.idle") return
      const repoRoot = directory || process.cwd()
      return type === "session.created"
        ? await createdHandler(repoRoot)
        : await idleHandler(repoRoot)
    },
    "tool.execute.after": async (input: any) => {
      const repoRoot = directory || process.cwd()
      return await afterHandler(repoRoot, input)
    },
  }
}

export default LifecycleAutopilot
