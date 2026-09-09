/**
 * gap-resolver.ts — Recursive gap resolution framework.
 *
 * DESIGN: Orchestrates gap definitions through trigger → context → eval → action → log.
 * Each gap is a JSON definition; the resolver executes them recursively.
 *
 * Modes:
 *   - SEMI-AUTOMATIC (default): suggests changes, requires approval
 *   - AUTOMATIC: executes changes directly (flag: GAP_RESOLVER_AUTO=true)
 *
 * R16: policy declares, instrument interprets.
 * R10: socratic trees provide deterministic decisions.
 *
 * INTEGRATION: Uses socratic-shell pattern for tree evaluation.
 * Each gap definition is a declarative config; the resolver is the interpreter.
 *
 * DYNAMIC GATES: Integrates with gate_registry.py to load gates from:
 * - Static gate trees (.opencode/plugins/support/trees/*.tree.vsm)
 * - Gap-definition gates (.opencode/plugins/operational/gap-definitions/*.gap.json)
 * - RSI-generated gates (from rsi_pipeline.py)
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, readFileSync, writeFileSync, readdirSync, copyFileSync, mkdirSync } from "node:fs"
import { join, dirname, basename, extname } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { logActivation } from "../../shared/log-activation"
import { findScript } from "../shared/find-plugin-script"

const execFileP = promisify(execFile)

// ─── Config ──────────────────────────────────────────────────────────────────

const GAP_DEFINITIONS_DIR = "gap-definitions"
const GAP_LOG_FILE = "logs/gap-resolution.jsonl"
const ENGINE_REL = "scripts/vsl/classifier/socratic_engine.py"

// Auto-mode flag (default: false = semi-automatic)
const AUTO_MODE = process.env.GAP_RESOLVER_AUTO === "true"

// Gate registry integration
const GATE_REGISTRY_ENABLED = process.env.GATE_REGISTRY_ENABLED !== "false"

// ─── Types ───────────────────────────────────────────────────────────────────

interface GapDefinition {
  id: string
  name: string
  description: string
  trigger: {
    type: string
    patterns?: string[]
    directories?: string[]
    events?: string[]
  }
  context: {
    gatherers: Array<{
      type: string
      [key: string]: any
    }>
  }
  evaluation: {
    type: string
    tree?: string
    inputs?: string[]
  }
  actions: Array<{
    condition: string
    action: string
    params?: Record<string, any>
  }>
  logging: {
    destination: string
    format: string
  }
}

interface GapContext {
  [key: string]: any
}

interface GapResult {
  gapId: string
  trigger: string
  decision: string
  home?: string
  actions: string[]
  autoExecuted: boolean
  timestamp: string
}

// ─── Gate Registry Integration ───────────────────────────────────────────────

interface GateRegistryGate {
  id: string
  name: string
  description: string
  gate_type: string
  source: string
  trigger: {
    type: string
    patterns?: string[]
    directories?: string[]
    events?: string[]
  }
  evaluation: {
    type: string
    tree?: any
  }
  actions: Array<{
    type: string
    severity?: string
    message?: string
  }>
  severity: string
  enabled: boolean
  metadata: Record<string, any>
}

/**
 * Load gap definitions from the unified gate registry.
 * This combines static gates, gap-definition gates, and RSI-generated gates.
 */
async function loadGapDefinitionsFromRegistry(repoRoot: string): Promise<GapDefinition[]> {
  if (!GATE_REGISTRY_ENABLED) {
    return []
  }

  try {
    // Call gate_registry.py to get all gates
    const registryScript = join(repoRoot, "packages/public/vsf-rsi/vsf_rsi/gate_registry.py")
    if (!existsSync(registryScript)) {
      return []
    }

    const { stdout } = await execFileP(
      "python3",
      [registryScript, "--json"],
      { cwd: repoRoot, timeout: 10000 }
    )

    const registry = JSON.parse(stdout)
    const gates: GapDefinition[] = []

    // Convert registry gates to GapDefinition format
    for (const [gateId, gateData] of Object.entries(registry.gates || {})) {
      const gate = gateData as GateRegistryGate
      if (!gate.enabled) continue

      // Convert gate_type to trigger type
      let triggerType = "always"
      if (gate.trigger?.type) {
        triggerType = gate.trigger.type
      }

      // Convert evaluation to gap format
      let evaluation = { type: "rule-based" }
      if (gate.evaluation?.type === "socratic" && gate.evaluation?.tree) {
        evaluation = {
          type: "socratic-tree",
          tree: typeof gate.evaluation.tree === "string" 
            ? gate.evaluation.tree 
            : JSON.stringify(gate.evaluation.tree)
        }
      }

      // Convert actions to gap format
      const actions = (gate.actions || []).map(action => ({
        condition: "true",
        action: action.type === "report" ? "log-success" : "alert-conflict",
        params: {
          message: action.message || `Gate ${gateId} triggered`,
          severity: action.severity || gate.severity
        }
      }))

      // Add severity-based action
      if (gate.severity === "CRITICAL" || gate.severity === "HIGH") {
        actions.push({
          condition: "decision === 'BLOCK'",
          action: "block-commit",
          params: { reason: `Gate ${gateId} blocked action` }
        })
      }

      const gapDef: GapDefinition = {
        id: gateId,
        name: gate.name,
        description: gate.description,
        trigger: {
          type: triggerType,
          ...gate.trigger
        },
        context: {
          gatherers: [{ type: "read-content" }]
        },
        evaluation,
        actions,
        logging: {
          destination: "logs/gap-resolution.jsonl",
          format: "jsonl"
        }
      }

      gates.push(gapDef)
    }

    return gates
  } catch (err: any) {
    // Registry not available or error, fallback to file-based loading
    return []
  }
}

// ─── Context Gatherers ───────────────────────────────────────────────────────

async function gatherContext(
  gatherers: GapDefinition["context"]["gatherers"],
  filePath: string,
  repoRoot: string
): Promise<GapContext> {
  const context: GapContext = { filePath }

  for (const gatherer of gatherers) {
    switch (gatherer.type) {
      case "read-content":
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const lines = content.split("\n").slice(0, gatherer.lines || 100)
          context.content = lines.join("\n")
          context.contentLength = content.length
          context.lineCount = content.split("\n").length
        }
        break

      case "parse-imports":
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const imports: string[] = []
          const importRegex = /(?:import|from|require)\s+['"]([^'"]+)['"]/g
          let match
          while ((match = importRegex.exec(content)) !== null) {
            imports.push(match[1])
          }
          context.imports = imports
        }
        break

      case "extract-exports":
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const exports: string[] = []
          const exportRegex = /(?:export\s+(?:default\s+)?(?:function|class|const|let|var)\s+)(\w+)/g
          let match
          while ((match = exportRegex.exec(content)) !== null) {
            exports.push(match[1])
          }
          context.exports = exports
        }
        break

      case "git-status":
        try {
          const { stdout } = await execFileP("git", ["status", "--porcelain", filePath], {
            cwd: repoRoot,
            timeout: 5000,
          })
          context.gitStatus = stdout.trim() || "clean"
          context.isNew = stdout.includes("??")
          context.isModified = stdout.includes("M ")
        } catch {
          context.gitStatus = "unknown"
        }
        break

      case "git-diff":
        try {
          // Get git diff for the file
          const { stdout: diffOutput } = await execFileP("git", ["diff", "HEAD", "--", filePath], {
            cwd: repoRoot,
            timeout: 5000,
          })
          context.gitDiff = diffOutput || ""
          context.hasChanges = diffOutput.length > 0
          
          // Analyze diff for completeness indicators
          if (diffOutput) {
            const addedLines = (diffOutput.match(/^\+[^+]/gm) || []).length
            const removedLines = (diffOutput.match(/^-[^-]/gm) || []).length
            const filesChanged = (diffOutput.match(/^diff --git/gm) || []).length
            
            context.addedLines = addedLines
            context.removedLines = removedLines
            context.filesChanged = filesChanged
            
            // Check for incomplete indicators
            const hasConflictMarkers = diffOutput.includes("<<<<<<<") || 
                                      diffOutput.includes(">>>>>>>") ||
                                      diffOutput.includes("=======")
            context.hasConflicts = hasConflictMarkers
            
            // Check for related changes (same file, different sections)
            const sections = diffOutput.split(/^@@/gm).length - 1
            context.patchSections = sections
            
            // Simple heuristic: if more than 3 sections, might be incomplete
            context.isComplete = sections <= 3 && !hasConflictMarkers
            context.hasRelatedChanges = sections > 1
          }
        } catch {
          context.gitDiff = ""
          context.hasChanges = false
        }
        break

      case "file-info":
        if (existsSync(filePath)) {
          const stat = await import("node:fs").then((fs) => fs.statSync(filePath))
          context.fileSize = stat.size
          context.fileModified = stat.mtime.toISOString()
          context.extension = extname(filePath)
          context.fileName = basename(filePath)
          context.directory = dirname(filePath)
        }
        break

      case "syntax-check":
        if (existsSync(filePath)) {
          const ext = extname(filePath)
          let syntaxValid = true
          let syntaxError = ""

          try {
            if (ext === ".ts") {
              // TypeScript syntax check
              await execFileP("npx", ["tsc", "--noEmit", filePath], {
                cwd: repoRoot,
                timeout: 10000,
              })
            } else if (ext === ".py") {
              // Python syntax check
              await execFileP("python3", ["-m", "py_compile", filePath], {
                cwd: repoRoot,
                timeout: 5000,
              })
            } else if (ext === ".sh") {
              // Shell syntax check
              await execFileP("bash", ["-n", filePath], {
                cwd: repoRoot,
                timeout: 5000,
              })
            }
          } catch (err: any) {
            syntaxValid = false
            syntaxError = err.message?.slice(0, 200) || "syntax error"
          }

          context.syntaxValid = syntaxValid
          context.syntaxError = syntaxError

          // Basic quality metrics
          const content = readFileSync(filePath, "utf-8")
          const lines = content.split("\n")
          context.lineCount = lines.length
          context.emptyLines = lines.filter((l: string) => l.trim() === "").length
          context.commentLines = lines.filter((l: string) => 
            l.trim().startsWith("//") || 
            l.trim().startsWith("#") || 
            l.trim().startsWith("/*") || 
            l.trim().startsWith("*")
          ).length

          // Simple quality score
          const hasExports = content.includes("export ")
          const hasImports = content.includes("import ")
          const hasComments = context.commentLines > 0
          context.qualityScore = "medium"
          if (hasExports && hasImports && hasComments) {
            context.qualityScore = "high"
          } else if (!hasExports && !hasImports) {
            context.qualityScore = "low"
          }
        }
        break

      case "dependency-check":
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const imports: string[] = []
          const missingDependencies: string[] = []
          let hasVersionConflict = false

          // Parse imports based on file extension
          const ext = extname(filePath)
          if (ext === ".ts") {
            // TypeScript imports
            const importRegex = /(?:import|from)\s+['"]([^'"]+)['"]/g
            let match
            while ((match = importRegex.exec(content)) !== null) {
              imports.push(match[1])
            }
          } else if (ext === ".py") {
            // Python imports
            const importRegex = /(?:import|from)\s+(\S+)/g
            let match
            while ((match = importRegex.exec(content)) !== null) {
              imports.push(match[1])
            }
          } else if (ext === ".sh") {
            // Shell script dependencies (source commands)
            const sourceRegex = /source\s+['"]([^'"]+)['"]/g
            let match
            while ((match = sourceRegex.exec(content)) !== null) {
              imports.push(match[1])
            }
          }

          // Check if dependencies exist
          for (const imp of imports) {
            // Skip relative imports and external packages
            if (imp.startsWith(".") || imp.startsWith("/")) {
              // Check if local file exists
              const localPath = join(dirname(filePath), imp)
              if (!existsSync(localPath) && !existsSync(localPath + ".ts") && !existsSync(localPath + ".py")) {
                missingDependencies.push(imp)
              }
            }
            // Check for version conflicts in package.json (simplified)
            if (ext === ".ts" && imp.includes("@")) {
              // This is a scoped package, check package.json
              const packageJsonPath = join(repoRoot, "package.json")
              if (existsSync(packageJsonPath)) {
                const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8"))
                const [scope, name] = imp.split("/")
                const packageName = `${scope}/${name}`
                if (packageJson.dependencies?.[packageName] || packageJson.devDependencies?.[packageName]) {
                  // Package exists, version check would go here
                  // For now, just mark as potentially having version conflict
                }
              }
            }
          }

          context.imports = imports
          context.missingDependencies = missingDependencies.length > 0 ? "true" : "false"
          context.missingDependenciesList = missingDependencies
          context.hasVersionConflict = hasVersionConflict
          context.importCount = imports.length
        }
        break

      case "conflict-check":
        if (existsSync(filePath)) {
          const content = readFileSync(filePath, "utf-8")
          const exports: string[] = []
          let hasConflict = false
          let conflictType = ""
          let conflictDetails = ""

          // Extract exports from current file
          const exportRegex = /(?:export\s+(?:default\s+)?(?:function|class|const|let|var)\s+)(\w+)/g
          let match
          while ((match = exportRegex.exec(content)) !== null) {
            exports.push(match[1])
          }

          // Scan for potential conflicts in the same directory
          const dir = dirname(filePath)
          const files = readdirSync(dir).filter(f => f !== basename(filePath))
          
          for (const file of files) {
            if (!file.endsWith(".ts") && !file.endsWith(".py") && !file.endsWith(".sh")) {
              continue
            }
            
            const otherFilePath = join(dir, file)
            try {
              const otherContent = readFileSync(otherFilePath, "utf-8")
              
              // Check for function signature overlaps
              const otherFunctions = otherContent.match(/(?:function|const|let|var)\s+(\w+)/g) || []
              const currentFunctions = content.match(/(?:function|const|let|var)\s+(\w+)/g) || []
              
              for (const func of currentFunctions) {
                if (otherFunctions.includes(func)) {
                  hasConflict = true
                  conflictType = "function_overlap"
                  conflictDetails = `Function ${func} already exists in ${file}`
                  break
                }
              }
              
              if (hasConflict) break
              
              // Check for duplicate logic (simplified: check for similar patterns)
              const currentPatterns = content.match(/(?:if|for|while|switch)\s*\(/g) || []
              const otherPatterns = otherContent.match(/(?:if|for|while|switch)\s*\(/g) || []
              
              if (currentPatterns.length > 3 && otherPatterns.length > 3) {
                // Both files have complex logic, potential for duplicate
                hasConflict = true
                conflictType = "duplicate_logic"
                conflictDetails = `Both files have complex logic patterns, potential duplication`
              }
              
              // Check for naming conflicts
              if (exports.length > 0) {
                const otherExports = otherContent.match(/(?:export\s+(?:default\s+)?(?:function|class|const|let|var)\s+)(\w+)/g) || []
                for (const exp of exports) {
                  if (otherExports.some(other => other.includes(exp))) {
                    hasConflict = true
                    conflictType = "naming_conflict"
                    conflictDetails = `Export ${exp} already exists in ${file}`
                    break
                  }
                }
              }
            } catch {
              // Skip files that can't be read
            }
          }

          context.exports = exports
          context.hasConflict = hasConflict ? "true" : "false"
          context.conflictType = conflictType
          context.conflictDetails = conflictDetails
          context.exportsCount = exports.length
        }
        break
    }
  }

  return context
}

// ─── Socratic Tree Evaluation ────────────────────────────────────────────────

async function evaluateTree(
  treePath: string,
  context: GapContext,
  repoRoot: string
): Promise<{ decision: string; truth: string; certified: boolean; home?: string }> {
  // Resolve engine via findScript (same pattern as socratic-shell)
  const enginePath = findScript(repoRoot, ENGINE_REL)
  if (!enginePath) {
    return { decision: "ERROR", truth: "engine not found", certified: false }
  }

  // Resolve tree via repo root
  const treeAbs = join(repoRoot, treePath)
  if (!existsSync(treeAbs)) {
    return { decision: "ERROR", truth: "tree not found", certified: false }
  }

  try {
    // Build docType from content (same pattern as vsf-classify-on-write)
    const docType = context.content?.match(/⟦\s*[^|]+\|\s*([^|]+)\s*\|/)?.[1] || ""
    
    // Skip if no docType (R9: no TYPE → '?' visible, no grito)
    if (!docType) {
      return { decision: "UNKNOWN", truth: "no doc type", certified: false }
    }

    const { stdout } = await execFileP(
      "python3", [enginePath, "eval-tree", treeAbs, "--doc-type", docType],
      { 
        env: { ...process.env },
        maxBuffer: 10 * 1024 * 1024,
        timeout: 10_000,
      }
    )

    const result = JSON.parse(stdout)
    return {
      decision: result.home || result.decision || "UNKNOWN",
      truth: result.truth || "UNCERTAIN",
      certified: result.certified || false,
      home: result.home,
    }
  } catch (err: any) {
    return { decision: "ERROR", truth: err.message?.slice(0, 200), certified: false }
  }
}

// ─── Action Executors ────────────────────────────────────────────────────────

async function executeAction(
  action: string,
  params: Record<string, any>,
  context: GapContext,
  repoRoot: string,
  autoMode: boolean
): Promise<{ executed: boolean; detail: string }> {
  switch (action) {
    case "move-file": {
      const source = context.filePath
      const targetDir = params.target || context.recommendedDirectory
      if (!targetDir) {
        return { executed: false, detail: "no target directory" }
      }

      const targetPath = join(repoRoot, targetDir, basename(source))

      if (autoMode) {
        // AUTOMATIC: move file directly
        try {
          mkdirSync(dirname(targetPath), { recursive: true })
          copyFileSync(source, targetPath)
          // Note: actual delete would need R17 consent
          return { executed: true, detail: `moved to ${targetDir}` }
        } catch (err: any) {
          return { executed: false, detail: err.message }
        }
      } else {
        // SEMI-AUTOMATIC: suggest move
        return {
          executed: false,
          detail: `SUGGEST: move ${basename(source)} to ${targetDir}`,
        }
      }
    }

    case "create-handler": {
      const scriptName = context.fileName?.replace(/\.(py|sh)$/, "")
      const category = context.directory?.match(/scripts\/state\/(\w+)/)?.[1] || "unknown"
      const handlerPath = join(repoRoot, ".opencode/plugins/operational/handlers", `${category}-auto.ts`)

      if (existsSync(handlerPath)) {
        return { executed: false, detail: `handler already exists: ${category}-auto.ts` }
      }

      if (autoMode) {
        // AUTOMATIC: create handler
        const handlerContent = `
/**
 * ${category}-auto.ts — auto-created handler for ${category} scripts.
 * Generated by gap-resolver.ts
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

export const ${category}AutoHandler: Handler = {
  id: "${category}-auto",
  priority: 5,
  events: ["session.idle"],
  classify: async () => true,
  execute: async (ctx) => {
    const script = join(ctx.repoRoot, "scripts/state/${category}/${scriptName}${extname(context.filePath)}")
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
        return { executed: true, detail: `created handler: ${category}-auto.ts` }
      } else {
        // SEMI-AUTOMATIC: suggest creation
        return {
          executed: false,
          detail: `SUGGEST: create handler for ${category}/${scriptName}`,
        }
      }
    }

    case "alert-conflict": {
      const message = params.message || "Conflict detected"
      return { executed: false, detail: `ALERT: ${message}` }
    }

    case "block-commit": {
      const reason = params.reason || "Quality gate failed"
      return { executed: false, detail: `BLOCK: ${reason}` }
    }

    case "log-success": {
      return { executed: true, detail: "OK" }
    }

    default:
      return { executed: false, detail: `unknown action: ${action}` }
  }
}

// ─── Gap Resolver Core ───────────────────────────────────────────────────────

export async function resolveGap(
  gapDef: GapDefinition,
  filePath: string,
  repoRoot: string,
  autoMode: boolean = AUTO_MODE
): Promise<GapResult> {
  const result: GapResult = {
    gapId: gapDef.id,
    trigger: gapDef.trigger.type,
    decision: "",
    home: undefined,
    actions: [],
    autoExecuted: autoMode,
    timestamp: new Date().toISOString(),
  }

  // 1. Check trigger match
  const fileExt = extname(filePath)
  const fileDir = dirname(filePath)
  const fileName = basename(filePath)

  let triggerMatch = false
  if (gapDef.trigger.patterns) {
    triggerMatch = gapDef.trigger.patterns.some((p) => {
      if (p.startsWith("*")) return fileExt === p.slice(1) || fileExt === p.slice(2)
      return fileName.includes(p)
    })
  }
  if (gapDef.trigger.directories) {
    triggerMatch = triggerMatch || gapDef.trigger.directories.some((d) => fileDir.includes(d))
  }

  if (!triggerMatch) {
    result.decision = "SKIP"
    return result
  }

  // 2. Gather context
  const context = await gatherContext(gapDef.context.gatherers, filePath, repoRoot)

  // 3. Evaluate
  if (gapDef.evaluation.type === "socratic-tree" && gapDef.evaluation.tree) {
    const evalResult = await evaluateTree(gapDef.evaluation.tree, context, repoRoot)
    result.decision = evalResult.decision
    result.home = evalResult.home

    // Enrich context with evaluation result
    context.decision = evalResult.decision
    context.truth = evalResult.truth
    context.certified = evalResult.certified
    context.home = evalResult.home
  } else {
    // Rule-based evaluation (simple pattern matching)
    result.decision = "RULE_BASED"
  }

  // 4. Execute actions
  for (const actionDef of gapDef.actions) {
    // Evaluate condition
    const condition = actionDef.condition
    let conditionMet = false

    if (condition.includes("decision ===")) {
      const expectedDecision = condition.match(/decision === '([^']+)'/)?.[1]
      conditionMet = result.decision === expectedDecision
    } else if (condition.includes("truth ===")) {
      const expectedTruth = condition.match(/truth === '([^']+)'/)?.[1]
      conditionMet = context.truth === expectedTruth
    } else if (condition === "true" || condition === "always") {
      conditionMet = true
    }

    if (conditionMet) {
      const actionResult = await executeAction(
        actionDef.action,
        actionDef.params || {},
        context,
        repoRoot,
        autoMode
      )
      result.actions.push(actionResult.detail)
    }
  }

  // 5. Log result
  await logGapResolution(result, repoRoot)

  return result
}

async function logGapResolution(result: GapResult, repoRoot: string): Promise<void> {
  const logPath = join(repoRoot, GAP_LOG_FILE)
  const logDir = dirname(logPath)

  if (!existsSync(logDir)) {
    mkdirSync(logDir, { recursive: true })
  }

  const logEntry = JSON.stringify(result) + "\n"
  writeFileSync(logPath, logEntry, { flag: "a" })
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

export default (): Plugin => {
  return {
    name: "gap-resolver",
    hooks: [
      // On file write: resolve gaps for new/modified files
      {
        event: "tool.execute.after",
        async handler({ directory, input }) {
          const toolName = input?.tool || ""
          if (!["write", "edit"].includes(toolName)) {
            return { result: "skip", durationMs: 0, detail: "not a write tool" }
          }

          const filePath = input?.filePath || input?.path || ""
          if (!filePath) return { result: "skip", durationMs: 0, detail: "no file path" }

          const start = Date.now()
          const repoRoot = directory || process.cwd()

          // Load gap definitions from registry (unified source)
          let gapDefs: GapDefinition[] = []
          
          // 1. Try loading from gate registry (includes static + RSI-generated)
          gapDefs = await loadGapDefinitionsFromRegistry(repoRoot)
          
          // 2. Fallback to file-based loading if registry unavailable
          if (gapDefs.length === 0) {
            const defsDir = join(repoRoot, ".opencode/plugins/operational", GAP_DEFINITIONS_DIR)
            if (existsSync(defsDir)) {
              const gapFiles = readdirSync(defsDir).filter((f) => f.endsWith(".gap.json"))
              for (const gapFile of gapFiles) {
                const gapPath = join(defsDir, gapFile)
                const gapDef: GapDefinition = JSON.parse(readFileSync(gapPath, "utf-8"))
                gapDefs.push(gapDef)
              }
            }
          }

          if (gapDefs.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no gap definitions" }
          }

          const results: GapResult[] = []
          for (const gapDef of gapDefs) {
            const result = await resolveGap(gapDef, filePath, repoRoot)
            if (result.decision !== "SKIP") {
              results.push(result)
            }
          }

          const duration = Date.now() - start
          const detail = results.length > 0
            ? results.map((r) => `${r.gapId}: ${r.decision}`).join("; ")
            : "no gaps triggered"

          await logActivation("gap-resolver", "tool.execute.after", "resolve", detail)

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail,
            summary: `${results.length} gaps resolved`,
          }
        },
      },

      // On session idle: resolve gaps for all tracked files
      {
        event: "session.idle",
        async handler({ directory }) {
          const start = Date.now()
          const repoRoot = directory || process.cwd()

          // Load gap definitions from registry (unified source)
          let gapDefs: GapDefinition[] = []
          
          // 1. Try loading from gate registry (includes static + RSI-generated)
          gapDefs = await loadGapDefinitionsFromRegistry(repoRoot)
          
          // 2. Fallback to file-based loading if registry unavailable
          if (gapDefs.length === 0) {
            const defsDir = join(repoRoot, ".opencode/plugins/operational", GAP_DEFINITIONS_DIR)
            if (existsSync(defsDir)) {
              const gapFiles = readdirSync(defsDir).filter((f) => f.endsWith(".gap.json"))
              for (const gapFile of gapFiles) {
                const gapPath = join(defsDir, gapFile)
                const gapDef: GapDefinition = JSON.parse(readFileSync(gapPath, "utf-8"))
                gapDefs.push(gapDef)
              }
            }
          }

          if (gapDefs.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no gap definitions" }
          }

          const results: GapResult[] = []

          // Scan for files that might need gap resolution
          const scanDirs = [".opencode/plugins", "scripts/state"]
          for (const scanDir of scanDirs) {
            const fullDir = join(repoRoot, scanDir)
            if (!existsSync(fullDir)) continue

            // Simple scan: check for .ts, .py, .sh files
            const files = readdirSync(fullDir, { recursive: true })
              .filter((f): f is string => typeof f === "string" && /\.(ts|py|sh)$/.test(f))

            for (const file of files.slice(0, 10)) { // Limit to 10 files per session
              const filePath = join(fullDir, file)
              for (const gapDef of gapDefs) {
                const result = await resolveGap(gapDef, filePath, repoRoot)
                if (result.decision !== "SKIP") {
                  results.push(result)
                }
              }
            }
          }

          const duration = Date.now() - start
          const detail = results.length > 0
            ? results.map((r) => `${r.gapId}: ${r.decision}`).join("; ")
            : "no gaps triggered"

          await logActivation("gap-resolver", "session.idle", "resolve", detail)

          return {
            result: results.length > 0 ? "ok" : "skip",
            durationMs: duration,
            detail,
            summary: `${results.length} gaps resolved`,
          }
        },
      },
    ],
  }
}
