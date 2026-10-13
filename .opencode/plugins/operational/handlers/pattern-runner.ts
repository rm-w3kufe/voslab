// design: docs/spec_revision/design-sources/pattern-runner-v1/pattern_runner.vsm
/**
 * pattern-runner.ts — declarative trigger registry (generalizes
 * scripts-automation.ts).
 *
 * DESIGN (PATTERN-RUNNER-v1): ONE generic handler reads a registry
 * (scripts/state/pattern_registry.json) of rules {on, match, run, args,
 * timeout_ms, driver, consent, desc} and executes them deterministically.
 * The handler holds NO business logic: it classifies (cheap, R10
 * deterministic) then spawns. Adding a trigger = editing the registry,
 * never this file (R16: policy declares, instrument interprets).
 *
 * RAILS (blocking, not advisory):
 * - R10: match ops are deterministic (equals|glob|regex|prefix|present);
 *   regex compiles once at load; no random, no time-dependence in classify.
 * - R17: consent=needs-nod → the runner REFUSES to spawn (blocked_reason).
 *   destructive rules cannot enter the registry without an explicit S5 nod.
 * - R9: a rule whose script is missing → visible detail + alert; silence
 *   is a breach. Failures route to state/rsi/alerts.jsonl (algedonic).
 * - R16: this file must not grow per-script logic; migrate to the registry.
 * - Doctrine C: deploy/firewall/publishing/LLM scripts stay OUT of the
 *   registry by design (see pattern_runner.vsm §3 scope).
 */
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { existsSync, readFileSync, appendFileSync } from "node:fs"
import { join, resolve, sep } from "node:path"
import { logActivation } from "../../../shared/log-activation"
import type { Handler, HandlerContext } from "../vsf-event-router"

const execFileP = promisify(execFile)

// ─── Registry schema (mirrors pattern_runner.vsm §1) ─────────────────────────

type MatchOp = "equals" | "glob" | "regex" | "prefix" | "present"
type Consent = "read-only" | "advisory" | "needs-nod"

interface MatchClause {
  field: string // event | tool_name | file_path | git_branch | <payload key>
  op: MatchOp
  pattern?: string // absent only for op=present
}

export interface RegistryRule {
  id: string
  on: string // event to subscribe (session.idle | tool.execute.after | ...)
  match: MatchClause[] // ALL clauses must hold (AND) — R10 deterministic
  run: string // repo-relative script path
  args: string[]
  timeout_ms?: number // default 15_000, ceiling 60_000
  driver: string // Sn that owns the algedonic channel (S1..S5)
  consent: Consent
  desc: string
}

const REGISTRY_REL = "scripts/state/pattern_registry.json"
const ALERTS_REL = "state/rsi/alerts.jsonl"
const DEFAULT_TIMEOUT = 15_000
const TIMEOUT_CEILING = 60_000

// ─── Deterministic matchers (R10) ────────────────────────────────────────────

const globCache = new Map<string, RegExp>()

/** Convert a simple glob to aanchored RegExp (cached). Deterministic. */
function globToRegex(glob: string): RegExp {
  const cached = globCache.get(glob)
  if (cached) return cached
  const escaped = glob
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".")
  const re = new RegExp(`^${escaped}$`)
  globCache.set(glob, re)
  return re
}

const regexCache = new Map<string, RegExp>()

function compileRegex(pattern: string): RegExp | null {
  const cached = regexCache.get(pattern)
  if (cached) return cached
  try {
    const re = new RegExp(pattern)
    regexCache.set(pattern, re)
    return re
  } catch {
    return null // invalid regex → rule cannot match (R9: surfaced in detail)
  }
}

/** Extract a field from context (structural only — no IO). */
function fieldValue(ctx: HandlerContext, field: string): string {
  const payload: any = (ctx as any).payload ?? {}
  switch (field) {
    case "event":
      return ctx.event
    case "tool_name":
      return String(payload.tool ?? "")
    case "file_path": {
      const a: any = payload.args ?? {}
      return String(a.file_path ?? a.filePath ?? "")
    }
    case "git_branch":
      return String(payload.git_branch ?? process.env.GIT_BRANCH ?? "")
    default:
      return String(payload[field] ?? "")
  }
}

/** One clause against context. Pure, deterministic (R10). */
function clauseHolds(ctx: HandlerContext, c: MatchClause): boolean {
  const value = fieldValue(ctx, c.field)
  switch (c.op) {
    case "present":
      return value !== ""
    case "equals":
      return value === (c.pattern ?? "")
    case "prefix":
      return value.startsWith(c.pattern ?? "")
    case "glob":
      return globToRegex(c.pattern ?? "").test(value)
    case "regex": {
      const re = compileRegex(c.pattern ?? "")
      return re !== null && re.test(value)
    }
    default:
      return false // unknown op → no match (never guess, R9)
  }
}

function ruleMatches(ctx: HandlerContext, rule: RegistryRule): boolean {
  if (rule.on !== ctx.event) return false
  return rule.match.every((c) => clauseHolds(ctx, c))
}

// ─── Registry loading (lazy, once) ───────────────────────────────────────────

let cachedRegistry: RegistryRule[] | null = null
let cachedRoot = ""

function loadRegistry(repoRoot: string): RegistryRule[] {
  if (cachedRegistry && cachedRoot === repoRoot) return cachedRegistry
  const path = join(repoRoot, REGISTRY_REL)
  if (!existsSync(path)) {
    cachedRegistry = []
    cachedRoot = repoRoot
    return cachedRegistry
  }
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8"))
    const rules: RegistryRule[] = Array.isArray(parsed) ? parsed : parsed.rules ?? []
    // Deterministic order regardless of file order (R10): sort by id.
    rules.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    cachedRegistry = rules
    cachedRoot = repoRoot
    return rules
  } catch {
    cachedRegistry = []
    cachedRoot = repoRoot
    return []
  }
}

// ─── Algedonic failure routing (R9) ──────────────────────────────────────────

let alertCounter = 0

/** Append one alert row. Fire-and-forget; never throws into the caller. */
function emitAlert(repoRoot: string, rule: RegistryRule, detail: string): void {
  try {
    alertCounter += 1
    const row = {
      alert_id: `alert-${Date.now()}-${process.pid % 10000}${alertCounter}`,
      ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      level: "error",
      alert_type: "pattern_runner_fail",
      source: `pattern-runner(${rule.driver})`,
      detail: `${rule.id}: ${detail}`.slice(0, 2000),
    }
    appendFileSync(join(repoRoot, ALERTS_REL), JSON.stringify(row) + "\n")
  } catch {
    // alerts.jsonl unwritable — degradation is visible via missing rows;
    // never let alerting break execution (advisory fail-open, G-34 pattern)
  }
}

// ─── The handler ─────────────────────────────────────────────────────────────

export const patternRunnerHandler: Handler = {
  id: "pattern-runner",
  priority: 3,
  // Channels declared in pattern_runner.vsm §5. A registry rule whose `on`
  // is outside this set never runs — add the channel here consciously.
  events: [
    "session.idle",
    "session.created",
    "tool.execute.after",
    "file.edited",
    "git.post-commit",
  ],

  classify: async (ctx) => {
    const rules = loadRegistry(ctx.repoRoot)
    return rules.some((r) => ruleMatches(ctx, r))
  },

  execute: async (ctx) => {
    const start = Date.now()
    const rules = loadRegistry(ctx.repoRoot).filter((r) => ruleMatches(ctx, r))
    const results: string[] = []
    let ranCount = 0
    let blockedCount = 0
    let errorCount = 0

    for (const rule of rules) {
      // R17 rail: needs-nod rules never spawn without an explicit nod.
      if (rule.consent === "needs-nod") {
        blockedCount += 1
        results.push(`${rule.id}: BLOCKED (R17 needs-nod, awaiting S5)`)
        continue
      }

      const scriptPath = resolve(ctx.repoRoot, rule.run)
      // Scope fence: the script must live inside the repo (doctrine C).
      if (!scriptPath.startsWith(ctx.repoRoot + sep)) {
        blockedCount += 1
        results.push(`${rule.id}: BLOCKED (path outside repo)`)
        continue
      }
      if (!existsSync(scriptPath)) {
        errorCount += 1
        results.push(`${rule.id}: script not found (${rule.run})`)
        emitAlert(ctx.repoRoot, rule, `script not found: ${rule.run}`)
        continue
      }

      const timeout = Math.min(rule.timeout_ms ?? DEFAULT_TIMEOUT, TIMEOUT_CEILING)
      try {
        // Shebang decides interpreter — deterministic, no guessing.
        const head = readFileSync(scriptPath, "utf-8").slice(0, 64)
        const interpreter = head.includes("python") ? "python3" : "bash"
        await execFileP(interpreter, [scriptPath, ...rule.args], {
          timeout,
          cwd: ctx.repoRoot,
        })
        results.push(`${rule.id}: OK`)
        ranCount++
      } catch (e: any) {
        errorCount++
        const detail =
          e?.stdout?.slice(0, 200) || e?.message?.slice(0, 200) || "unknown error"
        const timedOut = e?.killed === true || e?.signal === "SIGTERM"
        results.push(`${rule.id}: ${timedOut ? "TIMEOUT" : "FAIL"} ${detail}`)
        emitAlert(ctx.repoRoot, rule, timedOut ? `timeout ${timeout}ms` : detail)
      }
    }

    const durationMs = Date.now() - start
    const detail = results.join("; ")
    const result: "ok" | "warn" | "error" =
      errorCount > 0 ? "error" : blockedCount > 0 ? "warn" : "ok"

    await logActivation(
      ctx.repoRoot,
      "pattern-runner",
      ctx.event,
      "execute",
      result,
      detail,
      {
        durationMs,
        rules_matched: rules.length,
        rules_ran: ranCount,
        rules_blocked: blockedCount,
        rules_failed: errorCount,
      },
    )

    return {
      result: errorCount > 0 ? "error" : "ok",
      durationMs,
      detail,
    }
  },
}
