#!/usr/bin/env python3
# design: docs/spec_revision/design-sources/hardening-gaps-2026-10.vsm
"""variety_census.py — Delta C de hardening-gaps-2026-10 (task
HARDENING-VARIETY-CENSUS-1).

Variedad (VSM) más afirmada que medida → censo determinista sobre el
canal vivo logs/agent_plugin.jsonl (R10: conteo puro, sin LLM):

  1. taxonomía source×event_type por ventana (--window-days, default 7)
  2. cobertura = clases cuyo event_type matchea el trigger de algún
     plugin registrado (.opencode/plugins/registry.json) o cuyo source
     matchea un plugin/check registrado (checks_manifest)
   3. novelty: clase NUEVA (fuera del baseline) SIN handler registrado →
      emite alerta variety_deficit al canal algedónico canónico
      (state/rsi/alerts.jsonl, vía el emitter de Delta A)
   4. error_burst (S2, shadow-inventory-2026-10): clase con ≥N
      level=error en la ventana viva → alerta error_burst (class HEALTH
      post-detector R16) — covered ≠ actuado: tener handler no es tener
      camino de remediación
   5. reporte a state/epistemic/reports/variety_census_latest.json (+dated)

Baseline: state/variety/census_baseline.json — la primera corrida
(--update-baseline) snapshota las clases de la ventana; las corridas
posteriores miden novedad contra él.

Usage:
  variety_census.py [--window-days 7] [--update-baseline] [--no-emit]
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import importlib.util
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOG = os.path.join(ROOT, "logs", "agent_plugin.jsonl")
REGISTRY = os.path.join(ROOT, ".opencode", "plugins", "registry.json")
CHECKS_MANIFEST = os.path.join(
    ROOT, "packages", "public", "vsf-checks", "vsf_checks",
    "checks_manifest.json")
BASELINE = os.path.join(ROOT, "state", "variety", "census_baseline.json")
REPORTS = os.path.join(ROOT, "state", "epistemic", "reports")
ALERTS = os.path.join(ROOT, "state", "rsi", "alerts.jsonl")

# v2 (2026-10-19, S5 autopsy of the first census): coverage matched ONLY
# registry.json plugins — 118/124 "uncovered" classes were FALSE NEGATIVES
# (gate suite consumes its own gate.evaluate; rsi_bridge consumes
# rsi-cycle.*; sandbox.exec/session.idle/write.audit are self-consumed
# observability by the emitting daemon). Declared handler families — the
# honest consumer map. R10: deterministic membership, no inference.
HANDLER_FAMILIES = [
    {"name": "gate-suite", "consumer": "run_gates.py harness",
     "event_types": ["gate.evaluate"]},
    {"name": "rsi-bridge", "consumer": "tool_integration_bridge → kernel",
     "source_prefix": "rsi-cycle"},
    {"name": "self-observability",
     "consumer": "invoking daemon reads its own exec/activation result",
     "event_types": ["sandbox.exec", "session.idle", "write.audit"]},
]


def _load_emitter():
    """Reuse Delta A's dedup emitter (single writer to the channel)."""
    path = os.path.join(HERE, "external_detectors.py")
    spec = importlib.util.spec_from_file_location("ext_det_emit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── S2 error_burst (shadow-inventory-2026-10 / SHADOW-ERROR-TRIAGE-1) ─────
# R16 medir→alertar: escaneo de ~30 slices rotados (2026-10-20). Ráfaga
# incidente E2BIG (2026-10-19 22:17Z): tool-bridge:bridge.error=8,
# gap-resolver:gap.evaluate=7 en un slice; slices tranquilos ≤4 por clase.
# N=5 captura los incidentes S2 (7,6 y 8,7) sin disparar en ruido ≤4.
# Nota: la ventana efectiva es el slice del log vivo (rotación ~1h) ∩
# --window-days; la cadencia de corrida la dará SHADOW-SCHEDULED-SUITE-1.
BURST_THRESHOLD = 5


def detect_error_burst(error_counts, threshold=BURST_THRESHOLD,
                       window_label=""):
    """S2 cubierto≠actuado: clase con ≥threshold level=error en ventana.

    Puro/determinista (R10): dict {(src, evt): n} → lista de alertas,
    sin I/O ni reloj. Emisión vía el emitter canónico (dedupe
    (alert_type, source) unacked); class HEALTH en alert_triage TYPE_IMPACT
    (R16 post-detector).
    """
    out = []
    for (src, evt), n in sorted(error_counts.items()):
        n = int(n)
        if n >= int(threshold):
            where = f" en {window_label}" if window_label else ""
            out.append({
                "level": "error",
                "alert_type": "error_burst",
                "source": f"variety-census({src}:{evt})",
                "detail": (f"clase {src}:{evt} con {n} level=error{where} "
                           f"(>= umbral {threshold}) — errores sin "
                           f"triage (shadow-inventory S2)"),
            })
    return out


def _norm(row: dict) -> tuple[str, str]:
    """Schema A (instrument/hook) → B (source/event_type); tolerate ?."""
    src = row.get("source") or row.get("instrument") or "?"
    evt = row.get("event_type") or row.get("hook") or "?"
    return str(src), str(evt)


def _parse_ts(s) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def load_log(window_days: int, now: dt.datetime | None = None):
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=window_days) if window_days > 0 else None
    classes = Counter()
    sources = Counter()
    levels = Counter()
    error_classes = Counter()
    first_ts = None
    last_ts = None
    total = 0
    bad = 0
    with open(LOG) as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                bad += 1
                continue
            ts = _parse_ts(row.get("ts"))
            if cutoff and (ts is None or ts < cutoff):
                continue
            src, evt = _norm(row)
            classes[(src, evt)] += 1
            sources[src] += 1
            levels[str(row.get("level", "?"))] += 1
            if str(row.get("level", "")) == "error":
                error_classes[(src, evt)] += 1
            if ts is not None:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            total += 1
    span = (first_ts, last_ts)
    return classes, sources, levels, total, bad, error_classes, span


def _span_label(span, window_days: int) -> str:
    """Ventana efectiva del slice (rotación ~1h) ∩ window_days."""
    first, last = span
    if first is None or last is None:
        return f"slice vacío (window={window_days}d)"
    return (f"slice {first.strftime('%Y-%m-%dT%H:%MZ')}→"
            f"{last.strftime('%Y-%m-%dT%H:%MZ')} (window={window_days}d)")


def load_coverage() -> tuple[set, set, set]:
    """(event_types with registered trigger, plugin names, check names)."""
    triggers: set = set()
    plugins: set = set()
    try:
        reg = json.load(open(REGISTRY))
        for _cat, bundle in (reg.get("plugins") or {}).items():
            for pname, pdef in (bundle.get("plugins") or {}).items():
                plugins.add(pname)
                trig = pdef.get("trigger")
                if trig:
                    triggers.add(str(trig))
        for h in (reg.get("handlers") or {}).keys():
            plugins.add(str(h))
    except Exception:
        pass
    checks: set = set()
    try:
        man = json.load(open(CHECKS_MANIFEST))
        entries = man.get("checks") or man.get("entries") or man
        if isinstance(entries, dict):
            checks.update(str(k) for k in entries.keys())
        elif isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict):
                    checks.add(str(e.get("name") or e.get("id") or ""))
                else:
                    checks.add(str(e))
        checks.discard("")
    except Exception:
        pass
    return triggers, plugins, checks


def _covered(src: str, evt: str, triggers: set, plugins: set,
             checks: set) -> tuple[bool, str]:
    """Deterministic coverage: trigger glob-match, name membership, or
    declared handler family. Returns (covered, by_what)."""
    for t in triggers:
        try:
            if fnmatch.fnmatch(evt, t) or fnmatch.fnmatch(t, evt):
                return True, f"plugin-trigger:{t}"
        except Exception:
            continue
    if src in plugins:
        return True, "plugin-name"
    if src in checks:
        return True, "check-name"
    for fam in HANDLER_FAMILIES:
        if evt in (fam.get("event_types") or []):
            return True, f"family:{fam['name']}"
        pref = fam.get("source_prefix")
        if pref and src.startswith(pref):
            return True, f"family:{fam['name']}"
    return False, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--no-emit", action="store_true")
    ap.add_argument("--burst-threshold", type=int, default=BURST_THRESHOLD,
                    help="≥N level=error por clase → alerta error_burst "
                         f"(default {BURST_THRESHOLD}, medido R16 2026-10-20)")
    args = ap.parse_args()

    classes, sources, levels, total, bad, error_classes, span = load_log(
        args.window_days)
    triggers, plugins, checks = load_coverage()
    known: set = set()
    if os.path.isfile(BASELINE):
        try:
            known = set(map(tuple, json.load(open(BASELINE)).get(
                "classes", [])))
        except Exception:
            known = set()

    covered, uncovered = [], []
    cover_who = Counter()
    for (src, evt), n in sorted(classes.items()):
        ok, by = _covered(src, evt, triggers, plugins, checks)
        item = {"source": src, "event_type": evt, "n": n, "covered": ok,
                "by": by}
        if ok:
            cover_who[by.split(":")[0] if ":" not in by else
                      ":".join(by.split(":")[:2])] += 1
            covered.append(item)
        else:
            uncovered.append(item)

    novelty = [c for c in uncovered
               if (c["source"], c["event_type"]) not in known]
    # v2: the SILENCE side — baseline classes with zero events in window.
    # Report-only first (R16: measure before alerting): a rare class absent
    # 7d is not yet distinguishable from a dead component.
    vanished = sorted([list(k) for k in known if k not in classes])

    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    if args.update_baseline:
        with open(BASELINE, "w") as fp:
            json.dump({
                "snapshot_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "window_days": args.window_days,
                "classes": sorted([list(k) for k in classes]),
            }, fp, indent=1)

    emitted = 0
    bursts = detect_error_burst(dict(error_classes), args.burst_threshold,
                                _span_label(span, args.window_days))
    if (novelty or bursts) and not args.no_emit:
        em = _load_emitter()
        alerts = []
        if novelty:
            alerts.append({
                "level": "HEALTH",
                "alert_type": "variety_deficit",
                "source": "variety-census",
                "detail": (f"{len(novelty)} clase(s) nueva(s) sin handler "
                           f"registrado: "
                           + ", ".join(f"{c['source']}:{c['event_type']}"
                                       for c in novelty[:5])
                           + (f" (+{len(novelty)-5})" if len(novelty) > 5
                              else "")),
            })
        alerts.extend(bursts)
        emitted = em.emit(alerts, ALERTS)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "window_days": args.window_days,
        "log_lines_in_window": total,
        "unparseable_lines": bad,
        "distinct_sources": len(sources),
        "distinct_classes": len(classes),
        "covered_classes": len(covered),
        "coverage_frac": round(len(covered) / len(classes), 4)
        if classes else None,
        "coverage_by": dict(cover_who.most_common()),
        "vanished_classes": vanished,
        "vanished_count": len(vanished),
        "levels": dict(levels.most_common()),
        "top_classes": [{"source": s, "event_type": e, "n": n}
                        for (s, e), n in classes.most_common(15)],
        "uncovered_classes": uncovered[:40],
        "novelty": novelty[:40],
        "novelty_count": len(novelty),
        "error_burst_threshold": args.burst_threshold,
        "error_counts": {f"{s}:{e}": n
                         for (s, e), n in error_classes.most_common()},
        "error_burst_fired": [a["source"] for a in bursts],
        "baseline_known": len(known),
        "baseline_updated": bool(args.update_baseline),
        "alerts_emitted": emitted,
    }
    os.makedirs(REPORTS, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    for path in (os.path.join(REPORTS, "variety_census_latest.json"),
                 os.path.join(REPORTS, f"variety_census_{stamp}.json")):
        with open(path, "w") as fp:
            json.dump(report, fp, indent=1)

    print(f"variety census: window={args.window_days}d lines={total} "
          f"classes={len(classes)} sources={len(sources)} "
          f"coverage={report['coverage_frac']} "
          f"novelty={len(novelty)} bursts={len(bursts)} emitted={emitted}")
    if novelty:
        for c in novelty[:10]:
            print(f"  NOVELTY {c['source']}:{c['event_type']} n={c['n']}")
    for a in bursts:
        print(f"  BURST {a['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
