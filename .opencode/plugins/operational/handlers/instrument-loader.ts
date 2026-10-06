/**
 * instrument-loader.ts — Fase 3+4+5 of INSTRUMENT-OPERATOR-001.
 * design: docs/plans/instrument_operator_plan.vsm (S5 luz verde 2026-10-06)
 *
 * Fase 3 LOADER (advisory, styled on vsf-onboard-reminder): on session.idle
 * it replays the L_OCCASION table (system/boot/boot_manifest.vsm) — the
 * occasion -> instrument binding declared once (P5) — and reports which
 * session-scoped occasions produced no instrument event in the live log
 * window. Advisory only: never throws, never blocks (M2 authority: a
 * reminder does not veto; boot-ontology rejects throw in non-gate layers).
 *
 * Fase 4 DETECTOR — omission rules against the live log (rotates at 5MB,
 * so the log is the DETECTION WINDOW and instrument_misses.jsonl is the
 * durable record):
 *   R-d1 papers-without-paper_data — docs/papers/ content touched without
 *     any paper_data.vsm access in the same window (the A1 instance rmw3
 *     caught during the attractor-convergence reading, 2026-10-05).
 *     File-tool actions carry basenames only, so paper files are matched
 *     by basename with an ambiguity filter (basenames that also exist
 *     elsewhere under docs/ are excluded to avoid false positives).
 *   R-d2 close-without-journal — substantial tool activity in the window
 *     and no state_journal row created today (UTC) in state_journal.db
 *     (the A2 instance: 2 journal marks in a month).
 *   L-OCC session-scoped occasion (session.created / session.idle /
 *     tool.execute.after / vsm write) whose instrument logged nothing.
 *     daily/weekly/episodic cadences are SKIPPED (an occasion that runs
 *     slower than a session is not a session miss).
 *
 * Fase 5 DRAFT PROPOSALS: a rule that misses again (>= 2 entries in
 * instrument_misses.jsonl) appends a draft to instrument_drafts.jsonl —
 * status=draft, ratified=false, requires=S5. Nothing is ever activated
 * (auto_execute:false, R17). S5 ratifies by promoting the draft through
 * plan_registry; this handler never does.
 *
 * Once per session (payload.sessionID), fail-open everywhere: any read
 * error degrades that rule to "not evaluated" and the handler still
 * returns ok — observability must never break the session.
 */
import { existsSync, readFileSync, appendFileSync, mkdirSync, readdirSync, statSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { spawnSync } from "node:child_process"
import type { Handler, HandlerContext, HandlerResult } from "../vsf-event-router"
import { logActivation } from "../../../shared/log-activation"

// ─── Constants ───────────────────────────────────────────────────────────────

const MANIFEST_REL = "system/boot/boot_manifest.vsm"
const LOG_REL = "logs/agent_plugin.jsonl"
const MISSES_REL = "state/instrument_misses.jsonl"
const DRAFTS_REL = "state/instrument_drafts.jsonl"
const STATE_REL = "state/instrument_loader_state.json"
const JOURNAL_REL = "state_journal.db"
const PAPERS_REL = "docs/papers"
const PAPER_DATA_BASENAME = "paper_data.vsm"
const ACTIVITY_THRESHOLD = 15 // tool.execute.after events = "substantial"

/** artifact basename -> log source name (explicit, honest — unmapped rules are reported, never guessed) */
const SOURCE_MAP: Record<string, string> = {
  "vsf-onboard-reminder.ts": "vsf-onboard-reminder",
  "learning-cycle-scan.ts": "learning-cycle-scan",
  "gap-resolution.ts": "gap-resolution",
  "rsi_cycle.py": "rsi-cycle",
  "tool_integration_bridge.py": "rsi-cycle",
  "vsl-check-on-write.ts": "GATE",
}

// ─── Types ───────────────────────────────────────────────────────────────────

interface OccasionRule {
  path: string
  occasion: string
  cadence: "session" | "daily" | "weekly" | "episodic"
  logSource: string | null
}

interface MissRecord {
  ts: string
  rule: string
  detail: string
  event_type: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
}

function utcDay(): string {
  return new Date().toISOString().slice(0, 10)
}

/** Read + JSONL tail scan. Returns parsed events (best-effort, [] on error). */
function readLogEvents(repoRoot: string): Record<string, any>[] {
  try {
    const raw = readFileSync(join(repoRoot, LOG_REL), "utf-8")
    const out: Record<string, any>[] = []
    for (const line of raw.split("\n")) {
      if (!line.trim()) continue
      try {
        out.push(JSON.parse(line))
      } catch {
        /* partial line after rotation — skip */
      }
    }
    return out
  } catch {
    return []
  }
}

/** Parse the L_OCCASION layer out of the boot manifest (declared once, P5). */
function parseOccasionRules(repoRoot: string): OccasionRule[] {
  try {
    const txt = readFileSync(join(repoRoot, MANIFEST_REL), "utf-8")
    const start = txt.indexOf("layer(L_OCCASION)")
    if (start < 0) return []
    const end = txt.indexOf("\n  layer(", start + 1)
    const block = txt.slice(start, end > 0 ? end : undefined)
    const rules: OccasionRule[] = []
    const re = /artifact\("([^"]+)",\s*layer=\w+,\s*role=\w+,\s*hash="[^"]+",\s*owner="occasion=([^;"]+)/g
    let m: RegExpExecArray | null
    while ((m = re.exec(block)) !== null) {
      const path = m[1]
      const occasion = m[2].trim()
      const base = path.split("/").pop() || path
      const cadence: OccasionRule["cadence"] =
        occasion.includes("daily") ? "daily"
        : occasion.includes("weekly") ? "weekly"
        : occasion === "run_gates live battery" ? "episodic"
        : "session"
      rules.push({ path, occasion, cadence, logSource: SOURCE_MAP[base] ?? null })
    }
    return rules
  } catch {
    return [] // fail-open: no manifest, no audit (never brick the session)
  }
}

/** Recursively collect file basenames under dir. */
function collectBasenames(dir: string, acc: Set<string>): void {
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return
  }
  for (const name of entries) {
    const p = join(dir, name)
    try {
      if (statSync(p).isDirectory()) collectBasenames(p, acc)
      else acc.add(name)
    } catch {
      /* unreadable entry — skip */
    }
  }
}

/**
 * Paper basenames that are UNAMBIGUOUS: files under docs/papers/ whose
 * basename does not appear elsewhere under docs/ (file-tool actions carry
 * basenames only — an ambiguous "main.tex" must not accuse an unrelated read).
 */
function paperBasenames(repoRoot: string): Set<string> {
  const papers = new Set<string>()
  collectBasenames(join(repoRoot, PAPERS_REL), papers)
  if (papers.size === 0) return papers
  const collisions = new Set<string>()
  // Full-path collision pass: ambiguous iff basename appears at >= 2 paths.
  const countByName = new Map<string, number>()
  const walk = (dir: string): void => {
    let entries: string[]
    try {
      entries = readdirSync(dir)
    } catch {
      return
    }
    for (const name of entries) {
      const p = join(dir, name)
      try {
        if (statSync(p).isDirectory()) walk(p)
        else countByName.set(name, (countByName.get(name) || 0) + 1)
      } catch {
        /* skip */
      }
    }
  }
  walk(join(repoRoot, "docs"))
  for (const name of papers) {
    const n = countByName.get(name) || 0
    if (n > 1) collisions.add(name)
  }
  for (const name of collisions) papers.delete(name)
  papers.delete(PAPER_DATA_BASENAME) // access to it is the COMPLIANT act
  return papers
}

/** R-d2: rows created today (UTC) in the root state_journal.db (python stdlib — node has no sqlite). */
function journalRowsToday(repoRoot: string): number | null {
  const db = join(repoRoot, JOURNAL_REL)
  if (!existsSync(db)) return null
  const py = [
    "import sqlite3,sys,datetime",
    "day=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')",
    "c=sqlite3.connect('file:%s?mode=ro',uri=True)",
    "print(c.execute('select count(*) from state_journal where created_at like ?',(day+'%',)).fetchone()[0])",
  ].join("\n").replace("%s", db.replace(/'/g, ""))
  try {
    const r = spawnSync("python3", ["-c", py], { encoding: "utf-8", timeout: 10_000 })
    if (r.status !== 0) return null
    const n = parseInt((r.stdout || "").trim(), 10)
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

function appendJsonl(repoRoot: string, rel: string, obj: Record<string, any>): boolean {
  try {
    const p = join(repoRoot, rel)
    mkdirSync(join(repoRoot, rel.split("/").slice(0, -1).join("/")), { recursive: true })
    appendFileSync(p, JSON.stringify(obj) + "\n")
    return true
  } catch {
    return false
  }
}

function readJsonl(repoRoot: string, rel: string): Record<string, any>[] {
  try {
    return readFileSync(join(repoRoot, rel), "utf-8")
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l)
        } catch {
          return null
        }
      })
      .filter((x): x is Record<string, any> => x !== null)
  } catch {
    return []
  }
}

// ─── Once-per-session gate (fail-open) ───────────────────────────────────────

function shouldRun(repoRoot: string, sessionId: string | null): boolean {
  try {
    const p = join(repoRoot, STATE_REL)
    if (!existsSync(p)) return true
    const st = JSON.parse(readFileSync(p, "utf-8"))
    if (sessionId && st.lastSessionId === sessionId) return false
    if (!sessionId) {
      const last = Date.parse(st.lastRunIso || "0")
      if (Number.isFinite(last) && Date.now() - last < 6 * 3600_000) return false
    }
    return true
  } catch {
    return true // fail-open
  }
}

function markRun(repoRoot: string, sessionId: string | null): void {
  try {
    const p = join(repoRoot, STATE_REL)
    mkdirSync(join(repoRoot, "state"), { recursive: true })
    writeFileSync(p, JSON.stringify({ lastSessionId: sessionId, lastRunIso: utcNow() }) + "\n")
  } catch {
    /* advisory state must never break the handler */
  }
}

// ─── The handler ─────────────────────────────────────────────────────────────

export const instrumentLoaderHandler: Handler = {
  id: "instrument-loader",
  priority: 60, // late + advisory: audit after the session has done work
  events: ["session.idle"],

  classify: (ctx: HandlerContext): boolean => ctx.event === "session.idle",

  execute: async (ctx: HandlerContext): Promise<HandlerResult> => {
    const start = Date.now()
    const repoRoot = ctx.repoRoot || process.cwd()
    const sessionId =
      (typeof ctx.payload?.sessionID === "string" && ctx.payload.sessionID) ||
      (typeof ctx.payload?.session_id === "string" && ctx.payload.session_id) ||
      null

    if (!shouldRun(repoRoot, sessionId)) {
      return { result: "skip", durationMs: Date.now() - start, detail: "already audited this session" }
    }
    markRun(repoRoot, sessionId)

    const misses: MissRecord[] = []
    const ts = utcNow()

    // ── Fase 3: replay L_OCCASION, audit session-scoped firings ──
    const rules = parseOccasionRules(repoRoot)
    const events = readLogEvents(repoRoot)
    const bySource = new Map<string, number>()
    let toolAfter = 0
    let idleEvents = 0
    let createdEvents = 0
    let vsmWrite = false
    let papersTouched = false
    let paperDataTouched = false
    let paperEvidence = ""
    const paperFiles = rules.length ? paperBasenames(repoRoot) : new Set<string>()

    for (const e of events) {
      const src = String(e.source || "")
      bySource.set(src, (bySource.get(src) || 0) + 1)
      const et = String(e.event_type || "")
      const action = String(e.action || "")
      if (et === "tool.execute.after") toolAfter++
      if (et === "session.idle") idleEvents++
      if (et === "session.created") createdEvents++
      if ((et === "tool.execute.after" || et === "before" || et === "after") &&
          /(write|edit)/.test(action) && /\.vsm\b/.test(action)) vsmWrite = true
      if (action.includes(PAPER_DATA_BASENAME)) paperDataTouched = true
      if (!papersTouched) {
        if (action.includes(`${PAPERS_REL}/`) || action.includes("/docs/papers/")) {
          papersTouched = true
          paperEvidence = action.slice(0, 160)
        } else {
          for (const name of paperFiles) {
            if (name.length > 6 && action.includes(name)) {
              papersTouched = true
              paperEvidence = action.slice(0, 160)
              break
            }
          }
        }
      }
    }

    const skipped: string[] = []
    let unmapped = 0
    for (const rule of rules) {
      if (rule.cadence !== "session") {
        skipped.push(`${rule.path.split("/").pop()} (${rule.cadence})`)
        continue
      }
      if (!rule.logSource) {
        unmapped++
        continue
      }
      const fired = bySource.get(rule.logSource) || 0
      let occasionHappened = false
      if (rule.occasion === "session.created") occasionHappened = createdEvents > 0
      else if (rule.occasion === "session.idle") occasionHappened = idleEvents >= 2
      else if (rule.occasion === "tool.execute.after") occasionHappened = toolAfter >= 5
      else if (rule.occasion.includes("tool.execute.after")) occasionHappened = toolAfter >= 5
      else if (rule.occasion === "vsm write") occasionHappened = vsmWrite
      if (occasionHappened && fired === 0) {
        const base = rule.path.split("/").pop()
        misses.push({
          ts,
          rule: `L-OCC:${base}`,
          detail: `occasion '${rule.occasion}' occurred in window but source '${rule.logSource}' logged 0 events`,
          event_type: "instrument_loader.occasion_miss",
        })
      }
    }

    // ── Fase 4 R-d1: papers touched without paper_data in window ──
    if (papersTouched && !paperDataTouched) {
      misses.push({
        ts,
        rule: "R-d1",
        detail: `docs/papers content touched without ${PAPER_DATA_BASENAME} in window; evidence: ${paperEvidence}`,
        event_type: "instrument_loader.omission",
      })
    }

    // ── Fase 4 R-d2: substantial activity, no journal mark today ──
    let r1d2Note = ""
    if (toolAfter >= ACTIVITY_THRESHOLD) {
      const rows = journalRowsToday(repoRoot)
      if (rows === null) {
        r1d2Note = "R-d2 not evaluated (journal db unavailable — fail-open)"
      } else if (rows === 0) {
        misses.push({
          ts,
          rule: "R-d2",
          detail: `${toolAfter} tool events in window and 0 state_journal marks today (UTC)`,
          event_type: "instrument_loader.omission",
        })
      }
    }

    // ── Fase 5: repeat miss -> draft proposal (never activates) ──
    const prior = readJsonl(repoRoot, MISSES_REL)
    const priorCount = new Map<string, number>()
    for (const m of prior) {
      const rule = String(m.rule || "")
      priorCount.set(rule, (priorCount.get(rule) || 0) + 1)
    }
    const draftsToday = readJsonl(repoRoot, DRAFTS_REL).filter(
      (d) => String(d.ts || "").slice(0, 10) === utcDay(),
    )
    const draftRulesToday = new Set(draftsToday.map((d) => String(d.rule || "")))
    const drafts: string[] = []
    for (const m of misses) {
      const isRepeat = (priorCount.get(m.rule) || 0) >= 1
      if (isRepeat && !draftRulesToday.has(m.rule)) {
        const ok = appendJsonl(repoRoot, DRAFTS_REL, {
          ts,
          rule: m.rule,
          status: "draft",
          ratified: false,
          requires: "S5",
          plan_ref: "INSTRUMENT-OPERATOR-001",
          proposal: `Repeat omission (${m.rule}): draft proposal — ratify or reject in plan_registry; the loader never activates anything (auto_execute:false, R17).`,
          evidence: m.detail.slice(0, 300),
        })
        if (ok) drafts.push(m.rule)
      }
    }

    // ── Persist misses (durable — the log rotates) ──
    let persisted = 0
    for (const m of misses) {
      if (appendJsonl(repoRoot, MISSES_REL, m)) persisted++
    }

    const detail =
      `L_OCCASION replay: ${rules.length} rules, ${skipped.length} cadence-skipped, ` +
      `${unmapped} unmapped; window: ${events.length} events, tool.after=${toolAfter}` +
      (r1d2Note ? `; ${r1d2Note}` : "") +
      (misses.length
        ? `; MISSES ${misses.length}: ${misses.map((m) => m.rule).join(", ")}`
        : "; no omissions") +
      (drafts.length ? `; DRAFTS: ${drafts.join(", ")}` : "")

    try {
      await logActivation(
        repoRoot,
        "instrument-loader",
        "session.idle",
        "replay L_OCCASION + omission audit",
        misses.length ? "warn" : "ok",
        detail,
      )
    } catch {
      /* logging must never break the loader */
    }

    return {
      result: "ok",
      durationMs: Date.now() - start,
      detail,
      summary: misses.length
        ? `instrument-loader: ${misses.length} omission(s) recorded (${persisted} persisted${drafts.length ? `, ${drafts.length} draft(s)` : ""})`
        : `instrument-loader: ${rules.length} rules replayed, no omissions`,
    }
  },
}
