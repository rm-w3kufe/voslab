#!/usr/bin/env python3
"""cybernetic_rag_view — §7.2 the attested φ↑ view builder (view-module cybernetic-rag).

Clean module for the s5-opsroom view-host (LXC 109) — NOT the legacy api.py. Produces the model-agnostic
view body (global/nodes/edges, fig 6.3) by PROJECTING from a SOURCE, and certifies the SOURCE (not the
projection) per the view-module contract v0.2.1:

  - the source = the nucleus φ↑ telemetry (stasis_cos, in_omega, Lyapunov L/dL, reconciled).
  - the source is AX-STATE-attested (reuses scripts/state/state_attest.py: state_attest).
  - the builder VERIFIES the source attestation (state_verify, G-V3) against the LIVE source before it
    emits a tick. A tamper/forgery/stale source ⇒ certified=False ⇒ the host renders degraded, never
    blindly healthy. The view body itself is NOT re-signed (it is a projection, not a source of truth).

Synthetic-first: source='synthetic' (a stub telemetry surface). A later increment swaps the source for
the real nucleus φ↑ — SAME shape, SAME builder. Authoring in WSL; execution/test on the sandbox (108).

Run the gate suite (on n02 sandbox, never WSL):  python3 cybernetic_rag_view.py --gate72
"""
import os
import sys
import json
import sqlite3
import datetime

# Reuse the AX-STATE primitive (same dir on deploy; scripts/state on the repo).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "state"))
import state_attest as ax  # noqa: E402

SCHEMA = "cybernetic-rag-view/0.2"
MODULE_ID = "cybernetic-rag"
SYSTEM_ID = "alpha"
ATTEST_SUBJECT = "vsf.alpha.attest.view.cybernetic-rag"
SRC_TABLE = "telemetry"            # the φ↑ source surface (one row per metric)
VIA_FLOOR = 0.70                   # viability floor below which the loop is degraded


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def synthetic_source_con(stasis=0.95, in_omega=1, lyap_l=0.0123, lyap_dl=-0.0008, reconciled=1):
    """A synthetic φ↑ telemetry source as an in-memory surface (mirrors the real nucleus signals)."""
    con = sqlite3.connect(":memory:")
    con.execute(f"CREATE TABLE {SRC_TABLE} (k TEXT PRIMARY KEY, v REAL)")
    con.executemany(f"INSERT INTO {SRC_TABLE} VALUES (?,?)", [
        ("stasis_cos", stasis), ("in_omega", in_omega),
        ("lyap_l", lyap_l), ("lyap_dl", lyap_dl), ("reconciled", reconciled)])
    con.commit()
    return con


def _read_source(con):
    return {k: v for k, v in con.execute(f"SELECT k, v FROM {SRC_TABLE}")}


def build_view(con):
    """Project the model-agnostic view body (global/nodes/edges) from the LIVE source. Pure projection."""
    s = _read_source(con)
    in_omega = bool(s.get("in_omega", 0))
    via = s.get("stasis_cos", 0.0)
    ok = in_omega and via >= VIA_FLOOR
    reconciled = bool(s.get("reconciled", 0))

    def st(cond):
        return "healthy" if cond else "critical"

    glob = {
        "viability": round(via, 4),
        "in_omega": in_omega,
        "lyapunov": {"L": s.get("lyap_l"), "dL": s.get("lyap_dl"), "converging": s.get("lyap_dl", 0) < 0},
        "last_algedonic": None,
    }
    nodes = [
        {"id": "retrieve", "label": "Sparse retrieve (FTS5)", "stage": "retrieval", "sublevel": "A",
         "status": "healthy", "implemented": True, "metrics": {}},
        {"id": "omega", "label": "Ω viability gate", "stage": "gate", "sublevel": "B",
         "status": st(in_omega), "implemented": "partial", "metrics": {"in_omega": in_omega}},
        {"id": "generate", "label": "Generate (LLM L>=2)", "stage": "generation", "sublevel": "B",
         "status": "healthy", "implemented": True, "metrics": {"model": "qwen2.5-coder:7b"}},
        {"id": "viability", "label": "Viability score", "stage": "evaluation", "sublevel": "B",
         "status": "healthy" if via >= VIA_FLOOR else "degraded", "implemented": True,
         "metrics": {"stasis_cos": via, "L": s.get("lyap_l"), "dL": s.get("lyap_dl")}},
        {"id": "recover", "label": "Algedonic recovery", "stage": "recovery", "sublevel": "B",
         "status": "idle" if ok else "firing", "implemented": True, "metrics": {"policy": "degrade-not-halt"}},
        {"id": "crosscheck", "label": "logical = physical (S3*)", "stage": "crosscheck", "sublevel": "B",
         "status": st(reconciled), "implemented": True, "metrics": {"reconciled": reconciled}},
        {"id": "output", "label": "Output", "stage": "output", "sublevel": "B",
         "status": "healthy" if ok else "degraded", "implemented": True, "metrics": {}},
    ]
    edges = [
        {"from": "retrieve", "to": "omega", "kind": "flow", "state": "active"},
        {"from": "omega", "to": "generate", "kind": "flow", "state": "active" if in_omega else "idle", "guard": "in_omega"},
        {"from": "omega", "to": "recover", "kind": "flow", "state": "firing" if not in_omega else "idle", "guard": "out_omega"},
        {"from": "generate", "to": "viability", "kind": "flow", "state": "active"},
        {"from": "viability", "to": "output", "kind": "flow", "state": "active" if ok else "idle", "guard": "score_ok"},
        {"from": "viability", "to": "recover", "kind": "feedback", "state": "firing" if not ok else "idle", "guard": "score_low"},
        {"from": "recover", "to": "retrieve", "kind": "feedback", "state": "idle"},
        {"from": "crosscheck", "to": "recover", "kind": "feedback", "state": "firing" if not reconciled else "idle", "guard": "disagreement"},
        {"from": "viability", "to": "retrieve", "kind": "feedback", "state": "aspirational"},
    ]
    return {"global": glob, "nodes": nodes, "edges": edges}


def attest_source(con, attest_dir, sk, signer):
    """Publish a periodic SIGNED attestation of the source (the cert checkpoint). Returns the record."""
    return ax.state_attest(con, SRC_TABLE, sk, signer, attest_dir)


def build_tick(con, attest_dir, trusted, now_epoch=None):
    """Consumer side: VERIFY the latest source attestation vs the LIVE source (G-V3), then project the
    view. Returns (tick, findings). certified=False if the source fails verification."""
    findings = ax.state_verify(con, SRC_TABLE, attest_dir, trusted, {}, now_epoch=now_epoch)
    certified = (findings == [])
    head = ax._last_attest_hash(ax._surface_file(attest_dir, f"statedb.{SRC_TABLE}"))
    tick = {
        "schema": SCHEMA, "ts": _now_iso(), "system_id": SYSTEM_ID, "module_id": MODULE_ID,
        "source": "synthetic",
        "view": build_view(con),
        "source_ref": {"subject": ATTEST_SUBJECT, "head_hash": head},
        "certified": certified,
        "cert_findings": [f[0] for f in findings],
    }
    return tick, findings


# ── §7.3b — the REAL φ↑ source adapter (connection_schema events.jsonl, hash-chained) ────────────────
# The canonical φ↑ is the FILE /var/lib/vsf/vsf_nucleus/events.jsonl (NOT NATS — contract v0.2.2). It is
# Merkle-chained (prev_hash/hash per line). The view-host reads it read-only, verifies the chain linkage
# (the connection_schema integrity floor; Ed25519 signing of the source is the deeper PROD-A1b layer), and
# projects. Robust field extraction (recursive find) so it survives the exact JSON nesting.
def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _read_events_tail(path, n=20000, tail_bytes=8000000):
    """Read the last ~n lines by SEEKing the tail (never scan the 124MB+ file) + tolerate non-UTF-8 bytes
    (the long-lived events.jsonl has some). Window spans SEVERAL 60s sampler periods so the periodic
    invariant_check (stasis) + kernel_tick (l_x) are reliably present even if one is corrupt/dropped."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()  # discard the partial first line
        raw = f.read()
    out = []
    for ln in raw.decode("utf-8", errors="ignore").splitlines()[-n:]:
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _chain_ok(events, min_run=5):
    """Recent-integrity (connection_schema Merkle linkage): the most recent contiguous run of events whose
    prev_hash links to the previous event's hash must be >= min_run. Tolerant of the occasional corrupt /
    non-UTF-8 line older in the window (a noisy certifier is a dead certifier — the orphan-detector lesson);
    a real tamper breaks the recent suffix → not certified."""
    run = 1
    for i in range(len(events) - 1, 0, -1):
        ph, h = events[i].get("prev_hash"), events[i - 1].get("hash")
        if ph is not None and h is not None and ph == h:
            run += 1
        else:
            break
    return run >= min_run


def _latest(events, key):
    """The most recent value for `key`, scanning backward — by FIELD, not event_type (NB: not every
    invariant_check carries stasis_last; ~1/3 do, so 'latest invariant_check' is the wrong selector)."""
    for e in reversed(events):
        v = _find(e, key)
        if v is not None:
            return v
    return None


def source_from_events(path, tail=20000):
    """Build the φ↑ source dict from the REAL events.jsonl + a Merkle-chain-integrity flag."""
    events = _read_events_tail(path, tail)
    chain_ok = _chain_ok(events)
    stasis = _latest(events, "stasis_last")
    lx = _latest(events, "l_x")
    viable = _latest(events, "viable")
    lxs = [v for v in (_find(e, "l_x") for e in events) if isinstance(v, (int, float))]
    dl = round(lxs[-1] - lxs[-2], 7) if len(lxs) >= 2 else 0.0
    stasis = stasis if isinstance(stasis, (int, float)) else 0.0
    src = {
        "stasis_cos": round(stasis, 6),
        "in_omega": 1 if (viable if isinstance(viable, bool) else (stasis >= 0.9)) else 0,
        "lyap_l": round(lx, 5) if isinstance(lx, (int, float)) else 0.0,
        "lyap_dl": dl,
        "reconciled": 1,  # physical cross-check is topology_reconcile (separate); assume reconciled for now
        "_trust": _latest(events, "trust1_last"), "_var": _latest(events, "var1_last"),
    }
    return src, chain_ok


def build_tick_from_events(path, tail=20000):
    """Real φ↑ tick: project the view from events.jsonl; certified = the Merkle chain links."""
    src, chain_ok = source_from_events(path, tail)
    con = synthetic_source_con(stasis=src["stasis_cos"], in_omega=src["in_omega"],
                               lyap_l=src["lyap_l"], lyap_dl=src["lyap_dl"], reconciled=src["reconciled"])
    view = build_view(con)
    con.close()
    tick = {
        "schema": SCHEMA, "ts": _now_iso(), "system_id": SYSTEM_ID, "module_id": MODULE_ID,
        "source": "nucleus-events.jsonl",
        "view": view,
        "source_ref": {"file": path, "events_read": tail},
        "certified": bool(chain_ok), "cert_basis": "merkle-chain-linkage",
        "cert_findings": [] if chain_ok else ["CHAIN_BREAK"],
    }
    return tick, src, chain_ok


def _run_gate73_suite(path):
    """Validate the REAL-source adapter against a real events.jsonl sample (+ injection)."""
    import tempfile
    import shutil
    import os as _os
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tick, src, chain_ok = build_tick_from_events(path)
    print(f"# extracted source: {json.dumps(src)}")
    check("real stasis_cos extracted (>0)", isinstance(src["stasis_cos"], float) and src["stasis_cos"] > 0, str(src["stasis_cos"]))
    check("real lyapunov l_x extracted (>0)", src["lyap_l"] > 0, str(src["lyap_l"]))
    check("clean chain → certified", tick["certified"] is True, str(tick["cert_findings"]))
    check("G-V2: tick shape (source_ref+ts+system_id)", all(k in tick for k in ("ts", "system_id", "source_ref")))
    check("view projects 7 nodes from real data", len(tick["view"]["nodes"]) == 7)

    # injection: break a prev_hash in a copy → chain must fail → certified False
    tmp = tempfile.mkdtemp()
    broken = _os.path.join(tmp, "broken.jsonl")
    lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    if len(lines) >= 3:
        bad = json.loads(lines[-2]); bad["prev_hash"] = "deadbeef" * 8  # break the recent suffix
        lines[-2] = json.dumps(bad)
    open(broken, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    t2, _, ok2 = build_tick_from_events(broken)
    check("broken prev_hash → chain fails → not certified", t2["certified"] is False and ok2 is False)
    shutil.rmtree(tmp, ignore_errors=True)

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines_out = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "") for n, ok, d in cases]
    return passed, failed, lines_out


# ── §7.2 gate suite — G-V2 (tick shape) + G-V3 (source attestation verify) by injection ──────────────
def _run_gate72_suite():
    import tempfile
    import shutil
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="vsf-view-g72-")
    attest_dir = os.path.join(tmp, "attestations")
    sk, pub, signer = ax.load_or_generate_key(os.path.join(tmp, "keys"))
    trusted = {signer: pub}
    now = ax._parse_iso(_now_iso())

    # ── clean: healthy source, attested, verified ──
    con = synthetic_source_con()
    attest_source(con, attest_dir, sk, signer)
    tick, findings = build_tick(con, attest_dir, trusted, now_epoch=now)
    check("G-V2: tick has schema+ts+system_id+source_ref", all(
        k in tick for k in ("schema", "ts", "system_id", "source_ref")) and "head_hash" in tick["source_ref"])
    check("view well-formed (global/nodes/edges)", all(k in tick["view"] for k in ("global", "nodes", "edges"))
          and len(tick["view"]["nodes"]) == 7)
    check("G-V3: clean source verifies → certified", tick["certified"] is True, str(findings))
    check("healthy projection: in_omega + output healthy",
          tick["view"]["global"]["in_omega"] is True
          and next(n for n in tick["view"]["nodes"] if n["id"] == "output")["status"] == "healthy")

    # ── TAMPER: mutate the live source AFTER attestation → verify must fail → certified False ──
    con.execute(f"UPDATE {SRC_TABLE} SET v=0 WHERE k='in_omega'"); con.commit()
    tick2, findings2 = build_tick(con, attest_dir, trusted, now_epoch=now)
    check("G-V3: tampered source → ATTEST_TAMPER", "ATTEST_TAMPER" in {f[0] for f in findings2})
    check("tampered source → certified False", tick2["certified"] is False)
    check("projection reflects the tamper (Ω critical)",
          next(n for n in tick2["view"]["nodes"] if n["id"] == "omega")["status"] == "critical")

    # ── FORGERY: an untrusted signer → certified False ──
    con3 = synthetic_source_con()
    attest_source(con3, os.path.join(tmp, "a3"), sk, signer)
    t3, f3 = build_tick(con3, os.path.join(tmp, "a3"), {}, now_epoch=now)  # empty trusted set
    check("G-V3: untrusted signer → not certified", t3["certified"] is False
          and "ATTEST_FORGERY" in {f[0] for f in f3})

    con.close(); con3.close()
    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "")
             for n, ok, d in cases]
    return passed, failed, lines


def main():
    if "--gate72" in sys.argv:
        passed, failed, lines = _run_gate72_suite()
        print("# cybernetic_rag_view --gate72 — attested φ↑ builder (G-V2 shape + G-V3 cert by injection)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## §7.2: ✗ NOT MET — the builder/cert path is unsound. Do NOT wire the host.")
            return 1
        print("## §7.2: ✓ MET — view projects + the SOURCE is verified (cert flips on tamper/forgery).")
        print("##        Cleared to wire the s5-opsroom host (109): NATS φ↑ subscriber + this builder.")
        return 0
    if "--gate73" in sys.argv:
        i = sys.argv.index("--gate73")
        path = sys.argv[i + 1] if i + 1 < len(sys.argv) else "/var/lib/vsf/vsf_nucleus/events.jsonl"
        passed, failed, lines = _run_gate73_suite(path)
        print(f"# cybernetic_rag_view --gate73 — REAL φ↑ adapter on events.jsonl ({path})")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## §7.3b: ✗ NOT MET — real-source adapter unsound. Do NOT wire the host.")
            return 1
        print("## §7.3b: ✓ MET — view projects from REAL events.jsonl, chain-verified. Cleared to wire 109.")
        return 0
    if "--emit" in sys.argv:  # print one synthetic tick (for host wiring / inspection)
        con = synthetic_source_con()
        import tempfile
        d = tempfile.mkdtemp()
        sk, pub, signer = ax.load_or_generate_key(os.path.join(d, "k"))
        attest_source(con, os.path.join(d, "a"), sk, signer)
        tick, _ = build_tick(con, os.path.join(d, "a"), {signer: pub})
        print(json.dumps(tick, indent=2))
        return 0
    print("usage: cybernetic_rag_view.py [--gate72 | --emit]   # run on the n02 sandbox, never WSL")
    return 2


if __name__ == "__main__":
    sys.exit(main())
