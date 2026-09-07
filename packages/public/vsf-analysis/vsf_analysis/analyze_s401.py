#!/usr/bin/env python3
"""
analyze_s401.py — EXP-S4-01 analysis: S4 anticipation lead_time measurement.

Reads events.jsonl from nucleus + clima phi_up logs.
Measures: t(predictive_alert) − t(first_clima_excursion) = lead_time.

H_S401a: lead_time > 0 (S4 anticipates before algedonic fires).
H_S401_null: lead_time <= 0 (reaction only, no anticipation advantage).

Usage:
  python3 scripts/analysis/analyze_s401.py --events /path/to/events.jsonl
                                  [--clima-log /path/to/l3-punta-arenas.phi_up.jsonl]
                                  [--out docs/experiments/EXP-S4-01/results.vsm]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_ts(s: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    s = s.rstrip("Z").replace("T", " ")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.fromisoformat(s.split(".")[0]).replace(tzinfo=timezone.utc)


def load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file, skip bad lines and binary (Merkle chain) data."""
    events = []
    try:
        with open(path, "rb") as f:
            for raw_line in f:
                # Skip lines that start with non-printable bytes (Merkle chain binary headers)
                if not raw_line.strip():
                    continue
                try:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("{"):
                        continue
                    events.append(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
    except FileNotFoundError:
        print(f"[WARN] file not found: {path}", file=sys.stderr)
    return events


def extract_nucleus_events(events: list[dict], event_type: str) -> list[dict]:
    """Extract events of given type from nucleus events.jsonl."""
    return [e for e in events if e.get("event_type") == event_type]


def analyze(nucleus_path: Path, clima_log: Path | None, out_path: Path | None):
    print(f"[EXP-S4-01] loading nucleus events from {nucleus_path}")
    nucleus = load_jsonl(nucleus_path)
    print(f"  loaded {len(nucleus)} events")

    # --- NUCLEUS EVENTS ---
    alerts = extract_nucleus_events(nucleus, "predictive_alert")
    algeds = extract_nucleus_events(nucleus, "algedonic_emit")
    synths = extract_nucleus_events(nucleus, "s4_cross_domain_synthesis")

    print(f"\n--- NUCLEUS ---")
    print(f"  predictive_alert events: {len(alerts)}")
    print(f"  algedonic_emit events:   {len(algeds)}")
    print(f"  s4_cross_domain_synthesis events: {len(synths)}")

    # Print predictive_alert details
    if alerts:
        print("\n  predictive_alert details:")
        for a in alerts[-5:]:
            ts = a.get("ts", "?")
            m  = a.get("metrics", {})
            trig = m.get("trigger", m.get("triggers", "?"))
            conf = m.get("confidence", m.get("projection_confidence", "?"))
            sc   = m.get("projected_stasis_cos", "?")
            lead = m.get("lead_time_ticks", "?")
            print(f"    {ts} trigger={trig} conf={conf} projected_sc={sc} lead_time_ticks={lead}")

    if algeds:
        print("\n  algedonic_emit details:")
        for a in algeds[-5:]:
            ts = a.get("ts", "?")
            m  = a.get("metrics", {})
            cat = m.get("category", m.get("reason", "?"))
            sev = m.get("severity", "?")
            print(f"    {ts} category={cat} severity={sev}")

    # --- LEAD TIME MEASUREMENT (nucleus predictive_alert vs algedonic_emit) ---
    print("\n--- LEAD TIME MEASUREMENT ---")
    if not alerts and not algeds:
        h_result = "INCONCLUSIVE: no predictive_alert or algedonic_emit found"
    elif not alerts:
        h_result = "H_S401_null: predictive_alert never fired — algedonic only"
    elif not algeds:
        h_result = "PARTIAL: predictive_alert fired but no algedonic (load may have been too low)"
    else:
        # Match nearest algedonic to each alert
        lead_times = []
        for alert in alerts:
            alert_ts = parse_ts(alert.get("ts", ""))
            nearest_alg = min(algeds, key=lambda a: abs(
                (parse_ts(a.get("ts", "")) - alert_ts).total_seconds()
            ))
            alg_ts = parse_ts(nearest_alg.get("ts", ""))
            lead_s = (alg_ts - alert_ts).total_seconds()  # positive = alert fired before alg
            lead_times.append(lead_s)
            print(f"  alert={alert.get('ts')} algedonic={nearest_alg.get('ts')} lead={lead_s:.0f}s")

        mean_lead = sum(lead_times) / len(lead_times)
        if mean_lead > 0:
            h_result = f"H_S401a CONFIRMED: mean lead_time={mean_lead:.0f}s (S4 anticipates)"
        else:
            h_result = f"H_S401_null: mean lead_time={mean_lead:.0f}s (reaction, no anticipation)"

    print(f"\n  HYPOTHESIS: {h_result}")

    # --- CLIMA EXCURSION ANALYSIS (if clima log provided) ---
    clima_excursions = []
    if clima_log and clima_log.exists():
        print(f"\n--- CLIMA EXCURSIONS from {clima_log} ---")
        clima_events = load_jsonl(clima_log)
        for e in clima_events:
            if not e.get("in_omega", True):
                ts = e.get("ts", "?")
                sc = e.get("stasis_cos", "?")
                nid = e.get("node_id", "?")
                clima_excursions.append(e)
                print(f"  excursion: {nid} @ {ts} stasis_cos={sc}")

        if not clima_excursions:
            print("  no excursions found in clima log")
        else:
            # Measure: first clima excursion ts vs first predictive_alert ts
            first_excursion = min(clima_excursions, key=lambda e: e.get("ts", ""))
            exc_ts = parse_ts(first_excursion.get("ts", ""))
            if alerts:
                first_alert = min(alerts, key=lambda a: a.get("ts", ""))
                alert_ts = parse_ts(first_alert.get("ts", ""))
                s4_lead = (exc_ts - alert_ts).total_seconds()
                print(f"\n  first_excursion: {first_excursion.get('ts')} node={first_excursion.get('node_id')}")
                print(f"  first_alert:     {first_alert.get('ts')}")
                print(f"  S4_LEAD_vs_CLIMA: {s4_lead:.0f}s (positive = S4 fired before excursion)")
                if s4_lead > 0:
                    clima_verdict = f"H_S401a (CLIMA): S4 fired {s4_lead:.0f}s BEFORE first excursion"
                else:
                    clima_verdict = f"H_S401_null (CLIMA): S4 fired {abs(s4_lead):.0f}s AFTER first excursion"
                print(f"  CLIMA VERDICT: {clima_verdict}")

    # --- S4_SYNTH RESULTS ---
    if synths:
        print(f"\n--- S4_CROSS_DOMAIN_SYNTHESIS ({len(synths)} events) ---")
        for s in synths[-3:]:
            ts = s.get("ts", "?")
            m  = s.get("metrics", {})
            synthesis = m.get("synthesis", "?")
            urgency   = m.get("urgency", "?")
            print(f"  {ts} urgency={urgency}: {synthesis}")

    # --- RESULTS.VSM ---
    if out_path:
        now = datetime.utcnow().isoformat() + "Z"
        results_vsm = f"""@vsm 1.2.1
// EXP-S4-01 results — generated {now}
// analyzer: scripts/analysis/analyze_s401.py

results(EXP-S4-01, "S4 anticipatory channel validation") {{
  run_date:   "{now}"
  n_alerts:   {len(alerts)}
  n_algeds:   {len(algeds)}
  n_synths:   {len(synths)}
  n_clima_excursions: {len(clima_excursions)}

  verdict: "{h_result}"

  per_alert: [
"""
        for i, a in enumerate(alerts):
            m = a.get("metrics", {})
            results_vsm += f"""    {{
      ts: "{a.get('ts', '?')}"
      trigger: "{m.get('trigger', m.get('triggers', '?'))}"
      confidence: {m.get('confidence', m.get('projection_confidence', 0))}
      lead_time_ticks: {m.get('lead_time_ticks', 'null')}
    }}"""
            if i < len(alerts) - 1:
                results_vsm += ","
            results_vsm += "\n"

        results_vsm += """  ]
}
"""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(results_vsm)
        print(f"\n[EXP-S4-01] results written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="EXP-S4-01 analysis script")
    parser.add_argument("--events", default="/var/lib/vsf/vsf_nucleus/events.jsonl",
                        help="nucleus events.jsonl path")
    parser.add_argument("--clima-log", default=None,
                        help="clima L3 phi_up.jsonl for excursion analysis")
    parser.add_argument("--out", default=None,
                        help="output results.vsm path")
    args = parser.parse_args()

    analyze(
        nucleus_path=Path(args.events),
        clima_log=Path(args.clima_log) if args.clima_log else None,
        out_path=Path(args.out) if args.out else None,
    )


if __name__ == "__main__":
    main()
