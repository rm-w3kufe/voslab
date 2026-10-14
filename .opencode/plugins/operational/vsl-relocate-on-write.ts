/**
 * vsl-relocate-on-write — RELOCATE-VSM (propuesta sandbox 2026-08-14).
 * design: docs/spec_revision/design-sources/relocate-vsm-v1/relocate_vsm_spec.vsm
 *
 * Intercepts `git mv` of a .vsm under the corpus and runs
 * vsf_tools.relocate_vsm (installed package) to remap ALL pinned refs + internal headers
 * to the new path. Turns "move a document" from a manual, error-prone task
 * (incident DIR-SCHEMA-RECURSIVE: 29 renames, ~90% effort in refs) into a
 * one-shot automatic operation.
 *
 * WHY a plugin and not just a script: the relocation must fire AT THE MOMENT
 * of the move (keystroke latency, same argument as vsl-check-on-write) — an
 * agent who `git mv`s and continues writing carries broken refs until the
 * pre-commit gate stops them. The plugin closes that loop.
 *
 * Design (RELOCATE-VSM-SPEC.vsm, sandbox):
 *   hook:    tool.execute.after — intercepts bash containing 'git mv' + .vsm
 *   module:  python3 -m vsf_tools.relocate_vsm --from <old> --to <new>
 *   verify:  0 broken refs post-move + verifier green + checks green
 *   scope:   corpus = docs/spec_revision/ + docs/experiments/ + docs/plan/ +
 *            TASKS.vsm + child/sandbox/ + scripts/ (excl archive/sessions)
 *
 * RAIL SANDBOX: this plugin is the PROMOTED implementation of the sandbox
 * proposal. Any behavioral change goes back through sandbox first.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation } from "../../shared/log-activation";
import { algedonicAlert } from "../../shared/algedonic-alert";

// Canonical implementation: vsf_tools.relocate_vsm (installed package,
// tested). The old scripts/shared copy lacked `import os` (NameError at
// import) and scripts/docs/ never existed — both removed 2026-09-24.
// Invoked as module (no repo-file dependency); repo root located via
// opencode.json marker.
const execFileP = promisify(execFile);

/** True when the command moves a .vsm: git mv with a .vsm on either side. */
function isVsmMove(cmd: string): boolean {
  if (!/git\s+mv/.test(cmd)) return false;
  return /\.vsm/.test(cmd);
}

/**
 * Extract EVERY (from, to) pair of `git mv a b` in the command.
 *
 * Handles chained commands: `git mv a b && git mv c d` yields two pairs.
 * Handles flags before the operands: `git mv -f a b` → (a, b).
 * Each pair: the first two non-flag tokens after a `git mv` token.
 * Tokens are split on shell separators (&&, ||, ;) so a chain yields
 * independent commands, not one long token soup.
 */
function extractPaths(cmd: string): Array<{ from: string; to: string }> {
  const pairs: Array<{ from: string; to: string }> = [];
  // split on shell separators first: each chunk is one command
  const chunks = cmd.split(/\s*(?:&&|\|\||;)\s*/);
  for (const chunk of chunks) {
    // strip everything up to the FIRST 'git mv' in this chunk
    const rest = chunk.replace(/^.*?git\s+mv\s+/, "").trim();
    if (!rest) continue;
    const parts = rest.split(/\s+/).filter((p) => p && !p.startsWith("-"));
    if (parts.length < 2) continue;
    // first two non-flag tokens are old and new path (git mv allows flags before)
    const from = parts[0];
    const to = parts[1];
    if (!from.endsWith(".vsm") && !to.endsWith(".vsm")) continue;
    pairs.push({ from, to });
  }
  return pairs;
}

export const RelocateOnWrite: Plugin = async ({ directory }) => {
  const marker = findScript(directory || process.cwd(), "opencode.json");
  const repoRootDir = marker ? dirname(marker) : null;
  return {
    "tool.execute.after": async (input: any) => {
      if (input.tool !== "bash" && input.tool !== "Bash") return;
      const cmd = String(input.args?.command ?? "");
      if (!isVsmMove(cmd)) return;
      if (!repoRootDir) return; // no checkout — nothing to relocate (nothing staged)

      // AGENT-CYCLE-OBSERVABILITY: record the activation (never blocks).
      await logActivation(
        repoRootDir, "vsl-relocate-on-write", "tool.execute.after",
        "git mv .vsm detected", "ok");

      const pairs = extractPaths(cmd);
      if (pairs.length === 0) {
        // AUTO-DIAGNOSIS (2026-08-15): prints the received command and the
        // analysis so the next failure brings data, not a mystery.
        // Observed cases: stale plugin in runtime (process not restarted)
        // or uncovered syntax — the message now tells them apart.
        const chunks = cmd.split(/\s*(?:&&|\|\||;)\s*/);
        const diag = chunks.map((c, i) => {
          const rest = c.replace(/^.*?git\s+mv\s+/, "").trim();
          return `  chunk[${i}]="${c.trim().slice(0, 80)}" → rest="${rest.slice(0, 60)}"`;
        }).join("\n");
        console.error(
          "[vsl-relocate-on-write] git mv de .vsm detectado pero no pude " +
            "extraer --from/--to. Ejecuta manualmente:\n  " +
            "python3 -m vsf_tools.relocate_vsm --from <old> --to <new>\n" +
            "  — DIAGNÓSTICO (comando recibido):\n" + diag +
            "\n  — si esto es un git mv simple con .vsm, el runtime está " +
            "cargando el plugin VIEJO (reinicia opencode por completo)."
        );
        // Layer A: an unparseable relocate is a pain signal — route to the channel.
        algedonicAlert(repoRootDir || process.cwd(), "relocate_unparsed",
          "vsl-relocate(S2)", "warn",
          "git mv de .vsm detectado pero no pude extraer --from/--to — requiere acción manual");
        return;
      }

      for (const { from, to } of pairs) {
        try {
          const { stdout, stderr } = await execFileP(
            "python3",
            ["-m", "vsf_tools.relocate_vsm", "--from", from, "--to", to],
            { cwd: repoRootDir, env: { ...process.env }, maxBuffer: 10 * 1024 * 1024 }
          );
          if (stdout.trim()) console.error(stdout.trimEnd());
          if (stderr.trim()) console.error(stderr.trimEnd());
        } catch (e: any) {
          console.error(
            `[vsl-relocate-on-write] error: ${e?.message ?? e}. ` +
              "Ejecuta el script manualmente tras el git mv."
          );
          // Layer A: a failed relocate is a pain signal — route to the channel.
          algedonicAlert(repoRootDir || process.cwd(), "relocate_failed",
            "vsl-relocate(S2)", "error",
            `relocate_vsm error: ${String(e?.message ?? e).slice(0, 200)} — ejecuta manualmente tras el git mv`);
        }
      }
    },
  };
};

export default RelocateOnWrite;