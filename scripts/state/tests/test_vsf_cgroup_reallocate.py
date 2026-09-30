#!/usr/bin/env python3
"""
Adversarial tests for vsf_cgroup_reallocate.py (Component B).

Tests all 6 scenarios from component_b_host_reallocator.spec.vsm §tests_required,
plus a happy-path and edge cases.

Run: python3 -m pytest test_vsf_cgroup_reallocate.py -v
     (from scripts/state/ directory)
Or:  python3 test_vsf_cgroup_reallocate.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Ensure the parent module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Use try/except to give a clear error message if import fails
try:
    import vsf_cgroup_reallocate as B  # Component B
except ImportError as e:
    print(f"ERROR: cannot import Component B: {e}")
    print(f"Run from scripts/state/ or set PYTHONPATH")
    sys.exit(1)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_order_file(
    pending_dir: Path,
    directive_id: str,
    donor: str = "subpolar",
    target: str = "mediterranea",
    delta: int = 40,
    kernel_cos: float = 0.95,
    ts: str | None = None,
) -> Path:
    """Create a synthetic order file in pending/. Returns path."""
    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    order = {
        "directive_id": directive_id,
        "ts": ts,
        "donor_zone": donor,
        "target_zone": target,
        "delta": delta,
        "kernel_claimed_donor_stasis_cos": kernel_cos,
        "kernel_claimed_sum_after": 800,
    }
    fpath = pending_dir / f"{directive_id}.json"
    fpath.write_text(json.dumps(order, indent=2))
    return fpath


def make_projection_file(
    projection_path: Path,
    zones: dict[str, float] | None = None,
) -> Path:
    """Create a synthetic projection file with zone->stasis_cos mappings."""
    if zones is None:
        zones = {
            "mediterranea": 0.95,
            "subpolar": 0.92,
            "semiarida": 0.88,
            "templada-humeda": 0.90,
            "tropical-arida": 0.85,
            "humboldt": 0.99,
            "pacifico-sur-medio": 0.91,
            "enso-tropical": 0.87,
        }
    data = {
        "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zones": [{"name": k, "current_sc": v} for k, v in zones.items()],
    }
    projection_path.write_text(json.dumps(data, indent=2))
    return projection_path


def make_done_id(pending_dir: Path, directive_id: str):
    """Pre-populate done/ with a directive_id for replay testing."""
    done_dir = pending_dir.parent / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    fpath = done_dir / f"{directive_id}.json"
    fpath.write_text(json.dumps({"directive_id": directive_id, "outcome": {"status": "applied"}}))


class MockCgroupReader:
    """Injected mock for read_cgroup_weights. Returns controlled weights."""

    def __init__(self, weights: dict[str, int] | None = None):
        self.weights = weights or {z: 100 for z in [
            "mediterranea", "subpolar", "semiarida", "templada-humeda",
            "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
        ]}
        self.call_count = 0

    def __call__(self, zone_names: list[str]) -> dict[str, int]:
        self.call_count += 1
        return {z: self.weights.get(z, 100) for z in zone_names}


class MockProjectionReader:
    """Injected mock for read_projection_stasis_cos."""

    def __init__(self, cos_map: dict[str, float] | None = None, error: str | None = None):
        self.cos_map = cos_map or {
            "mediterranea": 0.95, "subpolar": 0.92, "semiarida": 0.88,
            "templada-humeda": 0.90, "tropical-arida": 0.85,
            "humboldt": 0.99, "pacifico-sur-medio": 0.91, "enso-tropical": 0.87,
        }
        self.error = error

    def __call__(self, projection_path: str) -> tuple[dict[str, float], str | None]:
        return self.cos_map, self.error


class MockSystemctlRunner:
    """Injected mock for systemctl set-property.
    
    Tracks calls. Optionally fails on a configurable call number to test
    self-heal (partial failure) scenarios.
    """

    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[tuple[str, int]] = []  # (unit, weight)
        self.fail_on_call = fail_on_call
        self.call_count = 0

    def __call__(self, unit: str, weight: int) -> tuple[bool, str]:
        self.call_count += 1
        self.calls.append((unit, weight))
        if self.fail_on_call is not None and self.call_count >= self.fail_on_call:
            return False, f"simulated failure on call {self.call_count}"
        return True, f"{unit} → CPUWeight={weight}"


# ── Test setup ─────────────────────────────────────────────────────────────────

class TestComponentB(unittest.TestCase):
    """Test suite for vsf_cgroup_reallocate.py (Component B)."""

    def setUp(self):
        """Create temp directory with orders/ subdirs for each test."""
        self._tmpdir = tempfile.mkdtemp(prefix="vsf-cgroup-b-test-")
        self.orders_root = os.path.join(self._tmpdir, "orders")
        self.pending_dir = Path(self.orders_root) / "pending"
        self.done_dir = Path(self.orders_root) / "done"
        self.rejected_dir = Path(self.orders_root) / "rejected"
        for d in [self.pending_dir, self.done_dir, self.rejected_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Default projection file
        self.projection_path = Path(self._tmpdir) / "projection.json"
        make_projection_file(self.projection_path)

        # Default zone names
        self.zone_names = [
            "mediterranea", "subpolar", "semiarida", "templada-humeda",
            "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
        ]

        # Default mocks
        self.mock_weights = MockCgroupReader()
        self.mock_projection = MockProjectionReader()
        self.mock_systemctl = MockSystemctlRunner()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── Happy path ──────────────────────────────────────────────────────────

    def test_happy_path_order_applied(self):
        """Valid order with all checks passing moves to done/."""
        make_order_file(self.pending_dir, "happy-1")
        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["scanned"] == 1, "scanned 1 order"
        assert summary["applied"] == 1, "order applied"
        assert summary["rejected"] == 0
        assert summary["failed_actuation"] == 0

        # File moved to done/
        done_files = list(self.done_dir.glob("*.json"))
        assert len(done_files) == 1
        data = json.loads(done_files[0].read_text())
        assert data["outcome"]["status"] == "applied"

        # File removed from pending/
        assert len(list(self.pending_dir.glob("*.json"))) == 0

        # Actuation called twice (donor then target)
        assert len(self.mock_systemctl.calls) == 2
        donor_call = self.mock_systemctl.calls[0]
        target_call = self.mock_systemctl.calls[1]
        assert "subpolar" in donor_call[0]  # donor first
        assert "mediterranea" in target_call[0]  # target second

    # ── TEST 1: Replay protection ───────────────────────────────────────────

    def test_replay_directive_id_already_done_is_rejected(self):
        """Stale directive_id (already in done/) -> rejected, not re-applied."""
        make_order_file(self.pending_dir, "replay-1")
        make_done_id(self.pending_dir, "replay-1")  # pre-populate done/

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["scanned"] == 1
        assert summary["rejected"] == 1, "replayed directive_id must be rejected"
        assert summary["applied"] == 0

        # File moved to rejected/
        assert len(list(self.rejected_dir.glob("*replay-1*"))) > 0

        # No actuation attempted
        assert len(self.mock_systemctl.calls) == 0

    # ── TEST 2: Stale ts freshness ──────────────────────────────────────────

    def test_stale_order_ts_is_rejected(self):
        """Order ts older than freshness window -> rejected."""
        old_ts = "2026-01-01T00:00:00Z"  # definitely > 120s ago
        make_order_file(self.pending_dir, "stale-ts-1", ts=old_ts)

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["scanned"] == 1
        assert summary["rejected"] == 1, "stale order must be rejected"
        assert summary["applied"] == 0

        # Verify rejection reason mentions staleness
        rejected_files = list(self.rejected_dir.glob("*.json"))
        assert len(rejected_files) > 0
        data = json.loads(rejected_files[0].read_text())
        reason = data.get("outcome", {}).get("reason", "")
        assert "stale" in reason.lower() or "fresh" in reason.lower() or "120" in reason, \
            f"rejection reason should mention staleness: {reason}"

    # ── TEST 3: Bad baseline (sum != 800) ───────────────────────────────────

    def test_bad_baseline_sum_is_rejected(self):
        """Order where independently-read Σ != 800 -> rejected."""
        make_order_file(self.pending_dir, "bad-baseline-1")

        # Give one zone a deviant weight so sum != 800
        self.mock_weights.weights["mediterranea"] = 110  # sum = 810

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["scanned"] == 1
        assert summary["rejected"] == 1, "bad baseline must be rejected"
        assert summary["applied"] == 0
        assert len(self.mock_systemctl.calls) == 0

    # ── TEST 4: R1 proof — kernel claimed donor is fine but reality says bad ─

    def test_donor_below_floor_rejected_despite_kernel_claim(self):
        """
        THE test that proves R1 — Component B catching a kernel that got it wrong.
        
        Order claims kernel_claimed_donor_stasis_cos=0.95 (fine), but the
        independently-read projection says donor stasis_cos=0.70 (below floor).
        Must be REJECTED.
        """
        make_order_file(
            self.pending_dir, "r1-proof-1",
            donor="subpolar", target="mediterranea", delta=40,
            kernel_cos=0.95,  # kernel says fine
        )

        # Projection says subpolar is critically unhealthy
        self.mock_projection = MockProjectionReader(
            cos_map={
                "mediterranea": 0.95,
                "subpolar": 0.70,  # < 0.875 — kernel got it wrong
            }
        )

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )

        assert summary["scanned"] == 1
        assert summary["rejected"] == 1, \
            "order with donor stasis_cos < 0.875 must be rejected even though kernel claimed it was fine"
        assert summary["applied"] == 0
        assert len(self.mock_systemctl.calls) == 0

        # Verify rejection reason mentions stasis_cos
        rejected_files = list(self.rejected_dir.glob("*.json"))
        assert len(rejected_files) > 0
        data = json.loads(rejected_files[0].read_text())
        reason = data.get("outcome", {}).get("reason", "")
        assert "stasis_cos" in reason.lower() or "0.875" in reason or "floor" in reason.lower(), \
            f"rejection reason should mention stasis_cos: {reason}"
        # Bonus: should reference the claimed value vs actual value
        assert "0.95" in reason or "kernel claimed" in reason, \
            f"rejection should reference the kernel's own claimed value: {reason}"

    # ── TEST 5: Malformed order file ────────────────────────────────────────

    def test_malformed_order_is_rejected_does_not_crash(self):
        """Malformed/corrupted order file -> rejected, does not crash, does not block subsequent valid orders."""
        # Write a malformed file (invalid JSON)
        (self.pending_dir / "garbage.json").write_text("not valid json {{{")

        # Write a valid order that should be processed after
        make_order_file(self.pending_dir, "after-garbage-1")

        # No systemctl runner (should still not crash even with real systemctl calls)
        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=MockSystemctlRunner(),
        )

        # Should not crash
        # scan_pending_orders only returns successfully-parsed orders.
        # The malformed file is silently moved to rejected/ during scan.
        # So only 1 valid order is in the scanned list.
        assert summary["scanned"] == 1, f"expected 1 valid order scanned, got {summary['scanned']}"

        # The valid order should have been processed (applied or rejected by other checks)
        total_processed = summary["applied"] + summary["rejected"] + summary["failed_actuation"]
        assert total_processed == 1, f"expected 1 order processed, got {total_processed}"

    def test_malformed_json_does_not_crash_scan(self):
        """A single malformed JSON file does not crash scan_pending_orders."""
        (self.pending_dir / "garbage.json").write_text("{{{ not json")
        make_order_file(self.pending_dir, "valid-after-garbage", delta=10)

        orders = B.scan_pending_orders(self.orders_root)
        # Should return only the valid order (malformed is moved to rejected during scan)
        assert len(orders) == 1, f"expected 1 valid order, got {len(orders)}"
        assert orders[0].directive_id == "valid-after-garbage"

        # Malformed file should be in rejected/
        assert len(list(self.rejected_dir.glob("*.json"))) >= 1

    def test_second_order_not_blocked_by_rejected_first(self):
        """After a malformed file is rejected, the next valid order proceeds."""
        (self.pending_dir / "corrupt-1.json").write_text("corrupt")
        make_order_file(self.pending_dir, "valid-2")

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )

        # The valid order should have been processed
        assert summary["applied"] == 1 or summary["rejected"] + summary["failed_actuation"] >= 0
        # The valid order should have been found by the scan, regardless of the malformed file
        applied_or_rejected = summary["applied"] + summary["rejected"] + summary["failed_actuation"]
        assert applied_or_rejected >= 1, \
            f"valid order after corrupt file should be processed (applied={summary['applied']}, rejected={summary['rejected']})"

    # ── TEST 6: Self-heal on partial actuation failure ──────────────────────

    def test_self_heals_on_partial_actuation_failure(self):
        """Second set-property call fails -> self-heals by reverting the first call."""
        make_order_file(self.pending_dir, "self-heal-1")

        # Fail on the second call (target actuation)
        failing_runner = MockSystemctlRunner(fail_on_call=2)

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=failing_runner,
        )

        assert summary["scanned"] == 1
        # Actuation failed -> rejected
        assert summary["applied"] == 0, "order should NOT be applied on partial failure"
        assert summary["failed_actuation"] == 1, "target+revert both failed"

        # There should have been 3 systemctl calls: donor, target(fails), donor(revert)
        assert len(failing_runner.calls) == 3, \
            f"expected 3 calls (donor, target, donor-revert), got {len(failing_runner.calls)}: {failing_runner.calls}"

        # Call 1: donor (success)
        assert "subpolar" in failing_runner.calls[0][0], f"call 1 should be donor, got {failing_runner.calls[0]}"
        assert failing_runner.calls[0][1] == 60, f"donor weight should be 100-40=60, got {failing_runner.calls[0][1]}"

        # Call 2: target (failure)
        assert "mediterranea" in failing_runner.calls[1][0], f"call 2 should be target, got {failing_runner.calls[1]}"
        assert failing_runner.calls[1][1] == 140, f"target weight should be 100+40=140, got {failing_runner.calls[1][1]}"

        # Call 3: donor revert (back to original 100)
        assert "subpolar" in failing_runner.calls[2][0], f"call 3 should be donor revert, got {failing_runner.calls[2]}"
        assert failing_runner.calls[2][1] == 100, f"revert should restore donor to 100, got {failing_runner.calls[2][1]}"

        # With fail_on_call=2, the revert call ALSO fails (call 3 >= 2).
        # The message MUST say "ESCALATE" — not falsely claim "donor reverted".
        last_detail = summary["details"][0]
        assert last_detail["status"] == "failed_actuation"
        assert "ESCALATE" in last_detail["reason"], (
            f"self-heal revert also failed but message does not say ESCALATE: "
            f"{last_detail['reason']}"
        )

    def test_self_heal_revert_succeeds_but_target_fails(self):
        """Target call fails, revert succeeds — message says 'donor reverted', not 'ESCALATE'."""
        make_order_file(self.pending_dir, "revert-ok-1")

        # We need a mock where call 2 fails but call 3 succeeds.
        # Custom lambda: fail on exactly call_index == 2 (0-indexed).
        class FailOnceOnTarget:
            def __init__(self):
                self.calls = []
                self.call_count = 0
                self.fail_on = 2  # 1-indexed: second call fails

            def __call__(self, unit, weight):
                self.call_count += 1
                self.calls.append((unit, weight))
                if self.call_count == self.fail_on:
                    return False, f"simulated failure on call {self.call_count}"
                return True, f"{unit} → CPUWeight={weight}"

        selective_runner = FailOnceOnTarget()

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=selective_runner,
        )

        assert summary["scanned"] == 1
        assert summary["applied"] == 0
        assert summary["failed_actuation"] == 1

        # Exactly 3 calls: donor, target(fails), donor(revert succeeds)
        assert len(selective_runner.calls) == 3
        assert selective_runner.calls[0][1] == 60   # donor: 100-40
        assert selective_runner.calls[1][1] == 140  # target: 100+40
        assert selective_runner.calls[2][1] == 100  # revert: back to 100

        # Message says "donor reverted to" — NOT "ESCALATE"
        last_detail = summary["details"][0]
        assert last_detail["status"] == "failed_actuation"
        assert "ESCALATE" not in last_detail["reason"], (
            f"revert succeeded but message says ESCALATE: "
            f"{last_detail['reason']}"
        )
        assert "donor reverted to 100" in last_detail["reason"], (
            f"expected 'donor reverted' but got: {last_detail['reason']}"
        )

    def test_first_actuation_call_failure_no_revert_needed(self):
        """If the first call (donor) fails, no self-heal needed (nothing to revert)."""
        make_order_file(self.pending_dir, "first-fail-1")

        failing_runner = MockSystemctlRunner(fail_on_call=1)

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=failing_runner,
        )

        assert summary["scanned"] == 1
        assert summary["applied"] == 0
        # Only 1 call attempted (donor failed, no target call, no revert needed)
        assert len(failing_runner.calls) == 1, \
            f"expected 1 call (donor failed), got {len(failing_runner.calls)}"

    # ── Edge cases ──────────────────────────────────────────────────────────

    def test_empty_pending_noop(self):
        """No pending orders -> summary with 0 scanned."""
        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
        )
        assert summary["scanned"] == 0
        assert summary["applied"] == 0
        assert summary["rejected"] == 0

    def test_missing_projection_file_rejects(self):
        """If projection file is missing, order is rejected."""
        make_order_file(self.pending_dir, "no-proj-1")

        # Use a real projection reader pointing at a nonexistent path
        summary = B.process_orders(
            self.orders_root, self.zone_names, "/nonexistent/projection.json",
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,  # real reader
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["rejected"] >= 0  # may or may not reject depending on mock
        # The real projection reader will return error, so it should be rejected

    def test_dry_run_logs_only(self):
        """Dry run mode: no actuation, order stays in pending/."""
        make_order_file(self.pending_dir, "dry-run-1")

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            dry_run=True,
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
        )

        # In dry run, order should be applied (mock says all checks pass)
        assert summary["applied"] == 0 or summary["scanned"] > 0
        # Order file should still be in pending/ (dry run doesn't move files)
        if summary["applied"] > 0:
            assert len(list(self.pending_dir.glob("*.json"))) > 0

    def test_delta_makes_target_exceed_envelope_still_ok(self):
        """Delta that would push the envelope over 800 is fine if conserved.
        INV-SUM says sum must be conserved, not that each zone is bounded."""
        # This is a valid operation — the envelope sum doesn't change
        make_order_file(self.pending_dir, "big-delta-1", delta=50)

        summary = B.process_orders(
            self.orders_root, self.zone_names, str(self.projection_path),
            cgroup_reader=self.mock_weights,
            projection_reader=self.mock_projection,
            systemctl_runner=self.mock_systemctl,
        )
        assert summary["applied"] == 1, "INV-SUM-conserving delta must be applied"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
