#!/usr/bin/env python3
"""
topology_loader.py — Load, validate, and resolve VSF infrastructure topology.

Usage:
    from topology_loader import load_topology, Topology

    topo = load_topology()  # loads from topology.json
    print(topo.host["hostname"])
    print(topo.container_ip("106"))  # -> "10.10.20.20"
    print(topo.service_port("nats"))  # -> 4222
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Resolve paths relative to this file (clone-portable)
_HERE = Path(__file__).resolve().parent
_DEFAULT_TOPO = _HERE / "topology.json"
_DEFAULT_SCHEMA = _HERE / "topology_schema.json"


class Topology:
    """Immutable topology snapshot with convenience accessors."""

    def __init__(self, data: dict):
        self._data = data
        self.host: dict = data["host"]
        self.containers: dict[str, dict] = data["containers"]
        self.services: dict[str, dict] = data["services"]
        self.paths: dict[str, str] = data["paths"]
        self.version: str = data.get("$version", "0.0.0")

    # ── Container accessors ──────────────────────────────────────────────

    def container_ids(self) -> list[str]:
        """Return sorted container IDs."""
        return sorted(self.containers.keys(), key=lambda x: int(x))

    def container_ip(self, cid: str) -> str:
        """Return IP for a container ID."""
        return self.containers[cid]["ip"]

    def container_name(self, cid: str) -> str:
        """Return name for a container ID."""
        return self.containers[cid]["name"]

    def container_by_name(self, name: str) -> Optional[tuple[str, dict]]:
        """Find container by name. Returns (id, data) or None."""
        for cid, c in self.containers.items():
            if c["name"] == name:
                return cid, c
        return None

    def containers_with_role(self, role: str) -> list[tuple[str, dict]]:
        """Find all containers with a given role."""
        return [
            (cid, c) for cid, c in self.containers.items()
            if role in c.get("roles", [])
        ]

    def containers_with_service(self, service: str) -> list[tuple[str, dict]]:
        """Find all containers running a given service."""
        return [
            (cid, c) for cid, c in self.containers.items()
            if service in c.get("services", [])
        ]

    # ── Service accessors ────────────────────────────────────────────────

    def service_port(self, name: str) -> int:
        """Return port for a named service."""
        return self.services[name]["port"]

    def service_container(self, name: str) -> str:
        """Return container ID hosting a named service."""
        return self.services[name]["container"]

    def service_ip(self, name: str) -> str:
        """Return IP of the container hosting a named service."""
        cid = self.service_container(name)
        return self.container_ip(cid)

    # ── Firewall helpers ─────────────────────────────────────────────────

    def fw_rules_for(self, cid: str) -> list[dict]:
        """Return firewall IN rules for a container."""
        fw = self.containers[cid].get("firewall", {})
        if not fw.get("enabled", False):
            return []
        return fw.get("rules", [])

    def fw_out_rules_for(self, cid: str) -> list[dict]:
        """Return firewall OUT rules for a container."""
        fw = self.containers[cid].get("firewall", {})
        return fw.get("out_rules", [])

    # ── NATS whitelist (derived) ─────────────────────────────────────────

    def nats_whitelist(self) -> list[dict]:
        """Return list of IPs allowed to connect to NATS port 4222."""
        nats_cid = self.service_container("nats")
        return self.fw_rules_for(nats_cid)

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return raw topology dict."""
        return self._data

    def __repr__(self) -> str:
        return (
            f"Topology(version={self.version}, "
            f"host={self.host['hostname']}, "
            f"containers={len(self.containers)}, "
            f"services={len(self.services)})"
        )


def load_topology(
    path: Optional[Path] = None,
    validate: bool = True,
) -> Topology:
    """Load and optionally validate topology.json.

    Args:
        path: Path to topology.json. Defaults to ./topology.json
        validate: Whether to validate against JSON Schema.

    Returns:
        Topology instance.

    Raises:
        FileNotFoundError: If topology file not found.
        ValueError: If validation fails.
    """
    topo_path = path or _DEFAULT_TOPO
    if not topo_path.exists():
        raise FileNotFoundError(f"Topology file not found: {topo_path}")

    with open(topo_path) as f:
        data = json.load(f)

    if validate:
        errors = validate_topology(data)
        if errors:
            raise ValueError(
                f"Topology validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

    return Topology(data)


def validate_topology(data: dict) -> list[str]:
    """Validate topology data. Returns list of error messages (empty = valid)."""
    errors = []

    # Check required top-level keys
    for key in ("host", "containers", "services", "paths"):
        if key not in data:
            errors.append(f"Missing required key: {key}")

    if errors:
        return errors  # Can't continue without required keys

    # Validate host
    host = data["host"]
    for key in ("hostname", "ssh_target", "bridge_ip", "vlans"):
        if key not in host:
            errors.append(f"host missing required key: {key}")

    # Validate containers
    containers = data["containers"]
    container_ips = {}
    nats_cid = None

    for cid, c in containers.items():
        # ID must be numeric
        if not cid.isdigit():
            errors.append(f"Container ID must be numeric: {cid}")

        # Required fields
        for key in ("name", "ip", "vlan", "status"):
            if key not in c:
                errors.append(f"Container {cid} missing required key: {key}")

        # IP uniqueness
        ip = c.get("ip", "")
        if ip in container_ips:
            errors.append(
                f"Duplicate IP {ip}: containers {container_ips[ip]} and {cid}"
            )
        container_ips[ip] = cid

        # Check if this is the NATS container
        if "nats" in c.get("roles", []):
            nats_cid = cid

    # Validate services reference existing containers
    for svc_name, svc in data.get("services", {}).items():
        svc_cid = svc.get("container", "")
        if svc_cid and svc_cid not in containers:
            errors.append(f"Service '{svc_name}' references unknown container: {svc_cid}")

    # Validate NATS whitelist has at least one rule
    if nats_cid:
        fw = containers[nats_cid].get("firewall", {})
        rules = fw.get("rules", [])
        if not rules:
            errors.append(f"NATS container {nats_cid} has no firewall rules (open to all)")

    return errors


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for topology validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate VSF topology.json")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(_DEFAULT_TOPO),
        help="Path to topology.json (default: ./topology.json)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    args = parser.parse_args()

    try:
        topo = load_topology(Path(args.path), validate=True)
        if args.json:
            print(json.dumps({"valid": True, "topology": repr(topo)}))
        else:
            print(f"✓ Topology valid: {topo}")
    except (FileNotFoundError, ValueError) as e:
        if args.json:
            print(json.dumps({"valid": False, "error": str(e)}))
        else:
            print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
