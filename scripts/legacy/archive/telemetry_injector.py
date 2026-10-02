#!/usr/bin/env python3
"""
Telemetry Injector — Feeds system state to BBS every hour
Runs on LXC 104 (Telemetry)
Accesses n02 Proxmox via SSH tunnel
"""

import subprocess
import json
import requests
from datetime import datetime
import time
import logging
import os

# ============================================================================
# Configuration
# ============================================================================

BBS_URL = "http://10.10.20.20:8600"  # LXC 106 BBS
SSH_HOST = "n02"  # SSH alias (via ProxyJump n01)
INJECTION_INTERVAL = 3600  # 1 hour

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# Proxmox Data Collection
# ============================================================================

def get_proxmox_state():
    """
    Collect state from n02 Proxmox host via SSH.
    Returns dict with hardware, containers, alerts.
    """
    try:
        # Get node info
        result = subprocess.run(
            f"ssh {SSH_HOST} 'pvesh get /nodes/n02 --output-format=json'",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            logger.error(f"Failed to query Proxmox: {result.stderr}")
            return None

        node_data = json.loads(result.stdout)

        # Extract hardware info
        hardware = {
            "cpu_cores": node_data.get("cpus", 8),
            "ram_total_gb": 24,  # Fixed for n02
            "ram_allocated_gb": 22.512,
            "ram_free_gb": 1.488,
            "disk_total_gb": node_data.get("maxdisk", 94) // (1024**3),
            "disk_used_gb": node_data.get("disk", 0) // (1024**3),
            "disk_free_gb": 68,
        }

        # Get LXC/VM status
        containers = {}

        # Query all containers
        lxc_result = subprocess.run(
            f"ssh {SSH_HOST} 'pct list --output-format=json'",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if lxc_result.returncode == 0:
            lxcs = json.loads(lxc_result.stdout)
            for lxc in lxcs:
                vmid = lxc["vmid"]
                name = lxc["name"]
                status = lxc["status"]

                # Get detailed config
                config_result = subprocess.run(
                    f"ssh {SSH_HOST} 'pct config {vmid}'",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                memory_mb = 1024  # Default
                if config_result.returncode == 0:
                    for line in config_result.stdout.split('\n'):
                        if line.startswith('memory:'):
                            memory_mb = int(line.split(':')[1].strip())
                            break

                containers[f"lxc_{vmid}_{name}"] = {
                    "status": status,
                    "vmid": vmid,
                    "name": name,
                    "ram_allocated_mb": memory_mb,
                    "ram_used_mb": int(memory_mb * 0.6),  # Estimate
                    "disk_gb": 10,
                    "network": f"10.10.20.{10 + vmid}",
                    "vlan": 20
                }

        # Query VMs
        qm_result = subprocess.run(
            f"ssh {SSH_HOST} 'qm list --output-format=json'",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if qm_result.returncode == 0:
            qms = json.loads(qm_result.stdout)
            for qm in qms:
                vmid = qm["vmid"]
                name = qm["name"]
                status = qm["status"]

                config_result = subprocess.run(
                    f"ssh {SSH_HOST} 'qm config {vmid}'",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                memory_mb = 1024
                if config_result.returncode == 0:
                    for line in config_result.stdout.split('\n'):
                        if line.startswith('memory:'):
                            memory_mb = int(line.split(':')[1].strip())
                            break

                containers[f"vm_{vmid}_{name}"] = {
                    "status": status,
                    "vmid": vmid,
                    "name": name,
                    "ram_allocated_mb": memory_mb,
                    "ram_used_mb": int(memory_mb * 0.6),
                    "cpu_load": 1.2,
                    "disk_gb": 80,
                    "network": f"10.10.30.{100 + vmid}",
                    "vlan": 30
                }

        # Generate alerts
        alerts = []

        # RAM alert
        if hardware["ram_allocated_gb"] > 22:
            alerts.append({
                "severity": "warning",
                "metric": "ram_allocation",
                "value": hardware["ram_allocated_gb"],
                "threshold": 23,
                "status": "high_utilization"
            })

        # Disk alert
        if hardware["disk_used_gb"] > 70:
            alerts.append({
                "severity": "warning",
                "metric": "disk_usage",
                "value": hardware["disk_used_gb"],
                "threshold": 70,
                "status": "disk_pressure"
            })

        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "node": "n02",
            "hardware": hardware,
            "containers": containers,
            "alerts": alerts
        }

    except Exception as e:
        logger.error(f"Error collecting Proxmox state: {e}")
        return None

# ============================================================================
# BBS Injection
# ============================================================================

def inject_state_to_bbs(state):
    """Send system state to BBS."""
    try:
        message = {
            "timestamp": state["timestamp"],
            "source": "telemetry",
            "topic": "system-state",
            "priority": "info",
            "ttl": 3600,
            "payload": state
        }

        response = requests.post(
            f"{BBS_URL}/api/message",
            json=message,
            timeout=5
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"State injected to BBS (msg_id={result['message_id']}, "
                f"containers={len(state['containers'])}, "
                f"alerts={len(state['alerts'])})"
            )
            return True
        else:
            logger.error(f"BBS returned {response.status_code}: {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error injecting to BBS: {e}")
        return False

# ============================================================================
# Main Loop
# ============================================================================

def main():
    logger.info("Telemetry Injector starting...")
    logger.info(f"BBS URL: {BBS_URL}")
    logger.info(f"Injection interval: {INJECTION_INTERVAL}s")

    while True:
        try:
            # Collect state
            logger.info("Collecting Proxmox state...")
            state = get_proxmox_state()

            if state:
                # Inject to BBS
                logger.info("Injecting state to BBS...")
                inject_state_to_bbs(state)
            else:
                logger.warning("Failed to collect Proxmox state")

        except Exception as e:
            logger.error(f"Error in main loop: {e}")

        # Sleep until next injection
        logger.info(f"Sleeping for {INJECTION_INTERVAL}s...")
        time.sleep(INJECTION_INTERVAL)

if __name__ == "__main__":
    main()
