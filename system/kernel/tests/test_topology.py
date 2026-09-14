#!/usr/bin/env python3
"""
test_topology.py — Tests for topology loader, schema, and reconciler.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from topology_loader import Topology, load_topology, validate_topology
from topology_reconciler import generate_fw_content, ReconcileEvent

_HERE = Path(__file__).resolve().parent
_TOPO = _HERE.parent.parent.parent / "topology.json"


# ── Loader tests ─────────────────────────────────────────────────────────

class TestTopologyLoader:
    """Test topology loading and validation."""

    def test_load_real_topology(self):
        """Load the actual topology.json."""
        topo = load_topology(validate=True)
        assert topo.version == "1.0.0"
        assert topo.host["hostname"] == "n02"
        assert len(topo.containers) == 15
        assert len(topo.services) == 7

    def test_container_ids_sorted(self):
        """Container IDs are returned sorted numerically."""
        topo = load_topology(validate=True)
        ids = topo.container_ids()
        assert ids == sorted(ids, key=lambda x: int(x))
        assert "101" in ids
        assert "117" in ids

    def test_container_ip(self):
        """Lookup container IP by ID."""
        topo = load_topology(validate=True)
        assert topo.container_ip("106") == "10.10.20.20"
        assert topo.container_ip("104") == "192.168.0.104"

    def test_container_name(self):
        """Lookup container name by ID."""
        topo = load_topology(validate=True)
        assert topo.container_name("101") == "s3-nucleus"
        assert topo.container_name("106") == "s2-broker"

    def test_container_by_name(self):
        """Find container by name."""
        topo = load_topology(validate=True)
        result = topo.container_by_name("s2-broker")
        assert result is not None
        cid, data = result
        assert cid == "106"

    def test_container_by_name_not_found(self):
        """Non-existent name returns None."""
        topo = load_topology(validate=True)
        assert topo.container_by_name("nonexistent") is None

    def test_containers_with_role(self):
        """Find containers by role."""
        topo = load_topology(validate=True)
        nats_nodes = topo.containers_with_role("nats")
        assert len(nats_nodes) == 1
        assert nats_nodes[0][0] == "106"

    def test_service_accessors(self):
        """Service port and container lookup."""
        topo = load_topology(validate=True)
        assert topo.service_port("nats") == 4222
        assert topo.service_container("nats") == "106"
        assert topo.service_ip("nats") == "10.10.20.20"

    def test_fw_rules_for(self):
        """Firewall rules retrieval."""
        topo = load_topology(validate=True)
        rules = topo.fw_rules_for("106")
        assert len(rules) > 0
        # NATS should have strict whitelist
        nats_ports = {r["port"] for r in rules}
        assert 4222 in nats_ports

    def test_fw_disabled_container(self):
        """Disabled firewall returns empty rules."""
        topo = load_topology(validate=True)
        rules = topo.fw_rules_for("108")  # dev-sandbox, fw disabled
        assert rules == []

    def test_nats_whitelist(self):
        """NATS whitelist is derived from 106's firewall rules."""
        topo = load_topology(validate=True)
        whitelist = topo.nats_whitelist()
        assert len(whitelist) > 0
        # All rules should be for port 4222 (NATS) or 8222 (monitoring) or 8600 (BBS) or 22 (SSH) or 0 (ICMP)
        for rule in whitelist:
            assert rule["port"] in (4222, 8222, 8600, 22, 0)

    def test_repr(self):
        """Topology repr includes key info."""
        topo = load_topology(validate=True)
        r = repr(topo)
        assert "n02" in r
        assert "15" in r  # containers


# ── Validation tests ─────────────────────────────────────────────────────

class TestValidation:
    """Test topology validation."""

    def test_valid_topology(self):
        """Valid topology passes validation."""
        topo = load_topology(validate=True)
        errors = validate_topology(topo.to_dict())
        assert errors == []

    def test_missing_host(self):
        """Missing host key fails."""
        errors = validate_topology({"containers": {}, "services": {}, "paths": {}})
        assert any("host" in e for e in errors)

    def test_duplicate_ip(self):
        """Duplicate IPs fail validation."""
        data = {
            "host": {"hostname": "test", "ssh_target": "t", "bridge_ip": "1.1.1.1", "vlans": {}},
            "containers": {
                "1": {"name": "a", "ip": "10.0.0.1", "vlan": 20, "status": "running"},
                "2": {"name": "b", "ip": "10.0.0.1", "vlan": 20, "status": "running"},
            },
            "services": {},
            "paths": {},
        }
        errors = validate_topology(data)
        assert any("Duplicate IP" in e for e in errors)

    def test_nats_no_rules(self):
        """NATS container with no rules fails validation."""
        data = {
            "host": {"hostname": "test", "ssh_target": "t", "bridge_ip": "1.1.1.1", "vlans": {}},
            "containers": {
                "1": {"name": "nats", "ip": "10.0.0.1", "vlan": 20, "status": "running",
                       "roles": ["nats"], "firewall": {"enabled": True, "rules": []}},
            },
            "services": {},
            "paths": {},
        }
        errors = validate_topology(data)
        assert any("NATS" in e for e in errors)

    def test_service_references_unknown_container(self):
        """Service referencing unknown container fails."""
        data = {
            "host": {"hostname": "test", "ssh_target": "t", "bridge_ip": "1.1.1.1", "vlans": {}},
            "containers": {
                "1": {"name": "a", "ip": "10.0.0.1", "vlan": 20, "status": "running"},
            },
            "services": {"svc": {"container": "999", "port": 8080}},
            "paths": {},
        }
        errors = validate_topology(data)
        assert any("999" in e for e in errors)


# ── Firewall generation tests ───────────────────────────────────────────

class TestFWGeneration:
    """Test .fw file generation."""

    def test_generate_disabled_fw(self):
        """Disabled firewall generates minimal .fw."""
        container = {"firewall": {"enabled": False, "rules": []}}
        content = generate_fw_content("108", container)
        assert "enable: 0" in content
        assert "[RULES]" not in content

    def test_generate_fw_with_rules(self):
        """FW with rules generates correct format."""
        container = {
            "firewall": {
                "enabled": True,
                "policy_in": "DROP",
                "rules": [
                    {"src": "10.10.20.1", "port": 22, "proto": "tcp", "note": "SSH"},
                ],
            }
        }
        content = generate_fw_content("101", container)
        assert "enable: 1" in content
        assert "policy_in: DROP" in content
        assert "[RULES]" in content
        assert "IN ACCEPT -source 10.10.20.1 -p tcp -dport 22" in content
        assert "# SSH" in content

    def test_generate_icmp_rule(self):
        """ICMP rule doesn't have -dport."""
        container = {
            "firewall": {
                "enabled": True,
                "rules": [
                    {"src": "10.10.20.1", "port": 0, "proto": "icmp", "note": "ping"},
                ],
            }
        }
        content = generate_fw_content("101", container)
        assert "-p icmp" in content
        assert "-dport" not in content

    def test_generate_out_rules(self):
        """OUT rules are generated."""
        container = {
            "firewall": {
                "enabled": True,
                "rules": [],
                "out_rules": [
                    {"dest": "10.10.20.0/24", "action": "DROP", "note": "Block VLAN20"},
                ],
            }
        }
        content = generate_fw_content("111", container)
        assert "OUT DROP -dest 10.10.20.0/24" in content
        assert "# Block VLAN20" in content

    def test_generate_nats_fw(self):
        """NATS container FW has all whitelist rules."""
        topo = load_topology(validate=True)
        nats_container = topo.containers["106"]
        content = generate_fw_content("106", nats_container)
        assert "enable: 1" in content
        assert "policy_in: DROP" in content
        # Should have rules for all NATS publishers
        assert "10.10.20.10" in content  # nucleus
        assert "10.10.20.104" in content  # algedonic
        assert "10.10.20.30" in content  # s3star


# ── Event tests ──────────────────────────────────────────────────────────

class TestEvents:
    """Test reconciliation events."""

    def test_event_to_dict(self):
        """Event serialization."""
        ev = ReconcileEvent(kind="fw_generated", container_id="106", detail="test")
        d = ev.to_dict()
        assert d["kind"] == "fw_generated"
        assert d["container_id"] == "106"
        assert "ts" in d
