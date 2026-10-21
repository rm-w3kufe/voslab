# design: docs/spec_revision/design-sources/algedonic-triage-v1/algedonic_triage.vsm
"""Deterministic (R10) tests for alert_triage (ALGEDONIC-TRIAGE-v1).
design: docs/spec_revision/design-sources/algedonic-triage-v1/algedonic_triage.vsm
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # system/kernel

from alert_triage import (  # noqa: E402
    IMPACT_W, NOW_FLOOR, DEFER_THRESHOLD, PERCENTILE_MIN, SAFE_RETRY_COMMANDS,
    aus_score, auto_remediate, age_w, burst_w, classify_impact, is_throttled,
    level_w, matches_focus, now_threshold, origin_key, parse_failed_command,
    retry_command_for, triage, triage_class, type_w,
)

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def _alert(**over):
    base = {
        "alert_id": "a1", "ts": "2026-10-14T06:00:00Z", "level": "warning",
        "alert_type": "handoff_needs_nod", "source": "handoff(rsi-predicate)",
        "acknowledged": False,
    }
    base.update(over)
    return base


class TestWeights:
    def test_level_w(self):
        assert level_w("critical") == 1.0
        assert level_w("error") == 0.7
        assert level_w("warning") == 0.3
        assert level_w("warn") == 0.3
        assert level_w("info") == 0.1
        assert level_w("weird") == 0.3  # default

    def test_classify_impact_known(self):
        assert classify_impact("handoff_needs_nod") == "BLOCKING"
        assert classify_impact("learning_investment_pending") == "BLOCKING"
        assert classify_impact("gates_weekly_fail") == "HEALTH"
        assert classify_impact("pattern_runner_fail") == "OPERACIONAL"
        assert classify_impact("latency_spike") == "NOISE"

    def test_classify_impact_monitoring_runners_health(self):
        """T4/T7 (S5 ok 2026-10-21): fails de la flota de timers = HEALTH,
        no default OPERACIONAL (antes clasificaban sin tipo declarado)."""
        assert classify_impact("gates_daily_fail") == "HEALTH"
        assert classify_impact("docs_reconcile_fail") == "HEALTH"
        assert classify_impact("restore_drill_fail") == "HEALTH"
        assert IMPACT_W[classify_impact("gates_daily_fail")] == 0.6

    def test_classify_impact_hygiene_batch_ready(self):
        """H2-F2 (plan hygiene_audit chain[3]-(ii), S5 luz verde): batch de
        candidatos de activación esperando decisión S5 = BLOCKING (familia
        learning_investment_pending — no es fail de salud, es decisión)."""
        assert classify_impact("hygiene_batch_ready") == "BLOCKING"
        assert IMPACT_W[classify_impact("hygiene_batch_ready")] == 1.0

    def test_classify_impact_unknown_defaults_operacional(self):
        assert classify_impact("brand_new_type") == "OPERACIONAL"
        assert IMPACT_W[classify_impact("brand_new_type")] == 0.4

    def test_age_w_caps_at_1(self):
        assert age_w("2026-10-12T12:00:00Z", NOW) == 1.0  # 48h → cap
        assert age_w("2026-10-14T00:00:00Z", NOW) == 0.25  # 12h / 48h
        assert age_w("2026-10-13T12:00:00Z", NOW) == 0.5   # 24h / 48h
        assert age_w(None, NOW) == 0.0

    def test_burst_w_caps_at_1(self):
        assert burst_w(10) == 1.0
        assert burst_w(50) == 1.0
        assert burst_w(5) == 0.5
        assert burst_w(0) == 0.0


class TestFocusElevation:
    def test_match_elevates_to_blocking(self):
        focus = [{"ref": "COMPONENT-B", "note": "wiring pattern-runner timer"}]
        # source token 'pattern' (>=4) appears in the note → match → BLOCKING
        assert matches_focus("pattern-runner(S3)", focus) is True
        assert type_w("pattern_runner_fail", "pattern-runner(S3)", focus) == 1.0

    def test_no_match_keeps_class(self):
        focus = [{"ref": "OTHER", "note": "unrelated"}]
        assert matches_focus("pattern-runner(S3)", focus) is False
        assert type_w("pattern_runner_fail", "pattern-runner(S3)", focus) == 0.4

    def test_short_source_tokens_ignored(self):
        # tokens <4 chars never match (avoid 'rsi', 's3' false positives)
        focus = [{"ref": "RSI", "note": "s3 work"}]
        assert matches_focus("rsi", focus) is False


class TestAUS:
    def test_deterministic(self):
        a = _alert()
        s1 = aus_score(a, [], 5, NOW)
        s2 = aus_score(a, [], 5, NOW)
        assert s1 == s2  # R10: same input → same score

    def test_components_sum(self):
        # level=warning(0.3) + BLOCKING(1.0) + age12h(0.25) + burst5(0.5) /4
        a = _alert(ts="2026-10-14T00:00:00Z")
        s = aus_score(a, [], 5, NOW)
        assert abs(s - (0.3 + 1.0 + 0.25 + 0.5) / 4) < 1e-9

    def test_triage_class_thresholds(self):
        assert triage_class(NOW_FLOOR) == "NOW"          # at the floor
        assert triage_class(0.74) == "NOW"               # default cutoff = floor
        assert triage_class(DEFER_THRESHOLD) == "DEFER"
        assert triage_class(0.39) == "ACCUMULATE"
        # explicit high cutoff pushes the boundary up
        assert triage_class(0.70, now_cutoff=0.75) == "DEFER"
        assert triage_class(0.80, now_cutoff=0.75) == "NOW"


class TestNowThreshold:
    def test_small_cohort_uses_floor_only(self):
        # < PERCENTILE_MIN scores → floor, no self-p90 (guard)
        assert now_threshold([0.1, 0.9]) == float(NOW_FLOOR)
        assert now_threshold([]) == float(NOW_FLOOR)

    def test_large_cohort_uses_max_floor_p90(self):
        # 20 scores 0.1..0.9ish; p90 ≈ high → threshold = max(floor, p90)
        scores = [i / 20 for i in range(20)]  # 0.00 .. 0.95
        t = now_threshold(scores)
        assert t >= NOW_FLOOR            # never below the absolute floor
        assert t >= scores[17]           # >= a near-p90 element

    def test_low_cohort_clamped_to_floor(self):
        # all scores below the floor → threshold stays at the floor (no NOW)
        scores = [0.1] * 10
        assert now_threshold(scores) == float(NOW_FLOOR)

    def test_deterministic(self):
        scores = [0.3, 0.5, 0.62, 0.65, 0.68, 0.7, 0.4, 0.55, 0.45, 0.9]
        assert now_threshold(scores) == now_threshold(list(scores))


class TestTriage:
    def test_groups_accumulate_by_origin(self):
        alerts = [
            _alert(alert_id="x1", alert_type="latency_spike", source="svc-a",
                   level="info", ts="2026-10-14T11:00:00Z"),
            _alert(alert_id="x2", alert_type="latency_spike", source="svc-a",
                   level="info", ts="2026-10-14T11:30:00Z"),
            _alert(alert_id="x3", alert_type="latency_spike", source="svc-b",
                   level="info", ts="2026-10-14T11:00:00Z"),
        ]
        r = triage(alerts, [], now=NOW)
        # same origin (svc-a|latency_spike) groups; svc-b is its own origin
        assert r["counts"]["accumulate_groups"] == 2
        # group score = max AUS of members
        ga = r["accumulate"]["svc-a|latency_spike"]
        member_max = max(a["_aus"] for a in ga["alerts"])
        assert ga["group_score"] == member_max

    def test_acknowledged_excluded(self):
        alerts = [_alert(acknowledged=True), _alert(alert_id="b")]
        r = triage(alerts, [], now=NOW)
        assert r["counts"]["unacked"] == 1

    def test_now_sorted_desc(self):
        alerts = [
            _alert(alert_id="lo", level="warning"),
            _alert(alert_id="hi", level="critical"),
        ]
        r = triage(alerts, [], now=NOW)
        scores = [a["_aus"] for a in r["now"] + r["defer"]]
        assert scores == sorted(scores, reverse=True)


class TestAutoRemediate:
    def test_needs_s5_types_not_autofixed(self):
        for t in ("handoff_needs_nod", "learning_investment_pending"):
            res = auto_remediate(_alert(alert_type=t))
            assert res == {"attempted": False, "destructive": False, "result": "needs_s5"}

    def test_reverify_types_attempted(self):
        for t in ("gates_weekly_fail", "bridge_call_failed"):
            res = auto_remediate(_alert(alert_type=t))
            assert res["attempted"] is True and res["destructive"] is False
            assert res["result"] == "reverify"

    def test_unknown_types_no_autorem(self):
        res = auto_remediate(_alert(alert_type="latency_spike"))
        assert res == {"attempted": False, "destructive": False, "result": "no_autorem"}

    def test_origin_key(self):
        assert origin_key(_alert()) == ("handoff(rsi-predicate)", "handoff_needs_nod")


class TestRetryHelpers:
    def test_parse_failed_command(self):
        d = ("callBridge(log-distill) error: Command failed: python3 -W ignore "
             "/x/tool_integration_bridge.py log-distill")
        assert parse_failed_command(d) == "log-distill"
        assert parse_failed_command("no callbridge here") is None
        assert parse_failed_command("") is None

    def test_retry_command_whitelist(self):
        # whitelisted command → returned
        a = _alert(alert_type="bridge_call_failed",
                   detail="callBridge(log-distill) error: ...")
        assert retry_command_for(a) == "log-distill"
        # non-whitelisted command → None (never re-run blindly, R17)
        b = _alert(alert_type="bridge_call_failed",
                   detail="callBridge(rsi-threshold-set) error: ...")
        assert retry_command_for(b) is None
        # wrong alert type → None
        assert retry_command_for(_alert(alert_type="gates_weekly_fail")) is None

    def test_safe_commands_are_read_only(self):
        # the whitelist must never contain mutating commands (R17 guard)
        banned = {"rsi-revoke", "rsi-threshold-set", "rsi-caution-clear"}
        assert not (SAFE_RETRY_COMMANDS & banned)

    def test_is_throttled(self, tmp_path):
        import sys
        from datetime import datetime, timezone
        m = tmp_path / "marker"
        now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        assert is_throttled(m, 1.0, now) is False       # no marker
        m.write_text("2026-10-14T11:30:00Z")             # 0.5h ago
        assert is_throttled(m, 1.0, now) is True         # within window
        assert is_throttled(m, 0.25, now) is False       # outside window
        m.write_text("not-a-timestamp")
        assert is_throttled(m, 1.0, now) is False        # bad marker → run
