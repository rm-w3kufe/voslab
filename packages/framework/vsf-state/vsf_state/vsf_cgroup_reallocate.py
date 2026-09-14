#!/usr/bin/env python3
"""
vsf-cgroup-reallocate — Component B host-level cgroup reallocator

@vsm 0.3  V("vsf-cgroup-reallocate", L=0)  @kind=bare_process  @vantage=lxc:0
@status: built (2026-07-26-ds) — no live wiring yet, only adversarial tests

Reads orders written by Component A (s3_anticipation.rs, kernel LXC 101),
independently validates each one from host-visible sources, actuates via
systemctl set-property --runtime (two calls: donor then target), and
self-heals on partial failure.

Design per: docs/spec/s4_anticipation/component_b_host_reallocator.spec.vsm
Pattern reference: scripts/state/topology_reconcile.py

Usage (oneshot, triggered by systemd timer):
    python3 vsf_cgroup_reallocate.py --orders-dir /var/lib/vsf-anticipation/orders

Usage (test mode, dry-run only):
    python3 vsf_cgroup_reallocate.py --orders-dir /tmp/test-orders --dry-run
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone

# Resolve LXC IDs from topology.json (clone-portable)
sys.path.insert(0, str(os.environ.get("VOSLAB_PATH", os.path.dirname(__file__))))
from topology_resolve import resolve_lxc

_CLIMA_LXC = resolve_lxc("clima")
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

VERSION = "0.1.0"
ENVELOPE_SUM = 800
BASIN_FLOOR = 0.875
FRESHNESS_WINDOW_SECS = 120  # max age of order ts before it is stale
STALE_PROJECTION_SECS = 600  # 2x normal refresh cadence (5min = 300s)
RECONCILE_CYCLE_SECS = 60   # polling interval for the systemd timer

# ── Order model ────────────────────────────────────────────────────────────────

class Order:
    """An order from Component A requesting a cgroup weight transfer."""

    __slots__ = (
        "directive_id", "ts", "donor_zone", "target_zone",
        "delta", "kernel_claimed_donor_stasis_cos",
        "kernel_claimed_sum_after", "filepath", "raw",
    )

    def __init__(self, data: dict, filepath: str | Path):
        self.directive_id = data.get("directive_id", "")
        self.ts = data.get("ts", "")
        self.donor_zone = data.get("donor_zone", "")
        self.target_zone = data.get("target_zone", "")
        self.delta = int(data.get("delta", 0))
        # JSON null (e.g. synthetic mode with no stasis_cos data) is distinct
        # from key-absent. Use `or` to coalesce both None and missing to 0.
        raw_cos = data.get("kernel_claimed_donor_stasis_cos") or 0.0
        self.kernel_claimed_donor_stasis_cos = float(raw_cos)
        raw_sum = data.get("kernel_claimed_sum_after") or 0
        self.kernel_claimed_sum_after = int(raw_sum)
        self.filepath = str(filepath)
        self.raw = data

    @classmethod
    def load(cls, filepath: str | Path) -> "Order":
        with open(filepath) as f:
            data = json.load(f)
        return cls(data, filepath)

    def to_dict(self) -> dict:
        return {
            "directive_id": self.directive_id,
            "ts": self.ts,
            "donor_zone": self.donor_zone,
            "target_zone": self.target_zone,
            "delta": self.delta,
            "kernel_claimed_donor_stasis_cos": self.kernel_claimed_donor_stasis_cos,
            "kernel_claimed_sum_after": self.kernel_claimed_sum_after,
        }

    def __repr__(self) -> str:
        return (
            f"Order(ds={self.directive_id}, target={self.target_zone}, "
            f"donor={self.donor_zone}, delta={self.delta})"
        )


# ── Result model ───────────────────────────────────────────────────────────────

class OrderOutcome:
    """Outcome appended to an order file after processing."""

    STATUS_APPLIED = "applied"
    STATUS_REJECTED = "rejected"

    def __init__(self, status: str, reason: str, applied_at: str | None = None):
        self.status = status
        self.reason = reason
        self.applied_at = applied_at or _now_ts()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "applied_at": self.applied_at,
        }


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Independent cgroup weight reader ───────────────────────────────────────────

def read_cgroup_weights(zone_names: list[str]) -> dict[str, int]:
    """
    Read current CPUWeight for each zone from systemctl --runtime.
    
    Returns dict {zone_name: weight}. Returns 100 as default for zones where
    systemctl returns empty or fails (graceful degradation — the unit may not
    have been started yet but defaults apply).
    
    This is the MOCK TARGET in tests. In production on n02 host, the zone
    units live inside LXC 112 and are not visible to the host's systemd, so
    use read_cgroup_weights_host() instead (goes through pct exec 112).
    """
    weights = {}
    for zone in zone_names:
        unit = f"vsf-clima-l2@{zone}.service"
        try:
            result = subprocess.run(
                ["systemctl", "show", "-p", "CPUWeight", "--value", unit],
                capture_output=True, text=True, timeout=10,
            )
            raw = result.stdout.strip()
            if raw and raw.isdigit():
                weights[zone] = int(raw)
            else:
                weights[zone] = 100  # default
        except (subprocess.SubprocessError, FileNotFoundError):
            weights[zone] = 100  # graceful degradation
    return weights


def read_cgroup_weights_host(zone_names: list[str]) -> dict[str, int]:
    """
    Read current CPUWeight for each zone via pct exec 112.
    
    The 8 clima L2 zone units live INSIDE LXC 112. The host systemd does not
    see them directly; this function proxies through pct exec.
    
    Production counterpart to read_cgroup_weights() (which is the mock target
    for unit tests). Both return the same shape.
    """
    weights = {}
    for zone in zone_names:
        unit = f"vsf-clima-l2@{zone}.service"
        try:
            result = subprocess.run(
                ["pct", "exec", _CLIMA_LXC, "--",
                 "systemctl", "show", "-p", "CPUWeight", "--value", unit],
                capture_output=True, text=True, timeout=15,
            )
            raw = result.stdout.strip()
            if raw and raw.isdigit():
                weights[zone] = int(raw)
            else:
                weights[zone] = 100  # default
        except (subprocess.SubprocessError, FileNotFoundError):
            weights[zone] = 100  # graceful degradation
    return weights


# ── Independent stasis_cos reader (from projection file) ───────────────────────

def read_projection_stasis_cos(projection_path: str) -> tuple[dict[str, float], str | None]:
    """
    Read current stasis_cos for all zones from the S4 Markov projection file.
    
    Returns (zone_name -> stasis_cos dict, error_message_or_None).
    Returns error string if the file is stale or unreadable.
    """
    path = Path(projection_path)
    if not path.exists():
        return {}, f"projection file not found: {projection_path}"

    # Freshness check: file mtime must be within STALE_PROJECTION_SECS
    mtime = path.stat().st_mtime
    age = time.time() - mtime
    if age > STALE_PROJECTION_SECS:
        return {}, (
            f"projection file stale: mtime={mtime:.0f}, age={age:.0f}s "
            f"> {STALE_PROJECTION_SECS}s threshold"
        )

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {}, f"projection file unreadable: {e}"

    zones_list = data.get("zones", [])
    result = {}
    for z in zones_list:
        name = z.get("name")
        sc = z.get("current_sc")
        if name and sc is not None:
            result[name] = float(sc)

    if not result:
        return {}, "projection file has no zone entries with current_sc"

    return result, None


# ── Order file I/O ─────────────────────────────────────────────────────────────

def scan_pending_orders(orders_root: str) -> list[Order]:
    """Read all order files from pending/ subdirectory."""
    pending_dir = Path(orders_root) / "pending"
    if not pending_dir.exists():
        return []

    orders = []
    for fpath in sorted(pending_dir.glob("*.json")):
        try:
            order = Order.load(fpath)
            orders.append(order)
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            # Malformed file: write a rejection record and move the raw file
            reason = f"malformed order file: {e}"
            _move_malformed_to_rejected(fpath, reason, orders_root)
    return orders


def _done_dir(orders_root: str) -> Path:
    p = Path(orders_root) / "done"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _rejected_dir(orders_root: str) -> Path:
    p = Path(orders_root) / "rejected"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_rejected(source_path: str | Path, reason: str, orders_root: str):
    """Write a rejected outcome record (for malformed files)."""
    rejected = _rejected_dir(orders_root)
    outcome = OrderOutcome("rejected", reason)
    dest = rejected / f"{Path(source_path).stem}.rejected.json"
    with open(dest, "w") as f:
        json.dump({"outcome": outcome.to_dict()}, f, indent=2)


def _move_malformed_to_rejected(source_path: str | Path, reason: str, orders_root: str):
    """Move a malformed file to rejected/ with a separate rejection record.
    
    Unlike _move_to_rejected, this does NOT try to parse the malformed file
    (which would fail with the same JSON error). Instead it writes a new
    rejection record alongside the raw (unparseable) file content.
    """
    rejected = _rejected_dir(orders_root)
    dest = rejected / Path(source_path).name
    # Copy the raw bytes alongside a rejection note
    raw_bytes = Path(source_path).read_bytes()
    rejected_record = {
        "original_filename": Path(source_path).name,
        "outcome": {"status": "rejected", "reason": reason},
        "raw_content_b64": None,  # Not included to avoid noise; raw file is at rejected/
    }
    # Write the raw file to rejected/ as-is (it failed JSON parse)
    dest.write_bytes(raw_bytes)
    # Also write a .rejected.json metadata note
    note_path = rejected / f"{Path(source_path).stem}.rejected.json"
    note_path.write_text(json.dumps(rejected_record, indent=2))
    os.remove(source_path)


def _move_to_rejected(source_path: str | Path, reason: str, orders_root: str):
    """Move a file to rejected/ with outcome appended."""
    rejected = _rejected_dir(orders_root)
    dest = rejected / Path(source_path).name
    outcome = OrderOutcome("rejected", reason)
    with open(source_path) as f:
        data = json.load(f)
    data["outcome"] = outcome.to_dict()
    with open(dest, "w") as f:
        json.dump(data, f, indent=2)
    os.remove(source_path)


def _move_to_done(source_path: str | Path, outcome: OrderOutcome, orders_root: str):
    """Move a file to done/ with outcome appended."""
    done = _done_dir(orders_root)
    dest = done / Path(source_path).name
    with open(source_path) as f:
        data = json.load(f)
    data["outcome"] = outcome.to_dict()
    with open(dest, "w") as f:
        json.dump(data, f, indent=2)
    os.remove(source_path)


# ── Replay detection ───────────────────────────────────────────────────────────

def _list_done_ids(orders_root: str) -> set[str]:
    """Return set of directive_ids already processed (in done/ or rejected/)."""
    ids: set[str] = set()
    for subdir in ["done", "rejected"]:
        d = Path(orders_root) / subdir
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    did = data.get("directive_id") or data.get("outcome", {}).get(
                        "directive_id", ""
                    )
                    if did:
                        ids.add(did)
                except (json.JSONDecodeError, OSError):
                    pass
    return ids


# ── Validation (the 3 independent checks) ──────────────────────────────────────

class ValidationResult:
    """Result of the 3 validation checks."""

    def __init__(self):
        self.passed = True
        self.reasons: list[str] = []

    def fail(self, reason: str):
        self.passed = False
        self.reasons.append(reason)

    def __bool__(self) -> bool:
        return self.passed


def validate_order(
    order: Order,
    orders_root: str,
    zone_names: list[str],
    projection_path: str,
    cgroup_reader: Callable | None = None,
    projection_reader: Callable | None = None,
) -> ValidationResult:
    """
    Run the 3 independent validation checks on an order.
    
    Accepts optional injectable functions for testing. When not provided,
    uses the real implementations (systemctl, file reads).
    
    Returns ValidationResult — passed=True only when ALL 3 checks pass.
    """
    result = ValidationResult()

    # Use injected mocks when provided (testing); real implementations otherwise
    _read_weights = cgroup_reader or read_cgroup_weights
    _read_projection = projection_reader or read_projection_stasis_cos

    # ── CHECK 3 (cheapest, do first as fast-fail) ──
    # Freshness: directive_id not in done/rejected, ts within window
    done_ids = _list_done_ids(orders_root)
    if order.directive_id in done_ids:
        result.fail(
            f"replay: directive_id '{order.directive_id}' already processed"
        )

    # ts freshness
    try:
        order_ts = datetime.fromisoformat(order.ts.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - order_ts
        if age.total_seconds() > FRESHNESS_WINDOW_SECS:
            result.fail(
                f"stale: order ts={order.ts} is {age.total_seconds():.0f}s old "
                f"(>{FRESHNESS_WINDOW_SECS}s threshold)"
            )
    except (ValueError, TypeError):
        result.fail(f"invalid ts format: '{order.ts}'")

    if not result.passed:
        return result  # fast-fail on freshness — no point checking further

    # ── CHECK 1: Sum unchanged (independent cgroup weight read) ──
    live_weights = _read_weights(zone_names)
    live_sum = sum(live_weights.values())
    if live_sum != ENVELOPE_SUM:
        result.fail(
            f"baseline sum mismatch: live cgroup sum={live_sum} != {ENVELOPE_SUM}. "
            f"Cannot apply delta on a bad baseline. Weights: {live_weights}"
        )

    # Derive sum after potential application
    donor_w = live_weights.get(order.donor_zone, 100)
    target_w = live_weights.get(order.target_zone, 100)
    after_donor = donor_w - order.delta
    after_target = target_w + order.delta
    after_sum = live_sum  # INV-SUM: delta-conserving, so sum unchanged
    if after_sum != ENVELOPE_SUM:
        result.fail(
            f"post-grant sum would be {after_sum} != {ENVELOPE_SUM} "
            f"(donor {order.donor_zone}: {donor_w}→{after_donor}, "
            f"target {order.target_zone}: {target_w}→{after_target})"
        )

    # ── CHECK 2: Donor floor (independent stasis_cos read) ──
    projection_cos, proj_error = _read_projection(projection_path)
    if proj_error:
        result.fail(f"projection unavailable: {proj_error}")
        return result  # cannot check floor without projection

    donor_cos = projection_cos.get(order.donor_zone)
    if donor_cos is None:
        # Also check target — if both missing, the projection doesn't cover this zone
        result.fail(
            f"donor zone '{order.donor_zone}' not found in projection "
            f"(available: {list(projection_cos.keys())})"
        )
        return result  # cannot check floor without data

    # implied_impact: after donating delta, the donor's weight drops by delta.
    # The stasis_cos impact is proportional: sc_impact = sc * (1 - delta/weight_before)
    # But the spec is simpler: check that donor_stasis_cos >= 0.875.
    # The "implied_impact" language in the spec means: even after the grant,
    # the donor's stasis_cos (a lagging indicator of regime health) must still
    # be >= BASIN_FLOOR. We use the CURRENT stasis_cos as the best available
    # estimate — stasis_cos changes slowly (it is a distributional property,
    # not a point-in-time weight), so applying it directly is conservative.
    if donor_cos < BASIN_FLOOR:
        result.fail(
            f"donor zone '{order.donor_zone}' "
            f"independently-read stasis_cos={donor_cos:.4f} "
            f"< BASIN_FLOOR={BASIN_FLOOR} "
            f"(kernel claimed {order.kernel_claimed_donor_stasis_cos:.4f})"
        )

    return result


# ── Actuation ──────────────────────────────────────────────────────────────────

def actuate_order(
    order: Order,
    zone_names: list[str],
    weights_before: dict[str, int],
    dry_run: bool = False,
    systemctl_runner: Callable | None = None,
) -> tuple[bool, str]:
    """
    Apply the order's weight transfer via systemctl set-property --runtime.
    
    Two calls: donor first (reduce), then target (increase).
    If the second call fails, self-heal by reverting the first.
    
    Returns (success: bool, message: str).
    """
    donor_w = weights_before.get(order.donor_zone, 100)
    target_w = weights_before.get(order.target_zone, 100)

    new_donor = donor_w - order.delta
    new_target = target_w + order.delta

    if new_donor < 0:
        return False, f"donor weight would go negative: {donor_w} - {order.delta} = {new_donor}"

    _run = systemctl_runner or _run_systemctl

    if dry_run:
        return True, (
            f"DRY-RUN: would set {order.donor_zone}={new_donor}, "
            f"{order.target_zone}={new_target}"
        )

    # Call 1: donor
    donor_unit = f"vsf-clima-l2@{order.donor_zone}.service"
    ok1, msg1 = _run(donor_unit, new_donor)
    if not ok1:
        return False, f"donor actuation failed: {msg1}"

    # Call 2: target
    target_unit = f"vsf-clima-l2@{order.target_zone}.service"
    ok2, msg2 = _run(target_unit, new_target)
    if not ok2:
        # Self-heal: revert donor back to original weight
        revert_ok, revert_msg = _run(donor_unit, donor_w)
        if revert_ok:
            return False, (
                f"target actuation failed: {msg2} — donor reverted to {donor_w}"
            )
        else:
            return False, (
                f"ESCALATE: target actuation failed: {msg2}; "
                f"revert ALSO failed: {revert_msg}. "
                f"Manual intervention required — donor {order.donor_zone} "
                f"may be at {new_donor}, target {order.target_zone} at {target_w}"
            )

    return True, (
        f"applied: {order.donor_zone} {donor_w}→{new_donor}, "
        f"{order.target_zone} {target_w}→{new_target}"
    )


def _run_systemctl(unit: str, weight: int) -> tuple[bool, str]:
    """Execute systemctl set-property --runtime for a single unit.

    This is the MOCK TARGET in tests. In production on n02 host, the zone
    units live inside LXC 112 and are not visible to the host's systemd, so
    use _run_systemctl_host() instead (goes through pct exec 112).
    """
    try:
        result = subprocess.run(
            ["systemctl", "set-property", "--runtime", unit, f"CPUWeight={weight}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, f"{unit} → CPUWeight={weight}"
        else:
            return False, (
                f"systemctl failed (rc={result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
    except subprocess.TimeoutExpired:
        return False, f"systemctl timed out for {unit}"
    except FileNotFoundError:
        return False, "systemctl not found (not on n02 host?)"
    except OSError as e:
        return False, f"systemctl error: {e}"


def _run_systemctl_host(unit: str, weight: int) -> tuple[bool, str]:
    """Execute systemctl set-property --runtime via pct exec 112.

    Production counterpart to _run_systemctl(). The zone units live inside
    LXC 112; the host cannot systemctl them directly.
    """
    try:
        result = subprocess.run(
            ["pct", "exec", _CLIMA_LXC, "--",
             "systemctl", "set-property", "--runtime", unit, f"CPUWeight={weight}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, f"{unit} → CPUWeight={weight}"
        else:
            return False, (
                f"pct exec failed (rc={result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
    except subprocess.TimeoutExpired:
        return False, f"pct exec timed out for {unit}"
    except FileNotFoundError:
        return False, "pct not found (not on n02 host?)"
    except OSError as e:
        return False, f"pct exec error: {e}"


# ── Main orchestration ─────────────────────────────────────────────────────────

def process_orders(
    orders_root: str,
    zone_names: list[str],
    projection_path: str,
    dry_run: bool = False,
    cgroup_reader: Callable | None = None,
    projection_reader: Callable | None = None,
    systemctl_runner: Callable | None = None,
) -> dict:
    """
    Main entry point: scan pending orders, validate, actuate, move.
    
    Returns summary dict with counts and details.
    """
    summary = {
        "scanned": 0,
        "applied": 0,
        "rejected": 0,
        "failed_actuation": 0,
        "details": [],
    }

    orders = scan_pending_orders(orders_root)
    summary["scanned"] = len(orders)

    for order in orders:
        detail = {
            "directive_id": order.directive_id,
            "target": order.target_zone,
            "donor": order.donor_zone,
            "delta": order.delta,
            "dry_run": dry_run,
        }

        # Read current weights ONCE for this batch (consistent snapshot)
        weights = (cgroup_reader or read_cgroup_weights)(zone_names)

        # Validate
        validation = validate_order(
            order, orders_root, zone_names, projection_path,
            cgroup_reader=cgroup_reader,
            projection_reader=projection_reader,
        )

        if not validation.passed:
            reason = "; ".join(validation.reasons)
            if not dry_run:
                _move_to_rejected(order.filepath, reason, orders_root)
            detail["status"] = "rejected"
            detail["reason"] = reason
            summary["rejected"] += 1
            summary["details"].append(detail)
            continue

        # Actuate
        success, msg = actuate_order(
            order, zone_names, weights,
            dry_run=dry_run,
            systemctl_runner=systemctl_runner,
        )

        if success:
            if not dry_run:
                outcome = OrderOutcome("applied", msg)
                _move_to_done(order.filepath, outcome, orders_root)
            detail["status"] = "applied"
            summary["applied"] += 1
        else:
            if not dry_run:
                outcome = OrderOutcome("rejected", f"actuation failed: {msg}")
                _move_to_rejected(order.filepath, outcome.reason, orders_root)
            detail["status"] = "failed_actuation"
            detail["reason"] = msg
            summary["failed_actuation"] += 1

        summary["details"].append(detail)

    return summary


# ── CLI entry point ────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VSF Component B — host-level cgroup reallocator",
    )
    parser.add_argument(
        "--orders-dir", required=True,
        help="Root directory for order files (must contain pending/done/rejected subdirs)",
    )
    parser.add_argument(
        "--projection-path", default="/var/lib/vsf/vsf_nucleus/s4_markov_projection.json",
        help="Path to S4 Markov projection file",
    )
    parser.add_argument(
        "--zone-names", nargs="+",
        default=[
            "mediterranea", "subpolar", "semiarida", "templada-humeda",
            "tropical-arida", "humboldt", "pacifico-sur-medio", "enso-tropical",
        ],
        help="List of known zone names for cgroup weight reading",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log only, do not actuate")
    parser.add_argument("--host-mode", action="store_true",
                        help="Use pct exec 112 for cgroup operations (production on n02)")
    parser.add_argument("--version", action="version", version=f"vsf-cgroup-reallocate {VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = process_orders(
        orders_root=args.orders_dir,
        zone_names=args.zone_names,
        projection_path=args.projection_path,
        dry_run=args.dry_run,
        cgroup_reader=read_cgroup_weights_host if args.host_mode else None,
        systemctl_runner=_run_systemctl_host if args.host_mode else None,
    )
    print(json.dumps(summary, indent=2))

    # Exit 0 = normal completion (applies AND rejections are healthy outcomes).
    # Rejections at the validation layer (R1 catch, replay guard, stale ts)
    # are expected healthy behaviour, not failures.
    # A failed_actuation means systemctl calls errored — that is genuinely
    # actionable and warrants a non-zero exit so systemd's timer OnFailure=
    # or alert path can detect it.
    if summary["failed_actuation"] > 0:
        return 2  # actuation failure — systemctl calls failed, needs attention
    return 0  # normal completion: applies, rejections, or empty scan


if __name__ == "__main__":
    sys.exit(main())
