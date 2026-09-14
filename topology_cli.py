#!/usr/bin/env python3
"""
topology_cli.py — CLI for VSF topology management.

Integration with vosi.py:
    python3 topology_cli.py status [--json]
    python3 topology_cli.py validate [--json]
    python3 topology_cli.py reconcile [--dry-run] [--json]
    python3 topology_cli.py daemon [--interval 30] [--dry-run]
    python3 topology_cli.py lookup <service-or-container> [--json]
    python3 topology_cli.py nats-rules [--json]
    python3 topology_cli.py events [--tail 20] [--json]
"""

import json
import sys
from pathlib import Path
from typing import Optional

from topology_loader import load_topology, Topology
from topology_reconciler import reconcile, discover_containers, log_events, ReconcileEvent

_HERE = Path(__file__).resolve().parent
_EVENTS_LOG = _HERE / "state" / "rsi" / "topology_events.jsonl"


def cmd_status(args):
    """Show topology status."""
    topo = load_topology(validate=True)
    actual = discover_containers(topo.host.get("ssh_target", "n02"))

    if args.get("json"):
        status_data = {
            "topology_version": topo.version,
            "host": topo.host["hostname"],
            "desired_count": len(topo.containers),
            "actual_count": len(actual),
            "containers": {},
            "discovered": {},
        }
        for cid in topo.container_ids():
            c = topo.containers[cid]
            actual_info = actual.get(cid)
            status_data["containers"][cid] = {
                "name": c["name"],
                "ip": c["ip"],
                "vlan": c.get("vlan", "?"),
                "desired_status": c["status"],
                "actual_status": actual_info["status"] if actual_info else "MISSING",
                "roles": c.get("roles", []),
                "services": c.get("services", []),
                "firewall_enabled": c.get("firewall", {}).get("enabled", False),
            }
        discovered = {cid: actual[cid] for cid in actual if cid not in topo.containers}
        status_data["discovered"] = discovered
        print(json.dumps(status_data, indent=2))
    else:
        print(f"Topology v{topo.version} — {topo.host['hostname']}")
        print(f"  Desired: {len(topo.containers)} containers | Actual: {len(actual)} containers")
        print()
        for cid in topo.container_ids():
            c = topo.containers[cid]
            actual_info = actual.get(cid)
            if actual_info:
                icon = "✓" if actual_info["status"] == "running" else "○"
                print(f"  {icon} {cid:>3s} {c['name']:<20s} {c['ip']:<18s} {actual_info['status']}")
            else:
                print(f"  ✗ {cid:>3s} {c['name']:<20s} {c['ip']:<18s} MISSING")

        discovered = {cid: actual[cid] for cid in actual if cid not in topo.containers}
        if discovered:
            print(f"\n  Discovered (not in topology):")
            for cid, info in sorted(discovered.items()):
                print(f"  ? {cid:>3s} {info['name']:<20s} {info['status']}")


def cmd_validate(args):
    """Validate topology.json."""
    try:
        topo = load_topology(validate=True)
        if args.get("json"):
            print(json.dumps({"valid": True, "version": topo.version, "containers": len(topo.containers)}))
        else:
            print(f"✓ Topology v{topo.version} valid ({len(topo.containers)} containers, {len(topo.services)} services)")
    except (FileNotFoundError, ValueError) as e:
        if args.get("json"):
            print(json.dumps({"valid": False, "error": str(e)}))
        else:
            print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reconcile(args):
    """Run reconciliation cycle."""
    topo = load_topology(validate=True)
    dry_run = args.get("dry_run", False)
    result = reconcile(topo, dry_run=dry_run)
    log_events(result.events)

    if args.get("json"):
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


def cmd_daemon(args):
    """Run reconciler as daemon."""
    from topology_reconciler import daemon
    daemon(
        interval=args.get("interval", 30),
        dry_run=args.get("dry_run", False),
    )


def cmd_lookup(args):
    """Look up a service or container by name/ID."""
    topo = load_topology(validate=True)
    query = args["query"]

    # Try as container ID
    if query in topo.containers:
        c = topo.containers[query]
        result = {"type": "container", "id": query, **c}
        if args.get("json"):
            print(json.dumps(result, indent=2))
        else:
            print(f"Container {query}: {c['name']}")
            print(f"  IP: {c['ip']} | VLAN: {c.get('vlan', '?')} | Status: {c['status']}")
            print(f"  Roles: {', '.join(c.get('roles', []))}")
            print(f"  Services: {', '.join(c.get('services', []))}")
        return

    # Try as container name
    found = topo.container_by_name(query)
    if found:
        cid, c = found
        result = {"type": "container", "id": cid, **c}
        if args.get("json"):
            print(json.dumps(result, indent=2))
        else:
            print(f"Container {cid}: {c['name']} ({c['ip']})")
        return

    # Try as service name
    if query in topo.services:
        svc = topo.services[query]
        cid = svc["container"]
        c = topo.containers.get(cid, {})
        result = {"type": "service", "name": query, "container_id": cid, "container": c, **svc}
        if args.get("json"):
            print(json.dumps(result, indent=2))
        else:
            print(f"Service '{query}': port {svc['port']}")
            print(f"  Container: {cid} ({c.get('name', '?')}) — {c.get('ip', '?')}")
        return

    # Not found
    if args.get("json"):
        print(json.dumps({"error": f"Not found: {query}"}))
    else:
        print(f"✗ Not found: {query}")
    sys.exit(1)


def cmd_nats_rules(args):
    """Show NATS whitelist rules."""
    topo = load_topology(validate=True)
    rules = topo.nats_whitelist()
    nats_cid = topo.service_container("nats")
    nats_ip = topo.container_ip(nats_cid)

    if args.get("json"):
        print(json.dumps({
            "nats_container": nats_cid,
            "nats_ip": nats_ip,
            "rules": rules,
            "count": len(rules),
        }, indent=2))
    else:
        print(f"NATS ({nats_cid}) — {nats_ip}:4222")
        print(f"  Whitelist: {len(rules)} rules")
        for r in rules:
            port_str = str(r.get('port', '*'))
            print(f"    {r['src']:<20s} → :{port_str:<5s}  {r.get('note', '')}")


def cmd_events(args):
    """Show recent topology events."""
    if not _EVENTS_LOG.exists():
        print("No events logged yet.")
        return

    lines = _EVENTS_LOG.read_text().strip().split("\n")
    tail = args.get("tail", 20)
    lines = lines[-tail:]

    if args.get("json"):
        events = [json.loads(line) for line in lines if line.strip()]
        print(json.dumps(events, indent=2))
    else:
        for line in lines:
            if line.strip():
                ev = json.loads(line)
                ts = ev.get("ts", "?")[:19]
                kind = ev.get("kind", "?")
                detail = ev.get("detail", "")
                cid = ev.get("container_id", "")
                print(f"  {ts}  {kind:<20s}  {cid:>3s}  {detail}")


# ── Main ─────────────────────────────────────────────────────────────────

COMMANDS = {
    "status": cmd_status,
    "validate": cmd_validate,
    "reconcile": cmd_reconcile,
    "daemon": cmd_daemon,
    "lookup": cmd_lookup,
    "nats-rules": cmd_nats_rules,
    "events": cmd_events,
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="VSF Topology CLI")
    parser.add_argument("command", choices=COMMANDS.keys(), help="Command to run")
    parser.add_argument("query", nargs="?", help="Query for lookup command")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--interval", type=int, default=30, help="Daemon interval (seconds)")
    parser.add_argument("--tail", type=int, default=20, help="Number of events to show")

    args = parser.parse_args()

    args_dict = vars(args)
    cmd = COMMANDS[args.command]
    cmd(args_dict)


if __name__ == "__main__":
    main()
