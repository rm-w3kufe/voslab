#!/usr/bin/env python3
"""s3_shadow_recompute.py — S3* semantic audit: meaning vs number (G2).
design: docs/spec_revision/design-sources/driver-topology-v1/driver_topology.vsm

Epistemic problem (s3star_audit semantic tier): structural checks pass on a
wrong MEANING — chain intact, broker agrees, number still a lie. This probe
re-derives stasis_cos from the PUBLISHED state vector against the PUBLISHED
stasis reference and compares with the CLAIMED value, sporadically.

Stasis-reference sourcing (S5 decision: option a): the nucleus publishes
BOTH shadow_sv and shadow_st on sampled ticks (tick % 20 == 0, post
SEMANTIC-DIVERGENCE-FIX capture-before-coupling). Recompute uses exactly
what was published. Residual honestly declared (s3star_audit von Neumann
ceiling): a nucleus faking BOTH vector and reference consistently passes —
joint chain+broker+recompute triple-fake is the residual risk. S3*-side
independent replay is the documented evolution, not this probe.

Sporadic-ness comes from the SOURCE (1-in-K sampling upstream, K=20): the
probe processes the newest samples found, no probe-side randomness (R10:
sampling upstream, deciding here — deterministic).

Cosine replica (kernel_step/state_vector.rs exact): dot/(norms), zero-guard
norm < 1e-10 → 0.0, clamp [-1,1]. Any deviation from this replica is a bug
in THIS file, not a finding — parity test pins it.

Findings (canon severities):
  semantic_divergence  |recomputed-claimed| > 0.02 ............ sev 8
    (touches the caution veto BY DESIGN: mis-reporting is grave)
  shadow_malformed     vectors missing/mismatched/non-finite ..... sev 5
Anti-strobe hysteresis (documented deviation from literal canon): flag on
breach, silent while flagged, clear below 0.015. Rationale: an hourly
sev-8 re-fire on a 0.021-vs-0.02 borderline would strobe caution_mode
(suspending ALL S3 decisions per trigger) with zero new information — the
ledger row persists pending_human either way. S5 may overrule to literal.

Runs on LXC 107 (telemetry bind-mount). Cron:
    */10 * * * * flock -n /var/lock/vsf_shadow_recompute.lock python3 /root/vsf-scripts/s3_shadow_recompute.py >> /var/log/vsf-shadow-recompute.log 2>&1
Deploy ships shared/vsf_algedonic_pub.py alongside (canonical publisher).
"""
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone

EVENTS_PATH = os.environ.get("VSF_EVENTS_PATH", "/mnt/telemetry/events.jsonl")
PROBE_DB    = os.environ.get("VSF_SHADOW_PROBE_DB",
                             "/var/lib/vsf/s3_star/shadow_recompute.db")
EPSILON = 0.02
CLEAR_EPSILON = 0.015
MAX_SAMPLES_PER_RUN = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cosine_similarity(a, b) -> float:
    """Exact replica of StateVector::cosine_similarity (state_vector.rs)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    v = dot / (na * nb)
    return max(-1.0, min(1.0, v))


def _as_floats(value):
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        out = [float(x) for x in value]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(x) for x in out):
        return None
    return out


def _validate_sample(sv_raw, st_raw):
    """Present-but-unusable samples are findings, not skips: a published
    degenerate vector (1-element, non-numeric, non-finite, mismatched) is
    exactly the kind of lie this probe exists to catch. Only fully-null
    pairs (non-sampled ticks, sporadic by construction) are skipped."""
    if sv_raw is None and st_raw is None:
        return None
    if sv_raw is None or st_raw is None:
        return ("malformed", "half-published sample (one side null)")
    sv, st = _as_floats(sv_raw), _as_floats(st_raw)
    if sv is None or st is None:
        return ("malformed", "non-numeric/non-finite/degenerate vector")
    if len(sv) != len(st):
        return ("malformed", f"vector lengths differ ({len(sv)} vs {len(st)})")
    return ("ok", sv, st)


def read_samples(path, limit):
    """Newest sampled ticks: dicts with status ok|malformed + fields."""
    samples = []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 512 * 1024))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return samples
    for line in raw.splitlines()[1:]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event_type") != "kernel_tick":
            continue
        metrics = e.get("metrics", {}) or {}
        kernel = metrics.get("kernel", {}) or {}
        claimed = kernel.get("stasis_cos")
        checked = _validate_sample(metrics.get("sampled_state_vector"),
                                   metrics.get("sampled_stasis_vec"))
        if checked is None:
            continue
        status, payload = checked[0], checked[1:]
        samples.append({
            "tick": kernel.get("tick"),
            "ts": e.get("timestamp") or e.get("ts") or "",
            "claimed": claimed,
            "status": status,
            "payload": payload,
        })
    samples.sort(key=lambda s: (s["ts"], s["tick"] if isinstance(s["tick"], int) else 0))
    return samples[-limit:]


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_poll TEXT NOT NULL, kind TEXT NOT NULL,
        detail TEXT NOT NULL, ref TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS poll_state (
        key TEXT PRIMARY KEY, value TEXT)""")
    return conn


def _load_pub_helper():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "shared"),
                 "/root/vsf-scripts/shared",
                 "/usr/local/lib/vsf"):
        mod = os.path.join(cand, "vsf_algedonic_pub.py")
        if os.path.isfile(mod):
            d = os.path.normpath(cand)
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import vsf_algedonic_pub as _m
                return _m
            except Exception as exc:
                print(f"shadow_recompute: publisher import failed ({mod}): {exc}",
                      file=sys.stderr)
                return None
    return None


def run(events_path=EVENTS_PATH, db_path=PROBE_DB, publish=None,
        limit=MAX_SAMPLES_PER_RUN):
    ts_poll = now_iso()
    samples = read_samples(events_path, limit)
    print(f"[{ts_poll}] shadow_recompute: {len(samples)} sampled tick(s) in scope")
    if not samples:
        print("shadow_recompute: no sampled ticks in tail (sparse by design) — silent")
        return 0

    conn = connect(db_path)
    row = conn.execute("SELECT value FROM poll_state WHERE key='divergence_flag'").fetchone()
    flagged = row is not None
    exceptions = []

    for s in samples:
        tick = s["tick"]
        ref = f"tick={tick}"
        if s["status"] == "malformed":
            exceptions.append(("shadow_malformed",
                               f"{ref}: {s['payload']}",
                               "phi_up shadow sample"))
            continue
        sv, st = s["payload"]
        claimed = s["claimed"]
        if not isinstance(claimed, (int, float)) or not math.isfinite(claimed):
            exceptions.append(("shadow_malformed",
                               f"{ref}: claimed stasis_cos missing/non-finite",
                               "phi_up kernel_tick"))
            continue
        recomputed = cosine_similarity(sv, st)
        delta = abs(recomputed - claimed)
        print(f"shadow_recompute: {ref} claimed={claimed:.4f} "
              f"recomputed={recomputed:.4f} delta={delta:.4f}")
        if delta > EPSILON and not flagged:
            flagged = True
            conn.execute("INSERT INTO poll_state(key,value) VALUES"
                         "('divergence_flag',?) ON CONFLICT(key) DO UPDATE "
                         "SET value=excluded.value", (ts_poll,))
            exceptions.append(("semantic_divergence",
                               f"{ref}: |{recomputed:.4f}-{claimed:.4f}|"
                               f"={delta:.4f} > {EPSILON}",
                               "phi_up shadow sample"))
        elif flagged and delta < CLEAR_EPSILON:
            flagged = False
            conn.execute("DELETE FROM poll_state WHERE key='divergence_flag'")
            print(f"shadow_recompute: {ref} back below clear band — flag cleared")

    now_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    for kind, detail, ref in exceptions:
        conn.execute("INSERT INTO exceptions (ts_poll, kind, detail, ref) "
                     "VALUES (?,?,?,?)", (ts_poll, kind, detail, ref))
        print(f"EXCEPTION [{kind}] {detail} ({ref})")
        sev = 8 if kind == "semantic_divergence" else 5
        rate_key = f"algedonic_pub_{kind}_{now_hour}"
        if not conn.execute("SELECT 1 FROM poll_state WHERE key=?",
                            (rate_key,)).fetchone():
            conn.execute("INSERT INTO poll_state(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO NOTHING", (rate_key, ts_poll))
            if publish is not None:
                try:
                    ok = publish(category=kind, severity=sev,
                                 source_id="s3-shadow-recompute", detail=detail)
                    print(f"shadow_recompute: algedonic [{kind}] delivered={ok}")
                except Exception as exc:
                    print(f"shadow_recompute: publish failed [{kind}]: {exc}",
                          file=sys.stderr)
    conn.commit()
    conn.close()
    if not exceptions:
        print("shadow_recompute: nominal — meanings match numbers")
    return 1 if exceptions else 0


def main() -> int:
    helper = _load_pub_helper()
    if helper is None:
        print("shadow_recompute: canonical publisher unavailable (ship shared/"
              "vsf_algedonic_pub.py alongside this script) — findings go "
              "to stdout/cron log ONLY this run", file=sys.stderr)
    return run(publish=(helper.publish if helper else None))


if __name__ == "__main__":
    sys.exit(main())
