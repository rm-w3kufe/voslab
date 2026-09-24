/**
 * vsf-remind — REMIND class instance.
 * design: docs/spec_revision/design-sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * CLASS-REMIND: session.start → "¿falta algo declarado? (D2 fail-safe)"
 * authority: advisory (fail-safe reminder)
 *
 * Evaluates if there's anything to remind at session start:
 * 1. Is there an active focus?
 * 2. Are there pending tasks?
 * 3. Is there a recent handoff?
 */
import type { Plugin } from "@opencode-ai/plugin";
import { socraticShell } from "../support/vsf-socratic-shell";
// EXPORT CONTRACT (incident 2026-09-23/24, RC-1): opencode invokes EVERY
// function export as a Plugin factory (Object.values). DO NOT add
// `export default` unless it is a Plugin object/function — an array
// or void export breaks the loader for the whole module. Named
// `export const X: Plugin` entries are safe (cf. decide.ts pattern).

export const RemindTree: Plugin = socraticShell({
  classId: "REMIND",
  treeRel: ".opencode/plugins/support/trees/remind.tree.vsm",
  hook: "event:session.start",
  context: (_input: any, _output: any, repoRoot: string) => {
    return { type: "REMIND", repoRoot };
  },
});
