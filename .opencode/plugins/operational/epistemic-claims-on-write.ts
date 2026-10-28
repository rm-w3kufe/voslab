/**
 * design: docs/spec_revision/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
 * epistemic-claims-on-write — H1 hook of the epistemic router (EP-2 of
 * EPISTEMIC-CERT-001, plan §3): a delivery artifact written (.md/.vsm) =>
 * register its EXPLICIT claims (the `<name>.claims.vsm` sidecar) in the
 * epistemic store, then fire the number audit (N: prose numbers vs
 * committed evidence).
 *
 *   1. python3 -m vos_kernel.epistemic register  <path>   (append-only, dedup)
 *   2. python3 scripts/plan/sidecard_reconcile.py ingest <path>
 *      (SIDE-v1/AUDIT-v1 only: sidecard -> .claims.vsm coverage)
 *   3. python3 -m vos_kernel.epistemic audit-artifact <path>   (numbers N)
 *
 * ADVISORY: reports through logActivation, never blocks — blocking belongs
 * to the existing write gates (R18). Fail-open by design: a broken python
 * invocation must not eat the agent's write (the commit gates still catch
 * a bad artifact).
 *
 * Scope: .md/.vsm inside the repo, skipping state/, node_modules/, .venv/,
 * .git/ (the trace stores and vendored trees are not delivery artifacts).
 *
 * WHY a hook: H1 is one of the plan's three doors (H1 on-write, H2 decision,
 * H3 close) — claims must be captured at the moment they are written, not
 * "remembered for the next round" (the specimen lesson: the hooks EXISTED
 * and nobody called them).
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join, relative, sep } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation } from "../../shared/log-activation";

const execFileP = promisify(execFile);

/** Repo-relative skip: state stores, vendored deps and VCS metadata. */
function shouldSkip(repoRoot: string, filePath: string): boolean {
  const rel = relative(repoRoot, filePath);
  if (rel === "" || rel.startsWith("..")) return true; // outside the repo
  const blocked = new Set([
    "state", "node_modules", ".venv", ".git", "__pycache__",
    ".pytest_cache", ".mypy_cache", "target",
  ]);
  return rel.split(sep).some((p) => blocked.has(p));
}

export const EpistemicClaimsOnWrite: Plugin = async ({ directory }) => {
  const marker = findScript(directory || process.cwd(), "opencode.json");
  const repoRootDir = marker ? dirname(marker) : null;
  return {
    "tool.execute.after": async (input: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const filePath = String(
        input.args?.file_path ?? input.args?.filePath ?? "",
      );
      if (!filePath.endsWith(".md") && !filePath.endsWith(".vsm")) return;
      if (!repoRootDir || shouldSkip(repoRootDir, filePath)) return;

      const env = {
        ...process.env,
        PYTHONPATH:
          join(repoRootDir, "packages", "framework") +
          (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""),
      };

      let registered = "n/a";
      let sidecard = "n/a";
      let audit = "n/a";
      try {
        // H1a — explicit claims (sidecar) into the store; rc 1 = sidecar
        // parse/validation errors (reported, never registered).
        try {
          const reg = await execFileP(
            "python3",
            ["-m", "vos_kernel.epistemic", "register", filePath],
            { env, maxBuffer: 10 * 1024 * 1024 },
          );
          const parsed = JSON.parse(reg.stdout || "{}");
          registered = String(parsed.registered ?? 0);
        } catch (e: any) {
          registered = "error";
          const detail = String(e?.stdout || e?.message || "").slice(0, 300);
          await logActivation(
            repoRootDir, "epistemic-claims", "tool.execute.after",
            `h1-register ${filePath}`, "error", detail,
          );
        }

        // H1c — sidecard coverage: SIDE-v1/AUDIT-v1 writes extract claims
        // into their .claims.vsm ledger, so coverage is fresh immediately.
        // The helper skips non-sidecard .vsm files and is fail-open.
        if (filePath.endsWith(".vsm")) {
          try {
            const ing = await execFileP(
              "python3",
              [join(repoRootDir, "scripts", "plan", "sidecard_reconcile.py"),
               "ingest", filePath],
              { env, maxBuffer: 10 * 1024 * 1024, timeout: 30000 },
            );
            const parsed = JSON.parse(ing.stdout || "{}");
            sidecard = parsed.skipped
              ? "skip"
              : String(parsed.ledger_status || "ok");
          } catch (e: any) {
            sidecard = "error";
            const detail = String(e?.stdout || e?.message || "").slice(0, 300);
            await logActivation(
              repoRootDir, "epistemic-claims", "tool.execute.after",
              `h1-sidecard ${filePath}`, "warn", detail,
            );
          }
        }

        // H1b — number audit (advisory): rc 1 means bare numbers/orphans
        // still uncovered; surface it as a warning, never block.
        try {
          await execFileP(
            "python3",
            ["-m", "vos_kernel.epistemic", "audit-artifact", filePath],
            { env, maxBuffer: 10 * 1024 * 1024 },
          );
          audit = "ok";
        } catch (e: any) {
          audit = "findings";
          const detail = String(e?.stdout || e?.stderr || e?.message || "")
            .slice(0, 400);
          await logActivation(
            repoRootDir, "epistemic-claims", "tool.execute.after",
            `h1-audit ${filePath}`, "warn", detail,
          );
        }

        await logActivation(
          repoRootDir, "epistemic-claims", "tool.execute.after",
          `h1 ${filePath}`, "ok",
          `registered=${registered} audit=${audit} sidecard=${sidecard}`,
        );
      } catch (e: any) {
        // fail-open: never break the write itself
        await logActivation(
          repoRootDir, "epistemic-claims", "tool.execute.after",
          `h1 ${filePath}`, "error", String(e?.message || e).slice(0, 300),
        );
      }
    },
  };
};

export default EpistemicClaimsOnWrite;
