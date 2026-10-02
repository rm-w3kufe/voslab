#!/usr/bin/env python3
"""
test_f3b_e2e.py — F3.b E2E acceptance test.

Verifies that a synthetic class-A condition triggers RC-3 survival_mode and that:
  (a) stdout log contains class_id=RC-3 + ratif_ref (dry-run path)
  (b) phi_down payload carries _class_id + _ratification_ref (non-dry-run path)

Run on LXC 108. No live NATS or nucleus required.
"""
import sys, os, io, json, tempfile

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import ac_algedonic
import ac_classifier

# ── Synthetic class-A events ──────────────────────────────────────────────────
# stasis_cos=0.65 < critical_below(0.70), viable=False — triggers survival_mode

def _make_kernel_tick(stasis_cos: float, viable: bool, tick: int) -> str:
    return json.dumps({
        'ts': f'2026-06-12T10:{tick:02d}:00Z',
        'event_type': 'kernel_tick',
        'status': 'ok',
        'metrics': {
            'tick': tick,
            'kernel': {'stasis_cos': stasis_cos, 'viable': viable, 'trust': 1.0},
            'lyapunov': {'regime': 'in_recurrent_set'},
        }
    })

SYNTHETIC_CLASS_A = '\n'.join(_make_kernel_tick(0.65, False, i) for i in range(5))

# ── Mock helpers ──────────────────────────────────────────────────────────────
_captured_publishes: list[dict] = []

def _mock_nats_publish(subject: str, payload: dict) -> bool:
    _captured_publishes.append({'subject': subject, 'payload': payload})
    return True


def _mock_fetch(_n: int = 20) -> str:
    return SYNTHETIC_CLASS_A


def _run_with_mocks(dry_run: bool, alerts_dir: str | None = None) -> str:
    _captured_publishes.clear()
    ac_algedonic._fetch_events = _mock_fetch
    ac_algedonic._nats_publish  = _mock_nats_publish
    ac_algedonic._NATS_OK       = True
    orig_state = ac_algedonic.STATE_PATH
    ac_algedonic.STATE_PATH = tempfile.mktemp(suffix='_ac_state.json')
    buf = io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        ac_algedonic.run(
            n_events=5,
            alerts_dir=alerts_dir or tempfile.mkdtemp(),
            dry_run=dry_run,
        )
    finally:
        sys.stdout = old_out
        ac_algedonic.STATE_PATH = orig_state
    return buf.getvalue()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_class_a_detected() -> None:
    output = _run_with_mocks(dry_run=True)
    assert 'class A' in output or "→ class A" in output, \
        f"Expected class A classification:\n{output}"
    print(f'PASS test_class_a_detected')


def test_dry_run_log_has_class_id() -> None:
    output = _run_with_mocks(dry_run=True)
    assert 'class_id=RC-3' in output, \
        f"Expected 'class_id=RC-3' in dry-run output:\n{output}"
    assert 'response_classes.vsm' in output, \
        f"Expected ratif_ref in dry-run output:\n{output}"
    print('PASS test_dry_run_log_has_class_id')


def test_phi_down_payload_has_class_id() -> None:
    _run_with_mocks(dry_run=False)
    phi_calls = [c for c in _captured_publishes if 'phi_down.params' in c['subject']]
    assert phi_calls, \
        f"Expected at least one phi_down publish. All calls: {_captured_publishes}"
    payload = phi_calls[0]['payload']
    assert payload.get('_class_id') == 'RC-3', \
        f"Expected _class_id=RC-3 in payload: {payload}"
    assert 'response_classes.vsm' in payload.get('_ratification_ref', ''), \
        f"Expected response_classes.vsm in _ratification_ref: {payload}"
    print(f'PASS test_phi_down_payload_has_class_id — payload _class_id={payload["_class_id"]}')


def test_non_dry_run_log_has_class_id() -> None:
    output = _run_with_mocks(dry_run=False)
    assert 'class_id=RC-3' in output, \
        f"Expected 'class_id=RC-3' in non-dry-run output:\n{output}"
    print('PASS test_non_dry_run_log_has_class_id')


if __name__ == '__main__':
    print('=== F3.b E2E acceptance test ===\n')
    test_class_a_detected()
    test_dry_run_log_has_class_id()
    test_phi_down_payload_has_class_id()
    test_non_dry_run_log_has_class_id()
    print('\n=== ALL TESTS PASSED — F3.b accept criterion satisfied ===')
