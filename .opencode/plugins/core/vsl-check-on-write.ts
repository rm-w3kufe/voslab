/**
 * vsl-check-on-write — conformance DAEMON the moment a .vsm is written (R18).
 * design: docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm
 *
 * Ported from Claude Code hook .claude/hooks/vsl-check-on-write. Runs
 * scripts/vsl/check.py on any .vsm written under docs/spec_revision/.
 *
 * R18_write_time_conformance (rmw3 S5 2026-08-17): AUTONOMÍA OPERACIONAL.
 * The daemon verifies grammar + encoding + structure + version at EVERY
 * write, not at commit. The instrument detects, the agent corrects, the
 * commit verifies — no human in the loop.
 *
 * BLOCKING (R18): check.py exit 1 with a version violation (marker
 * "version (R18)") is a POLICY BREACH — the bash script exits 1, this
 * plugin propagates stderr and logs result=fail. The agent MUST bump the
 * doc to the canonical version before continuing. Grammar/encoding failures
 * on a half-written doc are legitimately mid-flight — advisory (exit 0),
 * still reported.
 *
 * WHY it exists (2026-08-10): every component ran at COMMIT and nowhere
 * else — an agent wrote a whole document, then learned it carried eleven
 * defects and paid to rewrite what it had already paid to write.
 *
 * 2026-08-11 fix: the embedded `$` helper does NOT expose Bun Shell's
 * `.input()` API — every Write/Edit fired `... .input is not a function`.
 * Replaced with child_process.execFile.
 *
 * 2026-08-11 deadlock fix (second, same day): passing the payload via
 * `input:` still hung — the embedded runtime never closes the child's stdin,
 * so the script's `payload=$(cat)` blocked forever on a TTY. Fix: pass the
 * file path as an ARGUMENT, no stdin. The bash script keeps a stdin fallback
 * for Claude Code.
 *
 * 2026-08-17: R18 blocking — the script exits 1 on version violation; this
 * plugin propagates stderr (the daemon's report) and logs result=fail so
 * the agent cycle is observable (AGENT-CYCLE-OBSERVABILITY).
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation } from "../../shared/log-activation";
import { callBridge } from "../operational/tool-bridge";

const SCRIPT_REL = ".opencode/plugins/scripts/vsl-check-on-write";
const execFileP = promisify(execFile);

export const CheckOnWrite: Plugin = async ({ directory }) => {
  const SCRIPT = findScript(directory || process.cwd(), SCRIPT_REL);
  // repo root from the found script: <root>/.opencode/plugins/scripts/file
  // → 4 dirname levels up. No script → no logging (no checkout).
  const repoRootDir = SCRIPT
    ? dirname(dirname(dirname(dirname(SCRIPT))))
    : null;
  return {
    "tool.execute.after": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      // hook contract (opencode 1.18): args live in INPUT, not output
      const filePath = input.args?.file_path ?? input.args?.filePath;
      if (!filePath || !String(filePath).endsWith(".vsm")) return;
      if (!SCRIPT || !repoRootDir) return; // no checkout — nothing to check (nothing staged)

      try {
        const { stdout, stderr } = await execFileP(SCRIPT, [String(filePath)], {
          env: { ...process.env },
          maxBuffer: 10 * 1024 * 1024,
        });
        // the bash script reports the conformance daemon on stderr;
        // stdout may carry nothing. Propagate BOTH (2026-08-14: only stdout
        // was read — the write-time report never reached the agent).
        const report = [stderr.trim(), stdout.trim()].filter(Boolean).join("\n");
        if (report) console.error(report);
        await logActivation(
          repoRootDir, "vsl-check-on-write", "tool.execute.after",
          `check ${String(filePath)}`, "ok");
      } catch (e: any) {
        // The daemon blocked: R18 version violation, CLASSIFICATION
        // violation, OR a script error. The bash script already labels the
        // cause on its stderr ([DEMONIO R18] / [DEMONIO CLASSIFICATION]) —
        // propagate it VERBATIM so the agent sees WHY it was blocked and
        // corrects the right thing (2026-08-17: the catch used to wrap
        // EVERYTHING in [DEMONIO R18], so a classification block was
        // reported as a version violation and the agent fixed the wrong
        // cause — collision fixed).
        const detail = e?.stderr || e?.message || "unknown";
        const d = String(detail).trimEnd();
        const label = /\[DEMONIO (R18|CLASSIFICATION)\]/.test(d)
          ? ""               // script already labelled the cause — verbatim
          : "[DEMONIO R18] "; // script error / unknown cause — R18 default
        console.error(`${label}${d}`);

        // HOOK-FAILOPEN closure: a gate verdict (cause marker present)
        // RESTORES the pre-write snapshot (or quarantines a new file)
        // instead of merely reporting. Runner errors (no marker) never
        // revert good work. The failure still propagates (throw below).
        const fp = String(filePath);
        if (/\[DEMONIO |R18-BLOCK/.test(d)) {
          try {
            const stashed: any = await callBridge("vsm-stash", [fp]);
            if (stashed?.ok) {
              const restored: any = await callBridge("vsm-restore", [String(stashed.token || "")]);
              if (restored?.ok) {
                await logActivation(
                  repoRootDir, "vsl-check-on-write", "tool.execute.after",
                  `restore ${fp}`, "ok", "pre-write snapshot restored after gate block");
              } else {
                const quar: any = await callBridge("vsm-quarantine", [fp]);
                await logActivation(
                  repoRootDir, "vsl-check-on-write", "tool.execute.after",
                  `quarantine ${fp}`, quar?.ok ? "ok" : "error",
                  String(restored?.output || quar?.output || "").slice(0, 300));
              }
            }
          } catch (re: any) {
            await logActivation(
              repoRootDir, "vsl-check-on-write", "tool.execute.after",
              `restore ${fp}`, "error", String(re?.message || re).slice(0, 200));
          }
        }
        await logActivation(
          repoRootDir, "vsl-check-on-write", "tool.execute.after",
          `check ${String(filePath)}`, "fail", String(detail).slice(0, 500));
        throw new Error(`write-gate blocked ${fp}: gate verdict enforced (snapshot restored/quarantined) — fix and retry`);
      }
    },
  };
};

export default CheckOnWrite;