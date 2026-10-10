/**
 * gap-context.ts — Context gatherers for gap resolution.
 *
 * Each gatherer collects specific context about a file or action.
 * Used by gap-resolver.ts to build context for socratic evaluation.
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { readFileSync, existsSync, readdirSync } from "node:fs"
import { join, dirname } from "node:path"

const execFileP = promisify(execFile)

// ─── esbuild (validación TS/JS honesta) ──────────────────────────────────────

// Resuelve esbuild: PATH primero, luego el cache local de npx (orden
// estable, solo éxito se memoriza). null = no hay verificador disponible.
let esbuildMemo: string | null = null

async function resolveEsbuild(): Promise<string | null> {
  if (esbuildMemo) return esbuildMemo
  const candidates: string[] = ["esbuild"]
  try {
    const { homedir } = await import("node:os")
    const base = join(homedir(), ".npm", "_npx")
    if (existsSync(base)) {
      for (const d of readdirSync(base).sort()) {
        candidates.push(join(base, d, "node_modules", ".bin", "esbuild"))
      }
    }
  } catch {
    // sin cache npx: solo PATH
  }
  for (const c of candidates) {
    try {
      await execFileP(c, ["--version"], { timeout: 3000 })
      esbuildMemo = c
      return c
    } catch {
      // siguiente candidato
    }
  }
  return null
}

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ContextGatherer {
  type: string
  [key: string]: any
}

export interface GapContext {
  [key: string]: any
}

// ─── Context Gatherers ──────────────────────────────────────────────────────

export async function gatherContext(
  gatherers: ContextGatherer[],
  filePath: string,
  repoRoot: string
): Promise<GapContext> {
  const context: GapContext = {
    filePath,
    repoRoot,
    fileName: filePath.split("/").pop() || "",
    directory: dirname(filePath),
    timestamp: new Date().toISOString(),
  }

  for (const gatherer of gatherers) {
    switch (gatherer.type) {
      case "read-content": {
        try {
          if (existsSync(filePath)) {
            context.content = readFileSync(filePath, "utf-8")
          }
        } catch {
          // File not readable
        }
        break
      }

      case "parse-imports": {
        try {
          if (existsSync(filePath)) {
            const content = readFileSync(filePath, "utf-8")
            const imports = content.match(/^(?:import|from)\s+.+$/gm) || []
            context.imports = imports.map((i: string) => i.trim())
          }
        } catch {
          // File not readable
        }
        break
      }

      case "extract-exports": {
        try {
          if (existsSync(filePath)) {
            const content = readFileSync(filePath, "utf-8")
            const exports = content.match(/^export\s+(?:const|function|class|interface|type)\s+(\w+)/gm) || []
            context.exports = exports.map((e: string) => {
              const match = e.match(/(\w+)$/)
              return match?.[1] || ""
            }).filter(Boolean)
          }
        } catch {
          // File not readable
        }
        break
      }

      case "git-status": {
        try {
          const { stdout } = await execFileP(
            "git",
            ["status", "--porcelain", filePath],
            { cwd: repoRoot, timeout: 5000 }
          )
          context.gitStatus = stdout.trim() || "clean"
        } catch {
          context.gitStatus = "unknown"
        }
        break
      }

      case "git-diff": {
        try {
          const { stdout } = await execFileP(
            "git",
            ["diff", "--stat", filePath],
            { cwd: repoRoot, timeout: 5000 }
          )
          context.gitDiff = stdout.trim() || "no changes"
        } catch {
          context.gitDiff = "unknown"
        }
        break
      }

      case "file-info": {
        try {
          if (existsSync(filePath)) {
            const stats = await import("node:fs").then(fs => 
              fs.promises.stat(filePath)
            )
            context.fileInfo = {
              size: stats.size,
              created: stats.birthtime.toISOString(),
              modified: stats.mtime.toISOString(),
            }
          }
        } catch {
          // File not accessible
        }
        break
      }

      case "syntax-check": {
        if (filePath.endsWith(".py")) {
          try {
            await execFileP(
              "python3",
              ["-m", "py_compile", filePath],
              { timeout: 5000 }
            )
            context.syntaxValid = true
          } catch {
            context.syntaxValid = false
          }
        } else if (filePath.endsWith(".ts") || filePath.endsWith(".js")) {
          // esbuild es el único verificador honesto disponible aquí:
          // node --check es vacío para ESM detectado (rc=0 hasta en
          // archivos rotos) y da ERR_UNKNOWN_FILE_EXTENSION en .ts sano
          // (falso+ SYNTAX_ERROR, deuda REFS-OPT B2). Sin esbuild:
          // .ts NO setea syntaxValid -> quality-gate => UNKNOWN honesto;
          // .js conserva node --check (comportamiento pre-existente).
          const esbuild = await resolveEsbuild()
          if (esbuild) {
            try {
              await execFileP(
                esbuild,
                [filePath, "--outfile=/dev/null", "--log-level=error"],
                { timeout: 5000 }
              )
              context.syntaxValid = true
            } catch {
              context.syntaxValid = false
            }
          } else if (!filePath.endsWith(".ts")) {
            try {
              await execFileP("node", ["--check", filePath], { timeout: 5000 })
              context.syntaxValid = true
            } catch {
              context.syntaxValid = false
            }
          }
        }
        break
      }

      case "dependency-check": {
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const depPattern = /(?:import|require)\s*\(?['"]([^'"]+)['"]\)?/g
          const deps: string[] = []
          let match
          while ((match = depPattern.exec(content)) !== null) {
            if (!match[1].startsWith(".") && !match[1].startsWith("/")) {
              deps.push(match[1])
            }
          }
          context.dependencies = deps
        }
        break
      }

      case "conflict-check": {
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          context.hasConflictMarkers = content.includes("<<<<<<<") || 
                                      content.includes("=======") ||
                                      content.includes(">>>>>>>")
        }
        break
      }

      case "run-audit": {
        // Run a read-only audit command (execFile argv — never a shell) and
        // parse its JSON stdout into the context under `key`. A flat copy at
        // `<key>_state` feeds ctx_equals: engine predicates take flat keys,
        // not dotted paths. Missing/unparseable output leaves no `*_state`
        // key, so tree ctx_has guards evaluate UNKNOWN-safe (R9).
        // Added for covenant-update (S5 2026-10-02: expedited covenant
        // procedure, actions driven from the decision tree).
        const argv: string[] = gatherer.argv || []
        const key: string = gatherer.key || "audit"
        const timeoutMs: number = gatherer.timeoutMs ?? 30000
        if (!Array.isArray(argv) || argv.length === 0) {
          context[key] = { error: "run-audit: argv (array) required" }
          break
        }
        try {
          const { stdout } = await execFileP(String(argv[0]), argv.slice(1).map(String), {
            cwd: repoRoot,
            timeout: timeoutMs,
            maxBuffer: 8 * 1024 * 1024,
          })
          const parsed = JSON.parse(stdout)
          context[key] = parsed
          if (parsed && typeof parsed === "object" && typeof parsed.state === "string") {
            context[`${key}_state`] = parsed.state
          }
        } catch (err: any) {
          context[key] = {
            error: String(err?.message || err).slice(0, 300),
          }
        }
        break
      }
    }
  }

  return context
}
