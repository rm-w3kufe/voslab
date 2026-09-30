#!/usr/bin/env python3
"""
test_nucleus_realdata_wiring.py — Cross-component integration test

Proves Component A's order format and Component B's reader agree on
the nucleus_projection_contract schema, end-to-end, without requiring
Component A's Rust binary to be running.

Design per: docs/spec/s4_anticipation/nucleus_realdata_wiring.spec.vsm
  step_3: Load the order via Order.load() — prove no exception
  step_4: Run validate_order() with real read_projection_stasis_cos

Usage:
    python3 -m pytest scripts/state/test_nucleus_realdata_wiring.py -v

    # Or if pytest not available:
    python3 scripts/state/test_nucleus_realdata_wiring.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Ensure the parent dir is on the path for importing Component B
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import vsf_cgroup_reallocate as B


# ── Constants (must match the Rust side) ──
BASIN_FLOOR = 0.875
ENVELOPE_SUM = 800
ZONE_NAMES = [
    "mediterranea", "subpolar", "semiarida", "templada-humeda",
    "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
]


def make_fixture_projection(
    tmpdir: Path,
    zones: dict[str, float],
) -> Path:
    """Write a fixture projection file in the nucleus_projection_contract format.

    Args:
        tmpdir: Temp directory to write into.
        zones: Mapping of zone_name -> stasis_cos. Zones not listed are absent.

    Returns: Path to the written file.
    """
    data = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zones": [
            {"name": name, "current_sc": sc}
            for name, sc in zones.items()
        ],
    }
    path = tmpdir / "projection.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def make_order_json(
    orders_dir: Path,
    directive_id: str,
    target_zone: str,
    donor_zone: str,
    delta: int,
    kernel_claimed_cos: float | None,
    kernel_mode: str = "synthetic",
) -> Path:
    """Write a synthetic order JSON matching Component A's order_format.

    This is the EXACT same shape Component A's write_order_file() produces.
    """
    pending_dir = orders_dir / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    order_data = {
        "directive_id": directive_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "donor_zone": donor_zone,
        "target_zone": target_zone,
        "delta": delta,
        "kernel_claimed_donor_stasis_cos": kernel_claimed_cos,
        "kernel_claimed_sum_after": ENVELOPE_SUM,
        "kernel_mode": kernel_mode,
    }
    path = pending_dir / f"{directive_id}.json"
    path.write_text(json.dumps(order_data, indent=2))
    return path


class TestNucleusRealdataWiring(unittest.TestCase):
    """Cross-component integration: Component A output → Component B reader."""

    def setUp(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="vsf-nucleus-wiring-"))
        self.orders_dir = self._tmpdir / "orders"
        (self.orders_dir / "pending").mkdir(parents=True)
        (self.orders_dir / "done").mkdir(parents=True)
        (self.orders_dir / "rejected").mkdir(parents=True)

        # All zones at default weight (100), sum = 800
        self.mock_weights = lambda zone_names: {z: 100 for z in zone_names}

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── Step 3: Order.load() compatibility ──────────────────────────────────

    def test_order_load_accepts_kernel_mode_field(self):
        """Order.load() tolerates the 'kernel_mode' extra field (no crash)."""
        path = make_order_json(
            self.orders_dir, "km-test-1", "humboldt", "subpolar", 30, 0.95,
            kernel_mode="production",
        )
        order = B.Order.load(path)
        self.assertEqual(order.directive_id, "km-test-1")
        self.assertEqual(order.donor_zone, "subpolar")
        self.assertEqual(order.target_zone, "humboldt")
        self.assertEqual(order.delta, 30)
        self.assertAlmostEqual(order.kernel_claimed_donor_stasis_cos, 0.95)
        self.assertEqual(order.kernel_claimed_sum_after, ENVELOPE_SUM)
        # kernel_mode is stored in raw dict (Order.__init__ stores data as raw)
        self.assertEqual(order.raw.get("kernel_mode"), "production")

    def test_order_load_synthetic_mode_no_stasis_cos(self):
        """Synthetic mode order with null stasis_cos still loads cleanly."""
        path = make_order_json(
            self.orders_dir, "syn-test-1", "mediterranea", "subpolar", 20, None,
            kernel_mode="synthetic",
        )
        order = B.Order.load(path)
        self.assertEqual(order.directive_id, "syn-test-1")
        self.assertEqual(order.kernel_claimed_donor_stasis_cos, 0.0)
        self.assertEqual(order.raw.get("kernel_mode"), "synthetic")

    def test_order_load_all_required_fields_present(self):
        """Every required field in the order_format contract is populated."""
        path = make_order_json(
            self.orders_dir, "full-test-1", "pacifico-sur-medio", "semiarida",
            15, 0.88, kernel_mode="production",
        )
        order = B.Order.load(path)

        # All required fields must be non-empty/non-zero
        self.assertTrue(order.directive_id)
        self.assertTrue(order.ts)
        self.assertTrue(order.donor_zone)
        self.assertTrue(order.target_zone)
        self.assertGreater(order.delta, 0)
        self.assertGreater(order.kernel_claimed_sum_after, 0)

    # ── Step 4: validate_order() with real projection reader ──────────────

    def test_validate_order_healthy_donor_passes(self):
        """Healthy donor (stasis_cos >= 0.875) passes validation."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
            "subpolar": 0.92,
            "semiarida": 0.88,
            "templada-humeda": 0.85,
            "humboldt": 0.99,
            "pacifico-sur-medio": 0.91,
        })
        order_path = make_order_json(
            self.orders_dir, "val-happy", "humboldt", "subpolar", 40, 0.92,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(proj_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,  # real reader
        )
        self.assertTrue(result.passed, f"healthy donor should pass: {result.reasons}")

    def test_validate_order_below_floor_donor_rejected(self):
        """Below-floor donor (stasis_cos=0.85 < 0.875) is REJECTED."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
            "subpolar": 0.92,
            "templada-humeda": 0.85,  # BELOW floor
            "humboldt": 0.99,
        })
        order_path = make_order_json(
            self.orders_dir, "val-below", "humboldt", "templada-humeda", 40, 0.85,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(proj_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertFalse(result.passed, "below-floor donor must be REJECTED")
        self.assertTrue(
            any("BASIN_FLOOR" in r or "0.875" in r for r in result.reasons),
            f"rejection reason must mention floor threshold: {result.reasons}"
        )

    def test_validate_order_missing_zone_rejected(self):
        """Zone not present in projection file is REJECTED (fail-closed)."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
            "subpolar": 0.92,
            "humboldt": 0.99,
            # enso-tropical is ABSENT from projection
        })
        order_path = make_order_json(
            self.orders_dir, "val-miss", "humboldt", "enso-tropical", 40, 0.75,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(proj_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertFalse(result.passed, "missing-zone donor must be REJECTED (fail-closed)")
        self.assertTrue(
            any("not found" in r or "projection" in r for r in result.reasons),
            f"rejection reason must mention missing zone: {result.reasons}"
        )

    def test_validate_order_missing_projection_file_rejected(self):
        """When projection file doesn't exist, order is REJECTED."""
        nonexistent_path = self._tmpdir / "nonexistent.json"
        order_path = make_order_json(
            self.orders_dir, "val-noproj", "humboldt", "subpolar", 10, 0.92,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(nonexistent_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertFalse(result.passed, "missing projection must REJECT")
        self.assertTrue(
            any("unavailable" in r or "not found" in r for r in result.reasons),
            f"rejection reason must mention unavailable projection: {result.reasons}"
        )

    def test_validate_order_stale_projection_rejected(self):
        """Projection file older than STALE_PROJECTION_SECS is REJECTED."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
            "subpolar": 0.92,
        })
        # Age the file by writing with an artificially old mtime.
        # Use file's atime/mtime or create a file with a past timestamp.
        # Simplest: write the file, then wait 1s and check staleness.
        # But STALE_PROJECTION_SECS=600, so 1s won't help.
        # Instead: create a temp file alongside, set its st_mtime via os.utime
        # to (now - 700s), then rename it.

        stale_path = self._tmpdir / "stale_projection.json"
        stale_path.write_text(proj_path.read_text())

        # Age the file by 700 seconds
        past_time = time.time() - 700
        os.utime(str(stale_path), (past_time, past_time))

        order_path = make_order_json(
            self.orders_dir, "val-stale", "humboldt", "subpolar", 10, 0.92,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(stale_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertFalse(result.passed, "stale projection must REJECT")
        self.assertTrue(
            any("stale" in r or "unavailable" in r for r in result.reasons),
            f"rejection reason must mention stale: {result.reasons}"
        )

    def test_validate_order_zone_not_in_8_known_rejected(self):
        """A zone that is NOT one of the 8 managed L2 zones is rejected."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
        })
        # pretend the kernel claimed a bogus zone
        order_path = make_order_json(
            self.orders_dir, "val-bogus", "humboldt", "nonexistent-zone", 10, None,
            kernel_mode="production",
        )
        order = B.Order.load(order_path)

        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(proj_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertFalse(result.passed, "unknown zone must be REJECTED")
        # The missing weight for unknown zone defaults to 100 (cgroup reader),
        # so the baseline sum won't match → rejected.
        # But even if it matched, projection doesn't cover it → rejected.
        self.assertTrue(
            any("not found" in r or "projection" in r for r in result.reasons),
            f"rejection reason must mention projection: {result.reasons}"
        )

    # ── End-to-end: simulate full pipeline ─────────────────────────────────

    def test_end_to_end_pipeline_synthetic_mode(self):
        """Full pipeline: fixture → synthetic order → validate → pass."""
        proj_path = make_fixture_projection(self._tmpdir, {
            "mediterranea": 0.95,
            "subpolar": 0.92,
            "semiarida": 0.88,
            "templada-humeda": 0.85,
            "tropical-arida": 0.70,
            "humboldt": 0.99,
            "pacifico-sur-medio": 0.91,
            "enso-tropical": 0.87,
        })

        # Order for a grant: healthy donor subpolar -> target humboldt
        order_path = make_order_json(
            self.orders_dir, "e2e-1", "humboldt", "subpolar", 30, 0.92,
            kernel_mode="synthetic",
        )
        order = B.Order.load(order_path)

        # Validate with real projection reader
        result = B.validate_order(
            order,
            orders_root=str(self.orders_dir),
            zone_names=ZONE_NAMES,
            projection_path=str(proj_path),
            cgroup_reader=self.mock_weights,
            projection_reader=B.read_projection_stasis_cos,
        )
        self.assertTrue(result.passed, f"synthetic pipeline should pass: {result.reasons}")

        # Also verify the order contains kernel_mode
        self.assertEqual(order.raw.get("kernel_mode"), "synthetic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
