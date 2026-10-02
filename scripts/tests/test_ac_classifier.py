#!/usr/bin/env python3
"""Unit tests for ac_classifier.py — deterministic algedonic decision tree.

Run on LXC 108 (certify-before-cutover):
    python3 -m unittest scripts.tests.test_ac_classifier -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ac_classifier as cc


def tick(stasis=0.95, viable=True, trust=1.0, regime='in_recurrent_set'):
    return {'event_type': 'kernel_tick', 'status': 'nominal',
            'metrics': {'kernel': {'stasis_cos': stasis, 'viable': viable, 'trust': trust},
                        'lyapunov': {'regime': regime}, 'tick': 1}}


def inv(inv_id='VAR-1', passed=False, value=-1.5e-07, status='warn'):
    return {'event_type': 'invariant_check', 'status': status,
            'metrics': {'invariant_id': inv_id, 'pass': passed, 'value': value}}


def algedonic(status='warn'):
    return {'event_type': 'algedonic_signal', 'status': status, 'metrics': {'sig': 1}}


class TestKernelTickRules(unittest.TestCase):
    def test_nominal_is_C(self):
        r = cc.classify([tick()])
        self.assertEqual(r['cls'], 'C')
        self.assertEqual(r['label'], 'nominal')
        self.assertEqual(r['action'], cc._ACTION['C'])

    def test_viable_false_is_A(self):
        r = cc.classify([tick(viable=False)])
        self.assertEqual(r['cls'], 'A')
        self.assertIn('viable', r['evidence'])

    def test_stasis_below_critical_is_A(self):
        r = cc.classify([tick(stasis=0.65)])
        self.assertEqual(r['cls'], 'A')

    def test_stasis_below_warn_is_B(self):
        r = cc.classify([tick(stasis=0.75)])
        self.assertEqual(r['cls'], 'B')

    def test_stasis_gray_zone_is_C(self):
        # Primer: nominal >= 0.90, warning < 0.80 — 0.80..0.90 raises no finding.
        r = cc.classify([tick(stasis=0.85)])
        self.assertEqual(r['cls'], 'C')

    def test_trust_below_threshold_is_B(self):
        r = cc.classify([tick(trust=0.5)])
        self.assertEqual(r['cls'], 'B')
        self.assertIn('trust', r['evidence'])

    def test_regime_not_recurrent_is_B(self):
        r = cc.classify([tick(regime='escaping')])
        self.assertEqual(r['cls'], 'B')
        self.assertIn('escaping', r['evidence'])

    def test_only_latest_tick_counts(self):
        # An old bad tick followed by a healthy one → current state is nominal.
        r = cc.classify([tick(stasis=0.50, viable=False), tick()])
        self.assertEqual(r['cls'], 'C')

    def test_severity_precedence_A_over_B(self):
        r = cc.classify([tick(viable=False, trust=0.5)])
        self.assertEqual(r['cls'], 'A')
        self.assertIn('trust', r['evidence'])  # B finding still listed as evidence


class TestInvariantRules(unittest.TestCase):
    def test_three_consecutive_warns_is_B(self):
        r = cc.classify([tick(), inv(), inv(), inv()])
        self.assertEqual(r['cls'], 'B')
        self.assertIn('VAR-1', r['evidence'])

    def test_two_consecutive_warns_is_C(self):
        # pass=False + warn is normal for tiny variety — below streak threshold.
        r = cc.classify([tick(), inv(), inv()])
        self.assertEqual(r['cls'], 'C')

    def test_pass_resets_streak(self):
        r = cc.classify([tick(), inv(), inv(), inv(passed=True, status='nominal'), inv(), inv()])
        self.assertEqual(r['cls'], 'C')

    def test_streaks_are_per_invariant(self):
        # Interleaved warns on two invariants must not merge into one streak.
        r = cc.classify([tick(), inv('VAR-1'), inv('VAR-2'), inv('VAR-1'), inv('VAR-2')])
        self.assertEqual(r['cls'], 'C')

    def test_large_magnitude_single_warn_is_B(self):
        r = cc.classify([tick(), inv(value=-0.5)])
        self.assertEqual(r['cls'], 'B')
        self.assertIn('magnitude', r['label'])

    def test_large_value_on_passing_check_ignored(self):
        r = cc.classify([tick(), inv(passed=True, value=99.0, status='nominal')])
        self.assertEqual(r['cls'], 'C')


class TestAlgedonicAndEdgeCases(unittest.TestCase):
    def test_algedonic_warn_is_B(self):
        r = cc.classify([tick(), algedonic('warn')])
        self.assertEqual(r['cls'], 'B')

    def test_algedonic_critical_is_A(self):
        r = cc.classify([tick(), algedonic('critical')])
        self.assertEqual(r['cls'], 'A')

    def test_no_kernel_tick_is_B(self):
        r = cc.classify([inv()])
        self.assertEqual(r['cls'], 'B')
        self.assertIn('no kernel', r['label'])

    def test_empty_window_is_B(self):
        r = cc.classify([])
        self.assertEqual(r['cls'], 'B')

    def test_result_has_all_alert_fields(self):
        r = cc.classify([tick()])
        for key in ('cls', 'label', 'evidence', 'context', 'action'):
            self.assertIn(key, r)
            self.assertTrue(r[key])


class TestS4EthicsScan(unittest.TestCase):
    def _ethics_event(self, recommendation='CANDIDATE_RULE'):
        return {
            'event_type': 's4_ethics_scan',
            'status': 'ok',
            'metrics': {
                'scan_type': 'novel_scan',
                'trigger': 'periodic',
                'novel_pattern_candidate': True,
                'recommendation': recommendation,
                'integrity_check': 'pass',
                'qwen_confidence': 0.85,
                'reasoning': 'test',
            },
        }

    def test_ethics_scan_alone_is_C(self):
        r = cc.classify([tick(), self._ethics_event()])
        self.assertEqual(r['cls'], 'C')
        self.assertEqual(r['category'], 's4_ethics_candidate')
        self.assertIn('s4_ethics_scan candidate', r['label'])

    def test_ethics_severity_is_2(self):
        r = cc.classify([tick(), self._ethics_event()])
        self.assertEqual(r['severity'], 2)

    def test_ethics_scan_in_context(self):
        r = cc.classify([tick(), self._ethics_event()])
        self.assertIn('s4_ethics_scans: 1', r['context'])

    def test_ethics_does_not_override_A(self):
        r = cc.classify([tick(viable=False), self._ethics_event()])
        self.assertEqual(r['cls'], 'A')
        self.assertIn('s4_ethics_scans: 1', r['context'])

    def test_multiple_ethics_scans_counted(self):
        events = [tick(), self._ethics_event('CANDIDATE_RULE'), self._ethics_event('REVIEW')]
        r = cc.classify(events)
        self.assertIn('s4_ethics_scans: 2', r['context'])
        self.assertIn('CANDIDATE_RULE, REVIEW', r['evidence'])


class TestParseRaw(unittest.TestCase):
    def test_classify_raw_jsonl(self):
        raw = '\n'.join(json.dumps(e) for e in [tick(stasis=0.75)])
        r = cc.classify_raw(raw)
        self.assertEqual(r['cls'], 'B')

    def test_malformed_lines_dropped(self):
        raw = 'not json\n' + json.dumps(tick()) + '\n{"truncated":'
        r = cc.classify_raw(raw)
        self.assertEqual(r['cls'], 'C')

    def test_real_nucleus_shape(self):
        # Mirrors the live φ↑ VAR-1 signal: pass=False, value ≈ -1.5e-07, repeated.
        events = [tick(stasis=0.94)] + [inv('VAR-1') for _ in range(5)]
        r = cc.classify(events)
        self.assertEqual(r['cls'], 'B')
        self.assertIn('x5 consecutive', r['evidence'])


if __name__ == '__main__':
    unittest.main()
