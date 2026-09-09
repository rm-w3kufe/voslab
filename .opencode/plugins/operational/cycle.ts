/**
 * vsf-cycle — CYCLE class instance.
 * design: docs/spec_revision/design-sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * CLASS-CYCLE: session.idle → "¿el ciclo está vivo? ¿hay aprendizaje que registrar?"
 * authority: advisory (S2/S3*/S4 observability)
 *
 * Evaluates if the learning cycle is active:
 * 1. Is there session_learning_scan.sh?
 * 2. Is there learning_stats.py?
 * 3. Did the scan pass?
 */
import type { Plugin } from "@opencode-ai/plugin";
import { socraticShell } from "../support/vsf-socratic-shell";

export const CycleTree: Plugin = socraticShell({
  classId: "CYCLE",
  treeRel: ".opencode/plugins/support/trees/cycle.tree.vsm",
  hook: "event:session.idle",
  context: (_input: any, _output: any, repoRoot: string) => {
    return { type: "CYCLE", repoRoot };
  },
});
