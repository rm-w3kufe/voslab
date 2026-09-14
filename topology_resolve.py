#!/usr/bin/env python3
"""
topology_resolve.py — Resolve infrastructure references from topology.json.

Lightweight helper for scripts that need to resolve LXC IDs, IPs, or SSH
targets from topology.json without importing the full topology_loader.

Usage:
    from topology_resolve import resolve_lxc, resolve_ssh, resolve_nats

    cid = resolve_lxc("nats")          # -> "106"
    ip = resolve_ip("nats")            # -> "10.10.20.20"
    ssh = resolve_ssh()                # -> "ssh root@n02"
    lxc_ids = resolve_lxc_by_role("nucleus")  # -> ["101"]
"""

import json
import os
from pathlib import Path
from typing import Optional

_TOPO = None

def _load():
    global _TOPO
    if _TOPO is not None:
        return _TOPO

    # Try VOSLAB_PATH first, then relative to this file
    voslab = os.environ.get("VOSLAB_PATH", str(Path(__file__).resolve().parent.parent.parent))
    topo_path = Path(voslab) / "topology.json"
    if not topo_path.exists():
        topo_path = Path(__file__).resolve().parent / "topology.json"
    if not topo_path.exists():
        raise FileNotFoundError(f"topology.json not found (looked in {voslab} and {Path(__file__).resolve().parent})")

    with open(topo_path) as f:
        _TOPO = json.load(f)
    return _TOPO


def resolve_lxc(service_or_role: str) -> str:
    """Resolve a service name or role to its container ID.

    First tries service lookup, then role lookup.
    Returns the first matching container ID.
    """
    topo = _load()

    # Try as service name
    for svc_name, svc in topo.get("services", {}).items():
        if svc_name == service_or_role:
            return svc["container"]

    # Try as role
    for cid, c in topo.get("containers", {}).items():
        if service_or_role in c.get("roles", []) or service_or_role in c.get("services", []):
            return cid

    raise KeyError(f"No service or role '{service_or_role}' found in topology")


def resolve_ip(service_or_role: str) -> str:
    """Resolve a service name or role to its IP address."""
    topo = _load()
    cid = resolve_lxc(service_or_role)
    return topo["containers"][cid]["ip"]


def resolve_lxc_by_role(role: str) -> list[str]:
    """Return all container IDs that have a given role."""
    topo = _load()
    return [
        cid for cid, c in topo.get("containers", {}).items()
        if role in c.get("roles", []) or role in c.get("services", [])
    ]


def resolve_ssh() -> str:
    """Return SSH command prefix for the Proxmox host."""
    topo = _load()
    target = topo["host"]["ssh_target"]
    return f"ssh -o ConnectTimeout=5 {target}"


def resolve_host_ip() -> str:
    """Return the host bridge IP."""
    topo = _load()
    return topo["host"]["bridge_ip"]


def resolve_nats_host() -> str:
    """Return NATS host IP."""
    return resolve_ip("nats")


def resolve_nats_port() -> int:
    """Return NATS port."""
    topo = _load()
    return topo["services"]["nats"]["port"]


def resolve_service(name: str) -> dict:
    """Return full service definition."""
    topo = _load()
    return topo["services"][name]


def resolve_container(cid: str) -> dict:
    """Return full container definition."""
    topo = _load()
    return topo["containers"][cid]
