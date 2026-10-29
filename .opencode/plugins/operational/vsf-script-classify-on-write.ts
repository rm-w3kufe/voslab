/**
 * vsf-script-classify-on-write — script classification plugin
 *
 * CLAIM: classifies new scripts into the correct domain based on content analysis.
 * Discriminates between:
 *   - NEW script: needs classification and potential move
 *   - MODIFICATION to existing script: no move needed
 *
 * design: docs/design/sources/structural-integrity-checks-v1/structural_integrity_checks.vsm
 *
 * R16: this plugin implements structural classification rules.
 * R17: ADVISORY — suggests classification, never blocks.
 *
 * Uses tool.execute.after to detect write/edit operations on scripts.
 */
import type { Plugin } from "@opencode-ai/plugin";
import * as path from "node:path";
import * as fs from "node:fs";

// ─── Domain definitions ──────────────────────────────────────────────────────

interface Domain {
  name: string;
  path: string;
  keywords: string[];
  imports: string[];
  patterns: RegExp[];
}

const DOMAINS: Domain[] = [
  {
    name: "state",
    path: "scripts/state",
    keywords: ["state", "attest", "witness", "verify", "topology", "reconcile"],
    imports: ["sqlite3", "json", "hashlib"],
    patterns: [/state\.db/, /attest/, /witness/, /topology/],
  },
  {
    name: "vsl",
    path: "scripts/vsl",
    keywords: ["vsl", "parser", "tokenizer", "classify", "socratic", "verify"],
    imports: ["tokenizer", "symbol_table", "vsl_parser"],
    patterns: [/\.vsm/, /vsl/, /socratic/, /classify/],
  },
  {
    name: "audit",
    path: "scripts/audit",
    keywords: ["audit", "check", "verify", "compliance", "traceability"],
    imports: ["audit", "check", "verify"],
    patterns: [/audit/, /check_/, /verify_/, /compliance/],
  },
  {
    name: "s1-kernel",
    path: "scripts/s1-kernel",
    keywords: ["kernel", "patch", "l0", "l1", "l2", "aggregate", "node"],
    imports: ["kernel", "node_registry", "aggregate"],
    patterns: [/kernel/, /patch/, /l[012]_/, /aggregate/],
  },
  {
    name: "algedonic",
    path: "scripts/algedonic",
    keywords: ["algedonic", "alert", "signal", "chain", "g6"],
    imports: ["algedonic", "chain_verifier", "g6"],
    patterns: [/algedonic/, /chain/, /g6/, /signal/],
  },
  {
    name: "analysis",
    path: "scripts/analysis",
    keywords: ["analysis", "analyze", "checo", "graph", "heuristic"],
    imports: ["analyze", "checo", "graph"],
    patterns: [/analyze/, /checo/, /graph/, /heuristic/],
  },
  {
    name: "deploy",
    path: "scripts/deploy",
    keywords: ["deploy", "bundle", "start", "stop", "restart"],
    imports: ["deploy", "bundle"],
    patterns: [/deploy/, /bundle/, /start_/],
  },
  {
    name: "llm",
    path: "scripts/llm",
    keywords: ["llm", "qwen", "phi", "ollama", "prompt"],
    imports: ["qwen", "phi", "ollama"],
    patterns: [/qwen/, /phi/, /ollama/, /llm/],
  },
  {
    name: "tests",
    path: "scripts/tests",
    keywords: ["test", "assert", "mock", "fixture"],
    imports: ["pytest", "unittest", "mock"],
    patterns: [/test_/, /_test\.py/, /assert/],
  },
  {
    name: "shared",
    path: "scripts/shared",
    keywords: ["shared", "common", "util", "helper"],
    imports: ["shared", "common"],
    patterns: [/shared/, /common/, /util/],
  },
];

// ─── Classification logic ────────────────────────────────────────────────────

function classifyScript(filePath: string): Domain | null {
  let content: string;
  try {
    content = fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
  const basename = path.basename(filePath);
  const dirname = path.dirname(filePath);

  // Check if this is a modification to an existing script
  if (dirname.includes("scripts/")) {
    const relativePath = path.relative("scripts", dirname);
    const domainName = relativePath.split(path.sep)[0];
    const existingDomain = DOMAINS.find(d => d.name === domainName);
    if (existingDomain) {
      return null; // already in a domain directory — modification
    }
  }

  let bestDomain: Domain | null = null;
  let bestScore = 0;

  for (const domain of DOMAINS) {
    let score = 0;
    for (const keyword of domain.keywords) {
      if (basename.toLowerCase().includes(keyword.toLowerCase())) score += 10;
    }
    for (const imp of domain.imports) {
      if (content.includes(`import ${imp}`) || content.includes(`from ${imp}`)) score += 5;
    }
    for (const pattern of domain.patterns) {
      if (pattern.test(content) || pattern.test(basename)) score += 3;
    }
    if (score > bestScore) {
      bestScore = score;
      bestDomain = domain;
    }
  }

  return bestScore >= 5 ? bestDomain : null;
}

// ─── Plugin ──────────────────────────────────────────────────────────────────

const ScriptClassifyOnWrite: Plugin = async ({ directory }) => {
  return {
    "tool.execute.after": async (input: any, output: any) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const filePath = input.args?.file_path ?? input.args?.filePath ?? "";
      if (!filePath) return;

      const ext = path.extname(filePath);
      if (ext !== ".py" && ext !== ".sh") return;
      if (!filePath.includes("scripts/")) return;

      const domain = classifyScript(filePath);
      if (!domain) return;

      const relativePath = path.relative("scripts", filePath);
      const currentDomain = relativePath.split(path.sep)[0];

      if (currentDomain === domain.name) return; // already correct

      // Advisory — suggest classification
      console.error(
        `[SCRIPT CLASSIFY] ${path.basename(filePath)} → ${domain.name}/ (${domain.path})`
      );
      console.error(
        `  Suggested move: git mv ${filePath} ${domain.path}/`
      );
    },
  };
};

export default ScriptClassifyOnWrite;
