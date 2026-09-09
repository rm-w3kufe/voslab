/**
 * socratic-hook-engine.ts — Dynamic hook evaluation via socratic trees.
 *
 * REASONING: Instead of hardcoding hook logic in TypeScript, each hook
 * DECLARES its decision tree (socratic tree). A common interpreter
 * evaluates the tree against event dimensions (tool, ext, marker, etc.)
 * and executes the appropriate action.
 *
 * This is the production implementation of the concept in
 * scripts/vsl/classifier/socratic_hooks.py
 *
 * DESIGN:
 * - Each hook registers a socratic tree with:
 *   - id: unique identifier
 *   - trigger: event type(s) that activate it
 *   - tree: socratic decision tree (AND/OR/predicate)
 *   - actions: map of home → action to execute
 * - On event, engine evaluates all matching trees
 * - First tree that resolves to a non-'?' home executes its action
 * - Actions can be: "block", "warn", "log", "run:<script>", etc.
 */
import { exec } from "node:child_process"
import { promisify } from "node:util"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { logActivation } from "../../shared/log-activation"
import type { Handler } from "../vsf-event-router"

const execP = promisify(exec)

// ─── Tree Types ──────────────────────────────────────────────────────────────

interface PredicateNode {
  predicate: string
  args: (string | number | boolean)[]
}

interface OperatorNode {
  op: "AND" | "OR" | "NOT"
  children: SocraticNode[]
}

type SocraticNode = PredicateNode | OperatorNode

interface HookTree {
  id: string
  description: string
  trigger: string[] // event types: ["tool.execute.before", "tool.execute.after", "session.idle"]
  tree: SocraticNode & { else_home?: string }
  actions: Record<string, (ctx: HookContext) => Promise<void>>
}

interface HookContext {
  repoRoot: string
  event: string
  tool?: string
  file?: string
  ext?: string
  command?: string
  marker?: string
  [key: string]: any
}

// ─── Predicate Library ───────────────────────────────────────────────────────

const PREDICATES: Record<string, (...args: any[]) => boolean> = {
  // Tool predicates
  tool_is: (tool: string, expected: string) => tool === expected,
  tool_in: (tool: string, ...list: string[]) => list.includes(tool),
  tool_glob: (tool: string, pattern: string) => {
    const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$")
    return regex.test(tool)
  },

  // File predicates
  ext_is: (ext: string, expected: string) => ext === expected,
  ext_in: (ext: string, ...list: string[]) => list.includes(ext),
  ext_glob: (ext: string, pattern: string) => {
    const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$")
    return regex.test(ext)
  },
  file_glob: (file: string, pattern: string) => {
    const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$")
    return regex.test(file)
  },

  // Marker predicates
  marker_contains: (marker: string, text: string) => marker.includes(text),
  marker_glob: (marker: string, pattern: string) => {
    const regex = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$")
    return regex.test(marker)
  },

  // Event predicates
  event_is: (event: string, expected: string) => event === expected,
  event_glob: (event: string, pattern: string) => {
    const regex = new RegExp("^" + pattern.replace(/\*/g, ".*").replace(/\./g, "\\.") + "$")
    return regex.test(event)
  },

  // State predicates
  has_work: () => true, // placeholder — would check current_focus.json
  file_exists: (file: string, root: string) => existsSync(join(root, file)),
}

// ─── Tree Evaluator ──────────────────────────────────────────────────────────

function evaluateTree(
  node: SocraticNode,
  ctx: Record<string, any>,
): boolean {
  if (!node) return false

  // Predicate node
  if ("predicate" in node) {
    const pred = PREDICATES[node.predicate]
    if (!pred) return false

    // Resolve $variable references in args
    const resolvedArgs = node.args.map((arg) => {
      if (typeof arg === "string" && arg.startsWith("$")) {
        const varName = arg.slice(1)
        return ctx[varName] ?? arg
      }
      return arg
    })

    return pred(...resolvedArgs)
  }

  // Operator node
  if ("op" in node) {
    const children = (node as OperatorNode).children || []
    const results = children.map((child) => evaluateTree(child, ctx))

    switch ((node as OperatorNode).op) {
      case "AND":
        return results.every(Boolean)
      case "OR":
        return results.some(Boolean)
      case "NOT":
        return !results[0]
      default:
        return false
    }
  }

  return false
}

function resolveHome(
  tree: HookTree["tree"],
  ctx: Record<string, any>,
): string | null {
  // Check each child branch
  if ("children" in tree) {
    for (const child of tree.children) {
      if (evaluateTree(child, ctx)) {
        // Return the home from the child if it has one
        if ("home" in child) return (child as any).home
        // Otherwise check nested children
        if ("children" in child) {
          const nested = resolveHome(child as any, ctx)
          if (nested) return nested
        }
      }
    }
  }

  // Check the tree itself
  if ("home" in tree) {
    if (evaluateTree(tree, ctx)) {
      return (tree as any).home
    }
  }

  // Return else_home if no branch matched
  return (tree as any).else_home || null
}

// ─── Built-in Hook Trees ─────────────────────────────────────────────────────

const BUILTIN_HOOKS: HookTree[] = [
  // vsl-check-on-write: check .vsm writes for version violations
  {
    id: "vsl-check-socratic",
    description: "Socratic tree for .vsm write checks",
    trigger: ["tool.execute.after"],
    tree: {
      op: "OR",
      children: [
        {
          op: "AND",
          children: [
            { predicate: "tool_in", args: ["$tool", "write", "edit"] },
            { predicate: "ext_is", args: ["$ext", ".vsm"] },
            { predicate: "marker_contains", args: ["$marker", "version"] },
          ],
          home: "BLOCK",
        },
        {
          op: "AND",
          children: [
            { predicate: "tool_in", args: ["$tool", "write", "edit"] },
            { predicate: "ext_is", args: ["$ext", ".vsm"] },
          ],
          home: "CHECK",
        },
      ],
      else_home: "PASS",
    },
    actions: {
      BLOCK: async (ctx) => {
        await logActivation(ctx.repoRoot, "socratic-hook", ctx.event, "block", "policy_breach", `BLOCKED: ${ctx.tool} on ${ctx.file}`)
      },
      CHECK: async (ctx) => {
        // Run write gate orchestrator
        const script = join(ctx.repoRoot, "scripts/vsl/tools/write_gate_orchestrator.py")
        if (existsSync(script)) {
          try {
            await execP(`python3 "${script}" "${ctx.file}"`, { timeout: 10_000, cwd: ctx.repoRoot })
          } catch (e: any) {
            await logActivation(ctx.repoRoot, "socratic-hook", ctx.event, "warn", "gate_failure", e?.stdout?.slice(0, 200) || "gate failed")
          }
        }
      },
      PASS: async () => {}, // no-op
    },
  },

  // vsf-onboard-reminder: remind about boot on session.idle
  {
    id: "onboard-reminder-socratic",
    description: "Socratic tree for onboarding reminder",
    trigger: ["session.idle"],
    tree: {
      op: "OR",
      children: [
        {
          op: "AND",
          children: [
            { predicate: "event_is", args: ["$event", "session.idle"] },
            { predicate: "file_exists", args: ["system/boot/boot_manifest.vsm", "$repoRoot"] },
          ],
          home: "SILENT",
        },
        {
          op: "AND",
          children: [
            { predicate: "event_is", args: ["$event", "session.idle"] },
          ],
          home: "REMIND",
        },
      ],
      else_home: "PASS",
    },
    actions: {
      SILENT: async () => {}, // boot manifest exists, no reminder needed
      REMIND: async (ctx) => {
        await logActivation(ctx.repoRoot, "socratic-hook", ctx.event, "warn", "boot_reminder", "Boot manifest not cited — run boot sequence")
      },
      PASS: async () => {},
    },
  },

  // learning-cycle-scan: check for learning opportunities
  {
    id: "learning-scan-socratic",
    description: "Socratic tree for learning cycle scan",
    trigger: ["session.idle"],
    tree: {
      op: "OR",
      children: [
        {
          op: "AND",
          children: [
            { predicate: "event_is", args: ["$event", "session.idle"] },
          ],
          home: "SCAN",
        },
      ],
      else_home: "PASS",
    },
    actions: {
      SCAN: async (ctx) => {
        const script = join(ctx.repoRoot, "scripts/state/session_learning_scan.sh")
        if (existsSync(script)) {
          try {
            await execP(`bash "${script}" pass`, { timeout: 10_000, cwd: ctx.repoRoot })
            await logActivation(ctx.repoRoot, "socratic-hook", ctx.event, "ok", "scan_complete", "Learning scan completed")
          } catch (e: any) {
            await logActivation(ctx.repoRoot, "socratic-hook", ctx.event, "warn", "scan_failed", e?.stdout?.slice(0, 200) || "scan failed")
          }
        }
      },
      PASS: async () => {},
    },
  },
]

// ─── Plugin ──────────────────────────────────────────────────────────────────

import type { Plugin } from "@opencode-ai/plugin"

export default (): Plugin => {
  return {
    name: "socratic-hook-engine",
    hooks: [
      {
        event: "tool.execute.after",
        async handler({ directory, input }) {
          const toolName = input?.tool || ""
          const filePath = input?.filePath || input?.path || ""
          const ext = filePath.includes(".") ? "." + filePath.split(".").pop() : ""
          const command = input?.command || ""
          const marker = input?.marker || ""

          const hookCtx: HookContext = {
            repoRoot: directory || process.cwd(),
            event: "tool.execute.after",
            tool: toolName,
            file: filePath,
            ext,
            command,
            marker,
          }

          const matchingHooks = BUILTIN_HOOKS.filter((h) =>
            h.trigger.some((t) => "tool.execute.after".startsWith(t) || "tool.execute.after" === t),
          )

          if (matchingHooks.length === 0) {
            return { result: "skip", durationMs: 0, detail: "no matching hooks" }
          }

          for (const hook of matchingHooks) {
            const home = resolveHome(hook.tree, hookCtx)
            if (home && home !== "PASS" && home !== "?") {
              const action = hook.actions[home]
              if (action) {
                try {
                  await action(hookCtx)
                } catch (e: any) {
                  await logActivation(
                    directory || process.cwd(),
                    "socratic-hook",
                    "tool.execute.after",
                    "error",
                    "action_failed",
                    `Hook ${hook.id} action ${home} failed: ${e?.message?.slice(0, 100)}`,
                  )
                }
              }
            }
          }

          return { result: "ok", durationMs: 0, detail: `${matchingHooks.length} hooks evaluated` }
        },
      },
      {
        event: "session.idle",
        async handler({ directory }) {
          const hookCtx: HookContext = {
            repoRoot: directory || process.cwd(),
            event: "session.idle",
          }

          const matchingHooks = BUILTIN_HOOKS.filter((h) =>
            h.trigger.some((t) => "session.idle".startsWith(t) || "session.idle" === t),
          )

          for (const hook of matchingHooks) {
            const home = resolveHome(hook.tree, hookCtx)
            if (home && home !== "PASS" && home !== "?") {
              const action = hook.actions[home]
              if (action) {
                try {
                  await action(hookCtx)
                } catch (e: any) {
                  await logActivation(
                    directory || process.cwd(),
                    "socratic-hook",
                    "session.idle",
                    "error",
                    "action_failed",
                    `Hook ${hook.id} action ${home} failed: ${e?.message?.slice(0, 100)}`,
                  )
                }
              }
            }
          }

          return { result: "ok", durationMs: 0, detail: `${matchingHooks.length} hooks evaluated` }
        },
      },
    ],
  }
}
