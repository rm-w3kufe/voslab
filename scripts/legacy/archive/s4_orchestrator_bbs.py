#!/usr/bin/env python3
"""
S4 Intelligence — Reads BBS state, makes decisions
Runs on Ollama LXC 101
"""

import requests
import json
import time
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BBS_URL = "http://10.10.20.20:8600"  # LXC 106 BBS

class S4Orchestrator:
    """S4 Intelligence Layer — reads state, analyzes, publishes recommendations"""

    def __init__(self):
        self.state = {}
        self.decisions = []
        logger.info("S4 Orchestrator initialized")

    def read_system_state(self):
        """Read latest system-state from BBS"""
        try:
            r = requests.get(f"{BBS_URL}/api/state/current", timeout=5)
            if r.status_code == 200:
                result = r.json()
                if "state" in result:
                    self.state = result["state"]
                    logger.info(f"✓ System state read: node={self.state.get('node')}, "
                              f"ram_alloc={self.state.get('hardware', {}).get('ram_allocated_gb')}GB")
                    return True
        except Exception as e:
            logger.warning(f"Failed to read BBS state: {e}")
        return False

    def read_alerts(self):
        """Read alerts from BBS"""
        try:
            r = requests.get(f"{BBS_URL}/api/messages/alerts?limit=10", timeout=5)
            if r.status_code == 200:
                result = r.json()
                alerts = result.get("messages", [])
                if alerts:
                    logger.info(f"✓ Alerts read: {len(alerts)} pending")
                    return alerts
        except Exception as e:
            logger.warning(f"Failed to read alerts: {e}")
        return []

    def analyze_state(self):
        """Analyze system state and generate recommendations"""
        if not self.state:
            return

        hardware = self.state.get("hardware", {})
        containers = self.state.get("containers", {})

        decisions = []

        # Decision 1: RAM pressure
        ram_alloc = hardware.get("ram_allocated_gb", 0)
        if ram_alloc > 22:
            decisions.append({
                "type": "resource_constraint",
                "action": "reduce_concurrency",
                "target": "orchestrator",
                "reason": f"RAM allocated {ram_alloc}GB near limit (24GB)",
                "recommendation": "Limit concurrent inference to 1 model"
            })

        # Decision 2: Container health
        unhealthy = [name for name, info in containers.items() if info.get("status") != "running"]
        if unhealthy:
            decisions.append({
                "type": "container_alert",
                "action": "investigate",
                "target": unhealthy,
                "reason": f"{len(unhealthy)} containers not running",
                "recommendation": "Check logs, restart if needed"
            })

        # Decision 3: Disk usage
        disk_used = hardware.get("disk_used_gb", 0)
        if disk_used > 70:
            decisions.append({
                "type": "disk_pressure",
                "action": "cleanup",
                "reason": f"Disk {disk_used}GB used (94GB total)",
                "recommendation": "Rotate logs, clean temp files"
            })

        self.decisions = decisions
        if decisions:
            logger.info(f"✓ Generated {len(decisions)} decisions from state analysis")
        return decisions

    def publish_decisions(self):
        """Publish S4 analysis and recommendations back to BBS"""
        if not self.decisions:
            return

        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "s4_orchestrator",
            "topic": "s4-analysis",
            "priority": "info",
            "ttl": 86400,
            "payload": {
                "analysis_type": "state_analysis",
                "timestamp": datetime.utcnow().isoformat(),
                "decisions": self.decisions,
                "state_digest": {
                    "node": self.state.get("node"),
                    "ram_gb": self.state.get("hardware", {}).get("ram_allocated_gb"),
                    "containers": len(self.state.get("containers", {}))
                }
            }
        }

        try:
            r = requests.post(f"{BBS_URL}/api/message", json=message, timeout=5)
            if r.status_code == 200:
                result = r.json()
                logger.info(f"✓ Decisions published to BBS (msg_id={result.get('id')})")
                return True
        except Exception as e:
            logger.warning(f"Failed to publish decisions: {e}")

        return False

    def run_once(self):
        """Single orchestration cycle"""
        logger.info("=" * 60)
        logger.info("S4 ORCHESTRATION CYCLE")
        logger.info("=" * 60)

        # 1. Read state from BBS
        if not self.read_system_state():
            logger.warning("No system state available")
            return

        # 2. Read alerts
        alerts = self.read_alerts()
        if alerts:
            logger.info(f"Alerts to consider: {[a['payload'].get('alert_type') for a in alerts]}")

        # 3. Analyze and decide
        self.analyze_state()

        # 4. Publish recommendations back to BBS
        self.publish_decisions()

        logger.info("Cycle complete\n")

    def run_continuous(self, interval=300):
        """Run orchestration every N seconds"""
        logger.info(f"Starting continuous mode (interval={interval}s)")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in cycle: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    s4 = S4Orchestrator()
    s4.run_continuous(interval=300)  # Every 5 minutes
