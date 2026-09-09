/**
 * vsl-measure-before-write — MEASURE BEFORE ACTING (rmw3 2026-08-10).
 * design: docs/spec_revision/design-sources/plugin-audit-design-v1/plugin_audit_design.vsm
 *
 * Ported from Claude Code hook .claude/hooks/vsl-measure-before-write.
 * Aims the SAME correction at OpenCode: before Write/Edit touches a .vsm
 * under docs/spec_revision/, show the file's CURRENT state (lines,
 * declarations, balance, strict-parse result) so the agent reads before it
 * writes.
 *
 * BLOCKING (FASE-3-ENFORCEMENT-2026-08-22): if the file does NOT parse
 * --strict (vsl_parser.py reports ERROR), the write is BLOCKED. The agent
 * must fix the parsing errors before writing. Advisory for balanced/declared
 * info — that's informational, not a gate.
 *
 * Evidence it was needed (2026-08-09/10): four reading failures BEFORE the
 * edit — declared the nucleus at L=0 from memory; classified BASIN_FLOOR
 * without reading the _SANDBOX variant; diagnosed a line truncated by my own
 * cut; nearly TRIMMED 17 real declarations because the index misread them.
 *
 * The heavy lifting stays in the shared script (.opencode/plugins/scripts/),
 * which this plugin calls with the same JSON-on-stdin shape Claude Code used.
 *
 * 2026-08-11 fix: the embedded `$` helper does NOT expose Bun Shell's
 * `.input()` API — every Write/Edit fired `... .input is not a function`.
 * Replaced with child_process.execFile.
 *
 * 2026-08-11 deadlock fix (second, same day): passing the payload via
 * `input:` still hung — the embedded runtime never closes the child's stdin,
 * so the script's `payload=$(cat)` blocked forever on a TTY (child session
 * hung 4-12min per Edit). Fix: pass the file path as an ARGUMENT, no stdin.
 * The bash script keeps a stdin fallback for Claude Code.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation } from "../../shared/log-activation";

const SCRIPT_REL = ".opencode/plugins/scripts/vsl-measure-before-write";
const execFileP = promisify(execFile);

export const MeasureBeforeWrite: Plugin = async ({ directory }) => {
  const SCRIPT = findScript(directory || process.cwd(), SCRIPT_REL);
  // repo root from the found script: <root>/.opencode/plugins/scripts/file
  // → 4 dirname levels up. No script → no logging (no checkout).
  const repoRootDir = SCRIPT
    ? dirname(dirname(dirname(dirname(SCRIPT))))
    : null;
  return {
    "tool.execute.before": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const filePath = output.args?.file_path ?? output.args?.filePath;
      if (!filePath || !String(filePath).endsWith(".vsm")) return;
      if (!SCRIPT || !repoRootDir) return; // no checkout — nothing to measure (nothing staged)

      // AGENT-CYCLE-OBSERVABILITY: record the activation (never blocks).
      await logActivation(
        repoRootDir, "vsl-measure-before-write", "tool.execute.before",
        `measure ${String(filePath)}`, "ok");

      try {
        const { stdout, stderr } = await execFileP(SCRIPT, [String(filePath)], {
          env: { ...process.env },
          maxBuffer: 10 * 1024 * 1024,
        });
        const output = (stdout + stderr).trim();
        if (output) console.error(output);
        
        // BLOCKING (FASE-3-ENFORCEMENT-2026-08-22): if the file does NOT parse
        // --strict, BLOCK the write. The agent must fix parsing errors first.
        if (output.includes("does NOT parse --strict") || output.includes("ERROR")) {
          await logActivation(
            repoRootDir, "vsl-measure-before-write", "tool.execute.before",
            `BLOCKED ${String(filePath)} — parse errors`, "blocked");
          throw new Error(`MEASURE BLOCKED: ${filePath} does NOT parse --strict. Fix parsing errors before writing.`);
        }
      } catch (e: any) {
        // Re-throw our own blocking errors
        if (e?.message?.includes("MEASURE BLOCKED")) throw e;
        console.error(`[vsl-measure-before-write] script error: ${e?.message ?? e}`);
        await logActivation(
          repoRootDir, "vsl-measure-before-write", "tool.execute.before",
          `measure ${String(filePath)}`, "error", String(e?.message ?? e));
      }
    },
  };
};

export default MeasureBeforeWrite;