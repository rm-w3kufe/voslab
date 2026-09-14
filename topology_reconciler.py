#!/usr/bin/env python3
"""
topology_reconciler.py — Reconcile desired topology with actual Proxmox state.

Hybrid mode:
    - On-demand: python3 topology_reconciler.py reconcile [--dry-run]
    - Daemon:    python3 topology_reconciler.py daemon [--interval 30]

Generates .fw firewall files from topology.json.
Detects new/missing containers and emits events.
"""

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from topology_loader import Topology, load_topology

# ── Paths ────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_VOSLAB = _HERE
_FW_DIR = Path("/etc/pve/firewall")  # Proxmox firewall directory
_LOG_DIR = _VOSLAB / "state" / "rsi"
_EVENTS_LOG = _LOG_DIR / "topology_events.jsonl"


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class ReconcileEvent:
    """A reconciliation event."""
    kind: str  # container_added, container_removed, fw_generated, fw_skipped, error
    container_id: str = ""
    detail: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "ts": self.timestamp}
        if self.container_id:
            d["container_id"] = self.container_id
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class ReconcileResult:
    """Result of a reconciliation cycle."""
    events: list[ReconcileEvent] = field(default_factory=list)
    fw_generated: int = 0
    fw_skipped: int = 0
    containers_added: int = 0
    containers_removed: int = 0
    errors: int = 0

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def summary(self) -> str:
        parts = []
        if self.fw_generated:
            parts.append(f"{self.fw_generated} .fw generated")
        if self.fw_skipped:
            parts.append(f"{self.fw_skipped} .fw skipped (unchanged)")
        if self.containers_added:
            parts.append(f"{self.containers_added} containers discovered")
        if self.containers_removed:
            parts.append(f"{self.containers_removed} containers removed")
        if self.errors:
            parts.append(f"{self.errors} errors")
        return ", ".join(parts) if parts else "nothing to do"


# ── Firewall generator ──────────────────────────────────────────────────

def _cidr(src: str) -> str:
    """Normalize IP to CIDR format (Proxmox convention: single IPs get /32)."""
    if "/" in src:
        return src
    # Only add /32 to bare IPv4 addresses
    parts = src.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{src}/32"
    return src


def generate_fw_content(cid: str, container: dict) -> str:
    """Generate Proxmox .fw file content for a container."""
    lines = ["[OPTIONS]", ""]

    fw = container.get("firewall", {})
    enabled = fw.get("enabled", False)
    policy_in = fw.get("policy_in", "ACCEPT")

    lines.append(f"enable: {'1' if enabled else '0'}")
    if enabled and policy_in != "ACCEPT":
        lines.append(f"policy_in: {policy_in}")
    lines.append("")

    if not enabled:
        return "\n".join(lines) + "\n"

    if not fw.get("rules") and not fw.get("out_rules"):
        return "\n".join(lines) + "\n"

    lines.append("[RULES]")
    for rule in fw["rules"]:
        src = _cidr(rule["src"])
        port = rule.get("port", 0)
        proto = rule.get("proto", "tcp")
        note = rule.get("note", "")

        if proto == "icmp":
            line = f"IN ACCEPT -source {src} -p icmp"
        elif port == 0:
            line = f"IN ACCEPT -source {src} -p {proto}"
        else:
            line = f"IN ACCEPT -source {src} -p {proto} -dport {port}"

        if note:
            line += f" -log nolog # {note}"
        else:
            line += " -log nolog"

        lines.append(line)

    # OUT rules
    out_rules = fw.get("out_rules", [])
    if out_rules:
        lines.append("")
        for rule in out_rules:
            dest = _cidr(rule["dest"])
            action = rule.get("action", "DROP")
            note = rule.get("note", "")
            line = f"OUT {action} -dest {dest}"
            if note:
                line += f" -log nolog # {note}"
            else:
                line += " -log nolog"
            lines.append(line)

    return "\n".join(lines) + "\n"


def write_fw_file(cid: str, content: str, dry_run: bool = False) -> bool:
    """Write .fw file for a container. Returns True if written."""
    if dry_run:
        print(f"  [dry-run] Would write {_FW_DIR / f'{cid}.fw'}")
        return True

    try:
        _FW_DIR.mkdir(parents=True, exist_ok=True)
        fw_path = _FW_DIR / f"{cid}.fw"
        fw_path.write_text(content)
        return True
    except OSError as e:
        print(f"  ✗ Failed to write {fw_path}: {e}", file=sys.stderr)
        return False


# ── Proxmox discovery ───────────────────────────────────────────────────

def discover_containers(ssh_target: str) -> dict[str, dict]:
    """Run 'pct list' on the Proxmox host and return {id: {name, status}}."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", ssh_target, "pct list"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {}

        containers = {}
        for line in result.stdout.strip().split("\n")[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 3:
                cid, status, name = parts[0], parts[1], parts[2]
                containers[cid] = {"name": name, "status": status}
        return containers
    except (subprocess.TimeoutExpired, OSError):
        return {}


# ── Reconciler ──────────────────────────────────────────────────────────

def reconcile(
    topo: Topology,
    dry_run: bool = False,
    ssh_target: Optional[str] = None,
) -> ReconcileResult:
    """Reconcile desired topology with actual Proxmox state."""
    result = ReconcileResult()

    target = ssh_target or topo.host.get("ssh_target", "n02")

    # 1. Generate .fw files for all containers in topology
    for cid in topo.container_ids():
        container = topo.containers[cid]
        content = generate_fw_content(cid, container)

        # Check if file already exists and is identical
        fw_path = _FW_DIR / f"{cid}.fw"
        if fw_path.exists() and fw_path.read_text() == content:
            result.fw_skipped += 1
            continue

        if write_fw_file(cid, content, dry_run):
            result.fw_generated += 1
            result.events.append(ReconcileEvent(
                kind="fw_generated",
                container_id=cid,
                detail=f"{container['name']} ({cid})",
            ))
        else:
            result.errors += 1
            result.events.append(ReconcileEvent(
                kind="error",
                container_id=cid,
                detail="Failed to write .fw file",
            ))

    # 2. Discover actual containers on Proxmox
    actual = discover_containers(target)
    desired_ids = set(topo.containers.keys())
    actual_ids = set(actual.keys())

    # New containers (in Proxmox but not in topology)
    new_containers = actual_ids - desired_ids
    for cid in sorted(new_containers):
        result.containers_added += 1
        result.events.append(ReconcileEvent(
            kind="container_added",
            container_id=cid,
            detail=f"{actual[cid]['name']} ({actual[cid]['status']}) — NOT in topology.json",
        ))

    # Missing containers (in topology but not in Proxmox)
    missing = desired_ids - actual_ids
    for cid in sorted(missing):
        result.containers_removed += 1
        result.events.append(ReconcileEvent(
            kind="container_removed",
            container_id=cid,
            detail=f"{topo.containers[cid]['name']} — not found on Proxmox",
        ))

    return result


# ── Event logging ────────────────────────────────────────────────────────

def log_events(events: list[ReconcileEvent]):
    """Append events to the topology events log."""
    if not events:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_EVENTS_LOG, "a") as f:
        for ev in events:
            f.write(json.dumps(ev.to_dict(), default=str) + "\n")


# ── Daemon mode ──────────────────────────────────────────────────────────

_running = True

def _handle_signal(sig, frame):
    global _running
    _running = False


def daemon(interval: int = 30, dry_run: bool = False):
    """Run reconciler in daemon mode."""
    global _running

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print(f"Topology reconciler daemon started (interval={interval}s, dry_run={dry_run})")
    print("Press Ctrl+C to stop")

    while _running:
        try:
            topo = load_topology(validate=True)
            result = reconcile(topo, dry_run=dry_run)
            log_events(result.events)

            if result.events:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"[{ts}] {result.summary()}")
                for ev in result.events:
                    print(f"  → {ev.kind}: {ev.detail}")

        except Exception as e:
            print(f"  ✗ Reconcile error: {e}", file=sys.stderr)

        # Sleep in small increments so we can respond to signals
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)

    print("Daemon stopped")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="VSF Topology Reconciler")
    sub = parser.add_subparsers(dest="command")

    # reconcile
    p_reconcile = sub.add_parser("reconcile", help="Run one reconciliation cycle")
    p_reconcile.add_argument("--dry-run", action="store_true", help="Don't write files")
    p_reconcile.add_argument("--ssh", help="SSH target override")
    p_reconcile.add_argument("--json", action="store_true", help="Output as JSON")

    # daemon
    p_daemon = sub.add_parser("daemon", help="Run as daemon")
    p_daemon.add_argument("--interval", type=int, default=30, help="Check interval (seconds)")
    p_daemon.add_argument("--dry-run", action="store_true", help="Don't write files")

    # status
    p_status = sub.add_parser("status", help="Show current topology status")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    # validate
    p_validate = sub.add_parser("validate", help="Validate topology.json")
    p_validate.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command == "reconcile":
        topo = load_topology(validate=True)
        result = reconcile(topo, dry_run=args.dry_run, ssh_target=args.ssh)
        log_events(result.events)

        if args.json:
            print(json.dumps({
                "ok": result.ok,
                "summary": result.summary(),
                "events": [e.to_dict() for e in result.events],
            }, indent=2, default=str))
        else:
            print(f"Reconciliation: {result.summary()}")
            for ev in result.events:
                prefix = "  ⚠" if ev.kind in ("container_added", "container_removed") else "  ✓"
                print(f"{prefix} {ev.kind}: {ev.detail}")

    elif args.command == "daemon":
        daemon(interval=args.interval, dry_run=args.dry_run)

    elif args.command == "status":
        topo = load_topology(validate=True)
        actual = discover_containers(topo.host.get("ssh_target", "n02"))

        if args.json:
            status_data = {
                "topology_version": topo.version,
                "host": topo.host["hostname"],
                "desired": {cid: {"name": topo.containers[cid]["name"],
                                   "status": topo.containers[cid]["status"]}
                            for cid in topo.container_ids()},
                "actual": actual,
                "matching": {cid: cid in actual for cid in topo.container_ids()},
                "discovered": {cid: actual[cid] for cid in actual if cid not in topo.containers},
            }
            print(json.dumps(status_data, indent=2))
        else:
            print(f"Topology v{topo.version} — {topo.host['hostname']}")
            print(f"  Desired: {len(topo.containers)} containers")
            print(f"  Actual:  {len(actual)} containers")
            print()

            for cid in topo.container_ids():
                c = topo.containers[cid]
                actual_info = actual.get(cid)
                if actual_info:
                    status_icon = "✓" if actual_info["status"] == "running" else "○"
                    print(f"  {status_icon} {cid:>3s} {c['name']:<20s} {c['ip']:<18s} {actual_info['status']}")
                else:
                    print(f"  ✗ {cid:>3s} {c['name']:<20s} {c['ip']:<18s} MISSING")

            discovered = {cid: actual[cid] for cid in actual if cid not in topo.containers}
            if discovered:
                print(f"\n  Discovered (not in topology):")
                for cid, info in sorted(discovered.items()):
                    print(f"  ? {cid:>3s} {info['name']:<20s} {info['status']}")

    elif args.command == "validate":
        topo = load_topology(validate=True)
        if args.json:
            print(json.dumps({"valid": True, "version": topo.version}))
        else:
            print(f"✓ Topology v{topo.version} is valid")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
