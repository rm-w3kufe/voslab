/**
 * vsf-cycle — CYCLE class instance.
 * design: docs/design/sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * CLASS-CYCLE: session.idle → "¿el ciclo está vivo? ¿hay aprendizaje que registrar?"
 * authority: advisory (S2/S3-star/S4 observability)
 *
 * Evaluates if the learning cycle is active:
 * 1. Is there session_learning_scan.sh?
 * 2. Is there learning_stats.py?
 * 3. Did the scan pass?
 */
import type { Plugin } from "@opencode-ai/plugin";
import { socraticShell } from "../support/vsf-socratic-shell";
// EXPORT CONTRACT (incident 2026-09-23/24, RC-1): opencode invokes EVERY
// function export as a Plugin factory (Object.values). DO NOT add
// `export default` unless it is a Plugin object/function — an array
// or void export breaks the loader for the whole module. Named
// `export const X: Plugin` entries are safe (cf. decide.ts pattern).

export const CycleTree: Plugin = socraticShell({
  classId: "CYCLE",
  treeRel: ".opencode/plugins/support/trees/cycle.tree.vsm",
  hook: "event:session.idle",
  context: (_input: any, _output: any, repoRoot: string) => {
    return { type: "CYCLE", repoRoot };
  },
});
