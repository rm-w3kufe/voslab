#!/usr/bin/env python3
"""
Algedonic Classifier (AC) — deterministic decision tree (D4-L3, 2026-06-10).

Reads the last N events from φ↑ (events.jsonl on LXC 101) and classifies the
window with the deterministic decision tree in ac_classifier.py (A/B/C),
writing alert.vsm to the local alerts directory and to s5-alerts.db.

No LLM in the alert path (D6', R10 — signal channels use deterministic/
statistical methods). Algedonic latency: minutes → milliseconds.
The pre-D4-L3 Qwen-era alerts in s5-alerts.db remain as training data for
future statistical/DL classifiers over ℝ¹²⁸.

Usage:
    python3 scripts/algedonic/ac_algedonic.py [--n 20] [--out DIR] [--dry-run]

Store: s5-alerts.db ONLY (isolation rule — never writes to rag-nucleus.db).
Failure handling: every failure path emits a class-B self-alert
(monitor-the-monitor, via s4_store.self_alert).
"""

import sys, os, json, datetime, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_store
import ac_classifier
from s4_store import ALERTS_DIR

EVENTS_PATH_LXC = '/var/lib/vsf/vsf_nucleus/events.jsonl'

# ── NATS / phi_down (F3.b P2 wiring) ──────────────────────────────────────────
NATS_URL         = os.environ.get('NATS_URL', 'nats://10.10.20.20:4222')
VSF_ID           = os.environ.get('VSF_ID', 'alpha')
PHI_DOWN_SUBJECT = f'vsf.{VSF_ID}.phi_down.params'
ALGED_SUBJECT    = f'vsf.{VSF_ID}.algedonic'
STATE_PATH       = '/var/lib/vsf/ac_response_state.json'
S4_THROTTLE_REVERT_SECS = 3600   # 1 hour — per response_classes.vsm class 4

# ── D4-L2 ratification constants (response_classes.vsm:1.0) ───────────────────
RATIF_REF   = 'docs/spec/response_classes.vsm:1.0 RATIFIED 2026-06-12 rmw3(S5)'
RC_SURVIVAL = 'RC-3'   # response_class(survival_mode)
RC_S4T      = 'RC-4'   # response_class(s4_throttle)

try:
    import asyncio as _asyncio
    import nats as _nats_lib
    _NATS_OK = True
except ImportError:
    _NATS_OK = False


def _load_state() -> dict:
    """Load persistent response state (empty baseline if absent/corrupt)."""
    try:
        with open(STATE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {
            'survival_mode': {
                'active': False, 'entered_ts': None,
                'pre_s4': 300, 'pre_telemetry': 60, 'recovery_ticks': 0,
            },
            's4_throttle': {
                'active': False, 'entered_ts': None,
                'pre_s4': 300,
            },
        }


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, indent=2)


async def _nats_publish_async(subject: str, payload: dict) -> None:
    nc = await _nats_lib.connect(NATS_URL, connect_timeout=5)
    await nc.publish(subject, json.dumps(payload).encode())
    await nc.drain()


def _nats_publish(subject: str, payload: dict) -> bool:
    if not _NATS_OK:
        print(f'AC: nats-py unavailable — skipping publish to {subject}', file=sys.stderr)
        return False
    try:
        _asyncio.run(_nats_publish_async(subject, payload))
        return True
    except Exception as exc:
        print(f'AC: NATS publish failed ({subject}): {exc}', file=sys.stderr)
        return False


def _publish_phi_down(params: dict, origin: str, reason: str) -> bool:
    """Send a partial NucleusConfig override via φ↓. Returns True on success."""
    payload = {**params, '_origin': origin, '_reason': reason}
    ok = _nats_publish(PHI_DOWN_SUBJECT, payload)
    if ok:
        print(f'AC: φ↓ published: {params}  origin={origin}')
    return ok


def _publish_algedonic(severity: int, category: str, detail: str) -> bool:
    """Publish a direct algedonic signal (bypasses s4_store — Beer channel)."""
    payload = {
        'ts':        datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source_id': 'ac_algedonic',
        'category':  category,
        'severity':  severity,
        'detail':    detail,
    }
    return _nats_publish(ALGED_SUBJECT, payload)


# ── D4-L2 response class execution (F3.b) ─────────────────────────────────────

def _apply_response_classes(result: dict, now: str, dry_run: bool = False) -> dict:
    """Execute pre-authorized D4-L2 responses. Returns updated state dict.

    Runs AFTER persist_alert so the forensic record is written first.
    All actions are bounded by response_classes.vsm scope constraints."""
    state = _load_state()
    sm    = state['survival_mode']
    s4t   = state['s4_throttle']

    # ── Check survival_mode auto-revert ────────────────────────────────────────
    if sm['active']:
        last = result.get('cls') == 'C' and not result.get('survival_mode_trigger')
        if last:
            sm['recovery_ticks'] = sm.get('recovery_ticks', 0) + 1
        else:
            sm['recovery_ticks'] = 0
        if sm['recovery_ticks'] >= 5:
            print(f'AC: class_id={RC_SURVIVAL} ratif_ref={RATIF_REF} — survival_mode auto-revert (stasis recovered for 5 ticks)')
            if not dry_run:
                _publish_phi_down(
                    {'s4_cycle_interval_secs': sm['pre_s4'],
                     'telemetry_interval_secs': sm['pre_telemetry'],
                     '_class_id': RC_SURVIVAL, '_ratification_ref': RATIF_REF},
                    'ac_algedonic.survival_mode',
                    'survival_mode auto-revert: stasis recovered',
                )
                _publish_algedonic(2, 'stasis_deviation',
                                   f'survival_mode reverted after {sm["recovery_ticks"]} recovery ticks')
            sm['active'] = False
            sm['recovery_ticks'] = 0
    # ── Enter survival_mode ────────────────────────────────────────────────────
    elif result.get('survival_mode_trigger') and not dry_run:
        print(f'AC: class_id={RC_SURVIVAL} ratif_ref={RATIF_REF} — SURVIVAL MODE TRIGGERED')
        _publish_phi_down(
            {'s4_cycle_interval_secs': 0, 'telemetry_interval_secs': 1,
             '_class_id': RC_SURVIVAL, '_ratification_ref': RATIF_REF},
            'ac_algedonic.survival_mode',
            'stasis critical + not viable — minimise cognitive load',
        )
        _publish_algedonic(8, 'survival_mode',
                           f'survival_mode entered: {result["evidence"]}')
        sm['active'] = True
        sm['entered_ts'] = now
    elif result.get('survival_mode_trigger') and dry_run:
        print(f'AC: [dry-run] class_id={RC_SURVIVAL} ratif_ref={RATIF_REF} — would enter survival_mode')

    # ── Check s4_throttle auto-revert (1-hour timer) ───────────────────────────
    if s4t['active'] and s4t.get('entered_ts'):
        try:
            entered = datetime.datetime.fromisoformat(s4t['entered_ts'].replace('Z', '+00:00'))
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - entered).total_seconds()
            if elapsed >= S4_THROTTLE_REVERT_SECS and result.get('s4_timeout_count', 0) == 0:
                print(f'AC: class_id={RC_S4T} ratif_ref={RATIF_REF} — s4_throttle auto-revert ({elapsed:.0f}s elapsed, no timeouts)')
                if not dry_run:
                    _publish_phi_down(
                        {'s4_cycle_interval_secs': s4t['pre_s4'],
                         '_class_id': RC_S4T, '_ratification_ref': RATIF_REF},
                        'ac_algedonic.s4_throttle',
                        's4_throttle auto-revert: ollama responsive',
                    )
                s4t['active'] = False
        except (ValueError, TypeError):
            pass
    # ── Enter s4_throttle ─────────────────────────────────────────────────────
    elif not s4t['active'] and result.get('s4_timeout_count', 0) >= 3:
        current_s4 = s4t.get('pre_s4', 300)
        new_s4 = min(current_s4 * 2, 600)
        print(f'AC: class_id={RC_S4T} ratif_ref={RATIF_REF} — S4 THROTTLE TRIGGERED — s4_cycle {current_s4}→{new_s4}s')
        if not dry_run:
            _publish_phi_down(
                {'s4_cycle_interval_secs': new_s4,
                 '_class_id': RC_S4T, '_ratification_ref': RATIF_REF},
                'ac_algedonic.s4_throttle',
                'ollama timeout spike — reducing S4 cycle frequency',
            )
        s4t['active'] = True
        s4t['entered_ts'] = now
        s4t['pre_s4'] = current_s4
    elif result.get('s4_timeout_count', 0) >= 3 and dry_run:
        print(f'AC: [dry-run] class_id={RC_S4T} ratif_ref={RATIF_REF} — would enter s4_throttle (timeouts={result["s4_timeout_count"]})')

    _save_state(state)
    return state


# ── Event compression (dry-run display) ────────────────────────────────────────

def _format_events(raw_text: str) -> str:
    """Compress raw JSONL events to compact viability-relevant lines."""
    lines = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts    = e.get('ts', '?')[:19]
            etype = e.get('event_type', '?')
            status = e.get('status', '?')
            m = e.get('metrics', {})

            if etype == 'kernel_tick':
                k = m.get('kernel', {})
                lx = m.get('lyapunov', {})
                sc = k.get('stasis_cos')
                lines.append(
                    f"{ts} kernel_tick  "
                    f"stasis_cos={sc:.4f}  "
                    f"viable={k.get('viable')}  "
                    f"trust={k.get('trust', 0):.3f}  "
                    f"regime={lx.get('regime', '?')}  "
                    f"tick={m.get('tick', '?')}  "
                    f"status={status}"
                    if sc is not None else
                    f"{ts} kernel_tick status={status}"
                )
            elif etype == 'invariant_check':
                inv  = m.get('invariant_id', '?')
                pass_ = m.get('pass', '?')
                val  = m.get('value', 0)
                lines.append(
                    f"{ts} invariant  {inv}  pass={pass_}  value={val:.2e}  status={status}"
                )
            elif etype == 'algedonic_signal':
                lines.append(f"{ts} ALGEDONIC  {status}  {json.dumps(m)[:120]}")
            else:
                lines.append(f"{ts} {etype}  status={status}")
        except (json.JSONDecodeError, TypeError, ValueError):
            lines.append(line[:100])
    return '\n'.join(lines)


# ── Transport: fetch events from LXC 101 ──────────────────────────────────────

def _fetch_events(n: int = 20) -> str:
    # Fast path: running directly on LXC 101 — read the file locally.
    if os.path.exists(EVENTS_PATH_LXC):
        try:
            r = subprocess.run(['tail', '-n', str(n), EVENTS_PATH_LXC],
                               capture_output=True, timeout=10, text=True)
            return r.stdout.strip() if r.returncode == 0 else ''
        except Exception as e:
            print(f"AC fetch error (local): {e}", file=sys.stderr)
            return ''

    # Slow path: running from WSL — fetch via SSH pct exec + scp.
    tmp_n02 = '/tmp/ac_events.jsonl'
    ssh_cmd = (
        f"pct exec 101 -- bash -c "
        f"'tail -n {n} {EVENTS_PATH_LXC} > /tmp/ac_events.jsonl 2>/dev/null' ; "
        f"pct pull 101 /tmp/ac_events.jsonl {tmp_n02}"
    )
    r = subprocess.run(['ssh', 'root@n02', ssh_cmd],
                       capture_output=True, timeout=30, text=True)
    if r.returncode != 0:
        print(f"AC fetch error: {r.stderr.strip()}", file=sys.stderr)
        return ''
    r2 = subprocess.run(['scp', '-q', f'root@n02:{tmp_n02}', tmp_n02],
                        capture_output=True, timeout=30)
    if r2.returncode != 0:
        return ''
    try:
        with open(tmp_n02, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


# ── Alert block ────────────────────────────────────────────────────────────────

def _alert_vsm(result: dict, timestamp: str) -> str:
    """Render the classifier result as the alert.vsm block (same fields as the
    Qwen-era output — downstream readers unchanged)."""
    def q(s: str) -> str:
        return str(s).replace('"', "'")
    return (
        f'@vsm 1.2.1\n// ac_algedonic.py (deterministic tree)  {timestamp}\n\n'
        f'alert("nucleus-state-{timestamp}") {{\n'
        f'  class    = {result["cls"]}\n'
        f'  severity = {result["severity"]}\n'
        f'  category = "{result["category"]}"\n'
        f'  label    = "{q(result["label"])}"\n'
        f'  evidence = "{q(result["evidence"])}"\n'
        f'  context  = "{q(result["context"])}"\n'
        f'  action   = "{q(result["action"])}"\n'
        f'}}\n'
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def run(n_events: int = 20, alerts_dir: str = ALERTS_DIR, dry_run: bool = False) -> int:
    print(f"AC: fetching last {n_events} events from LXC 101 ...")
    raw_events = _fetch_events(n_events)
    if not raw_events:
        print("AC: no events retrieved — is nucleus running?", file=sys.stderr)
        if not dry_run:
            s4_store.self_alert('No events from nucleus',
                                  f'fetch of last {n_events} events from LXC 101 returned nothing',
                                  'check vsf-nucleus-operational + events.jsonl on LXC 101',
                                  alerts_dir, source='ac')
        return 1

    result = ac_classifier.classify_raw(raw_events)
    print(f"AC: norm source: {ac_classifier.NORM_SOURCE}")
    print(f"AC: classified {raw_events.count(chr(10)) + 1} events → class {result['cls']} "
          f"({result['label']})")

    if dry_run:
        print("AC: dry-run — alert not persisted. Compact events:")
        print(_format_events(raw_events))
        print(f"\nclass={result['cls']}  label={result['label']}")
        print(f"evidence: {result['evidence']}")
        now_dry = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        _apply_response_classes(result, now_dry, dry_run=True)
        return 0

    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # D4-L2 response classes run BEFORE variety attenuation so active modes (survival_mode,
    # s4_throttle) can check revert conditions every cron tick regardless of persist decision.
    _apply_response_classes(result, now, dry_run=False)

    # Variety attenuation (F3.d finding 2026-06-11): class C every minute is a log,
    # not a filter — Beer's Cyberfilter surfaces only significant deviations.
    # A/B always persist; C persists as a 1-per-hour heartbeat (keeps SD digest
    # evidence of nominal operation without drowning it).
    if result['cls'] == 'C':
        marker = '/var/lib/vsf/ac_last_c_persist'
        try:
            last = os.path.getmtime(marker)
        except OSError:
            last = 0.0
        import time
        if time.time() - last < 3600:
            print("AC: class C within heartbeat window — not persisted (variety attenuation)")
            return 0
        with open(marker, 'w') as fh:
            fh.write(str(time.time()))

    vsm  = _alert_vsm(result, now)
    path = s4_store.persist_alert(vsm, now, alerts_dir)

    print(f"AC: alert → {path}")
    print(f"AC: indexed into s5-alerts.db")
    print('\n' + vsm)

    # F3.b observation classes 1+2: publish algedonic for B/A deviations.
    # Conditional on nats availability (no_nats_required=true in plan).
    if result['cls'] in ('A', 'B') and _NATS_OK:
        _publish_algedonic(result['severity'], result['category'], result['evidence'])

    return 0


def main(argv: list) -> int:
    p = argparse.ArgumentParser(description='CRAG Algedonic Classifier (AC) — deterministic')
    p.add_argument('--n',       type=int, default=20,       help='events to read (default 20)')
    p.add_argument('--out',     default=ALERTS_DIR,         help='alerts output directory')
    p.add_argument('--dry-run', action='store_true',         help='fetch + classify, no persist')
    a = p.parse_args(argv[1:])
    return run(a.n, a.out, a.dry_run)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
