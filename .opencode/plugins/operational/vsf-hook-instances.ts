/**
 * design: docs/spec_revision/sandbox/plugin-s2-coordination-v1/plugin_s2_coordination.vsm
 * vsf-hook-instances — wires the 8 proactive socratic hooks as socraticShell
 * instances (PLUGIN-CLASS-TAXONOMY-v1). Each hook has a context builder
 * (extracts from tool payload) and an act function (BLOCK or advisory).
 *
 * Registered in opencode.json under plugins[]. Backed by eval_tree_vsf.py
 * wrapper which loads VSF predicates (classifier + hook) before evaluating.
 */
import type { Plugin } from "@opencode-ai/plugin";
import { readFileSync, existsSync } from "node:fs";
import { socraticShell } from "../support/vsf-socratic-shell";

const TREES = ".opencode/plugins/support/trees";

function filePathOf(input: any): string | undefined {
  return input?.args?.file_path ?? input?.args?.filePath;
}
function contentOf(input: any): string {
  const p = filePathOf(input);
  if (input?.args?.content) return String(input?.args?.content);
  if (p && existsSync(String(p))) {
    try { return readFileSync(String(p), "utf8"); } catch { return ""; }
  }
  return "";
}
function isVsm(input: any): boolean {
  const p = filePathOf(input);
  return !!p && String(p).endsWith(".vsm");
}
function isPy(input: any): boolean {
  const p = filePathOf(input);
  return !!p && String(p).endsWith(".py");
}
function changeTypeOf(input: any): string {
  const p = filePathOf(input) ?? "";
  if (String(p).includes("spec_revision") || String(p).includes("vsl_language")) return "spec";
  if (String(p).includes("plugins")) return "plugins";
  if (String(p).includes("scripts")) return "code";
  return "spec";
}

// ── 1. doc_auto_associate (advisory: sugiere asociar) ────────────────────
export const DocAutoAssociate: Plugin = socraticShell({
  classId: "ASSOCIATE",
  treeRel: `${TREES}/doc_auto_associate.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isVsm(input)) return { skip: true };
    const p = filePathOf(input);
    return { new_doc_path: p, new_doc_content: contentOf(input), type: "DOC" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      console.error(`[SOCRATIC ASSOCIATE] ${p}: tema existente/snowball detectado — asocia o referencia (advisory)`);
      return { result: "warn", detail: "associate" };
    }
    return { result: "ok", detail: "new" };
  },
});

// ── 2. doc_duplicate_detect (BLOCK) ──────────────────────────────────────
export const DocDuplicateDetect: Plugin = socraticShell({
  classId: "DUP",
  treeRel: `${TREES}/doc_duplicate_detect.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isVsm(input)) return { skip: true };
    const p = filePathOf(input);
    return { new_doc_path: p, new_doc_content: contentOf(input), type: "DOC" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      throw new Error(`DOC-DUPLICATE BLOCKED: ${p} — ya existe un doc con el mismo tema (doc_duplicate_detect). Asocia en lugar de duplicar.`);
    }
    return { result: "ok", detail: "no-dup" };
  },
});

// ── 3. doc_hierarchy_enforce (BLOCK si FUENTE sin approval) ──────────────
export const DocHierarchyEnforce: Plugin = socraticShell({
  classId: "HIER",
  treeRel: `${TREES}/doc_hierarchy_enforce.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isVsm(input)) return { skip: true };
    const p = filePathOf(input);
    return { new_doc_path: p, new_doc_content: contentOf(input), type: "DOC" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      throw new Error(`DOC-HIERARCHY BLOCKED: ${p} — FUENTE requiere approval/ratificación (has_approval). Añade marker antes de escribir.`);
    }
    return { result: "ok", detail: "hierarchy-ok" };
  },
});

// ── 4. doc_snowball_prevent (BLOCK) ──────────────────────────────────────
export const DocSnowballPrevent: Plugin = socraticShell({
  classId: "SNOW",
  treeRel: `${TREES}/doc_snowball_prevent.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isVsm(input)) return { skip: true };
    return { new_doc_content: contentOf(input), type: "DOC" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      throw new Error(`DOC-SNOWBALL BLOCKED: ${p} — documento sobre documentos (snowball). No crees meta-docs.`);
    }
    return { result: "ok", detail: "not-snowball" };
  },
});

// ── 5. script_auto_associate (BLOCK if it needs a tree and has none) ─────
export const ScriptAutoAssociate: Plugin = socraticShell({
  classId: "SCR-ASSOC",
  treeRel: `${TREES}/script_auto_associate.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isPy(input)) return { skip: true };
    const p = filePathOf(input) ?? "";
    return { script_path: p, script_name: p.split("/").pop()?.replace(".py", "") ?? "", type: "SCRIPT" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      throw new Error(`SCRIPT-ASSOCIATE BLOCKED: ${p} — script complejo sin árbol socrático. Crea ${TREES}/<nombre>.tree.vsm primero.`);
    }
    return { result: "ok", detail: "script-ok" };
  },
});

// ── 6. script_staging_process (advisory) ─────────────────────────────────
export const ScriptStagingProcess: Plugin = socraticShell({
  classId: "SCR-STAGE",
  treeRel: `${TREES}/script_staging_process.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isPy(input)) return { skip: true };
    const p = filePathOf(input) ?? "";
    return { script_path: p, script_name: p.split("/").pop()?.replace(".py", "") ?? "", type: "SCRIPT" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      console.error(`[SOCRATIC SCR-STAGE] ${p}: script complejo — considera staging a approved/merged`);
      return { result: "warn", detail: "stage" };
    }
    return { result: "ok", detail: "simple" };
  },
});

// ── 7. version_bump_enforce (BLOCK if spec changed without a bump) ──────
export const VersionBumpEnforce: Plugin = socraticShell({
  classId: "VER",
  treeRel: `${TREES}/version_bump_enforce.tree.vsm`,
  hook: "tool.execute.before",
  context: (input: any) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    if (!isVsm(input)) return { skip: true };
    const p = filePathOf(input);
    return { change_type: changeTypeOf(input), file_path: p, type: "DOC" };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      throw new Error(`VERSION-BUMP BLOCKED: ${p} — cambio de especificación requiere @vsm bump y CHANGELOG (version_bump_enforce).`);
    }
    return { result: "ok", detail: "version-ok" };
  },
});

// ── 8. language_change_protocol (advisory) ───────────────────────────────
export const LanguageChangeProtocol: Plugin = socraticShell({
  classId: "LANG",
  treeRel: `${TREES}/language_change_protocol.tree.vsm`,
  hook: "tool.execute.after",
  context: (input: any, _output: any, repoRoot: string) => {
    if (input?.tool !== "write" && input?.tool !== "edit") return { skip: true };
    const p = filePathOf(input) ?? "";
    // only the VSL language spec file triggers this protocol
    if (!String(p).includes("vsl_language_primer")) return { skip: true };
    return { change_type: "spec", file_path: p, type: "DOC", _repoRoot: repoRoot };
  },
  act: async (decision: any, input: any) => {
    const p = filePathOf(input);
    if (decision.truth === "TRUE") {
      console.error(`[SOCRATIC LANG] ${p}: protocolo de cambio de lenguaje — actualiza code→plugins→CHANGELOG (advisory)`);
      return { result: "warn", detail: "lang-protocol" };
    }
    return { result: "ok", detail: "lang-ok" };
  },
});

// Export the 8 instances as named function exports ONLY — no default.
// opencode's loader does Object.values(mod) and treats EACH function export
// as a separate Plugin (must return Hooks). An array default made the whole
// module fail ("Plugin export is not a function"). A merge-function default
// would DOUBLE-register (named ×8 + merge×1). Named-only matches cycle.ts
// pattern and loads each instance exactly once (fix 2026-09-23).
// (HOOK_INSTANCES merge helper removed — loader already iterates named exports.)
