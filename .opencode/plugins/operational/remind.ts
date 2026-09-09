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

export const RemindTree: Plugin = socraticShell({
  classId: "REMIND",
  treeRel: ".opencode/plugins/support/trees/remind.tree.vsm",
  hook: "event:session.start",
  context: (_input: any, _output: any, repoRoot: string) => {
    return { type: "REMIND", repoRoot };
  },
});
