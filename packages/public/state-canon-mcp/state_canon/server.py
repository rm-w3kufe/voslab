"""Minimal MCP server (stdio, JSON-RPC 2.0, newline-delimited). Stdlib only.

Exposes the state-canon surface (INTERFACE.md):
  tools:     state_onboard · state_query · state_verify · state_reconcile ·
             state_journal_mark · state_journal_diff · state_journal_history (opt-in, --journal)
             state_l1_stats (L1 cache KPI — F2)
  resources: state://digest · state://schema · state://rules · state://handoff

Run:
  python3 -m state_canon.server --state path/to/state.json
  python3 -m state_canon.server --sqlite path/to/ops.db
  python3 -m state_canon.server --git path/to/repo
  python3 -m state_canon.server --microstack path/to/corpus/microstack
  python3 -m state_canon.server --instance path/to/my_instance.py:ARG   # bring your own
    # add --journal path/to/journal.db to any of the above to enable state_journal_*
    # add --focus path/to/focus.json to any of the above to enable state_focus_* + state_query('focus')

L1 memo (F2): state_query is served through a version-keyed session cache
(see l1_cache.py). Default mode is shadow — always fresh reads, observed
divergences only. state_verify/state_reconcile bypass it by construction
(they never call state_query). VOS_L1_MODE=shadow|live|off,
kill switch VOS_L1_CACHE=0.

L2 view (F3b): state_onboard is materialized as a cross-session view keyed
by the SET of input versions (see l2_cache.py), always stamped with its
snapshot id (§5.2). state_reconcile is the refresh path and stays ALWAYS
FRESH (§4.4) — L2 wraps state_onboard ONLY. VOS_L2_MODE=shadow|live|off,
kill switch VOS_L2_CACHE=0, store VOS_L2_PATH (else
<focus-dir>/state/cache/onboard_l2.json).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from .digest import assemble
from .focus import FocusTracker
from .journal import StateJournal
from .l1_cache import L1Cache, file_signature, l1_mode, query_key
from .l2_cache import L2View, digest_key, l2_mode, snapshot_stamp, unkeyed_stamp
from .provider import JsonStateProvider, StateProvider
from .reconcile import Reconciler
from . import __version__

PROTOCOL_VERSION = "2024-11-05"

# Cost hints in the descriptions are deliberate: EXP-TOKEN-GROUNDING showed all
# agents default to the broadest tool (state_onboard) even for narrow questions,
# wasting ~4x tokens. The description is the steering surface we have.
TOOLS = [
    {"name": "state_onboard",
     "description": "EXPENSIVE (full digest, ~500 tok): the whole current picture in one call — "
                    "services+status, drift, rules, last decision. Use ONCE at session start, or for "
                    "genuinely broad questions. For a specific service/record, use state_query instead. "
                    "Answer is a stamped L2 snapshot (see the snapshot line; refresh: state_reconcile).",
     "inputSchema": {"type": "object",
                     "properties": {"fresh": {"type": "boolean",
                                              "description": "bypass the L2 view and recompute "
                                                             "(still updates the view)"}}}},
    {"name": "state_query",
     "description": "CHEAP (~80 tok): a narrow slice of canonical state, on demand — one domain, "
                    "optionally filtered by field equality. PREFER this for any specific question "
                    "(e.g. domain='services', filter={'name':'cache'}).",
     "inputSchema": {"type": "object",
                     "properties": {"domain": {"type": "string"},
                                    "filter": {"type": "object"},
                                    "fresh": {"type": "boolean",
                                              "description": "bypass the L1 cache and re-read "
                                                             "the provider (still updates the cache)"}},
                     "required": ["domain"]}},
    {"name": "state_l1_stats",
     "description": "CHEAP (~60 tok): L1/L2 cache KPI — modes, hits/misses/bypasses, divergence "
                    "counts (must be 0 before live mode, §7.1).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_verify",
     "description": "Don't trust the report — check a claim against ground truth. "
                    "Claim = records matching `filter` in `domain` are expected to have `expect` field values.",
     "inputSchema": {"type": "object",
                     "properties": {"domain": {"type": "string"},
                                    "filter": {"type": "object"},
                                    "expect": {"type": "object"}},
                     "required": ["domain", "expect"]}},
    {"name": "state_reconcile",
     "description": "model≡reality: recompute declared-vs-observed drift live (fresh, not the stored snapshot).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_journal_mark",
     "description": "MODERATE (~200 tok): save a state snapshot to the journal for later diff/tracking. "
                    "Call at session end to capture state; diff next session to see what changed. "
                    "Requires the server to be started with --journal.",
     "inputSchema": {"type": "object",
                     "properties": {"session_id": {"type": "string", "description": "optional session label"},
                                    "drifts": {"type": "array", "items": {"type": "object"},
                                               "description": "optional drift list"}}}},
    {"name": "state_journal_diff",
     "description": "CHEAP (~100 tok): diff two journal snapshots to see what changed.",
     "inputSchema": {"type": "object",
                     "properties": {"from_id": {"type": "integer", "description": "snapshot id (default: second-last)"},
                                    "to_id": {"type": "integer", "description": "snapshot id (default: last)"}}}},
    {"name": "state_journal_history",
     "description": "CHEAP (~80 tok): show recent journal snapshots.",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "description": "max entries (default 10)"}}}},
    {"name": "state_focus_mark",
     "description": "Upsert a focus entry by ref. Creates if new, updates status/note if existing. "
                    "Requires --focus PATH at server start.",
     "inputSchema": {"type": "object",
                     "properties": {"ref": {"type": "string", "description": "focus entry identifier"},
                                    "status": {"type": "string",
                                               "description": "optional: active | paused | done (default: active)"},
                                    "note": {"type": "string", "description": "optional context note"}},
                     "required": ["ref"]}},
    {"name": "state_focus_close",
     "description": "Close (mark done) a focus entry by ref. Requires --focus PATH at server start.",
     "inputSchema": {"type": "object",
                     "properties": {"ref": {"type": "string", "description": "focus entry identifier"},
                                    "note": {"type": "string", "description": "optional closing note"}},
                     "required": ["ref"]}},
    # ── Schema evolution tools (opt-in, --schema-evo) ──
    {"name": "state_schema_evo_status",
     "description": "CHEAP (~80 tok): current schema evolution state — domains tracked, drifts, patterns.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_schema_evo_snapshot",
     "description": "MODERATE (~150 tok): take schema snapshots for all domains. Required before drift detection.",
     "inputSchema": {"type": "object",
                     "properties": {"domains": {"type": "array", "items": {"type": "string"},
                                               "description": "optional list of domains (default: all)"}}}},
    {"name": "state_schema_evo_drift",
     "description": "CHEAP (~80 tok): detect schema drift by comparing latest snapshots.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "state_schema_evo_patterns",
     "description": "MODERATE (~120 tok): analyze drift patterns over recent history.",
     "inputSchema": {"type": "object",
                     "properties": {"lookback": {"type": "integer", "description": "snapshots to analyze (default 10)"},
                                    "min_occurrences": {"type": "integer", "description": "min occurrences (default 3)"}}}},
    {"name": "state_schema_evo_propose",
     "description": "MODERATE (~120 tok): propose schema changes based on drift patterns.",
     "inputSchema": {"type": "object",
                     "properties": {"confidence_threshold": {"type": "number", "description": "min confidence (default 0.7)"}}}},
]

RESOURCES = [
    {"uri": "state://digest", "name": "digest", "description": "compact onboard digest", "mimeType": "text/plain"},
    {"uri": "state://schema", "name": "schema", "description": "domains + fields", "mimeType": "application/json"},
    {"uri": "state://rules", "name": "rules", "description": "active rules", "mimeType": "application/json"},
    {"uri": "state://handoff", "name": "handoff", "description": "last decision / handoff", "mimeType": "application/json"},
    {"uri": "state://schema-history", "name": "schema-history", "description": "schema snapshots over time", "mimeType": "application/json"},
]


class StateRagServer:
    def __init__(self, provider: StateProvider, reconcilers: list[Reconciler] | None = None,
                 digest_policy: dict | None = None, journal_db: str | None = None,
                 focus_file: str | None = None, journal_stats_fn=None, journal_rag_fn=None,
                 schema_evo_file: str | None = None):
        self.provider = provider
        self.reconcilers = reconcilers or []
        self.digest_policy = digest_policy
        self.l1 = L1Cache()  # F2: version-keyed memo for state_query only
        # F3b: cross-session L2 view for state_onboard — store resolution:
        # VOS_L2_PATH env (tests/ops seam), else repo-anchored next to the
        # focus file, else memory-only slot (in-process value, no persistence).
        l2_path = os.environ.get("VOS_L2_PATH")
        if not l2_path and focus_file:
            l2_path = str(Path(focus_file).resolve().parent
                          / "state" / "cache" / "onboard_l2.json")
        self.l2 = L2View(l2_path)
        self.journal = (StateJournal(journal_db, stats_fn=journal_stats_fn, rag_fn=journal_rag_fn)
                        if journal_db else None)
        self.focus = FocusTracker(focus_file) if focus_file else None
        if self.focus:
            # Give any reconciler that wants live focus data the SAME tracker
            # instance state_focus_mark/state_query('focus') read and write —
            # not an independently re-derived path, which could silently point
            # elsewhere. Duck-typed and optional: reconcilers that don't touch
            # focus are unaffected.
            for rec in self.reconcilers:
                bind = getattr(rec, "bind_focus_tracker", None)
                if bind:
                    bind(self.focus)
        # Schema evolution (opt-in, --schema-evo)
        self._schema_evolution = None
        if schema_evo_file:
            from .schema_evolution import SchemaEvolution
            self._schema_evolution = SchemaEvolution(schema_evo_file)

    # ── tool implementations ──
    def state_onboard(self, fresh: bool = False) -> str:
        """The L2 seam (§5.2): stamped snapshot view over assemble().

        state_reconcile remains the refresh path and NEVER reads this view
        (§4.4 ALWAYS FRESH) — only this presentation surface is materialized.
        Unkeyable inputs (a domain without version()) degrade to a fresh
        compute stamped as live — never to a stale claim.
        """
        inputs, unversioned = self._l2_inputs()
        if inputs is None:
            digest = assemble(self.provider, self.reconcilers, policy=self.digest_policy)
            return unkeyed_stamp(unversioned) + "\n" + digest
        key = digest_key(inputs)
        stamp = snapshot_stamp(key)
        mode = l2_mode()
        entry = self.l2.get() if mode != "off" else None
        valid = entry is not None and entry["key"] == key
        if mode != "off":
            if fresh:
                self.l2.bypass()
            elif valid:
                self.l2.hit()
                if mode == "live":
                    return stamp + "\n" + entry["digest"]
                # shadow: fall through — serve fresh, observe below
            else:
                self.l2.miss()
        digest = assemble(self.provider, self.reconcilers, policy=self.digest_policy)
        if mode != "off":
            if valid and entry["digest"] != digest:
                # same input set, different output: key incomplete or
                # assemble non-deterministic → live enable blocked (§7.1)
                self.l2.diverge(key)
            self.l2.put(key, digest)
        return stamp + "\n" + digest

    def _l2_inputs(self) -> tuple[str | None, list[str]]:
        """Canonical input-version material for the digest key (§5.2).

        Covers everything assemble() reads: every provider domain, the
        focus file, the digest policy, and the reconciler set (class
        names — a behavior change without a name change is caught by the
        shadow divergence comparison, not by the key).
        """
        parts: list[str] = []
        unversioned: list[str] = []
        try:
            domains = sorted(self.provider.list_domains())
        except Exception:  # noqa: BLE001 — unkeyable, not fatal
            return None, ["<list_domains-failed>"]
        for d in domains:
            v = self._provider_version(d)
            if v is None:
                unversioned.append(d)
            parts.append(f"{d}={v}")
        if self.focus:
            parts.append("focus=" + file_signature(self.focus.path))
        parts.append("policy=" + json.dumps(self.digest_policy or {},
                                            sort_keys=True, default=str))
        parts.append("rec=" + ",".join(type(r).__name__
                                       for r in self.reconcilers))
        if unversioned:
            return None, unversioned
        return "\n".join(parts), []

    def state_query(self, domain: str, filter: dict | None = None,
                    fresh: bool = False) -> list[dict]:
        if domain == "focus":
            if not self.focus:
                return [{"error": "focus not enabled (start server with --focus)"}]
            # Focus version = stat of the focus file itself: catches THIS
            # server's mark/close writes AND any external writer (plugins,
            # other agents) — read-your-writes without a write-side hook.
            return self._l1_run(domain, filter, file_signature(self.focus.path),
                                fresh,
                                lambda: self.focus.query((filter or {}).get("ref")))
        return self._l1_run(domain, filter, self._provider_version(domain),
                            fresh, lambda: self.provider.query(domain, filter))

    def _provider_version(self, domain: str) -> str | None:
        """Fail-soft: any provider without version() — or whose version()
        raises — degrades to passthrough (uncacheable), never to a crash."""
        fn = getattr(self.provider, "version", None)
        if not callable(fn):
            return None
        try:
            return fn(domain)
        except Exception:  # noqa: BLE001 — a broken version() must not fail a query
            return None

    def _l1_run(self, domain: str, filter: dict | None, version: str | None,
                fresh: bool, read) -> list[dict]:
        """The single L1 seam for state_query (§4.2).

        off/unknown-version → straight passthrough. Otherwise: serve the
        entry only in live mode on version match (deep-copied both ways);
        shadow always falls through to a fresh read and compares, counting
        any content divergence — that counter is the enable gate (§7.1).
        """
        mode = l1_mode()
        if mode == "off" or version is None:
            return read()
        key = query_key(domain, filter)
        entry = self.l1.peek(key)
        valid = entry is not None and entry["version"] == version
        if fresh:
            self.l1.bypass()
        elif valid:
            self.l1.hit()
            if mode == "live":
                return deepcopy(entry["records"])
            # shadow: fall through — serve fresh, observe below
        else:
            self.l1.miss()
        records = read()
        if valid and entry["records"] != records:
            # version said "same" but content differed: versioning is
            # unsound for this domain → counted, never served stale
            self.l1.diverge(key, domain)
        self.l1.put(key, version, records)
        return records

    def state_verify(self, domain: str, expect: dict, filter: dict | None = None) -> dict:
        records = self.provider.query(domain, filter)
        if not records:
            result = {"holds": False, "reason": "no_records_matched", "filter": filter}
        else:
            mismatches = [
                {"record": r, "field": k, "expected": v, "actual": r.get(k)}
                for r in records for k, v in expect.items() if r.get(k) != v
            ]
            result = {"holds": not mismatches,
                      "checked": len(records),
                      "mismatches": mismatches,
                      "evidence": records if not mismatches else None}
        warning = self._reconciler_mismatch_warning(domain)
        if warning:
            result["warning"] = warning
        return result

    def _reconciler_mismatch_warning(self, domain: str) -> str | None:
        """If a reconciler is registered for `domain`, cross-check the provider's
        data against reconciler.observe(). Disagreement is the exact symptom of the
        provider being wired to declared/config state instead of the reconciled
        canon — which silently inverts what state_verify is supposed to guarantee
        (see INTERFACE.md 'Provider contract'). Best-effort: any error while
        cross-checking is swallowed, since this is a diagnostic aid, not a gate."""
        rec = next((r for r in self.reconcilers if getattr(r, "domain", None) == domain), None)
        if rec is None:
            return None
        try:
            observed = {o[rec.key]: o for o in rec.observe() if rec.key in o}
            provided = {p[rec.key]: p for p in self.provider.query(domain) if rec.key in p}
        except Exception:
            return None
        disagreements = sorted(
            key for key in (set(observed) & set(provided))
            if str(observed[key].get(rec.status_field, "")).lower()
               != str(provided[key].get(rec.status_field, "")).lower()
        )
        if not disagreements:
            return None
        return (f"provider data for domain '{domain}' disagrees with the registered "
                f"reconciler's observe() on '{rec.status_field}' for {len(disagreements)} "
                f"record(s) ({disagreements[:5]}) — the provider may be wired to declared/"
                f"config state instead of the reconciled canon; results may not reflect "
                f"ground truth")

    def state_reconcile(self) -> list[dict]:
        return [d.as_dict() for rec in self.reconcilers for d in rec.diff()]

    # ── resource reads ──
    def read_resource(self, uri: str) -> tuple[str, str]:
        if uri == "state://digest":
            return "text/plain", self.state_onboard()
        if uri == "state://schema":
            return "application/json", json.dumps(
                {d: self.provider.schema(d) for d in self.provider.list_domains()}, indent=1)
        if uri == "state://rules":
            return "application/json", json.dumps(self.provider.query("rules"), indent=1)
        if uri == "state://handoff":
            meta = (self.provider.query("meta") or [{}])[0]
            return "application/json", json.dumps(meta.get("last_decision", {}), indent=1)
        if uri == "state://schema-history":
            if self._schema_evolution is not None:
                history = self._schema_evolution.tracker.get_history("")
                return "application/json", json.dumps(
                    [s.to_dict() for s in history[-50:]], indent=1)
            return "application/json", json.dumps({"error": "schema evolution not enabled"}, indent=1)
        raise ValueError(f"unknown resource: {uri}")

    # ── JSON-RPC dispatch (pure function of request → response | None) ──
    def dispatch(self, req: dict) -> dict | None:
        method, req_id, params = req.get("method"), req.get("id"), req.get("params") or {}
        if req_id is None:  # notification → no response
            return None
        try:
            result = self._route(method, params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:  # noqa: BLE001 — a server must answer, not die
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}

    def _route(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "state-canon", "version": __version__}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "resources/list":
            return {"resources": RESOURCES}
        if method == "resources/read":
            mime, text = self.read_resource(params["uri"])
            return {"contents": [{"uri": params["uri"], "mimeType": mime, "text": text}]}
        if method == "tools/call":
            out = self._call_tool(params["name"], params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, indent=1)
            return {"content": [{"type": "text", "text": text}]}
        raise ValueError(f"unknown method: {method}")

    def _call_tool(self, name: str, args: dict) -> Any:
        if name == "state_onboard":
            return self.state_onboard(bool(args.get("fresh")))
        if name == "state_query":
            return self.state_query(args["domain"], args.get("filter"),
                                    bool(args.get("fresh")))
        if name == "state_l1_stats":
            return {"l1": self.l1.stats(), "l2": self.l2.stats()}
        if name == "state_verify":
            return self.state_verify(args["domain"], args["expect"], args.get("filter"))
        if name == "state_reconcile":
            return self.state_reconcile()
        if name == "state_journal_mark":
            return self._journal_mark(args.get("session_id"), args.get("drifts"))
        if name == "state_journal_diff":
            return self._journal_diff(args.get("from_id"), args.get("to_id"))
        if name == "state_journal_history":
            return self._journal_history(args.get("limit", 10))
        if name == "state_focus_mark":
            return self._focus_mark(args["ref"], args.get("status"), args.get("note"))
        if name == "state_focus_close":
            return self._focus_close(args["ref"], args.get("note"))
        if name == "state_schema_evo_status":
            return self.state_schema_evo_status()
        if name == "state_schema_evo_snapshot":
            return self.state_schema_evo_snapshot(args.get("domains"))
        if name == "state_schema_evo_drift":
            return self.state_schema_evo_drift()
        if name == "state_schema_evo_patterns":
            return self.state_schema_evo_patterns(args.get("lookback", 10), args.get("min_occurrences", 3))
        if name == "state_schema_evo_propose":
            return self.state_schema_evo_propose(args.get("confidence_threshold", 0.7))
        raise ValueError(f"unknown tool: {name}")

    # ── journal tools ──

    def _journal_mark(self, session_id: str | None = None,
                       drifts: list[dict] | None = None) -> dict:
        if not self.journal:
            return {"error": "journal not enabled (start server with --journal)"}
        if drifts is None and self.reconcilers:
            drifts = [d.as_dict() for rec in self.reconcilers for d in rec.diff()]
        jid = self.journal.mark(session_id=session_id or "",
                                 snapshot_type="mcp",
                                 drifts=drifts)
        return {"snapshot_id": jid, "drift_count": len(drifts or [])}

    def _journal_diff(self, from_id: int | None = None,
                       to_id: int | None = None) -> dict:
        if not self.journal:
            return {"error": "journal not enabled"}
        return self.journal.diff(from_id=from_id, to_id=to_id)

    def _journal_history(self, limit: int = 10) -> list[dict]:
        if not self.journal:
            return [{"error": "journal not enabled"}]
        h = self.journal.history(limit=limit)
        return [{
            "id": r["id"],
            "type": r["snapshot_type"],
            "findings": r["production_findings"],
            "drifts": r["drift_count"],
            "rag_accuracy": f"{r['rag_accuracy']:.0%}" if r.get("rag_accuracy") else "-",
            "session": r["session_id"] or "-",
            "at": r["created_at"],
        } for r in h]

    # ── focus tools ──

    def _focus_mark(self, ref: str, status: str | None = None,
                    note: str | None = None) -> dict:
        if not self.focus:
            return {"error": "focus not enabled (start server with --focus)"}
        entry = self.focus.mark(ref, status=status, note=note)
        return {"ref": entry["ref"], "status": entry["status"], "updated_at": entry["updated_at"]}

    def _focus_close(self, ref: str, note: str | None = None) -> dict:
        if not self.focus:
            return {"error": "focus not enabled (start server with --focus)"}
        entry = self.focus.close(ref, note=note)
        return {"ref": entry["ref"], "status": entry["status"], "updated_at": entry["updated_at"]}

    # ── schema evolution tools (opt-in, --schema-evo) ──

    def state_schema_evo_status(self) -> dict:
        """Get schema evolution status."""
        if self._schema_evolution is None:
            return {"error": "schema evolution not enabled (start server with --schema-evo)"}
        return self._schema_evolution.get_status()

    def state_schema_evo_snapshot(self, domains: list[str] | None = None) -> dict:
        """Take schema snapshots for all domains."""
        if self._schema_evolution is None:
            return {"error": "schema evolution not enabled (start server with --schema-evo)"}
        snapshots = self._schema_evolution.snapshot_all(self.provider, domains)
        return {
            "snapshots_taken": len(snapshots),
            "domains": [s.domain for s in snapshots],
            "timestamp": snapshots[0].timestamp if snapshots else None,
        }

    def state_schema_evo_drift(self) -> dict:
        """Detect schema drift."""
        if self._schema_evolution is None:
            return {"error": "schema evolution not enabled (start server with --schema-evo)"}
        drifts = self._schema_evolution.detect_drift()
        return {
            "drift_count": len(drifts),
            "drifts": [d.to_dict() for d in drifts],
            "drift_kinds": list(set(d.kind for d in drifts)) if drifts else [],
        }

    def state_schema_evo_patterns(self, lookback: int = 10,
                                   min_occurrences: int = 3) -> dict:
        """Analyze drift patterns."""
        if self._schema_evolution is None:
            return {"error": "schema evolution not enabled (start server with --schema-evo)"}
        patterns = self._schema_evolution.analyze_patterns(lookback, min_occurrences)
        return {
            "pattern_count": len(patterns),
            "patterns": [p.to_dict() for p in patterns],
            "high_confidence": len([p for p in patterns if p.confidence > 0.7]),
        }

    def state_schema_evo_propose(self, confidence_threshold: float = 0.7) -> dict:
        """Propose schema changes based on drift patterns."""
        if self._schema_evolution is None:
            return {"error": "schema evolution not enabled (start server with --schema-evo)"}
        proposals = self._schema_evolution.propose(self.provider, confidence_threshold)
        return {
            "proposal_count": len(proposals),
            "proposals": proposals,
        }

    # ── stdio loop ──
    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.dispatch(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def _load_instance_file(module_path, arg: str):
    """Load an instance module (a .py with load(arg) [+ DIGEST_POLICY,
    JOURNAL_STATS_FN, JOURNAL_RAG_FN]) → (provider, reconcilers, digest_policy,
    journal_stats_fn, journal_rag_fn). This is the bring-your-own hook.

    JOURNAL_STATS_FN/JOURNAL_RAG_FN let an instance populate StateJournal's
    instance-specific columns (production_findings, rag_accuracy, etc.) without
    that schema knowledge living in the shared journal.py core — same pattern
    as DIGEST_POLICY, just for the journal instead of the digest."""
    import importlib.util
    import sys
    from pathlib import Path
    inst = Path(module_path)
    spec = importlib.util.spec_from_file_location(inst.stem, inst)
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module — required by @dataclass and
    # other Python internals that look up cls.__module__ in sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    provider, reconcilers = mod.load(arg)
    return (provider, reconcilers, getattr(mod, "DIGEST_POLICY", None),
            getattr(mod, "JOURNAL_STATS_FN", None), getattr(mod, "JOURNAL_RAG_FN", None))


def main() -> None:
    from pathlib import Path
    instances_dir = Path(__file__).resolve().parents[1] / "instances"

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", help="path to a state.json (JsonStateProvider, no reconciler)")
    ap.add_argument("--sqlite", help="path to any SQLite DB (every table/view becomes a domain, read-only)")
    ap.add_argument("--git", help="path to a git repository (GitStateProvider + reconciler, read-only)")
    ap.add_argument("--microstack", help="path to the microstack corpus dir (demo: provider + reconciler)")
    ap.add_argument("--instance", metavar="MODULE.py:ARG",
                    help="bring your own instance: a module exposing load(arg) [+ DIGEST_POLICY]")
    ap.add_argument("--journal", metavar="PATH",
                    help="enable state_journal_* tools, persisting snapshots to PATH (SQLite DB)")
    ap.add_argument("--focus", metavar="PATH",
                    help="enable state_focus_* tools + state_query('focus'), "
                         "persisting per-agent focus entries to PATH (JSON)")
    ap.add_argument("--schema-evo", metavar="PATH",
                    help="enable state_schema_evo_* tools, persisting schema history to PATH (JSON)")
    args = ap.parse_args()

    journal_stats_fn = journal_rag_fn = None
    if args.instance:
        module_path, _, arg = args.instance.rpartition(":")
        provider, reconcilers, policy, journal_stats_fn, journal_rag_fn = _load_instance_file(module_path, arg)
    elif args.microstack:
        provider, reconcilers, policy, journal_stats_fn, journal_rag_fn = _load_instance_file(
            instances_dir / "microstack.py", args.microstack)
    elif args.git:
        from .git_provider import DIGEST_POLICY as git_policy
        from .git_provider import load as git_load
        provider, reconcilers = git_load(args.git)
        policy = git_policy
    elif args.sqlite:
        from .sqlite_provider import SqliteStateProvider
        provider, reconcilers, policy = SqliteStateProvider(args.sqlite), [], None
    elif args.state:
        provider, reconcilers, policy = JsonStateProvider(args.state), [], None
    else:
        ap.error("need one of --state, --sqlite, --git, --microstack, --instance")

    StateRagServer(provider, reconcilers, policy, journal_db=args.journal, focus_file=args.focus,
                   journal_stats_fn=journal_stats_fn, journal_rag_fn=journal_rag_fn,
                   schema_evo_file=args.schema_evo).serve()


if __name__ == "__main__":
    main()
