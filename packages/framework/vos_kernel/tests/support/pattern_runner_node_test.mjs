// pattern_runner_node_test.mjs — REAL execution of pattern-runner.ts
// (design: docs/spec_revision/design-sources/pattern-runner-v1/pattern_runner.vsm).
// Invoked by packages/framework/vos_kernel/tests/test_pattern_runner.py after
// esbuild bundles the handler. Verifies, against a fixture repo root:
//   1. classify: event+match routing (true on match, false off-match)
//   2. execute: read-only script runs, marker side-effect observable
//   3. R17 rail: consent=needs-nod NEVER spawns (marker absent, BLOCKED)
//   4. R9: failing script → alert row (alert_type=pattern_runner_fail)
//   5. R9: missing script → detail + alert, never silence
//   6. R10 determinism: repeated classify identical; registry sorted by id
// Exits 0 iff every assertion holds (R4: the bundle is the shipped code).
import { readFileSync, existsSync, writeFileSync, mkdirSync, rmSync } from "node:fs"
import { join } from "node:path"

const [, , bundlePath, repoRoot] = process.argv
if (!bundlePath || !repoRoot) {
  console.error("usage: pattern_runner_node_test.mjs <bundle> <fixtureRepoRoot>")
  process.exit(2)
}

const { patternRunnerHandler } = await import(bundlePath)
const results = []
let failed = 0

function check(name, cond, extra = "") {
  results.push(`${cond ? "PASS" : "FAIL"}: ${name}${extra ? " — " + extra : ""}`)
  if (!cond) failed += 1
}

const mkCtx = (event, payload = {}) => ({
  event,
  directory: repoRoot,
  repoRoot,
  ts: new Date().toISOString(),
  eventId: "test-event",
  payload,
})

const ALERTS = join(repoRoot, "state/rsi/alerts.jsonl")
const readAlerts = () =>
  existsSync(ALERTS)
    ? readFileSync(ALERTS, "utf-8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l))
    : []

// ── 1. classify: routing ─────────────────────────────────────────────────────
const idle = mkCtx("session.idle")
check("classify session.idle matches registry rules", await patternRunnerHandler.classify(idle) === true)

const created = mkCtx("session.created")
check("classify session.created has no rules → false", await patternRunnerHandler.classify(created) === false)

// tool.execute.after with a glob rule (write to docs/**)
const toolDoc = mkCtx("tool.execute.after", { tool: "write", args: { file_path: "docs/spec/index.vsm" } })
check("classify tool.execute.after glob match (docs/**)", await patternRunnerHandler.classify(toolDoc) === true)

const toolOther = mkCtx("tool.execute.after", { tool: "write", args: { file_path: "src/main.rs" } })
check("classify tool.execute.after off-glob → false", await patternRunnerHandler.classify(toolOther) === false)

// ── 2/3/4/5. execute against the fixture registry ────────────────────────────
// Fixture registry (written by the pytest wrapper) contains:
//   run-marker (read-only, writes marker-a), needs-nod-rule (would write
//   marker-b), fail-rule (exit 1), missing-rule (absent script), glob-rule.
const execResult = await patternRunnerHandler.execute(idle)
check("execute returns ok/error shape", ["ok", "error"].includes(execResult.result), execResult.result)

check("read-only rule ran (marker-a exists)", existsSync(join(repoRoot, "marker-a")))
check("R17: needs-nod rule blocked (marker-b absent)", !existsSync(join(repoRoot, "marker-b")))
check("R17: BLOCKED appears in detail", String(execResult.detail).includes("BLOCKED (R17 needs-nod"))

check("R9: fail-rule surfaced in detail", String(execResult.detail).includes("fail-rule"))
const alerts = readAlerts()
check("R9: fail alert written (alert_type)", alerts.some((a) => a.alert_type === "pattern_runner_fail"))
check("R9: missing-script alert written", alerts.some((a) => String(a.detail).includes("missing-rule")))
check("R9: timeout/alert carries driver Sn", alerts.every((a) => /pattern-runner\(S[1-5]\)/.test(a.source)))

// glob rule on tool.execute.after: docs write triggers glob-rule (writes marker-c)
await patternRunnerHandler.execute(toolDoc)
check("glob rule ran on docs write (marker-c exists)", existsSync(join(repoRoot, "marker-c")))

// ── 6. determinism (R10) ─────────────────────────────────────────────────────
const c1 = await patternRunnerHandler.classify(idle)
const c2 = await patternRunnerHandler.classify(idle)
check("determinism: repeated classify identical", c1 === c2 && c1 === true)

const e1 = await patternRunnerHandler.execute(idle)
const e2 = await patternRunnerHandler.execute(idle)
// Same context → same rules ran (detail prefix identical modulo alert ids)
const stripIds = (d) => String(d).replace(/alert-\d+-\d+/g, "ALERT")
check("determinism: repeated execute same rule outcome", stripIds(e1.detail) === stripIds(e2.detail))

// registry is sorted by id: run-marker < needs-nod? order fixed by sort
const order = String(e1.detail)
check("registry executed in sorted-by-id order", order.indexOf("fail-rule") < order.indexOf("missing-rule"))

console.log(results.join("\n"))
console.log(`pattern-runner node test: ${failed === 0 ? "ALL PASS" : `${failed} FAIL`} (${results.length} checks)`)
process.exit(failed === 0 ? 0 : 1)
