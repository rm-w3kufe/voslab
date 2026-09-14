# VSF Topology Configuration

## Overview

`topology.json` is the **single source of truth** for VSF infrastructure. It defines:

- **Containers**: all Proxmox LXC containers (IDs, IPs, VLANs, roles)
- **Services**: network services (NATS, BBS, Ollama, etc.)
- **Firewall rules**: per-container Proxmox firewall configuration
- **Paths**: filesystem paths inside containers

The topology is **clone-portable**: a new clone of vOSlab can point to a different `topology.json` and work without editing code.

## Files

| File | Purpose |
|------|---------|
| `topology.json` | Desired infrastructure state |
| `topology_schema.json` | JSON Schema for validation |
| `topology_loader.py` | Load + validate + accessors |
| `topology_reconciler.py` | Reconcile desired vs actual, generate .fw files |
| `topology_cli.py` | CLI interface |

## Quick Start

```bash
# Validate topology
python3 topology_cli.py validate

# Show status (desired vs actual)
python3 topology_cli.py status

# Reconcile (generate .fw files)
python3 topology_cli.py reconcile --dry-run   # preview
python3 topology_cli.py reconcile             # apply

# Run as daemon (auto-reconcile every 30s)
python3 topology_cli.py daemon --interval 30

# Look up a service
python3 topology_cli.py lookup nats
python3 topology_cli.py lookup 106
python3 topology_cli.py lookup s3-nucleus

# Show NATS whitelist
python3 topology_cli.py nats-rules

# Show recent events
python3 topology_cli.py events --tail 10
```

## Adding a New Container

1. Create the container in Proxmox (via web UI or `pct create`)
2. Add entry to `topology.json` under `containers`:

```json
"118": {
  "name": "my-new-service",
  "ip": "10.10.20.118",
  "vlan": 20,
  "status": "running",
  "roles": ["my-role"],
  "firewall": {
    "enabled": true,
    "policy_in": "DROP",
    "rules": [
      {"src": "10.10.20.1", "port": 22, "proto": "tcp", "note": "SSH from host"}
    ]
  }
}
```

3. Run reconciliation:

```bash
python3 topology_cli.py reconcile
```

This generates `/etc/pve/firewall/118.fw` on the Proxmox host.

## Adding a New Service

Add to `services` in `topology.json`:

```json
"my_service": {
  "container": "118",
  "port": 9090,
  "network": "vlan20"
}
```

Reference via `topology_loader.py`:

```python
from topology_loader import load_topology
topo = load_topology()
ip = topo.service_ip("my_service")
port = topo.service_port("my_service")
```

## Firewall Rules

Each container can have firewall rules in its `firewall` section:

```json
"firewall": {
  "enabled": true,
  "policy_in": "DROP",     // default policy (ACCEPT or DROP)
  "rules": [               // IN rules
    {"src": "10.10.20.1", "port": 22, "proto": "tcp", "note": "SSH from host"},
    {"src": "10.10.0.0/16", "port": 4222, "proto": "tcp", "note": "NATS"}
  ],
  "out_rules": [           // OUT rules (optional)
    {"dest": "10.10.20.0/24", "action": "DROP", "note": "Block VLAN20"}
  ]
}
```

### Rule fields

| Field | Required | Description |
|-------|----------|-------------|
| `src` / `dest` | yes | Source/destination IP or CIDR |
| `port` | yes | Port number (0 for ICMP) |
| `proto` | no | Protocol: `tcp` (default), `udp`, `icmp` |
| `note` | no | Human-readable description |

### Generated .fw format

The reconciler generates Proxmox-compatible `.fw` files:

```
[OPTIONS]
enable: 1
policy_in: DROP

[RULES]
IN ACCEPT -source 10.10.20.1/32 -p tcp -dport 22 -log nolog # SSH from host
IN ACCEPT -source 10.10.0.0/16 -p tcp -dport 4222 -log nolog # NATS
```

## NATS Whitelist

NATS (container 106) uses a strict whitelist. To add a new publisher/subscriber:

1. Add the container to `topology.json`
2. Add a firewall rule to container 106's rules:

```json
{"src": "10.10.20.118", "port": 4222, "proto": "tcp", "note": "NATS: 118 my-new-service"}
```

3. Run `python3 topology_cli.py reconcile`

## Network Topology

```
n02 (Proxmox host)
├── vmbr0      192.168.0.168/24  ← bridge LAN (management)
├── vmbr0.10   VLAN 10           ← management
├── vmbr0.20   VLAN 20           ← services (NATS, BBS, nucleus)
├── vmbr0.30   VLAN 30           ← hop/jump (bbh)
├── vmbr0.40   VLAN 40           ← reserved
└── vmbr0.50   VLAN 50           ← SOC (indexer, server, dashboard)
```

### Container network assignments

| VLAN | Containers | Purpose |
|------|------------|---------|
| 20 | 101, 106, 107, 108, 109, 110, 112, 113 | Core services |
| 30 | 105, 111 | BBH (hop-isolated) |
| 50 | 115, 116, 117 | SOC stack |
| bridge | 104, 114 | Dual-homed / management |

## Container Reference

| ID | Name | IP | VLAN | Roles |
|----|------|-----|------|-------|
| 101 | s3-nucleus | 10.10.20.10 | 20 | nucleus, ollama-client, phi-up |
| 104 | s5-policy | 192.168.0.104 | bridge | algedonic, s5-console, bbs-bridge |
| 105 | bbh-prod | 10.10.30.110 | 30 | bbh |
| 106 | s2-broker | 10.10.20.20 | 20 | nats, bbs |
| 107 | s3star-audit | 10.10.20.30 | 20 | s3-star, kpi-publisher |
| 108 | dev-sandbox | 10.10.20.108 | 20 | sandbox, testing |
| 109 | s5-opsroom | 10.10.20.109 | 20 | view-host |
| 110 | s4-intelligence | 10.10.20.110 | 20 | intelligence, ollama-host |
| 111 | bbh-lab | 10.10.30.111 | 30 | bbh-lab |
| 112 | s1-clima | 10.10.20.112 | 20 | clima, phi-up |
| 113 | s1-econ | 10.10.20.113 | 20 | econ, phi-up |
| 114 | jupyter-lab | 192.168.0.114 | bridge | jupyter |
| 115 | s5-soc-indexer | 10.10.50.115 | 50 | soc-indexer |
| 116 | s5-soc-server | 10.10.50.116 | 50 | soc-server |
| 117 | s5-soc-dashboard | 10.10.50.117 | 50 | soc-dashboard |

## Reconciler Modes

### On-demand

```bash
python3 topology_cli.py reconcile              # apply changes
python3 topology_cli.py reconcile --dry-run    # preview only
```

### Daemon

```bash
python3 topology_cli.py daemon --interval 30   # check every 30s
python3 topology_cli.py daemon --dry-run       # monitor only
```

The daemon:
1. Loads `topology.json`
2. Generates `.fw` files for all containers
3. Discovers actual containers via `pct list`
4. Reports new/missing containers
5. Logs events to `state/rsi/topology_events.jsonl`

### Integration with vosi

Add to `vosi.py`:

```python
def cmd_topology(args):
    """Topology management."""
    from topology_cli import cmd_status, cmd_validate, cmd_reconcile
    sub = args.get("sub", "status")
    if sub == "status":
        cmd_status(args)
    elif sub == "validate":
        cmd_validate(args)
    elif sub == "reconcile":
        cmd_reconcile(args)
```

## Event Log

Events are logged to `state/rsi/topology_events.jsonl`:

```json
{"kind": "fw_generated", "container_id": "118", "detail": "my-new-service (118)", "ts": "2026-09-13T..."}
{"kind": "container_added", "container_id": "119", "detail": "unknown-container (running) — NOT in topology.json", "ts": "..."}
```

## Clone Portability

When cloning vOSlab to a new host:

1. Copy `topology.json` to the new host
2. Edit `topology.json` with the new host's topology
3. Run `python3 topology_cli.py reconcile` on the new host
4. The reconciler generates all `.fw` files automatically

No code changes needed — the topology is data-driven.
