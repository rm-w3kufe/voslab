#!/usr/bin/env python3
"""
cyberfilter_census.py — Longitudinal Cyberfilter Census (VSF methodology).

Extracts the two-axis viability signature from a running VSF system, from data that
already exists in operation (no new instrumentation):

  Axis A — FILTER CALIBRATION (Ashby / Beer's Cyberfilter):
    From the algedonic ledger. How the S3* audit discriminates variety:
      - attenuation:  fraction of findings auto-resolved with a machine reason
                      (the KNOWN perturbation classes the filter absorbs)
      - frontier:     types that only ESCALATE (0 auto-handled) = variety the filter
                      does not yet model → each is a handler-task (double-loop growth)
      - evidence:     fraction closed with machine-checkable evidence (R12 transition
                      from narrative to evidence-gated closure)

  Axis B — LOOP CLOSURE (Lyapunov / attractor):
    From the nucleus φ↑ chain (events.jsonl). Per run (a restart resets tick→1, the
    canonical perturbation), the recovery trajectory back to the stasis attractor:
      - time-to-attractor (ticks until trust≥THR and stasis_cos≥THR)
      - mean_l trend (descending ⇒ contraction toward the recurrent set)

Double payoff (why it is a METHODOLOGY, not just an analysis):
  (1) it PRODUCES a paper result (longitudinal operational closure, grounded in a
      falsifiable frame: null = detections do not track real excursions AND/OR excursions
      do not return to the attractor);
  (2) it DRIVES the backlog (each frontier type → a filter-handler task; each
      non-recovering perturbation → a viability debt). Measure viability + improve it.

Deterministic, stdlib only. Reproducible: point it at a pulled ledger.db (+ optional
events.jsonl tail). Same inputs → same signature (no timestamps in output ordering).

Usage:
  cyberfilter_census.py --ledger ledger.db [--events events.jsonl] [--attractor 0.999]
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter


def axis_a(ledger_path):
    db = sqlite3.connect(ledger_path)
    db.row_factory = sqlite3.Row
    rows = list(db.execute("SELECT type, status, severity, evidence_json FROM algedonic_ledger"))
    total = len(rows)
    if total == 0:
        return {"total": 0}
    auto = sum(1 for r in rows if r["status"] in ("agent_handled", "auto_handled"))
    escalated = sum(1 for r in rows if r["status"] == "pending_human")
    acked = sum(1 for r in rows if r["status"] == "acked")
    has_ev = sum(1 for r in rows if r["evidence_json"])
    # per-type discrimination
    by_type = {}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        a = sum(1 for r in sub if r["status"] in ("agent_handled", "auto_handled"))
        p = sum(1 for r in sub if r["status"] == "pending_human")
        by_type[t] = {"n": len(sub), "auto": a, "pending": p,
                      "sev": int(max(r["severity"] for r in sub))}
    # frontier = types with escalations but zero auto-handling (filter has no handler)
    frontier = sorted([t for t, v in by_type.items() if v["auto"] == 0 and v["pending"] > 0],
                      key=lambda t: -by_type[t]["pending"])
    return {
        "total": total,
        "attenuation_rate": round(auto / total, 3),
        "escalation_rate": round(escalated / total, 3),
        "acked": acked,
        "evidence_coverage": round(has_ev / total, 3),
        "frontier": frontier,
        "frontier_load": sum(by_type[t]["pending"] for t in frontier),
        "by_type": by_type,
    }


def axis_b(events_path, attractor=0.999):
    """Split the φ↑ stream into runs at tick resets; per run measure recovery."""
    runs = _split_runs(events_path)
    out = []
    for run in runs:
        if len(run) < 2:
            continue
        # time to attractor: first tick where trust and stasis_cos both >= attractor
        ttr = None
        for r in run:
            if r["trust"] is not None and r["stasis_cos"] is not None \
               and r["trust"] >= attractor and r["stasis_cos"] >= attractor:
                ttr = r["tick"]
                break
        mls = [r["mean_l"] for r in run if r["mean_l"] is not None]
        l_descends = len(mls) >= 2 and mls[-1] < mls[0]
        out.append({
            "start_tick": run[0]["tick"], "end_tick": run[-1]["tick"],
            "len": len(run),
            "trust_start": round(run[0]["trust"], 4) if run[0]["trust"] is not None else None,
            "time_to_attractor_ticks": ttr,
            "mean_l_start": round(mls[0], 5) if mls else None,
            "mean_l_end": round(mls[-1], 5) if mls else None,
            "l_descends": l_descends,
            "recovered": ttr is not None,
        })
    return out


def axis_b_excursions(events_path, dip=0.999, warmup_skip=15):
    """Organic (within-run) perturbation→recovery: post-warmup dips of stasis_cos below
    `dip` that return, WITHOUT a restart. This is the external-perturbation recovery the
    per-run warmup metric cannot see (the system perturbed while healthy, returning).

    KNOWN RESULT (EXP-S4-02): stasis_cos is the variable the kernel REGULATES to invariance
    — Block-A dims dominate the 128-D cosine and absorb Block-B perturbation — so at a healthy
    operating point it rarely dips below 0.999. A count of 0 here CONFIRMS the regulated-variable
    finding at longitudinal scale; it does NOT mean 'no perturbations'. To see organic
    excursion→recovery, measure the PERTURBATION channel (Block-B pressures / entropy / mean_l /
    omega.margin_free), not the regulated variable. (Census v2 TODO: --channel flag.)"""
    runs = _split_runs(events_path)
    exc = []
    for run in runs:
        settled = [r for r in run if r["tick"] is not None and r["tick"] > warmup_skip
                   and r["stasis_cos"] is not None]
        if len(settled) < 3:
            continue
        in_e = False
        start = mn = None
        for r in settled:
            sc = r["stasis_cos"]
            if not in_e and sc < dip:
                in_e, start, mn = True, r["tick"], sc
            elif in_e:
                mn = min(mn, sc)
                if sc >= dip:
                    exc.append({"start": start, "depth": round(mn, 5),
                                "recovery_ticks": r["tick"] - start, "recovered": True})
                    in_e = False
        if in_e:
            exc.append({"start": start, "depth": round(mn, 5),
                        "recovery_ticks": None, "recovered": False})
    return exc


def _split_runs(events_path):
    runs, cur, prev = [], [], None
    for line in open(events_path):
        if '"kernel_tick"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("metrics", {})
        tick = m.get("tick")
        k = m.get("kernel", {})
        rec = {"tick": tick, "stasis_cos": k.get("stasis_cos"),
               "trust": k.get("trust"), "mean_l": m.get("lyapunov", {}).get("mean_l")}
        if prev is not None and tick is not None and tick < prev:
            if cur:
                runs.append(cur)
            cur = []
        cur.append(rec)
        prev = tick
    if cur:
        runs.append(cur)
    return runs


def main():
    ap = argparse.ArgumentParser(description="Longitudinal Cyberfilter Census")
    ap.add_argument("--ledger", required=True, help="path to algedonic ledger.db")
    ap.add_argument("--events", help="path to a nucleus events.jsonl (tail is fine)")
    ap.add_argument("--attractor", type=float, default=0.999, help="attractor threshold")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    a = axis_a(args.ledger)
    b = axis_b(args.events, args.attractor) if args.events else None
    exc = axis_b_excursions(args.events, args.attractor) if args.events else None
    sig = {"axis_a_filter_calibration": a, "axis_b_loop_closure": b,
           "axis_b_organic_excursions": exc}

    if args.json:
        print(json.dumps(sig, indent=2))
        return

    print("═══ LONGITUDINAL CYBERFILTER CENSUS ═══")
    print(f"\nAXIS A — filter calibration ({a['total']} findings)")
    print(f"  attenuation (auto-resolved known variety): {a['attenuation_rate']:.0%}")
    print(f"  escalation  (to human):                    {a['escalation_rate']:.0%}")
    print(f"  evidence-gated closure (R12):              {a['evidence_coverage']:.0%}")
    print(f"  variety FRONTIER (un-modeled → handler tasks): {', '.join(a['frontier']) or '(none)'}")
    print(f"    frontier load (pending, un-handled): {a['frontier_load']}")
    print("  discrimination by type (auto / pending):")
    for t, v in sorted(a["by_type"].items(), key=lambda kv: -kv[1]["sev"]):
        tag = "  ← FRONTIER" if t in a["frontier"] else ""
        print(f"    {t:22} auto={v['auto']:>3} pend={v['pending']:>3} sev={v['sev']}{tag}")
    if b is not None:
        print(f"\nAXIS B — loop closure ({len(b)} runs, attractor≥{args.attractor})")
        rec = sum(1 for r in b if r["recovered"])
        desc = sum(1 for r in b if r["l_descends"])
        print(f"  runs that recovered to attractor: {rec}/{len(b)}")
        print(f"  runs with mean_l descending (contraction): {desc}/{len(b)}")
        for r in b:
            ttr = r["time_to_attractor_ticks"]
            print(f"    run[{r['start_tick']}..{r['end_tick']}] len={r['len']:>3} "
                  f"trust0={r['trust_start']} ttr={ttr} "
                  f"L:{r['mean_l_start']}→{r['mean_l_end']} {'↓' if r['l_descends'] else '·'}")
        if exc is not None:
            rec = sum(1 for e in exc if e["recovered"])
            print(f"\n  ORGANIC excursions (post-warmup dip<{args.attractor}, no restart): {len(exc)}"
                  f"  recovered: {rec}/{len(exc)}")
            for e in exc[:12]:
                rt = e["recovery_ticks"]
                print(f"    dip@tick{e['start']} depth={e['depth']} "
                      f"recovery={'%d ticks' % rt if rt is not None else 'truncated'}")


if __name__ == "__main__":
    sys.exit(main())
