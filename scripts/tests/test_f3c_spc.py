#!/usr/bin/env python3
"""
test_f3c_spc.py — F3.c acceptance test: per-variable EWMA+CUSUM SPC.

Verifies that:
  (a) nominal sequence raises 0 exceptions
  (b) drift sequence raises exactly 1 exception (no storm)
  (c) sustained drift after cooldown raises 1 more (confirming no infinite suppression)
  (d) second S1 unit (vsf-s3-star / exception_count) also works

Run on LXC 108. Uses temp files for manifests + SPC state.
"""
import sys, os, json, tempfile

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import kpi_spc

# ── Temp manifest file ────────────────────────────────────────────────────────
_MANIFESTS = {
    "@vsm": "1.0",
    "manifests": [
        {"component": "vsf-nucleus-operational", "variable": "stasis_cos",
         "expected_min": 0.90, "expected_max": 1.0, "ewma_alpha": 0.2,
         "cusum_direction": "lower", "cusum_k": 0.01, "cusum_h": 0.05,
         "cooldown_ticks": 5},
        {"component": "vsf-nucleus-operational", "variable": "trust",
         "expected_min": 0.80, "expected_max": 1.0, "ewma_alpha": 0.2,
         "cusum_direction": "lower", "cusum_k": 0.01, "cusum_h": 0.05,
         "cooldown_ticks": 5},
        {"component": "vsf-nucleus-operational", "variable": "viable",
         "expected_min": 1.0, "expected_max": 1.0, "ewma_alpha": 0.5,
         "cusum_direction": "lower", "cusum_k": 0.1, "cusum_h": 0.5,
         "cooldown_ticks": 5},
        {"component": "vsf-s3-star", "variable": "exception_count",
         "expected_min": 0.0, "expected_max": 1.0, "ewma_alpha": 0.2,
         "cusum_direction": "upper", "cusum_k": 0.5, "cusum_h": 4.0,
         "cooldown_ticks": 5},
    ]
}

_tmp_dir  = tempfile.mkdtemp()
_manifest = os.path.join(_tmp_dir, 'kpi_manifests.json')
_state    = os.path.join(_tmp_dir, 'spc_state.json')
with open(_manifest, 'w') as f:
    json.dump(_MANIFESTS, f)

kpi_spc.MANIFESTS_PATH = _manifest
kpi_spc.SPC_STATE_PATH = _state


def _reset():
    if os.path.exists(_state):
        os.remove(_state)


# ── Test 1: nominal → 0 exceptions ───────────────────────────────────────────
def test_nominal_no_exception():
    _reset()
    total = 0
    for _ in range(5):
        hits = kpi_spc.check_all('vsf-nucleus-operational',
                                 {'stasis_cos': 0.99, 'trust': 1.0, 'viable': 1})
        total += len(hits)
    assert total == 0, f'Expected 0 exceptions for nominal sequence, got {total}'
    print('PASS test_nominal_no_exception')


# ── Test 2: drift → exactly 1 exception (no storm) ───────────────────────────
def test_drift_one_exception():
    _reset()
    exceptions = []
    for _ in range(5):  # 2 ticks accumulate S- past h=0.05, then cooldown suppresses
        hits = kpi_spc.check_all('vsf-nucleus-operational',
                                 {'stasis_cos': 0.85, 'trust': 1.0, 'viable': 1})
        exceptions.extend(hits)
    assert len(exceptions) == 1, \
        f'Expected exactly 1 exception for 5-tick drift, got {len(exceptions)}: {exceptions}'
    assert exceptions[0][0] == 'stasis_cos', \
        f"Expected stasis_cos exception, got: {exceptions[0]}"
    assert 'CUSUM-lower' in exceptions[0][1], \
        f"Expected CUSUM-lower in reason: {exceptions[0][1]}"
    print(f'PASS test_drift_one_exception — {exceptions[0]}')


# ── Test 3: cooldown expires, drift re-triggers ───────────────────────────────
def test_cooldown_expiry_re_triggers():
    _reset()
    # First trigger
    for _ in range(5):
        kpi_spc.check_all('vsf-nucleus-operational',
                          {'stasis_cos': 0.85, 'trust': 1.0, 'viable': 1})
    # Cooldown = 5 ticks; run 6 more drift ticks → should get 1 more exception
    second_batch = []
    for _ in range(8):
        hits = kpi_spc.check_all('vsf-nucleus-operational',
                                 {'stasis_cos': 0.85, 'trust': 1.0, 'viable': 1})
        second_batch.extend(hits)
    assert len(second_batch) >= 1, \
        f'Expected re-trigger after cooldown, got {len(second_batch)} exceptions'
    print(f'PASS test_cooldown_expiry_re_triggers — {len(second_batch)} exception(s) after cooldown')


# ── Test 4: second S1 unit (vsf-s3-star / exception_count) ───────────────────
def test_s3star_exception_count():
    _reset()
    # Nominal: 0-1 exceptions per poll → S+ stays at 0
    for _ in range(5):
        hits = kpi_spc.check_all('vsf-s3-star', {'exception_count': 0})
        assert not hits, f'Expected no SPC exception for 0 counts, got {hits}'

    # Elevated: 3 exceptions/poll → S+ should breach h=4.0 after 2-3 ticks
    drift_hits = []
    for _ in range(5):
        hits = kpi_spc.check_all('vsf-s3-star', {'exception_count': 3})
        drift_hits.extend(hits)
    assert len(drift_hits) >= 1, \
        f'Expected SPC exception for elevated exception_count, got {len(drift_hits)}'
    assert drift_hits[0][0] == 'exception_count', f'Wrong variable: {drift_hits[0]}'
    print(f'PASS test_s3star_exception_count — {drift_hits[0]}')


# ── Test 5: viable=0 triggers immediately ────────────────────────────────────
def test_viable_false_triggers():
    _reset()
    hits = kpi_spc.check_all('vsf-nucleus-operational',
                             {'stasis_cos': 0.99, 'trust': 1.0, 'viable': 0})
    assert len(hits) >= 1, f'Expected exception for viable=0, got {hits}'
    assert any(h[0] == 'viable' for h in hits), f'Expected viable exception: {hits}'
    print(f'PASS test_viable_false_triggers — {hits}')


if __name__ == '__main__':
    print('=== F3.c SPC acceptance test ===\n')
    test_nominal_no_exception()
    test_drift_one_exception()
    test_cooldown_expiry_re_triggers()
    test_s3star_exception_count()
    test_viable_false_triggers()
    print('\n=== ALL TESTS PASSED — F3.c accept criterion satisfied ===')
