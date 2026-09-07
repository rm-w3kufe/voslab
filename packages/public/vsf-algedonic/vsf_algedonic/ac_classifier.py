#!/usr/bin/env python3
"""
Algedonic Classifier (AC) — deterministic decision tree over φ↑ events.

Transcribes the AC primer thresholds (ac_algedonic.py) into pure Python so the
algedonic path S1→S5 needs no LLM (D6': LLM only at the human-interface boundary;
signal channels use deterministic/statistical methods). Cybersyn: Cyberfilter is
statistical, Opsroom is human synthesis.

UPDATED: Now uses socratic engine for decision logic via ac_classify.tree.vsm
Predicates registered: ac_viable_false, ac_stasis_critical, ac_stasis_warning,
ac_trust_degraded, ac_regime_not_nominal, ac_algedonic_critical,
ac_algedonic_warning, ac_invariant_streak, ac_invariant_magnitude,
ac_s4_ethics_candidate
"""

import json
import os
import re
import sys
from pathlib import Path

# Add classifier path for socratic engine
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "vsl" / "classifier"))

from vsf_socratic_engine import _create_engine, _ROOT

# Built-in defaults — overridden by norm.vsm when present (F3.a: the ratifiable
# operating norm is the single source; these remain as fail-safe for the signal
# path if the file is absent or unparsable).
STASIS_WARN     = 0.80
STASIS_CRITICAL = 0.70
TRUST_WARN      = 0.8
REGIME_NOMINAL  = 'in_recurrent_set'
INV_CONSEC_WARN = 3      # consecutive pass=False+warn ticks per invariant = concern
INV_MAG_LARGE   = 1e-3   # |value| at/above this = large magnitude = concern

_NORM_PATHS = [
    os.environ.get('VSF_NORM_PATH', ''),
    '/root/vsf-scripts/norm.vsm',                                  # LXC deploy location
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', 'docs', 'spec', 'norm.vsm'),                # repo (WSL dev)
]

NORM_SOURCE = 'built-in defaults'

# Load tree
TREE = _ROOT / ".opencode/plugins/support/trees/ac_classify.tree.vsm"


def _load_norm() -> None:
    """Read thresholds from norm.vsm (block-aware key=value scan). Fail-safe:
    any error leaves the built-in defaults untouched."""
    global STASIS_WARN, STASIS_CRITICAL, TRUST_WARN, REGIME_NOMINAL
    global INV_CONSEC_WARN, INV_MAG_LARGE, NORM_SOURCE
    path = next((p for p in _NORM_PATHS if p and os.path.exists(p)), None)
    if path is None:
        return
    try:
        block, vals = None, {}
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.split('//')[0].strip()
                m = re.match(r'^(\w+)\s*\{', line)
                if m:
                    block = m.group(1)
                    continue
                if line.startswith('}'):
                    block = None
                    continue
                m = re.match(r'^(\w+)\s*=\s*("?)([^"]*)\2', line)
                if m and block:
                    vals[f'{block}.{m.group(1)}'] = m.group(3).strip()
        STASIS_WARN     = float(vals.get('stasis_cos.warn_below', STASIS_WARN))
        STASIS_CRITICAL = float(vals.get('stasis_cos.critical_below', STASIS_CRITICAL))
        TRUST_WARN      = float(vals.get('trust.warn_below', TRUST_WARN))
        REGIME_NOMINAL  = vals.get('regime.nominal', REGIME_NOMINAL)
        INV_CONSEC_WARN = int(vals.get('invariants.consec_warn_max', INV_CONSEC_WARN))
        INV_MAG_LARGE   = float(vals.get('invariants.magnitude_max', INV_MAG_LARGE))
        NORM_SOURCE = path
    except Exception as exc:                      # fail-safe: defaults stand
        print(f'AC: norm.vsm load failed ({exc}) — using built-in defaults',
              file=sys.stderr)


_load_norm()

_SEVERITY = {'A': 2, 'B': 1, 'C': 0}
_ACTION = {
    'A': 'escalate to S5/human operator now',
    'B': 'monitor — re-evaluate next AC cycle',
    'C': 'none — system nominal',
}

def _category_from_label(label: str) -> str:
    """Map primary finding label to a category tag (F3.b observation field)."""
    label = label.lower()
    if 'viable' in label:      return 'not_viable'
    if 'stasis' in label:      return 'stasis_deviation'
    if 'trust' in label:       return 'trust_deviation'
    if 'regime' in label:      return 'regime_deviation'
    if 'algedonic' in label:   return 'algedonic'
    if 'invariant' in label:   return 'invariant_deviation'
    if 'telemetry' in label:   return 'telemetry_missing'
    if 's4_ethics' in label:   return 's4_ethics_candidate'
    return 'nominal'


def _severity_int(cls: str, category: str) -> int:
    """Numeric severity for Beer algedonic channel and s5-alerts.db schema."""
    if cls == 'A':
        return 8
    if cls == 'B':
        return 6 if category == 'trust_deviation' else 5
    return 2


def parse_events(raw_text: str) -> list:
    """Parse φ↑ JSONL text into event dicts; malformed lines are dropped."""
    events = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict):
            events.append(e)
    return events


def classify(events: list) -> dict:
    """Decision tree over a φ↑ event window (oldest → newest).

    Returns {'cls','label','evidence','context','action','severity','category',
             'survival_mode_trigger','s4_timeout_count'} — extended for F3.b wiring.
    
    Uses socratic engine for decision logic via ac_classify.tree.vsm."""
    last_tick = None          # most recent kernel_tick metrics
    consec_warn = {}          # invariant_id → consecutive pass=False+warn count
    inv_max_mag = {}          # invariant_id → max |value| seen in window
    algedonic = []            # (status, payload) of algedonic_signal events
    s4_ethics_candidates = [] # recommendation strings from s4_ethics_scan events
    n_ticks = 0
    consec_critical_not_viable = 0   # consecutive ticks with stasis < CRITICAL and viable=False
    max_consec_cnv = 0               # peak of the above (for survival_mode trigger)
    s4_timeout_count = 0             # s4-analysis events with status=timeout

    for e in events:
        etype = e.get('event_type')
        m = e.get('metrics', {}) or {}
        if etype == 'kernel_tick':
            n_ticks += 1
            k = m.get('kernel', {}) or {}
            if k.get('stasis_cos') is not None:
                sc = k.get('stasis_cos')
                viable = k.get('viable')
                last_tick = {
                    'stasis_cos': sc,
                    'viable':     viable,
                    'trust':      k.get('trust'),
                    'regime':     (m.get('lyapunov', {}) or {}).get('regime'),
                }
                if sc < STASIS_CRITICAL and viable is False:
                    consec_critical_not_viable += 1
                    max_consec_cnv = max(max_consec_cnv, consec_critical_not_viable)
                else:
                    consec_critical_not_viable = 0
        elif etype in ('s4-analysis', 's4_analysis') and e.get('status') == 'timeout':
            s4_timeout_count += 1
        elif etype == 'invariant_check':
            inv = m.get('invariant_id', '?')
            warn = (m.get('pass') is False) and (e.get('status') == 'warn')
            consec_warn[inv] = consec_warn.get(inv, 0) + 1 if warn else 0
            if m.get('pass') is False:
                try:
                    mag = abs(float(m.get('value', 0)))
                except (TypeError, ValueError):
                    mag = 0.0
                inv_max_mag[inv] = max(inv_max_mag.get(inv, 0.0), mag)
        elif etype == 'algedonic_signal':
            algedonic.append((e.get('status', '?'), json.dumps(m)[:80]))
        elif etype == 's4_ethics_scan':
            rec = m.get('recommendation', 'REVIEW')
            s4_ethics_candidates.append(rec)

    # Build context for socratic engine
    ctx = {
        'last_tick': last_tick,
        'consec_warn': consec_warn,
        'inv_max_mag': inv_max_mag,
        'algedonic': algedonic,
        's4_ethics_candidates': s4_ethics_candidates,
    }

    # Use socratic engine for decision
    engine = _create_engine()
    tree_text = TREE.read_text(encoding="utf-8")
    result = engine.evaluate(tree_text, ctx)
    
    # Map home to classification
    cls = result.home
    label = result.evidence.get('truth', 'unknown') if result.evidence else 'unknown'
    
    # Build evidence string
    findings = []
    if last_tick is None:
        findings.append('no kernel telemetry')
    else:
        if last_tick['viable'] is False:
            findings.append('viable=False')
        sc = last_tick['stasis_cos']
        if sc < STASIS_CRITICAL:
            findings.append(f'stasis_cos={sc:.4f} < {STASIS_CRITICAL}')
        elif sc < STASIS_WARN:
            findings.append(f'stasis_cos={sc:.4f} < {STASIS_WARN}')
        tr = last_tick['trust']
        if tr is not None and tr < TRUST_WARN:
            findings.append(f'trust={tr:.3f} < {TRUST_WARN}')
        regime = last_tick['regime']
        if regime is not None and regime != REGIME_NOMINAL:
            findings.append(f'regime={regime}')
    
    for status, payload in algedonic:
        findings.append(f'algedonic_signal status={status}')
    
    for inv, count in consec_warn.items():
        if count >= INV_CONSEC_WARN:
            findings.append(f'{inv} warn x{count}')
    for inv, mag in inv_max_mag.items():
        if mag >= INV_MAG_LARGE:
            findings.append(f'{inv} |value|={mag:.2e}')
    
    if s4_ethics_candidates:
        findings.append(f's4_ethics: {", ".join(s4_ethics_candidates)}')
    
    evidence = '; '.join(findings) if findings else 'all nominal'

    context = (f'window: {len(events)} events, {n_ticks} kernel_ticks; '
               f'invariant warn streaks: '
               + (', '.join(f'{i}={c}' for i, c in sorted(consec_warn.items())) or 'none')
               + f'; s4_ethics_scans: {len(s4_ethics_candidates)}')

    survival_trigger = max_consec_cnv >= INV_CONSEC_WARN
    category = _category_from_label(label)
    return {'cls': cls, 'label': label, 'evidence': evidence,
            'context': context, 'action': _ACTION[cls],
            'severity': _severity_int(cls, category),
            'category': category,
            'survival_mode_trigger': survival_trigger,
            's4_timeout_count': s4_timeout_count}


def classify_raw(raw_text: str) -> dict:
    """Convenience: parse JSONL text and classify."""
    return classify(parse_events(raw_text))
