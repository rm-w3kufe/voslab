/**
 * design: docs/spec_revision/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
 * analytic-on-read — Automatic analysis hook.
 * 
 * Triggers when:
 *   1. Reading a PDF document
 *   2. Reading from docs/papers/ or docs/correspondence/
 *   3. Explicit analysis request (future: intent detection)
 * 
 * Runs analytic_engine (L1: claim extraction + routing).
 * 
 * ADVISORY: reports through logActivation, never blocks.
 * Fail-open: a broken analysis must not eat the read.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join, relative, extname } from "node:path";
import { findScript } from "../../shared/find-plugin-script";
import { logActivation } from "../../shared/log-activation";

const execFileP = promisify(execFile);

/** Paths that should always trigger analysis */
const ANALYZE_DIRS = [
  "docs/papers/",
  "docs/correspondence/",
  "docs/experiments/",
];

/** Extensions that should trigger analysis */
const ANALYZE_EXTS = new Set([".pdf", ".vsm", ".md", ".tex"]);

/** Skip paths (don't analyze these) */
const SKIP_PATTERNS = [
  "node_modules",
  ".venv",
  ".git",
  "__pycache__",
  "state/",
];

function shouldAnalyze(repoRoot: string, filePath: string): boolean {
  const rel = relative(repoRoot, filePath);
  
  // Skip patterns
  if (SKIP_PATTERNS.some((p) => rel.includes(p))) return false;
  
  // Always analyze certain directories
  if (ANALYZE_DIRS.some((d) => rel.includes(d))) return true;
  
  // Analyze by extension
  const ext = extname(filePath).toLowerCase();
  if (ANALYZE_EXTS.has(ext)) return true;
  
  return false;
}

export const AnalyticOnRead: Plugin = async ({ directory }) => {
  const marker = findScript(directory || process.cwd(), "opencode.json");
  const repoRootDir = marker ? dirname(marker) : null;
  
  return {
    "tool.execute.after": async (input: any) => {
      // Only trigger on read operations
      if (input.tool !== "read") return;
      
      const filePath = String(
        input.args?.file_path ?? input.args?.filePath ?? "",
      );
      if (!filePath || !repoRootDir) return;
      if (!shouldAnalyze(repoRootDir, filePath)) return;

      const env = {
        ...process.env,
        PYTHONPATH:
          join(repoRootDir, "packages", "public") +
          (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""),
      };

      try {
        // Run analysis (L1 by default)
        const script = `
import sys
sys.path.insert(0, "${join(repoRootDir, "packages", "public")}")
sys.path.insert(0, "${join(repoRootDir, "packages", "framework")}")

from analytic_engine import analyze

result = analyze(
    "${filePath}",
    name="${relative(repoRootDir, filePath)}",
    route=True,
    persist=True,   # read -> explicit ledger sidecar (idempotent)
)

import json
print(json.dumps({
    "source_id": result.get("source_id", ""),
    "claims": len(result.get("claims", [])),
    "coverage": result.get("coverage", {}),
    "level": result.get("level", "L1"),
    "ledger_status": result.get("ledger_status") or "",
}))
`;

        const proc = await execFileP(
          "python3",
          ["-c", script],
          { env, maxBuffer: 10 * 1024 * 1024, timeout: 30000 },
        );

        const output = JSON.parse(proc.stdout || "{}");
        
        await logActivation(
          repoRootDir,
          "analytic-engine",
          "tool.execute.after",
          `analyze ${relative(repoRootDir, filePath)}`,
          "ok",
          `claims=${output.claims} level=${output.level} ledger=${output.ledger_status || "none"}`,
        );
      } catch (e: any) {
        // Fail-open: never break the read itself
        await logActivation(
          repoRootDir,
          "analytic-engine",
          "tool.execute.after",
          `analyze ${relative(repoRootDir, filePath)}`,
          "warn",
          String(e?.message || e).slice(0, 300),
        );
      }
    },
  };
};

export default AnalyticOnRead;
