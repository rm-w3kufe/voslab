/**
 * design: docs/design/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
 * lifecycle-discovery.ts — lifecycle census (P23).
 *
 * S2 REGISTER (design base): docs/design/sandbox/plugin-s2-coordination-v1/
 * plugin_s2_coordination.vsm →
 *   "P23|lifecycle-discovery.ts|session.idle|scope=discover lifecycle state|
 *    autoridad=advisory|órgano=S2"
 *
 * D-28 REDESIGN (S5 2026-10-07 — REDISEÑAR contra P22/P23, no retirar):
 *   - Dispatch: session.idle arrives ONLY through the generic `event` hook
 *     (CC-1 finding — same fix as session-lifecycle 2026-10-07). The old
 *     `{name, hooks:[...]}` export was never dispatched AND never loaded
 *     (disconnected at FIX-C 2026-10-07).
 *   - Scope per P23 = "discover lifecycle state": CENSUS + REPORT ONLY.
 *     The old auto-register rewrote registry.json with a retired flat schema
 *     over today's category-nested shape, duplicated entries into
 *     opencode.json (wrong `./` path form), and generated handler stubs
 *     against a retired Handler API — while its registry lookup used a flat
 *     key over nested data, so EVERYTHING looked unregistered. Registration
 *     is governance (S2 P-register row + plugin-location-valid +
 *     plugin-s2-coherent); an advisory plugin cannot write the .vsm spec row
 *     that plugin-s2-coherent demands (R18), so auto-register was
 *     incoherent with the very spec it implements (R16).
 *   - Findings visible every idle (R9), never silent, never blocking.
 *
 * Census covers:
 *   1. plugins: disk .ts ↔ registry (key OR file field) ↔ opencode wiring
 *      ↔ handler catalog ↔ import graph → orphans / stale / wiring gaps
 *   2. scripts: scripts/state/ disk walk ↔ scripts_state_manifest.vsm
 *      (missing / extra — kept fresh by vsf-scripts-manifest-updater)
 *
 * R16: policy declares, instrument interprets.
 * R9: unknown discoveries are visible, never silent.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { join, dirname } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"

// ─── Config ──────────────────────────────────────────────────────────────────

const REGISTRY_REL = join(".opencode", "plugins", "registry.json")
const OPENCODE_REL = "opencode.json"
const MANIFEST_REL = join(
  "system",
  "instance",
  "vsf-instance-v1",
  "scripts_state_manifest.vsm"
)

// Directories to scan for plugins
const PLUGIN_DIRS = [
  ".opencode/plugins/core",
  ".opencode/plugins/operational",
  ".opencode/plugins/operational/handlers",
  ".opencode/plugins/manual",
  ".opencode/plugins/support",
  ".opencode/shared",
]

const SCRIPT_STATE_DIR = "scripts/state"

// Skip patterns
const SKIP_PATTERNS = ["node_modules", ".git", "__pycache__", "*.test.ts", "*.spec.ts", "*.d.ts"]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function shouldSkip(path: string): boolean {
  return SKIP_PATTERNS.some((pattern) => {
    if (pattern.startsWith("*")) return path.endsWith(pattern.slice(1))
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

// ─── Census: plugins ─────────────────────────────────────────────────────────

interface CatalogSets {
  keys: Set<string> // registry entry names (any category) + "handler:*"
  files: Set<string> // registry entry file fields (e.g. "epistemic-claims-on-write.ts")
  handlerFiles: Set<string> // registry.handlers.files (e.g. "session-init.ts")
}

function catalogSets(registry: any): CatalogSets {
  const keys = new Set<string>()
  const files = new Set<string>()
  const handlerFiles = new Set<string>()
  const cats = registry?.plugins || {}
  for (const cat of Object.values(cats) as any[]) {
    if (!cat || typeof cat !== "object") continue
    for (const [name, ent] of Object.entries(cat.plugins || {})) {
      keys.add(name)
      const f = (ent as any)?.file
      if (typeof f === "string") files.add(f)
    }
  }
  const hf = registry?.handlers?.files
  if (Array.isArray(hf)) for (const f of hf) if (typeof f === "string") handlerFiles.add(f)
  return { keys, files, handlerFiles }
}

function wiredSet(opencode: any): Set<string> {
  const wired = new Set<string>()
  for (const p of opencode?.plugin || []) {
    if (typeof p === "string") wired.add(p.split("/").pop() || "")
    else if (p && typeof p === "object" && typeof p.path === "string")
      wired.add(p.path.split("/").pop() || "")
  }
  wired.delete("")
  return wired
}

function importedSet(repoRoot: string): Set<string> {
  // Static import graph: basenames (no .ts) referenced via relative imports.
  const imported = new Set<string>()
  for (const dir of PLUGIN_DIRS) {
    const full = join(repoRoot, dir)
    if (!existsSync(full)) continue
    let files: string[] = []
    try {
      files = readdirSync(full)
    } catch {
      continue
    }
    for (const f of files) {
      if (!f.endsWith(".ts") || shouldSkip(f)) continue
      let content = ""
      try {
        content = readFileSync(join(full, f), "utf-8")
      } catch {
        continue
      }
      const re = /from\s+"(\.[^"]+)"/g
      let m: RegExpExecArray | null
      while ((m = re.exec(content)) !== null) {
        imported.add((m[1].split("/").pop() || "").replace(/\.ts$/, ""))
      }
    }
  }
  return imported
}

interface PluginCensus {
  wired: number
  catalogued: number
  handlers: { onDisk: number; cataloged: number }
  orphans: string[] // on disk: not wired, not catalogued, not handler, not imported
  stale: string[] // catalogued/handler file missing on disk
  gaps: string[] // wired but absent from registry catalog
}

function censusPlugins(repoRoot: string): PluginCensus {
  const registry = readJsonFile(join(repoRoot, REGISTRY_REL)) || {}
  const opencode = readJsonFile(join(repoRoot, OPENCODE_REL)) || {}
  const { keys, files, handlerFiles } = catalogSets(registry)
  const wired = wiredSet(opencode)
  const imported = importedSet(repoRoot)

  const orphans: string[] = []
  const diskFiles = new Set<string>()
  for (const dir of PLUGIN_DIRS) {
    const full = join(repoRoot, dir)
    if (!existsSync(full)) continue
    let entries: string[] = []
    try {
      entries = readdirSync(full)
    } catch {
      continue
    }
    for (const f of entries) {
      if (!f.endsWith(".ts") || shouldSkip(f)) continue
      diskFiles.add(f)
      const n = f.replace(/\.ts$/, "")
      const isCatalogued =
        keys.has(n) || keys.has(`handler:${n}`) || files.has(f) || handlerFiles.has(f)
      if (wired.has(f) || isCatalogued || imported.has(n)) continue
      orphans.push(`${dir}/${f}`)
    }
  }

  const stale: string[] = []
  for (const f of [...files, ...handlerFiles]) if (!diskFiles.has(f)) stale.push(f)

  const gaps: string[] = []
  for (const w of [...wired].sort()) {
    const n = w.replace(/\.ts$/, "")
    if (!(keys.has(n) || keys.has(`handler:${n}`) || files.has(w) || handlerFiles.has(w)))
      gaps.push(w)
  }

  // handlers: on-disk count vs cataloged count
  const handlerDir = join(repoRoot, ".opencode/plugins/operational/handlers")
  let handlersOnDisk = 0
  if (existsSync(handlerDir)) {
    try {
      handlersOnDisk = readdirSync(handlerDir).filter((f) => f.endsWith(".ts")).length
    } catch {}
  }

  return {
    wired: wired.size,
    catalogued: keys.size,
    handlers: { onDisk: handlersOnDisk, cataloged: handlerFiles.size },
    orphans: orphans.sort(),
    stale: stale.sort(),
    gaps,
  }
}

// ─── Census: scripts manifest ────────────────────────────────────────────────

interface ScriptCensus {
  manifestTotal: number
  missing: string[] // on disk, absent from manifest
  extra: string[] // in manifest, absent from disk
}

function censusScripts(repoRoot: string): ScriptCensus {
  const res: ScriptCensus = { manifestTotal: 0, missing: [], extra: [] }
  const manifestPath = join(repoRoot, MANIFEST_REL)
  const listed = new Set<string>()
  try {
    const content = readFileSync(manifestPath, "utf-8")
    const re = /"([^"]+\.(?:py|sh))"/g
    let m: RegExpExecArray | null
    while ((m = re.exec(content)) !== null) {
      const p = m[1]
      // Real entries are paths relative to scripts/state/. The manifest also
      // quotes usage/command lines ("python3 scripts/shared/…", "scripts/…")
      // outside the estructura() block — those are not inventory entries.
      if (p.includes(" ") || p.startsWith("scripts/") || p.startsWith("python")) continue
      listed.add(p)
    }
    res.manifestTotal = listed.size
  } catch {
    res.extra = ["<scripts_state_manifest.vsm missing or unreadable>"]
    return res
  }

  const disk = new Set<string>()
  const root = join(repoRoot, SCRIPT_STATE_DIR)
  const walk = (dir: string) => {
    let entries: any[] = []
    try {
      entries = readdirSync(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const ent of entries) {
      if (shouldSkip(ent.name)) continue
      const full = join(dir, ent.name)
      if (ent.isDirectory()) walk(full)
      else if (ent.name.endsWith(".py") || ent.name.endsWith(".sh"))
        disk.add(full.slice(root.length + 1).split("\\").join("/"))
    }
  }
  if (existsSync(root)) walk(root)

  for (const p of disk) if (!listed.has(p)) res.missing.push(p)
  for (const p of listed) if (!disk.has(p)) res.extra.push(p)
  res.missing.sort()
  res.extra.sort()
  return res
}

// ─── Plugin (D-28 dispatch shape) ───────────────────────────────────────────

const LifecycleDiscovery: Plugin = async ({ directory }) => {
  return {
    event: async (input: any) => {
      const ev = input?.event ?? input
      const type = typeof ev?.type === "string" ? ev.type : ""
      if (type !== "session.idle") return
      const start = Date.now()
      const repoRoot = findRepoRoot(directory || process.cwd())
      try {
        const p = censusPlugins(repoRoot)
        const s = censusScripts(repoRoot)

        const parts: string[] = [
          `wired=${p.wired}`,
          `catalog=${p.catalogued}`,
          `handlers=${p.handlers.onDisk}/${p.handlers.cataloged}`,
        ]
        if (p.orphans.length > 0)
          parts.push(
            `orphans=${p.orphans.length} (${p.orphans.map((x) => (x.split("/").pop() || x).replace(/\.ts$/, "")).join(", ")})`
          )
        if (p.stale.length > 0) parts.push(`stale=${p.stale.length} (${p.stale.join(", ")})`)
        if (p.gaps.length > 0) parts.push(`wiring-gaps=${p.gaps.length} (${p.gaps.join(", ")})`)
        if (s.extra.length > 0 && s.extra[0].startsWith("<"))
          parts.push(`scripts=manifest UNREADABLE`)
        else if (s.missing.length > 0 || s.extra.length > 0)
          parts.push(
            `scripts drift: missing=${s.missing.length}${s.missing.length ? " (" + s.missing.slice(0, 5).join(", ") + ")" : ""}, extra=${s.extra.length}${s.extra.length ? " (" + s.extra.slice(0, 5).join(", ") + ")" : ""}`
          )
        else parts.push(`scripts=manifest ok (${s.manifestTotal})`)

        const detail = parts.join(", ")
        await logActivation(directory, "lifecycle-discovery", "session.idle", "census", "ok", detail)
        return { result: "ok", durationMs: Date.now() - start, detail, summary: detail }
      } catch (e: any) {
        const msg = String(e?.message || e).slice(0, 200)
        await logActivation(directory, "lifecycle-discovery", "session.idle", "census", "error", msg)
        return { result: "error", durationMs: Date.now() - start, detail: msg }
      }
    },
  }
}

export default LifecycleDiscovery
