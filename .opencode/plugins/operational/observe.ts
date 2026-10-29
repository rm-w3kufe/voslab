/**
 * vsf-observe — OBSERVE class instance.
 * design: docs/design/sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * CLASS-OBSERVE: any activation → "¿quién corrió y qué pasó?"
 * authority: log-only (S5 directiva: observa y mejora)
 *
 * Evaluates if an activation should be logged:
 * 1. Is there an instrument?
 * 2. Is there a hook?
 * 3. Is there a result?
 */
import type { Plugin } from "@opencode-ai/plugin";
import { socraticShell } from "../support/vsf-socratic-shell";
// EXPORT CONTRACT (incident 2026-09-23/24, RC-1): opencode invokes EVERY
// function export as a Plugin factory (Object.values). DO NOT add
// `export default` unless it is a Plugin object/function — an array
// or void export breaks the loader for the whole module. Named
// `export const X: Plugin` entries are safe (cf. decide.ts pattern).

export const ObserveTree: Plugin = socraticShell({
  classId: "OBSERVE",
  treeRel: ".opencode/plugins/support/trees/observe.tree.vsm",
  hook: "event:session.idle",
  context: (_input: any, _output: any, repoRoot: string) => {
    return { type: "OBSERVE", repoRoot };
  },
});
