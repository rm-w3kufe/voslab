/**
 * lifecycle-discovery.ts — auto-discovery and registration of plugins/scripts.
 *
 * DESIGN: scans workspace for new plugins and scripts, auto-registers them
 * in the lifecycle system. No manual intervention needed.
 *
 * How it works:
 *   1. On session.idle: scan for new .ts plugins in .opencode/plugins/
 *   2. On session.idle: scan for new scripts in scripts/
 *   3. Auto-classify scripts by location (governance/attestation/tasks/monitoring)
 *   4. Auto-register in registry.json and opencode.json
 *   5. Log what was discovered
 *
 * R16: policy declares, instrument interprets.
 * R9: unknown discoveries are visible, never silent.
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, readFileSync, writeFileSync, readdirSync, statSync } from "node:fs"
import { join, dirname, basename, extname } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"

const execP = promisify(exec)

// ─── Config ──────────────────────────────────────────────────────────────────

const REGISTRY_FILE = ".opencode/plugins/registry.json"
const OPENCODE_FILE = "opencode.json"

// Directories to scan for plugins
const PLUGIN_DIRS = [
  ".opencode/plugins/core",
  ".opencode/plugins/operational",
  ".opencode/plugins/operational/handlers",
  ".opencode/plugins/manual",
  ".opencode/plugins/support",
]

// Directories to scan for scripts
const SCRIPT_DIRS = [
  "scripts/state/governance",
  "scripts/state/attestation",
  "scripts/state/tasks",
  "scripts/state/monitoring",
  "scripts/state/lifecycle",
]

// Script classification by directory
const SCRIPT_CLASSIFICATION: Record<string, string> = {
  "scripts/state/governance": "governance",
  "scripts/state/attestation": "attestation",
  "scripts/state/tasks": "tasks",
  "scripts/state/monitoring": "monitoring",
  "scripts/state/lifecycle": "lifecycle",
}

// Skip patterns
const SKIP_PATTERNS = [
  "node_modules",
  ".git",
  "__pycache__",
  "*.test.ts",
  "*.spec.ts",
  "*.d.ts",
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function shouldSkip(path: string): boolean {
  return SKIP_PATTERNS.some((pattern) => {
    if (pattern.startsWith("*")) {
      return path.endsWith(pattern.slice(1))
    }
    return path.includes(pattern)
  })
}

function findRepoRoot(directory: string): string {
  let p = directory || process.cwd()
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(p, ".git"))) return p
    const parent = dirname(p)
    if (parent === p) break
    p = parent
  }
  return directory
}

function readJsonFile(path: string): any {
  try {
    return JSON.parse(readFileSync(path, "utf-8"))
  } catch {
    return null
  }
}

function writeJsonFile(path: string, data: any): void {
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n")
}

function getCategoryForDir(dir: string): string {
  for (const [pattern, category] of Object.entries(SCRIPT_CLASSIFICATION)) {
    if (dir.includes(pattern)) return category
  }
  return "unknown"
}

// ─── Plugin Discovery ────────────────────────────────────────────────────────

interface DiscoveredPlugin {
  path: string
  name: string
  category: string
  isNew: boolean
}

function scanForPlugins(repoRoot: string): DiscoveredPlugin[] {
  const discovered: DiscoveredPlugin[] = []

  for (const dir of PLUGIN_DIRS) {
    const fullPath = join(repoRoot, dir)
    if (!existsSync(fullPath)) continue

    const files = readdirSync(fullPath).filter(
      (f) => f.endsWith(".ts") && !shouldSkip(f)
    )

    for (const file of files) {
      const filePath = join(dir, file)
      const name = file.replace(".ts", "")
      const category = dir.includes("core")
        ? "core"
        : dir.includes("operational/handlers")
          ? "operational/handlers"
          : dir.includes("operational")
            ? "operational"
            : dir.includes("manual")
              ? "manual"
              : "support"

      discovered.push({
        path: filePath,
        name,
        category,
        isNew: true, // Will be checked against registry
      })
    }
  }

  return discovered
}

function checkIfRegistered(
  plugin: DiscoveredPlugin,
  registry: any
): boolean {
  const plugins = registry?.plugins || {}
  return (
    plugins[plugin.name] !== undefined ||
    plugins[`handler:${plugin.name}`] !== undefined
  )
}

// ─── Script Discovery ────────────────────────────────────────────────────────

interface DiscoveredScript {
  path: string
  name: string
  category: string
  isNew: boolean
}

function scanForScripts(repoRoot: string): DiscoveredScript[] {
  const discovered: DiscoveredScript[] = []

  for (const dir of SCRIPT_DIRS) {
    const fullPath = join(repoRoot, dir)
    if (!existsSync(fullPath)) continue

    const files = readdirSync(fullPath).filter(
      (f) => (f.endsWith(".sh") || f.endsWith(".py")) && !shouldSkip(f)
    )

    for (const file of files) {
      const filePath = join(dir, file)
      const name = file.replace(/\.(sh|py)$/, "")
      const category = getCategoryForDir(dir)

      discovered.push({
        path: filePath,
        name,
        category,
        isNew: true, // Will be checked against handlers
      })
    }
  }

  return discovered
}

function checkIfScriptIntegrated(
  script: DiscoveredScript,
  repoRoot: string
): boolean {
  // Check if script is referenced in any handler
  const handlersDir = join(repoRoot, ".opencode/plugins/operational/handlers")
  if (!existsSync(handlersDir)) return false

  const handlers = readdirSync(handlersDir).filter((f) => f.endsWith(".ts"))
  for (const handler of handlers) {
    const content = readFileSync(join(handlersDir, handler), "utf-8")
    if (content.includes(script.path) || content.includes(script.name)) {
      return true
    }
  }

  return false
}

// ─── Auto-Registration ───────────────────────────────────────────────────────

function autoRegisterPlugin(
  plugin: DiscoveredPlugin,
  registry: any,
  opencode: any
): { registered: boolean; changes: string[] } {
  const changes: string[] = []

  // Add to registry
  if (!registry.plugins) registry.plugins = {}
  registry.plugins[plugin.name] = {
    file: basename(plugin.path),
    category: plugin.category,
    hook: "auto-registered",
    pattern: "*",
    priority: 10,
    blocking: false,
    registered: true,
    dir: plugin.category + "/",
    description: `Auto-registered by lifecycle-discovery`,
  }
  changes.push(`registry: ${plugin.name}`)

  // Add to opencode.json if not present
  if (opencode && opencode.plugin) {
    const pluginPath = `./${plugin.path}`
    if (!opencode.plugin.includes(pluginPath)) {
      opencode.plugin.push(pluginPath)
      changes.push(`opencode: ${plugin.name}`)
    }
  }

  return { registered: true, changes }
}

function autoRegisterScript(
  script: DiscoveredScript,
  repoRoot: string
): { registered: boolean; changes: string[] } {
  const changes: string[] = []

  // Find or create handler for this category
  const handlerName = `${script.category}-auto`
  const handlerPath = join(
    repoRoot,
    ".opencode/plugins/operational/handlers",
    `${handlerName}.ts`
  )

  if (!existsSync(handlerPath)) {
    // Create a minimal handler
    const handlerContent = `
/**
 * ${handlerName}.ts — auto-registered handler for ${script.category} scripts.
 * Generated by lifecycle-discovery.ts
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const ${handlerName}Handler: Handler = {
  id: "${handlerName}",
  priority: 5,
  events: ["session.idle"],
  classify: async () => true,
  execute: async (ctx) => {
    const script = join(ctx.repoRoot, "${script.path}")
    if (!existsSync(script)) return { result: "skip", durationMs: 0, detail: "not found" }
    try {
      const ext = script.endsWith(".py") ? "python3" : "bash"
      await execP(\`\${ext} \${script}\`, { cwd: ctx.repoRoot, timeout: 30_000 })
      return { result: "pass", durationMs: 0, detail: "executed" }
    } catch (err: any) {
      return { result: "fail", durationMs: 0, detail: err.message?.slice(0, 200) }
    }
  },
}
`
    writeFileSync(handlerPath, handlerContent)
    changes.push(`handler: ${handlerName}.ts`)
  }

  return { registered: changes.length > 0, changes }
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

export default (): Plugin => {
  return {
    name: "lifecycle-discovery",
    hooks: [
      // On session idle: discover and register new plugins/scripts
      {
        event: "session.idle",
        async handler({ directory }) {
          const start = Date.now()
          const repoRoot = findRepoRoot(directory)
          const results: string[] = []

          // 1. Load registry and opencode
          const registryPath = join(repoRoot, REGISTRY_FILE)
          const opencodePath = join(repoRoot, OPENCODE_FILE)

          let registry = readJsonFile(registryPath) || { plugins: {} }
          let opencode = readJsonFile(opencodePath) || { plugin: [] }

          // 2. Discover new plugins
          const plugins = scanForPlugins(repoRoot)
          const newPlugins = plugins.filter((p) => !checkIfRegistered(p, registry))

          for (const plugin of newPlugins) {
            const { changes } = autoRegisterPlugin(plugin, registry, opencode)
            results.push(`plugin: ${plugin.name} (${changes.join(", ")})`)
          }

          // 3. Discover new scripts
          const scripts = scanForScripts(repoRoot)
          const newScripts = scripts.filter(
            (s) => !checkIfScriptIntegrated(s, repoRoot)
          )

          for (const script of newScripts) {
            const { changes } = autoRegisterScript(script, repoRoot)
            if (changes.length > 0) {
              results.push(`script: ${script.name} (${changes.join(", ")})`)
            }
          }

          // 4. Save changes
          if (newPlugins.length > 0) {
            writeJsonFile(registryPath, registry)
            writeJsonFile(opencodePath, opencode)
          }

          const duration = Date.now() - start
          const detail =
            results.length > 0
              ? `discovered: ${results.join("; ")}`
              : "no new plugins/scripts"

          await logActivation(directory, "lifecycle-discovery", "session.idle", "scan", results.length > 0 ? "ok" : "skip", detail)

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail,
            summary: `${newPlugins.length} plugins, ${newScripts.length} scripts`,
          }
        },
      },
    ],
  }
}
