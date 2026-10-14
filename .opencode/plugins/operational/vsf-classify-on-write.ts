/**
 * vsf-classify-on-write — CLASSIFY class instance (PLUGIN-CLASS-TAXONOMY-v1).
 * design: docs/spec_revision/design-sources/plugin-class-taxonomy-v1/plugin_class_taxonomy.vsm
 *
 * The FIRST real instance of the socratic shell: when a .vsm is written,
 * evaluate the CLASSIFY tree (classify.tree.vsm) against the doc's TYPE and
 * report WHERE the questionnaire says it lives. Write-time universal (fase c):
 * the questionnaire IS the write-time gate — the agent sees immediately if
 * the doc's home matches the tree's answer.
 *
 * BLOCKING (FASE-3-ENFORCEMENT-2026-08-22): when the questionnaire decides
 * a doc is misplaced (truth === "FALSE" with certified evidence), the write
 * is BLOCKED. The agent must move the doc to its correct location per the
 * classification tree. Advisory for UNKNOWN (no evidence) — the file is not
 * classifiable (no TYPE, or the tree cannot decide).
 */
import type { Plugin } from "@opencode-ai/plugin";
import { readFileSync } from "node:fs";
import { socraticShell } from "../support/vsf-socratic-shell";
import { algedonicAlert } from "../../shared/algedonic-alert";

export const ClassifyOnWrite: Plugin = socraticShell({
  classId: "CLASSIFY",
  treeRel: ".opencode/plugins/support/trees/classify.tree.vsm",
  hook: "tool.execute.after",
  context: (input: any, output: any) => {
    // tool.execute.after fires for EVERY tool (write, edit, read, bash,
    // grep, websearch…) — only .vsm writes/edits are in CLASSIFY scope.
    // Skip everything else so the shell never evaluates an empty docType
    // (which produced false "opina sin certificar" noise on reads of .vsm
    // files — CLASSIFY-READ-TOOL-NOISE, 2026-08-19).
    if (input.tool !== "write" && input.tool !== "edit") return { skip: true };
    // hook contract (opencode 1.18): args live in INPUT, not output
    const filePath = input.args?.file_path ?? input.args?.filePath;
    if (!filePath || !String(filePath).endsWith(".vsm")) return { skip: true };
    // extract the TYPE from the doc header (slot 2) if we can read it
    let docType = "";
    try {
      const first = readFileSync(String(filePath), "utf8").split("\n", 1)[0];
      const m = first.match(/⟦\s*[^|]+\|\s*([^|]+)\s*\|/);
      docType = m ? m[1].trim() : "";
    } catch { /* unreadable → ctx empty → engine reports UNKNOWN */ }
    // No TYPE in the header (TASKS.vsm, HANDOFF.vsm.md, *.vsm backlog files
    // without a ⟦ header ⟧): the CLASSIFY questionnaire has no question to
    // answer — skip WITHOUT evaluating (evaluating an empty docType produces
    // UNKNOWN → the act() treats certified=false as a failure and screams
    // "opina sin certificar" for a file that was never in scope. Same R9
    // contract as socratic_gate.py: no TYPE → '?' visible, no grito,
    // CLASSIFY-NO-TYPE-NOISE, 2026-08-19).
    if (!docType) return { skip: true };
    return { type: docType };
  },
  act: async (decision: any, input: any, output: any, _repoRoot: string) => {
    const filePath = input.args?.file_path ?? input.args?.filePath;
    // R9 (never silent, never invented): UNKNOWN (no evidence) is NOT a
    // failure — the engine could not decide, so we say '?' quietly and move
    // on. Only FALSE (certified evidence of misplacement) deserves the
    // BLOCK (FASE-3-ENFORCEMENT-2026-08-22). Same contract as socratic_gate.py
    // (UNKNOWN → '?', no grito; CLASSIFY-NO-TYPE-NOISE, 2026-08-19).
    if (decision.certified && decision.truth === "TRUE") {
      const home = decision.home ?? "?";
      console.error(`[SOCRATIC CLASSIFY] ${filePath} → ${home} (${decision.truth})`);
      return { result: "ok", detail: `home=${home}` };
    }
    if (decision.truth === "FALSE") {
      const home = decision.home ?? "?";
      console.error(`[SOCRATIC CLASSIFY] ${filePath}: BLOCKED — fuera de lugar (R10) — evidencia de desclasificación (${home})`);
      // Layer A: an R10 misclassification is a pain signal — route to the
      // algedonic channel so S5 sees the violation pattern over time.
      algedonicAlert(process.cwd(), "classify_blocked_r10", "vsf-classify(S3)",
        "error", `${filePath}: BLOCKED — fuera de lugar (R10) — evidencia de desclasificación (${home})`);
      // BLOCK the write: the agent must move the doc to its correct location
      throw new Error(`CLASSIFY BLOCKED: ${filePath} belongs in ${home} (classification tree). Move the doc to ${home} before writing.`);
    }
    // UNKNOWN → quiet '?', no grito (R9): the file is not classifiable
    // (no TYPE, or the tree cannot decide) — that is expected for backlog
    // files like TASKS.vsm.
    if (filePath) console.error(`[SOCRATIC CLASSIFY] ${filePath}: '?' (R9 — no clasificable, no bloquea)`);
    return { result: "unknown", detail: "R9 unknown" };
  },
});

export default ClassifyOnWrite;
