/**
 * lifecycle-autopilot.ts — project-agnostic lifecycle management.
 *
 * DESIGN: detects ANY project in the workspace, auto-registers it,
 * and keeps it updated throughout its lifecycle. No manual setup needed.
 *
 * How it works:
 *   1. On session.created: scan workspace for projects, inject status
 *   2. On session.idle: detect new projects, update state, promote/demote
 *   3. On tool.execute.after: track significant writes to any project
 *
 * Project detection: looks for markers (git repo, package.json, Cargo.toml,
 * pyproject.toml, go.mod, etc.) in common workspace locations.
 *
 * State machine: draft → design → implementing → testing → consolidating → stable → archived
 *
 * R16: policy declares, instrument interprets.
 * R9: unknown states are visible, never silent.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, readFileSync, writeFileSync, readdirSync, statSync } from "node:fs"
import { join, dirname, basename } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"

const execFileP = promisify(execFile)

// ─── Config ──────────────────────────────────────────────────────────────────

const FOCUS_FILE = "current_focus.json"

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

// ─── Helpers ─────────────────────────────────────────────────────────────────

function findFocusFile(directory: string): string | null {
  let p = directory || process.cwd()
  for (let i = 0; i < 6; i++) {
    const candidate = join(p, FOCUS_FILE)
    if (existsSync(candidate)) return candidate
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return null
}

function readFocus(focusPath: string): any {
  try {
    return JSON.parse(readFileSync(focusPath, "utf-8"))
  } catch {
    return null
  }
}

function writeFocus(focusPath: string, data: any): void {
  data.updated = new Date().toISOString().split("T")[0]
  writeFileSync(focusPath, JSON.stringify(data, null, 2) + "\n")
}

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

async function gitInfo(repoPath: string): Promise<{ branch: string; lastCommit: string; recentCommits: number }> {
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
      "git", ["log", "--oneline", "--since=7 days ago", "--no-merges"],
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
  branch?: string
  lastCommit?: string
  recentCommits?: number
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
        } catch { continue }

        const marker = hasMarker(fullPath)
        if (marker) {
          const id = basename(fullPath)
          projects.push({
            id,
            path: fullPath,
            name: id,
            marker,
          })
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

function detectTransitions(data: any): TransitionResult[] {
  const results: TransitionResult[] = []

  for (const project of data.projects || []) {
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
    const allDone = milestones.length > 0 && milestones.every((m: any) => m.status === "done")
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

// ─── Plugin ──────────────────────────────────────────────────────────────────

export default (): Plugin => {
  return {
    name: "lifecycle-autopilot",
    hooks: [
      // On session start: scan for projects, inject status
      {
        event: "session.created",
        async handler({ directory }) {
          const start = Date.now()
          const focusPath = findFocusFile(directory)
          if (!focusPath) return { result: "skip", durationMs: 0, detail: "no focus file" }

          const data = readFocus(focusPath)
          if (!data) return { result: "skip", durationMs: 0, detail: "invalid focus" }

          // 1. Scan for projects in workspace
          const repoRoot = dirname(focusPath)
          const scanned = await scanForProjects(repoRoot)

          // 2. Detect new projects (not in registry yet)
          const existing = new Set((data.projects || []).map((p: any) => p.id))
          const newProjects = scanned.filter((p) => !existing.has(p.id))

          // 3. Auto-register new projects
          for (const proj of newProjects) {
            const info = await gitInfo(proj.path)
            const project = {
              id: proj.id,
              name: proj.name,
              path: proj.path,
              state: "implementing", // has git = already implementing
              marker: proj.marker,
              branch: info.branch,
              created: new Date().toISOString().split("T")[0],
              updated: info.lastCommit || new Date().toISOString().split("T")[0],
              milestones: [],
              next_action: "Define milestones",
              auto_detected: true,
            }
            data.projects = data.projects || []
            data.projects.push(project)
          }

          // 4. Inject status
          const active = (data.projects || []).filter(
            (p: any) => p.state !== "archived" && p.state !== "stable"
          )

          if (active.length === 0 && newProjects.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no active projects" }
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

          // 5. Write back if new projects added
          if (newProjects.length > 0) {
            writeFocus(focusPath, data)
          }

          await logActivation(directory, "lifecycle-autopilot", "session.created", "scan", "ok", msg)

          return {
            result: "ok",
            durationMs: Date.now() - start,
            detail: msg,
            summary: `${active.length} active, ${newProjects.length} new`,
          }
        },
      },

      // On session idle: update state, detect transitions
      {
        event: "session.idle",
        async handler({ directory }) {
          const start = Date.now()
          const focusPath = findFocusFile(directory)
          if (!focusPath) return { result: "skip", durationMs: 0, detail: "no focus file" }

          const data = readFocus(focusPath)
          if (!data) return { result: "skip", durationMs: 0, detail: "invalid focus" }

          const results: string[] = []

          // 1. Re-scan for new projects
          const repoRoot = dirname(focusPath)
          const scanned = await scanForProjects(repoRoot)
          const existing = new Set((data.projects || []).map((p: any) => p.id))
          const newProjects = scanned.filter((p) => !existing.has(p.id))

          for (const proj of newProjects) {
            const info = await gitInfo(proj.path)
            data.projects = data.projects || []
            data.projects.push({
              id: proj.id,
              name: proj.name,
              path: proj.path,
              state: "implementing",
              marker: proj.marker,
              branch: info.branch,
              created: new Date().toISOString().split("T")[0],
              updated: info.lastCommit || new Date().toISOString().split("T")[0],
              milestones: [],
              next_action: "Define milestones",
              auto_detected: true,
            })
            results.push(`new: ${proj.id} (${proj.marker})`)
          }

          // 2. Update existing projects with fresh git info
          for (const project of data.projects || []) {
            if (!project.path || project.state === "archived") continue
            if (!existsSync(project.path)) continue

            const info = await gitInfo(project.path)
            if (info.lastCommit && info.lastCommit !== project.lastCommit) {
              project.lastCommit = info.lastCommit
              project.updated = info.lastCommit
              project.recentCommits = info.recentCommits
              if (project.branch !== info.branch) {
                project.branch = info.branch
              }
              results.push(`${project.id}: updated (branch=${info.branch}, commits_7d=${info.recentCommits})`)
            }
          }

          // 3. Detect transitions
          const transitions = detectTransitions(data)
          for (const t of transitions) {
            if (t.from !== t.to) {
              const project = data.projects.find((p: any) => p.id === t.project)
              if (project) {
                project.state = t.to
                project.updated = new Date().toISOString().split("T")[0]
                results.push(`${t.project}: ${t.from}→${t.to}`)
              }
            } else if (t.reason.startsWith("STALE") || t.reason.startsWith("SUGGEST")) {
              results.push(`${t.project}: ${t.reason}`)
            }
          }

          // 4. Write back
          if (results.length > 0) {
            writeFocus(focusPath, data)
          }

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
              // Ignore errors from status script
            }
          }

          const duration = Date.now() - start
          await logActivation(directory, "lifecycle-autopilot", "session.idle", "update", "ok", results.join("; "))

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail: results.join("; ") || "nothing to do",
            summary: results.join("; "),
          }
        },
      },

      // On file write: track significant changes
      {
        event: "tool.execute.after",
        async handler({ directory, input }) {
          const toolName = input?.tool || ""
          if (!["write", "edit"].includes(toolName)) {
            return { result: "skip", durationMs: 0, detail: "not a write tool" }
          }

          const filePath = input?.filePath || input?.path || ""
          if (!filePath) return { result: "skip", durationMs: 0, detail: "no file path" }

          // Check if this file is inside a tracked project
          const focusPath = findFocusFile(directory)
          if (!focusPath) return { result: "skip", durationMs: 0, detail: "no focus file" }

          const data = readFocus(focusPath)
          if (!data) return { result: "skip", durationMs: 0, detail: "invalid focus" }

          // Find which project this file belongs to
          for (const project of data.projects || []) {
            if (!project.path) continue
            if (filePath.startsWith(project.path)) {
              // Update timestamp
              project.updated = new Date().toISOString().split("T")[0]
              project.lastActivity = filePath
              writeFocus(focusPath, data)
              await logActivation(directory, "lifecycle-autopilot", "tool.execute.after", "track", "ok", `${project.id}: ${filePath}`)
              return {
                result: "ok",
                durationMs: 0,
                detail: `${project.id}: tracked`,
                summary: `${project.id} updated`,
              }
            }
          }

          return { result: "skip", durationMs: 0, detail: "file not in tracked project" }
        },
      },
    ],
  }
}
